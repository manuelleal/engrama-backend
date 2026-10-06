"""Los efectos: el nivel confirmado y las monedas — `docs/ESPEC_eventos_anillo.md` C9 a C15.

  NV1  C9, C10   SET confirma el nivel y `/auth/me` lo trae; gana la medición más reciente.
  NV3  C11, C12  a quién le toca (su institución, un estudiante) y qué puede emitir cada origen.
  NV5  C13       el juego y la clase en vivo NO mueven el nivel.
  MC1  C14, C15  la bolsa agotada y el tope de 20 por sesión: el evento se guarda, no se paga.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from tests.seguridad.veredictos import sembrar
from tests.webhooks import _ayuda as ay

pytestmark = pytest.mark.integ

T0 = ay.HACE_DOS_DIAS


def _fecha(visto: Any) -> Any:
    if not isinstance(visto, dict) or not isinstance(visto.get("assessed_at"), str):
        return None
    return datetime.fromisoformat(visto["assessed_at"].replace("Z", "+00:00"))


# =============================================================================
# NV1 — C9 y C10
# =============================================================================
def test_nv1_set_confirma_el_nivel_y_gana_el_mas_reciente(integ) -> None:
    """NV1 (C9, C10): null -> B1 provisional; uno anterior no lo baja; uno posterior, sí."""
    ay.preparar()
    c = ay.clase(integ)
    ana = c.estudiantes[0]
    antes = ay.nivel(integ, ana)
    b1 = ay.de_set(c.tenant, ana, "B1", cuando=T0)
    primero = ay.cortos(ay.enviar("set", ay.lote_de_set(b1)))
    en_me, en_session = ay.nivel(integ, ana), ay.nivel(integ, ana, "/auth/session")
    confirmado = {
        "antes": antes, "respuesta": primero,
        "me": (ay.nivel_corto(integ, ana), sorted(en_me) if isinstance(en_me, dict) else en_me,
               _fecha(en_me) == T0),
        "session_igual_a_me": en_session == en_me,
        "repetido": ay.cortos(ay.enviar("set", ay.lote_de_set(b1))),
    }
    pasos = {
        "uno_anterior": (ay.de_set(c.tenant, ana, "A2", cuando=T0 - timedelta(days=1),
                                   intento="1000"), None),
        "uno_posterior": (ay.de_set(c.tenant, ana, "B2", cuando=T0 + timedelta(hours=1),
                                    provisional=False, intento="2000"), None),
        "misma_fecha_llega_despues": (ay.de_set(c.tenant, ana, "C1", provisional=False,
                                                cuando=T0 + timedelta(hours=1),
                                                intento="2001"), None),
    }
    mas_reciente = {}
    for nombre, (evento, _) in pasos.items():
        mas_reciente[nombre] = (ay.cortos(ay.enviar("set", ay.lote_de_set(evento))),
                                ay.nivel_corto(integ, ana))
    observado = {"confirmado": confirmado, "mas_reciente": mas_reciente,
                 "efectos": [e for e, _ in ay.efectos(integ)],
                 "filas_de_nivel": int(integ.valor("select count(*) from confirmed_levels"))}
    ok: tuple[Any, ...] = (200, 1, 0, [], [])
    assert observado == {
        "confirmado": {
            "antes": None, "respuesta": ok,
            "me": (("B1", "set", True), ["assessed_at", "cefr", "provisional", "source"], True),
            "session_igual_a_me": True, "repetido": (200, 0, 1, [], [])},
        "mas_reciente": {"uno_anterior": (ok, ("B1", "set", True)),
                         "uno_posterior": (ok, ("B2", "set", False)),
                         "misma_fecha_llega_despues": (ok, ("C1", "set", False))},
        "efectos": ["level_set", "level_older", "level_set", "level_set"], "filas_de_nivel": 1,
    }, f"NV1: {observado}"


# =============================================================================
# NV3 — C11 y C12
# =============================================================================
def test_nv3_a_quien_le_toca_y_que_emite_cada_origen(integ) -> None:
    """NV3 (C11, C12): el nivel es del estudiante en SU institución; cada origen, lo suyo."""
    ay.preparar()
    a, b = ay.clase(integ, estudiantes=2), ay.clase(integ)
    ana, otro = a.estudiantes
    sembrar(integ, "insert into memberships (tenant_id, profile_id, role, group_code, "
                   "is_active, full_name) values (:t, :p, 'student', 'G1', true, 'Ana en B')",
            t=b.tenant, p=ana)
    ajenos = {
        "de_otra_institucion": ay.de_set(a.tenant, b.estudiantes[0]),
        "un_docente": ay.de_set(a.tenant, a.profe),
        "inexistente": ay.de_set(a.tenant, uuid4()),
    }
    sujetos = {n: ay.cortos(ay.enviar("set", ay.lote_de_set(e))) for n, e in ajenos.items()}
    sin_escribir = int(integ.valor("select count(*) from confirmed_levels"))
    bueno = ay.cortos(ay.enviar("set", ay.lote_de_set(ay.de_set(a.tenant, ana))))
    se_ve = {"ana_en_a": ay.nivel_corto(integ, ana),
             "ana_desde_b": ay.nivel(integ, ana, **{"X-Tenant-ID": str(b.tenant)}),
             "otro_estudiante_de_a": ay.nivel(integ, otro)}
    manana = datetime.now(UTC) + timedelta(days=1)
    por_origen = {
        "set_emite_monedas": ay.cortos(ay.enviar("set", ay.lote([
            {**a.monedas(5), "source": "set"}]))),
        "set_emite_monedas_como_live": ay.cortos(ay.enviar("set", ay.lote([a.monedas(5, n=1)]))),
        "live_emite_nivel": ay.cortos(ay.enviar("live", ay.lote([
            ay.de_set(a.tenant, otro, "C2")]))),
        "invalidos": ay.cortos(ay.enviar("set", ay.lote_de_set(
            ay.de_set(a.tenant, otro, "B3", intento="i1"),
            ay.de_set(a.tenant, otro, score_total=101, intento="i2"),
            ay.de_set(a.tenant, otro, estado="estimado", intento="i3"),
            ay.de_set(a.tenant, otro, cuando=manana, intento="i4")))),
    }
    observado = {"sujetos": sujetos, "sin_escribir": sin_escribir, "el_bueno": bueno,
                 "se_ve": se_ve, "por_origen": por_origen,
                 "saldos": [ay.saldo(integ, p) for p in a.estudiantes],
                 "nivel_del_otro": ay.nivel(integ, otro)}

    def rechazo(*motivos: str) -> tuple[Any, ...]:
        return (200, 0, 0, list(motivos), [])

    assert observado == {
        "sujetos": dict.fromkeys(ajenos, rechazo("unknown_subject")), "sin_escribir": 0,
        "el_bueno": (200, 1, 0, [], []),
        "se_ve": {"ana_en_a": ("B1", "set", True), "ana_desde_b": None,
                  "otro_estudiante_de_a": None},
        "por_origen": {"set_emite_monedas": rechazo("unknown_type"),
                       "set_emite_monedas_como_live": rechazo("unknown_type"),
                       "live_emite_nivel": rechazo("unknown_type"),
                       "invalidos": rechazo(*["invalid_event"] * 4)},
        "saldos": [0, 0], "nivel_del_otro": None,
    }, f"NV3: {observado}"


# =============================================================================
# NV5 — C13
# =============================================================================
def _ganar_un_reto(integ: Any, c: ay.Clase, alumno: Any) -> tuple[int, Any]:
    """El estudiante gana un reto por `/submit` (cobra monedas y XP)."""
    reto, preguntas = integ.crear_challenge(c.tenant, c.profe, coins=20, xp=15)
    intento = integ.crear_intento(c.tenant, reto, alumno, status="in_progress")
    r = ay.client.post(
        f"/challenges/attempts/{intento}/submit", headers=integ.headers(alumno),
        json={"answers": [{"question_id": str(q), "answer": x}
                          for q, x in zip(preguntas, ("A", "B"), strict=True)]})
    return r.status_code, (ay.cuerpo_json(r) or {}).get("coins_earned")


def test_nv5_el_juego_y_la_clase_en_vivo_no_mueven_el_nivel(integ) -> None:
    """NV5 (C13): un reto ganado, 100 aciertos en vivo y monedas: el nivel queda idéntico."""
    ay.preparar()
    c = ay.clase(integ, estudiantes=2)
    con_nivel, sin_nivel = c.estudiantes
    ay.enviar("set", ay.lote_de_set(ay.de_set(c.tenant, con_nivel, "B1")))
    antes = ay.nivel(integ, con_nivel)
    retos = [_ganar_un_reto(integ, c, p) for p in c.estudiantes]
    xp_tras_el_reto = [integ.valor("select xp from profiles where id = :p", p=p)
                       for p in c.estudiantes]
    en_vivo = []
    for n in (0, 1):
        aciertos = [c.de_eva("answer.submitted", n=n, sufijo=f"-{i}") for i in range(100)]
        en_vivo.append(ay.cortos(ay.enviar("live", ay.lote([*aciertos, c.monedas(5, n=n)]))))
    observado = {
        "retos_ganados": retos, "en_vivo": en_vivo,
        "nivel_identico": ay.nivel(integ, con_nivel) == antes and isinstance(antes, dict),
        "el_que_no_tenia": ay.nivel(integ, sin_nivel),
        "saldos": [ay.saldo(integ, p) for p in c.estudiantes],
        "xp_igual_que_tras_el_reto": [integ.valor("select xp from profiles where id = :p", p=p)
                                      for p in c.estudiantes] == xp_tras_el_reto,
        "filas_de_nivel": int(integ.valor("select count(*) from confirmed_levels")),
    }
    assert observado == {
        "retos_ganados": [(200, 20), (200, 20)], "en_vivo": [(200, 101, 0, [], [])] * 2,
        "nivel_identico": True, "el_que_no_tenia": None, "saldos": [25, 25],
        "xp_igual_que_tras_el_reto": True, "filas_de_nivel": 1,
    }, f"NV5: {observado}"


# =============================================================================
# MC1 — C14 y C15
# =============================================================================
def test_mc1_bolsa_agotada_y_tope_por_sesion(integ) -> None:
    """MC1 (C14, C15): sin bolsa o pasado el tope, el evento se guarda y no se paga."""
    ay.preparar()
    pobre = ay.clase(integ, pool=5)
    p = pobre.estudiantes[0]
    de_10 = pobre.monedas(10)
    r = ay.enviar("live", ay.lote([de_10]))
    bolsa = {
        "de_10_con_5_en_la_bolsa": ay.resumen(r),
        "guardado_sin_pagar": (ay.efectos(integ), ay.saldo(integ, p), ay.libro(integ)),
        "de_5": ay.cortos(ay.enviar("live", ay.lote([pobre.monedas(5, sufijo="-b")]))),
        "saldo_y_bolsa": (ay.saldo(integ, p), integ.saldo("tenant", pobre.tenant)),
    }
    c = ay.clase(integ, estudiantes=2)
    a, b = c.estudiantes
    hasta_20 = ay.cortos(ay.enviar("live", ay.lote([c.monedas(12), c.monedas(8, sufijo="-b")])))
    uno_mas = c.monedas(1, sufijo="-c")
    tope = {
        "doce_y_ocho": (hasta_20, ay.saldo(integ, a)),
        "uno_mas": (ay.resumen(ay.enviar("live", ay.lote([uno_mas]))), ay.saldo(integ, a)),
        "en_otra_sesion": (ay.cortos(ay.enviar("live", ay.lote(
            [c.monedas(5, sesion="aula-2")], sesion="aula-2"))), ay.saldo(integ, a)),
        "a_otro_estudiante": (ay.cortos(ay.enviar("live", ay.lote([c.monedas(20, n=1)]))),
                              ay.saldo(integ, b)),
    }
    observado = {"bolsa": bolsa, "tope": tope}
    ok: tuple[Any, ...] = (200, 1, 0, [], [])
    assert observado == {
        "bolsa": {
            "de_10_con_5_en_la_bolsa": (200, 1, 0, [], [(de_10["event_id"], "pool_exhausted")]),
            "guardado_sin_pagar": ([("pool_exhausted", 0)], 0, []), "de_5": ok,
            "saldo_y_bolsa": (5, 0)},
        "tope": {
            "doce_y_ocho": ((200, 2, 0, [], []), 20),
            "uno_mas": ((200, 1, 0, [], [(uno_mas["event_id"], "session_cap_exceeded")]), 20),
            "en_otra_sesion": (ok, 25), "a_otro_estudiante": (ok, 20)},
    }, f"MC1: {observado}"
