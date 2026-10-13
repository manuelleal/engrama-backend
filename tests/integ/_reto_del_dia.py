"""La simulación del humo y de la réplica del "reto del día" (no se recolecta).

`docs/ESPEC_humo_reto_del_dia.md` §2. Un banco sintético, un reloj simulado
(uno solo para la racha, la tanda, el cierre de intentos, el repaso y el
instante de cada respuesta) y estudiantes con una política fija. Todo por
HTTP, por las rutas que usará la web.

Cada decisión sale de `Random("semilla|quién|día|ítem|intento")`: no depende
del orden en que lleguen las cosas.
"""
from __future__ import annotations

import random
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from src.challenge_engine.service import attempts as attempts_mod
from src.challenge_engine.service import por_pregunta as por_pregunta_mod
from src.engrama_core.service import attendance as attendance_mod
from src.practica import service as practica_mod
from src.racha import service as racha_mod
from src.refuerzo import service as refuerzo_mod
from tests.challenge_engine import _l1 as l1
from tests.racha import _ayuda as ra
from tests.refuerzo import _ayuda as rf

client = l1.client
INICIO = datetime(2026, 10, 12, 13, 0, tzinfo=UTC)  # lunes, 8:00 en Bogotá
LETRAS = "ABCD"
NODOS = (rf.UNO, rf.DOS, rf.TRES)  # 3 nodos: el tope de 3 repasos por tanda nunca corta
PROHIBIDAS = ("correct_answer", "explanation", "oracion_correcta", "accepted_answers",
              "tolerancia", "Regla de ")
DESTREZAS = ("grammar", "vocabulary")
ROLES = (("original", 1), ("gemela", 2), ("repaso", 3))


class Reloj:
    """El instante simulado. Solo avanza."""

    def __init__(self) -> None:
        self.t = INICIO

    def a(self, dia: int, hora: int = 0) -> None:
        self.t = max(self.t + timedelta(seconds=1),
                     INICIO + timedelta(days=dia, hours=hora))

    def pasa(self, segundos: int) -> None:
        self.t += timedelta(seconds=segundos)


def instalar(mp: pytest.MonkeyPatch, reloj: Reloj) -> None:
    """Todos los relojes del camino leen el simulado."""

    class _Fecha(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
            return reloj.t

    mp.setattr(attempts_mod, "datetime", _Fecha)
    for modulo, nombre in ((practica_mod, "_instante"), (racha_mod, "_ahora"),
                           (refuerzo_mod, "_ahora"), (por_pregunta_mod, "_ahora"),
                           (attendance_mod, "_ahora")):
        mp.setattr(modulo, nombre, lambda: reloj.t)


@dataclass
class Banco:
    clave: dict[str, str] = field(default_factory=dict)  # pregunta -> label correcta
    item: dict[str, str] = field(default_factory=dict)  # pregunta -> item_ref
    de_refuerzo: set[str] = field(default_factory=set)  # retos `solo_refuerzo`
    titulos_de_refuerzo: set[str] = field(default_factory=set)
    retos: int = 0


def _pregunta(familia: str, k: int, rol: str, nodo: str, clave: str) -> dict[str, Any]:
    item = f"{familia}-{k}"
    otras = [x for x in LETRAS if x != clave]
    return l1.pregunta(
        f"{item}: She ___ it.", clave, opciones={x: f"{item} op{x}" for x in LETRAS},
        item_ref=item, familia=familia, rol=rol, nodos=[nodo],
        explanation={"regla": f"Regla de {familia}.", "ejemplo": f"Ejemplo de {item}.",
                     "por_opcion": {x: f"No es {x} en {item}." for x in otras}})


def sembrar_banco(integ: Any, c: Any, unidades: dict[str, int], *, gemelas: bool = True,
                  max_attempts: int = 2) -> Banco:
    """Por nivel y unidad: 2 retos del feed y, de cada uno, su reto de gemelas y el de repaso."""
    banco = Banco()
    for nivel, cuantas in unidades.items():
        for u in range(1, cuantas + 1):
            for d, destreza in enumerate(DESTREZAS):
                base = f"{nivel.lower()}-u{u:02d}-{destreza[:3]}"
                for rol, k in ROLES:
                    if rol != "original" and not gemelas:  # ni gemelas ni repasos
                        continue
                    preguntas = [
                        _pregunta(f"{base}-f{j}", k, rol, NODOS[(u + j + d) % len(NODOS)],
                                  LETRAS[(u + j + k + d) % len(LETRAS)])
                        for j in (1, 2, 3)]
                    titulo = f"{nivel}-u{u:02d} {destreza} {rol}"
                    reto, ids = l1.reto(
                        integ, c.profe, titulo, preguntas, grupo=c.grupo, nivel=nivel,
                        topic=f"{nivel.lower()}-u{u:02d}", skill=destreza,
                        max_attempts=max_attempts, solo_refuerzo=rol != "original")
                    banco.retos += 1
                    if rol != "original":
                        banco.de_refuerzo.add(reto)
                        banco.titulos_de_refuerzo.add(titulo)
                    for pregunta_id, p in zip(ids, preguntas, strict=True):
                        banco.clave[pregunta_id] = p["correct_answer"]
                        banco.item[pregunta_id] = p["item_ref"]
    return banco


@dataclass(frozen=True)
class Politica:
    nombre: str
    asiste: tuple[int, ...]  # días de la semana (0 = lunes)
    practica: tuple[int, ...]
    tandas: int
    modo: str  # sabe | azar | copia
    acierta: float = 0.0
    segundos: tuple[int, int] = (1, 2)


CUATRO = (
    Politica("clases", asiste=(1, 3), practica=(5,), tandas=1, modo="sabe", acierta=0.75,
             segundos=(8, 20)),
    Politica("solo", asiste=(), practica=(0, 2, 4), tandas=2, modo="sabe", acierta=0.75,
             segundos=(8, 20)),
    Politica("azar", asiste=(), practica=(0, 1, 3, 5), tandas=2, modo="azar"),
    Politica("copia", asiste=(), practica=(0, 2, 4), tandas=1, modo="copia"),
)


class Simulacion:
    """Corre a los estudiantes día por día y cuenta lo que no debe pasar."""

    def __init__(self, integ: Any, c: Any, banco: Banco, reloj: Reloj, semilla: int,
                 quienes: dict[str, UUID]) -> None:
        self.integ, self.c, self.banco, self.reloj, self.semilla = integ, c, banco, reloj, semilla
        self.quienes = quienes
        self.vistas: dict[str, dict[str, str]] = defaultdict(dict)  # las claves que ya le mostraron
        self.errores_5xx = 0
        self.fugas = 0
        self.refuerzo_fuera_de_lugar = 0
        self.rachas_rotas_sin_contenido = 0
        self.idiomas: Counter[str] = Counter()
        self.tandas_vacias: Counter[str] = Counter()
        self.primer_error = ""

    # ------------------------------------------------------------- utilidades
    def _h(self, nombre: str) -> dict[str, str]:
        return self.integ.headers(self.quienes[nombre])

    def _ver(self, r: Any) -> Any:
        if r.status_code >= 500:
            self.errores_5xx += 1
            self.primer_error = self.primer_error or f"{r.request.method} {r.request.url.path}"
        return r

    def _revisar(self, cuerpo: Any) -> None:
        """Nada de lo que llega ANTES de responder trae la clave ni la explicación."""
        texto = str(cuerpo)
        if any(p in texto for p in PROHIBIDAS):
            self.fugas += 1

    def _elegir(self, p: Politica, dia: int, pregunta: str, intento: int) -> tuple[str, int]:
        """`(la opción que marca, cuántos segundos tarda)`."""
        r = random.Random(f"{self.semilla}|{p.nombre}|{dia}|{self.banco.item[pregunta]}|{intento}")
        sabida = self.vistas[p.nombre].get(pregunta)
        if p.modo == "copia" and sabida is not None:
            return sabida, 2  # copia la clave que le mostraron
        clave = self.banco.clave[pregunta]
        if p.modo == "sabe":
            acierta = sabida is not None or r.random() < p.acierta  # lo explicado se aprende
            marca = clave if acierta else r.choice([x for x in LETRAS if x != clave])
        else:
            marca = r.choice(LETRAS)
        return marca, r.randint(*p.segundos)

    # ---------------------------------------------------------------- acciones
    def jugar(self, p: Politica, dia: int, reto: str) -> bool | None:
        """Un intento pregunta por pregunta. `None` si no se pudo abrir (sin intentos)."""
        inicio = self._ver(client.post(f"/challenges/{reto}/attempt", headers=self._h(p.nombre)))
        if inicio.status_code != 201:
            return None
        cuerpo = inicio.json()
        self._revisar(cuerpo)
        intento, numero = cuerpo["attempt_id"], cuerpo["attempt_number"]
        for q in sorted(cuerpo["challenge"]["questions"], key=lambda q: q["order_index"]):
            marca, segundos = self._elegir(p, dia, q["id"], numero)
            self.reloj.pasa(segundos)
            r = self._ver(l1.responder_crudo(self.integ, self.quienes[p.nombre], intento,
                                             q["id"], marca))
            if r.status_code == 200:
                self.vistas[p.nombre][q["id"]] = r.json()["correct_answer"]
                self.idiomas[(r.json()["explanation"] or {}).get("idioma", "sin")] += 1
        self.reloj.pasa(1)
        fin = self._ver(l1.terminar_crudo(self.integ, self.quienes[p.nombre], intento))
        return bool(fin.json()["is_correct"]) if fin.status_code == 200 else None

    def repasar(self, p: Politica, dia: int, pendiente: dict[str, Any]) -> None:
        pregunta = pendiente["pregunta"]["id"]
        marca, segundos = self._elegir(p, dia, pregunta, 0)
        self.reloj.pasa(segundos)
        r = self._ver(client.post(
            f"/challenges/refuerzo/{pendiente['entrada_id']}/respuestas",
            headers=self._h(p.nombre), json={"question_id": pregunta, "answer": marca}))
        if r.status_code == 200:
            self.vistas[p.nombre][pregunta] = r.json()["correct_answer"]

    def asistir(self, p: Politica) -> None:
        """El profe abre la sesión y el estudiante marca un minuto después (llega a tiempo)."""
        codigo = self.integ.crear_sesion_asistencia(
            self.c.tenant, self.c.grupo, self.c.profe, inicio=self.reloj.t)
        self.reloj.pasa(60)
        self._ver(client.post("/core/attendance/check-in", json={"session_code": codigo},
                              headers=self._h(p.nombre)))

    def practicar(self, p: Politica, dia: int) -> None:
        for _ in range(p.tandas):
            self.reloj.pasa(2)
            r = self._ver(client.post("/challenges/tanda", headers=self._h(p.nombre)))
            if r.status_code != 200:
                return
            self._revisar(r.json())
            tanda = r.json()["tanda"]
            if tanda is None:
                self.tandas_vacias[p.nombre] += 1
                return
            if tanda["modo"] != "segunda_vuelta":
                self.refuerzo_fuera_de_lugar += sum(
                    1 for x in tanda["retos"] if x["reto"]["id"] in self.banco.de_refuerzo)
            for pendiente in tanda["repaso"]:
                self.repasar(p, dia, pendiente)
            for x in tanda["retos"]:
                if x["estado"] != "pendiente":
                    continue
                gano = self.jugar(p, dia, x["reto"]["id"])
                if p.modo == "copia" and gano is False:
                    self.jugar(p, dia, x["reto"]["id"])  # reintenta en el acto
            otra = self._ver(client.get("/challenges/tanda", headers=self._h(p.nombre)))
            if otra.status_code != 200 or not otra.json()["puede_pedir_otra"]:
                return

    def _feed(self, p: Politica) -> None:
        r = self._ver(client.get("/challenges/", headers=self._h(p.nombre)))
        if r.status_code == 200:
            self.refuerzo_fuera_de_lugar += sum(
                1 for x in r.json() if x["title"] in self.banco.titulos_de_refuerzo)

    def _racha(self, p: Politica) -> tuple[int, int]:
        c = ra.leer(self.integ, self.quienes[p.nombre])
        return (c["racha_semanas"], c["protectores"]) if isinstance(c, dict) else (-1, -1)

    def _vigilar_el_cierre(self, politicas: tuple[Politica, ...], semana: int,
                           antes: dict[str, tuple[int, int]]) -> None:
        """Una semana con un día sin contenido no puede bajar la racha ni gastar protector."""
        desde = (INICIO + timedelta(days=7 * (semana - 1))).date()
        for p in politicas:
            marcada = self.integ.valor(
                "select count(*) from activity_days where profile_id = :p and sin_contenido "
                "and local_date >= :d and local_date < :h", p=self.quienes[p.nombre], d=desde,
                h=desde + timedelta(days=7))
            ahora = self._racha(p)
            if marcada and (ahora[0] < antes[p.nombre][0] or ahora[1] < antes[p.nombre][1]):
                self.rachas_rotas_sin_contenido += 1

    def correr(self, politicas: tuple[Politica, ...], semanas: int) -> None:
        antes: dict[str, tuple[int, int]] = {}
        for dia in range(7 * semanas):
            semana, dia_de_semana = divmod(dia, 7)
            self.reloj.a(dia)
            if dia_de_semana == 0 and semana > 0:
                self._vigilar_el_cierre(politicas, semana, antes)
            for i, p in enumerate(politicas):
                self.reloj.a(dia, hora=1 + 2 * i)
                if dia_de_semana in p.asiste:
                    self.asistir(p)
                if dia_de_semana in p.practica:
                    self.practicar(p, dia)
                if dia_de_semana == 6:
                    self._feed(p)
            if dia_de_semana == 6:
                self.reloj.a(dia, hora=10)
                antes = {p.nombre: self._racha(p) for p in politicas}
        self.reloj.a(7 * semanas)  # el lunes siguiente: se cierra la última semana
        self._vigilar_el_cierre(politicas, semanas, antes)


# ------------------------------------------------------------------- la medición
def _pct(parte: int, total: int) -> float:
    return round(100.0 * parte / total, 1) if total else 0.0


def _dia_local(instante: datetime) -> str:
    return (instante - timedelta(hours=5)).date().isoformat()


def _segundos_por_dia(integ: Any, quien: UUID) -> dict[str, float]:
    """`{día: mediana de segundos entre respuestas seguidas de un mismo intento}`."""
    por_intento: dict[Any, list[datetime]] = defaultdict(list)
    for intento, cuando in l1.filas(
            integ, "select attempt_id, answered_at from challenge_attempt_answers "
                   "where profile_id = :p order by attempt_id, answered_at", p=quien):
        por_intento[intento].append(cuando)
    por_dia: dict[str, list[float]] = defaultdict(list)
    for instantes in por_intento.values():
        for a, b in zip(instantes, instantes[1:], strict=False):
            por_dia[_dia_local(b)].append((b - a).total_seconds())
    return {dia: statistics.median(v) for dia, v in por_dia.items()}


def _pagas_por_intento(integ: Any, quien: UUID) -> Counter[int]:
    """Cuántas pagas de retos cobró en su intento 1, 2, ... de cada reto."""
    orden: dict[Any, list[Any]] = defaultdict(list)
    for reto, intento in l1.filas(
            integ, "select challenge_id, id from challenge_attempts where student_id = :p "
                   "and status = 'completed' order by challenge_id, completed_at, id", p=quien):
        orden[reto].append(str(intento))
    cuenta: Counter[int] = Counter()
    for reto, intento in l1.filas(
            integ, "select l.metadata->>'challenge_id', l.metadata->>'attempt_id' "
                   "from coin_ledger l join coin_wallets w on w.id = l.to_wallet_id "
                   "where w.owner_type = 'profile' and w.owner_id = :p and l.action = "
                   "'challenge' and l.amount > 0", p=quien):
        cuenta[orden[UUID(reto)].index(intento) + 1] += 1
    return cuenta


def medir_estudiante(integ: Any, quien: UUID, semanas: int) -> dict[str, Any]:
    """Lo que el archivo guarda de UN estudiante: su resultado y sus datos de vigilancia."""
    monedas = {str(a): int(m) for a, m in l1.filas(
        integ, "select l.action, sum(l.amount) from coin_ledger l join coin_wallets w "
               "on w.id = l.to_wallet_id where w.owner_type = 'profile' and w.owner_id = :p "
               "group by 1 order by 1", p=quien)}
    total = sum(monedas.values())
    dias = l1.filas(
        integ, "select local_date, activo, via_asistencia, respuestas, correctas, "
               "primeras_correctas, por_origen, sin_contenido from activity_days "
               "where profile_id = :p order by local_date", p=quien)
    segundos = _segundos_por_dia(integ, quien)
    por_respuestas = [d for d in dias if d[1] and d[3] >= 6 and d[4] >= 4]
    dudosos = [d for d in por_respuestas
               if d[5] * 10 <= d[3] * 3 or segundos.get(d[0].isoformat(), 99.0) < 3]
    repetidos = [d for d in por_respuestas if set(d[6] or {}) == {"reto_repetido"}]
    por_semana: dict[int, list[Any]] = defaultdict(list)
    for d in dias:
        por_semana[(d[0] - INICIO.date()).days // 7].append(d)
    cumplidas = [s for s in range(semanas) if sum(1 for d in por_semana[s] if d[1]) >= 3]
    sin_respuestas = [s for s in cumplidas if sum(d[3] for d in por_semana[s]) == 0]
    pagas = _pagas_por_intento(integ, quien)
    racha = ra.leer(integ, quien)
    cola = l1.filas(
        integ, "select count(*), count(*) filter (where exists (select 1 from "
               "reinforcement_answers a where a.queue_id = q.id)) from reinforcement_queue q "
               "where q.profile_id = :p", p=quien)[0]
    repasos = l1.filas(
        integ, "select count(*), count(*) filter (where not c.solo_refuerzo) "
               "from reinforcement_answers a join challenge_questions q on q.id = "
               "a.question_id join challenges c on c.id = q.challenge_id "
               "where a.profile_id = :p", p=quien)[0]
    tandas = l1.filas(integ, "select modo, count(*) from practice_tandas where profile_id = :p "
                             "group by 1 order by 1", p=quien)
    dias_con_tanda = l1.filas(
        integ, "select count(*), count(*) filter (where n >= 2) from (select local_date, "
               "count(*) n from practice_tandas where profile_id = :p group by 1) x", p=quien)[0]
    return {
        "monedas": total, "de_donde": monedas,
        "racha": (racha["racha_semanas"], racha["mejor_racha"], racha["semanas_cumplidas"],
                  racha["protectores"]),
        "dias_activos": sum(1 for d in dias if d[1]),
        "dias_activos_solo_por_asistencia": sum(1 for d in dias if d[1] and d[2] and d[3] < 6),
        "semanas_cumplidas": cumplidas,
        "nivel_de_practica": integ.valor(
            "select nivel from practice_levels where profile_id = :p", p=quien),
        "tandas_por_modo": {str(m): int(n) for m, n in tandas},
        "dias_en_el_tope": (int(dias_con_tanda[1]), int(dias_con_tanda[0])),
        "dias_sin_contenido": sum(1 for d in dias if d[7]),
        "acierto_primer_intento_pct": _pct(sum(d[5] for d in dias), sum(d[3] for d in dias)),
        "respuestas_por_answers": int(integ.valor(
            "select count(*) from challenge_attempt_answers where profile_id = :p", p=quien)),
        "reintentos_con_gemela": int(integ.valor(
            "select count(*) from challenge_attempts where student_id = :p "
            "and served_questions is not null", p=quien)),
        "vigilancia": {
            "dias_activos_por_respuestas": len(por_respuestas),
            "dias_activos_dudosos_pct": _pct(len(dudosos), len(por_respuestas)),
            "pagas_por_intento": {str(k): v for k, v in sorted(pagas.items())},
            "pagas_en_intento_2_pct": _pct(sum(v for k, v in pagas.items() if k >= 2),
                                           sum(pagas.values())),
            "semanas_cumplidas_sin_respuestas_pct": _pct(len(sin_respuestas), len(cumplidas)),
            "bono_sobre_monedas_pct": _pct(monedas.get("streak_week", 0), total),
            "repaso_respondido_pct": _pct(int(cola[1]), int(cola[0])),
            # Cuántas respuestas del repaso fueron sobre preguntas de retos DEL FEED (no de
            # los `solo_refuerzo`): el repaso le mostró la clave de un reto que paga.
            "repasos": int(repasos[0]), "repasos_con_preguntas_del_feed": int(repasos[1]),
            "dias_activos_solo_repetidos_pct": _pct(len(repetidos), len(por_respuestas)),
        },
    }


def medir(integ: Any, sim: Simulacion, semanas: int) -> dict[str, Any]:
    """El archivo entero: los criterios (ceros) y lo de cada estudiante."""
    dobles = int(integ.valor(
        "select count(*) from (select 1 from coin_ledger where action = 'challenge' "
        "and amount > 0 group by to_wallet_id, metadata->>'challenge_id' "
        "having count(*) > 1) x"))
    huecos = l1.filas(integ, "select nivel_agotado, count(*) from practice_tandas "
                             "where nivel_agotado is not null group by 1 order by 1")
    return {
        "alembic_version": integ.valor("select version_num from alembic_version"),
        "semilla": sim.semilla, "semanas": semanas, "retos_sembrados": sim.banco.retos,
        "criterios": {
            "errores_5xx": sim.errores_5xx,
            "claves_antes_de_responder": sim.fugas,
            "retos_de_refuerzo_fuera_de_lugar": sim.refuerzo_fuera_de_lugar,
            "pagas_dobles": dobles,
            "nivel_escrito": int(integ.valor("select count(*) from confirmed_levels")),
            "rachas_rotas_sin_contenido": sim.rachas_rotas_sin_contenido,
        },
        "explicaciones_por_idioma": dict(sorted(sim.idiomas.items())),
        "huecos": {str(n): int(k) for n, k in huecos},
        "tandas_vacias": dict(sorted(sim.tandas_vacias.items())),
        "estudiantes": {nombre: medir_estudiante(integ, quien, semanas)
                        for nombre, quien in sim.quienes.items()},
    }
