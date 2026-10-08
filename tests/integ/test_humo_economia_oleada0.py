"""HE0 (humo) y RE0 (réplica) de la economía, oleada 0 — `docs/ESPEC_economia_oleada0.md` §3.4 y §3.5.

HE0: una institución con bolsa de 200.000 y un grupo de 30 (6 muy activos, 18
típicos y 6 que solo asisten) durante 4 semanas: clase martes y jueves a las
18:00 de Bogotá; en la semana 2, además, miércoles a las 19:30 y una SEGUNDA
sesión el jueves a las 19:30 (9 días de clase, 10 sesiones); 3 retos por semana
creados sin `coins_reward` ni `max_winners`; y una sesión de EVA por semana por
la puerta de eventos. Todo por las rutas HTTP y la CLI, con `random.Random(42)`.
Escribe `tests/_salida/humo_economia_oleada0.json` (en `.gitignore`) ANTES de
afirmar.

Los números de `HUMO_PREDICHO` NO salieron de una medición: son la predicción de
la espec, escrita antes del código. Si el humo da otra cosa, la predicción no se
toca: se reporta la diferencia (METODO, regla 8).

RE0 solo corre con `ENGRAMA_REPLICA_ECONOMIA=1`, con entradas que no se usaron al
desarrollar (semilla 7, 45 estudiantes, 3 semanas de lunes, miércoles y viernes,
otra configuración, una bolsa chica que cruza el umbral, una recarga a mitad y un
estudiante inscrito en dos instituciones). Sus esperados los calcula el propio
test, con su aritmética, SIN importar `economia.py`.
"""
from __future__ import annotations

import json
import logging
import os
import random
from datetime import date, timedelta
from typing import Any
from uuid import UUID

import pytest

from src.shared.config import settings
from src.shared.models import Membership
from tests.integ import _economia as sim
from tests.integ_db import RAIZ_BACKEND
from tests.onboarding import test_recarga as rec
from tests.onboarding._ayuda import sembrar_institucion
from tests.webhooks import _ayuda as eva

pytestmark = pytest.mark.integ

RUTA_HUMO_ECONOMIA = RAIZ_BACKEND / "tests" / "_salida" / "humo_economia_oleada0.json"
SEMILLA = 42
REPLICA = os.environ.get("ENGRAMA_REPLICA_ECONOMIA") == "1"
LUNES_1 = date(2026, 10, 5)  # la semana 1 del humo: martes 6 y jueves 8 de octubre

# La PREDICCIÓN de la espec (§3.4), copiada tal cual. No se ajusta.
HUMO_PREDICHO: dict[str, Any] = {
    "alembic_version": "041_refuerzo", "semilla": 42, "estudiantes": 30, "semanas": 4,
    "dias_de_clase": 9, "sesiones": 10, "retos": 12,
    "perfiles": {
        "muy_activo": {"n": 6, "asistencia": 90, "retos": 120, "eva": 80, "total": 290},
        "tipico": {"n": 18, "asistencia": 70, "retos": 40, "eva": 48, "total": 158},
        "solo_asiste": {"n": 6, "asistencia": 45, "retos": 0, "eva": 48, "total": 93}},
    "emision": {"asistencia": 2070, "retos": 1440, "eva": 1632, "total": 5142},
    "bolsa": {"emitido": 200000, "saldo": 194858, "umbral": 20000, "en_alerta": False},
    "asistencias_registradas": 300, "pagos_de_asistencia": 270, "asistencias_sin_paga": 30,
    "max_pagos_de_asistencia_por_estudiante_y_dia": 1, "mayor_pago_de_asistencia": 10,
    "pagos_de_reto": 144, "mayor_pago_de_reto": 10, "ganadores_del_reto_mas_ganado": 24,
    "aciertos_sin_paga_por_cupo": 0,
    "racha_tras_la_segunda_sesion": {"3": 30}, "racha_mas_larga": 3,
    "eva_no_acreditadas_por_tope": 24, "descuadre": 0,
}

ACCIONES = {"asistencia": "attendance", "retos": "challenge", "eva": "live"}


@pytest.fixture(autouse=True)
def _apagar_los_secretos_al_terminar() -> Any:
    yield
    eva.soltar()


def _calendario_del_humo() -> list[tuple[date, int, int, str]]:
    """(día, hora, minuto, tipo) de las 10 sesiones, en orden."""
    sesiones: list[tuple[date, int, int, str]] = []
    for semana in range(4):
        lunes = LUNES_1 + timedelta(weeks=semana)
        sesiones.append((lunes + timedelta(days=1), 18, 0, "martes"))
        if semana == 1:  # tres días seguidos, y el jueves dos sesiones
            sesiones.append((lunes + timedelta(days=2), 19, 30, "miercoles"))
        sesiones.append((lunes + timedelta(days=3), 18, 0, "jueves"))
        if semana == 1:
            sesiones.append((lunes + timedelta(days=3), 19, 30, "segunda"))  # ya es viernes en UTC
    return sesiones


def _es_puntual(perfil: str, tipo: str) -> bool:
    """Muy activo: siempre. Típico: martes y miércoles. Solo asiste: nunca. A la 2.ª, todos."""
    return tipo == "segunda" or perfil == sim.MUY_ACTIVO or (
        perfil == sim.TIPICO and tipo != "jueves")


def _sesion_de_eva(c: eva.Clase, perfil_de: dict[UUID, str], semana: int) -> int:
    """El lote de una clase en vivo: 12 + 8 + 4 los muy activos, 12 los demás. Devuelve los no acreditados."""
    sesion = f"humo-e0-eva-{semana}"
    eventos = [c.de_eva("live.session.started", sesion=sesion)]
    for n, alumno in enumerate(c.estudiantes):
        montos = (12, 8, 4) if perfil_de[alumno] == sim.MUY_ACTIVO else (12,)
        eventos += [c.monedas(m, n=n, sesion=sesion, sufijo=f"-{k}") for k, m in enumerate(montos)]
    eventos.append(c.de_eva("live.session.closed", sesion=sesion))
    visto = eva.resumen(eva.enviar("live", eva.lote(eventos, batch_id=sesion, sesion=sesion)))
    return sum(1 for _, motivo in visto[4] if motivo == "session_cap_exceeded") \
        if len(visto) == 5 else -1


def _retos_de_la_semana(integ: Any, rng: random.Random, docente: UUID, grupo: UUID,
                        perfil_de: dict[UUID, str], semana: int) -> list[dict[str, Any]]:
    """3 retos de 5 preguntas; el ORDEN en que se envían lo decide la semilla."""
    retos = [sim.crear_reto(integ, rng, docente, grupo, f"Semana {semana + 1}, reto {k}",
                            preguntas=5)[1] for k in (1, 2, 3)]
    tareas: list[tuple[UUID, int, bool]] = []  # (estudiante, reto, ¿falla una?)
    for alumno, perfil in perfil_de.items():
        if perfil == sim.MUY_ACTIVO:
            tareas += [(alumno, k, False) for k in range(3)]
        elif perfil == sim.TIPICO:  # el 1 perfecto; el 2 con 4 de 5 en sus dos intentos
            tareas += [(alumno, 0, False), (alumno, 1, True), (alumno, 1, True)]
    rng.shuffle(tareas)
    resultados = []
    for alumno, k, falla in tareas:
        reto = retos[k]
        if reto is None:
            resultados.append({"estado": "reto no creado"})
            continue
        resultados.append(sim.intentar(integ, alumno, reto,
                                       falla=rng.randrange(5) if falla else None))
    return resultados


def test_he0_humo_cuatro_semanas_con_treinta_estudiantes(integ, monkeypatch, capsys) -> None:
    rng = random.Random(SEMILLA)
    monkeypatch.delenv("BOLSA_UMBRAL_ALERTA_PCT", raising=False)
    eva.preparar()
    tenant = sembrar_institucion(integ, "humo-e0", pool=200_000)
    grupo = integ.crear_grupo(tenant, "G1")
    docente = integ.crear_perfil(tenant, rol="teacher", group_code="G1")
    alumnos = [integ.crear_perfil(tenant, group_code="G1") for _ in range(30)]
    perfil_de = sim.repartir(rng, alumnos, (6, 18, 6))
    clase = eva.Clase(tenant, docente, alumnos)

    calendario = _calendario_del_humo()
    racha_tras_la_segunda: dict[str, int] = {}
    for dia, hora, minuto, tipo in calendario:
        puntuales = {a: _es_puntual(p, tipo) for a, p in perfil_de.items()}
        sim.pasar_lista(integ, monkeypatch, rng, docente, sim.a_las(dia, hora, minuto), puntuales,
                        limite_s=5 * 60)
        if tipo == "segunda":
            racha_tras_la_segunda = {str(r): n for r, n in sim.rachas(integ, alumnos).items()}
    no_acreditadas, resultados = 0, []
    for semana in range(4):
        no_acreditadas += _sesion_de_eva(clase, perfil_de, semana)
        resultados += _retos_de_la_semana(integ, rng, docente, grupo, perfil_de, semana)

    emitido = sim.emision(integ, tenant)
    bolsa = rec.cli(capsys, integ, ["bolsa", "--slug", "humo-e0"])[1]
    saldos = sum(int(integ.saldo("profile", a) or 0) for a in alumnos)
    datos = {
        "alembic_version": integ.valor("select version_num from alembic_version"),
        "semilla": SEMILLA, "estudiantes": len(alumnos), "semanas": 4,
        "dias_de_clase": len({d for d, *_ in calendario}), "sesiones": len(calendario),
        "retos": int(integ.valor("select count(*) from challenges where tenant_id = :t",
                                 t=tenant)),
        "perfiles": sim.por_perfil(perfil_de, sim.cobrado(integ, tenant), ACCIONES),
        "emision": {**{rubro: emitido[accion] for rubro, accion in ACCIONES.items()},
                    "total": sum(emitido.values())},
        "bolsa": {k: bolsa.get(k) for k in ("emitido", "saldo", "umbral", "en_alerta")},
        **sim.asistencia_en_numeros(integ, tenant),
        "ganadores_del_reto_mas_ganado": int(integ.valor(
            "select max(current_winners) from challenges where tenant_id = :t", t=tenant) or 0),
        "aciertos_sin_paga_por_cupo": sim.sin_paga(resultados),
        "racha_tras_la_segunda_sesion": racha_tras_la_segunda,
        "racha_mas_larga": int(integ.valor(
            "select max(longest_streak) from profiles where id = any(:ids)", ids=alumnos) or 0),
        "eva_no_acreditadas_por_tope": no_acreditadas,
        "descuadre": int(bolsa.get("emitido") or 0) - int(bolsa.get("saldo") or 0) - saldos,
    }
    # Primero se escribe (para poder reportarlo), después se afirma.
    RUTA_HUMO_ECONOMIA.parent.mkdir(parents=True, exist_ok=True)
    RUTA_HUMO_ECONOMIA.write_text(
        json.dumps(datos, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    assert datos == HUMO_PREDICHO, f"HE0: {datos}"


# =============================================================================
# RE0 — la réplica, con entradas nuevas
# =============================================================================
R_BASE, R_BONO, R_MINUTOS, R_TOPE, R_PCT = 4, 3, 10, 15, 25
R_BOLSA, R_RECARGA, R_N = 3000, 2000, (9, 27, 9)
R_LUNES_1 = date(2026, 11, 2)


def _avisos(caplog: Any, tenant: UUID) -> list[tuple[int, int]]:
    """(umbral, emitido) de cada línea `bolsa_baja` de esa institución, en orden."""
    lineas = []
    for registro in caplog.records:
        campos = dict(p.split("=", 1) for p in registro.getMessage().split()[1:] if "=" in p)
        if registro.name == "engrama.economia" and campos.get("institucion") == str(tenant):
            lineas.append((int(campos["umbral"]), int(campos["emitido"])))
    return lineas


def _replica_configurada(mp: pytest.MonkeyPatch) -> None:
    for nombre, valor in (("asistencia_monedas_base", R_BASE), ("reto_monedas_tope", R_TOPE),
                          ("asistencia_monedas_puntualidad", R_BONO), ("reto_ganadores_piso", 1),
                          ("asistencia_minutos_puntualidad", R_MINUTOS),
                          ("bolsa_umbral_alerta_pct", R_PCT)):
        mp.setattr(settings, nombre, valor)
    mp.setenv("BOLSA_UMBRAL_ALERTA_PCT", str(R_PCT))  # la CLI lo lee del entorno
    mp.delenv("BOLSA_RECARGA_MAXIMA", raising=False)


@pytest.mark.skipif(not REPLICA, reason="réplica de la economía: ENGRAMA_REPLICA_ECONOMIA=1")
def test_re0_replica_otra_configuracion_bolsa_chica_y_dos_instituciones(
        integ, monkeypatch, capsys, caplog) -> None:
    rng = random.Random(7)
    caplog.set_level(logging.WARNING, logger="engrama.economia")
    _replica_configurada(monkeypatch)
    a = sembrar_institucion(integ, "rep-a", pool=R_BOLSA)
    b = sembrar_institucion(integ, "rep-b", pool=500)
    grupo_a = integ.crear_grupo(a, "G1")
    integ.crear_grupo(b, "G1")
    profe_a = integ.crear_perfil(a, rol="teacher", group_code="G1")
    profe_b = integ.crear_perfil(b, rol="teacher", group_code="G1")
    alumnos = [integ.crear_perfil(a, group_code="G1") for _ in range(sum(R_N))]
    perfil_de = sim.repartir(rng, alumnos, R_N)
    doble = next(x for x, p in perfil_de.items() if p == sim.SOLO_ASISTE)
    integ._insertar(Membership(tenant_id=b, profile_id=doble, role="student", group_code="G1",
                               is_active=True, full_name="Persona doble"))
    rechazo_16 = sim.crear_reto(integ, rng, profe_a, grupo_a, "sobre el tope", preguntas=3,
                                coins_reward=R_TOPE + 1)[0]
    cupos, resultados, recargas = [], [], []
    for semana in range(3):
        lunes = R_LUNES_1 + timedelta(weeks=semana)
        for desfase, tipo in ((0, "lunes"), (2, "miercoles"), (4, "viernes")):
            puntuales = {x: p == sim.MUY_ACTIVO or (p == sim.TIPICO and tipo == "lunes")
                         for x, p in perfil_de.items()}
            dia = lunes + timedelta(days=desfase)
            sim.pasar_lista(integ, monkeypatch, rng, profe_a, sim.a_las(dia, 18), puntuales,
                            limite_s=R_MINUTOS * 60)
            if (semana, tipo) == (1, "miercoles"):  # la doble sesión: todos puntuales, paga 0
                sim.pasar_lista(integ, monkeypatch, rng, profe_a, sim.a_las(dia, 19, 30),
                                dict.fromkeys(alumnos, True), limite_s=R_MINUTOS * 60)
            if (semana, tipo) == (0, "lunes"):  # el mismo día, el doble marca también en B
                inicio = sim.a_las(dia, 18)
                codigo_b = sim.abrir_sesion(integ, monkeypatch, profe_b, inicio, minutos=30)
                sim.llegar(integ, monkeypatch, doble, codigo_b, inicio + timedelta(seconds=30), b)
        retos = [sim.crear_reto(integ, rng, profe_a, grupo_a, f"Réplica {semana}-{k}",
                                preguntas=3, coins_reward=R_TOPE)[1] for k in (1, 2)]
        if semana == 2:  # uno insertado a mano con 50: paga el tope (15)
            cid, qids = integ.crear_challenge(a, profe_a, respuestas=("A", "B", "A"), coins=50,
                                              group_id=grupo_a, max_winners=sum(R_N))
            retos.append(sim.Reto(cid, qids, ["A", "B", "A"]))
        cupos += [r.cupo for r in retos[:2] if r is not None]
        tareas = [(x, r) for x, p in perfil_de.items() for k, r in enumerate(retos)
                  if r is not None and (p == sim.MUY_ACTIVO or (p == sim.TIPICO and k == 0))]
        rng.shuffle(tareas)
        resultados += [sim.intentar(integ, x, r, tenant=a) for x, r in tareas]
        if semana == 1:  # la recarga a mitad, y su repetición
            orden = rec.orden(slug="rep-a", monedas=R_RECARGA, referencia="REP-1")
            recargas = [rec.cli(capsys, integ, orden), rec.cli(capsys, integ, orden)]

    # Los esperados, con la aritmética del test (no se importa `economia.py`).
    asistencia = {sim.MUY_ACTIVO: 9 * (R_BASE + R_BONO),
                  sim.TIPICO: 3 * (R_BASE + R_BONO) + 6 * R_BASE, sim.SOLO_ASISTE: 9 * R_BASE}
    retos_de = {sim.MUY_ACTIVO: 7 * R_TOPE, sim.TIPICO: 3 * R_TOPE, sim.SOLO_ASISTE: 0}
    n_de = dict(zip(sim.PERFILES, R_N, strict=True))
    total = sum(n_de[p] * (asistencia[p] + retos_de[p]) for p in sim.PERFILES)
    semana_normal = (total - n_de[sim.MUY_ACTIVO] * R_TOPE) // 3  # sin el reto de 50
    tras_dos = R_BOLSA - 2 * semana_normal
    emitido_final = R_BOLSA + R_RECARGA
    umbrales = (R_BOLSA * R_PCT // 100, emitido_final * R_PCT // 100)
    final = emitido_final - total
    esperado = {
        "crear con 16": 422, "cupos": [sum(R_N)] * 6,
        "perfiles": {p: {"n": n_de[p], "asistencia": asistencia[p], "retos": retos_de[p],
                         "total": asistencia[p] + retos_de[p]} for p in sim.PERFILES},
        "emision": {"attendance": sum(n_de[p] * asistencia[p] for p in sim.PERFILES),
                    "challenge": sum(n_de[p] * retos_de[p] for p in sim.PERFILES)},
        "asistencias": (sum(R_N) * 10, sum(R_N) * 9, sum(R_N), 1, R_BASE + R_BONO),
        "mayor_pago_de_reto": R_TOPE, "aciertos_sin_paga_por_cupo": 0,
        "recargas": [(0, {"institucion": "rep-a", "recargado": R_RECARGA,
                          "saldo": tras_dos + R_RECARGA, "emitido": emitido_final,
                          "repetida": False}),
                     (0, {"institucion": "rep-a", "recargado": 0, "saldo": tras_dos + R_RECARGA,
                          "emitido": emitido_final, "repetida": True})],
        "avisos": [(umbrales[0], R_BOLSA), (umbrales[1], emitido_final)],
        "bolsa": (3, {"institucion": "rep-a", "saldo": final, "emitido": emitido_final,
                      "umbral": umbrales[1], "porcentaje": R_PCT, "en_alerta": True}),
        "descuadre": 0,
        "el doble en B": ({"attendance": R_BASE + R_BONO}, 500 - (R_BASE + R_BONO), 1),
    }
    numeros = sim.asistencia_en_numeros(integ, a)
    bolsa = rec.cli(capsys, integ, ["bolsa", "--slug", "rep-a"])
    observado = {
        "crear con 16": rechazo_16, "cupos": cupos,
        "perfiles": sim.por_perfil(perfil_de, sim.cobrado(integ, a),
                                   {"asistencia": "attendance", "retos": "challenge"}),
        "emision": dict(sim.emision(integ, a)),
        "asistencias": tuple(numeros[k] for k in (
            "asistencias_registradas", "pagos_de_asistencia", "asistencias_sin_paga",
            "max_pagos_de_asistencia_por_estudiante_y_dia", "mayor_pago_de_asistencia")),
        "mayor_pago_de_reto": numeros["mayor_pago_de_reto"],
        "aciertos_sin_paga_por_cupo": sim.sin_paga(resultados),
        "recargas": recargas, "avisos": _avisos(caplog, a), "bolsa": bolsa,
        "descuadre": emitido_final - int(bolsa[1].get("saldo") or 0)
        - sum(sim.emision(integ, a).values()),
        "el doble en B": (dict(sim.cobrado(integ, b).get(doble, {})), integ.saldo("tenant", b),
                          sim.asistencia_en_numeros(integ, b)["asistencias_registradas"]),
    }
    assert observado == esperado, f"RE0: {observado}"
