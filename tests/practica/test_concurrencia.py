"""CC1 a CC3 y RA1: dos pedidos a la vez del mismo estudiante, y el reancla con SET.

`docs/ESPEC_humo_reto_del_dia.md` §4: lo que `ESPEC_practica_y_tanda.md` §10
dejó sin medir. "A la vez" son dos hilos, cada uno con su cliente; para que no
sea suerte, cada test ensancha la ventana con una pausa justo DESPUÉS del punto
donde el candado serializa. Tramposos: `tests/tramposos/test_tramposos_reto_del_dia.py`.
"""
from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import pytest

from src.challenge_engine.service import intento_formas as formas_mod
from src.practica import service as service_mod
from tests.challenge_engine import _l1 as l1
from tests.grader import _ayuda as gr
from tests.practica import _ayuda as ay
from tests.racha import _ayuda as ra
from tests.seguridad.veredictos import sembrar as sql

pytestmark = pytest.mark.integ

P = "pendiente"


def _con_pausa(mp: pytest.MonkeyPatch, modulo: Any, nombre: str, segundos: float = 0.4) -> None:
    """`modulo.nombre` espera antes de seguir: los dos pedidos quedan montados uno sobre otro."""
    buena = getattr(modulo, nombre)

    async def _lenta(*args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(segundos)
        return await buena(*args, **kwargs)

    mp.setattr(modulo, nombre, _lenta)


def _preparar(integ: Any, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, UUID, list[Any]]:
    """Un estudiante con cuatro retos y con sus filas de racha y de nivel YA creadas (ayer)."""
    ra.fijar_dia(monkeypatch, ra.dia(0))
    ay.sin_escalera(monkeypatch)
    c = gr.colegio(integ, "9A", n=1)
    ana = c.estudiantes[0]
    retos = [ay.reto(integ, c.profe, f"t{i}", 3, grupo=c.grupo, topic=f"a2-u0{i}")
             for i in (1, 2, 3, 4)]
    assert isinstance(ay.tanda(integ, ana), dict)
    ra.fijar_dia(monkeypatch, ra.dia(1))
    return c, ana, retos


def _tandas_de_hoy(integ: Any) -> int:
    return int(integ.valor("select count(*) from practice_tandas where local_date = :d",
                           d=ra.dia(1)))


def _pedir(integ: Any, quien: UUID) -> Any:
    return lambda cliente: cliente.post("/challenges/tanda", headers=integ.headers(quien))


def _enviar(integ: Any, quien: UUID, intento: str, preguntas: list[str]) -> Any:
    cuerpo = {"answers": [{"question_id": q, "answer": "A"} for q in preguntas]}
    return lambda cliente: cliente.post(f"/challenges/attempts/{intento}/submit",
                                        headers=integ.headers(quien), json=cuerpo)


def test_cc1_dos_tandas_a_la_vez(integ, monkeypatch) -> None:
    """CC1: dos `POST /challenges/tanda` a la vez dan la MISMA tanda y dejan una fila."""
    _c, ana, _retos = _preparar(integ, monkeypatch)
    _con_pausa(monkeypatch, service_mod, "_tandas_de_hoy")
    juntas = l1.a_la_vez(_pedir(integ, ana), _pedir(integ, ana))
    cuerpos = [r.json() for r in juntas if r.status_code == 200]
    observado = {
        "estados": sorted(r.status_code for r in juntas),
        "la_misma_tanda": len(cuerpos) == 2 and cuerpos[0] == cuerpos[1],
        "tandas_de_hoy": _tandas_de_hoy(integ),
        "lo_que_ve_despues": ay.corta(ay.tanda(integ, ana, "GET")),
    }
    assert observado == {
        "estados": [200, 200], "la_misma_tanda": True, "tandas_de_hoy": 1,
        "lo_que_ve_despues": ("A2", False, (1, "nuevo", "A2", [("t1", P, 10), ("t2", P, 10)],
                                            6, 0, False), 1, False, False, False),
    }, f"CC1: {observado}"


def test_cc2_dos_submit_del_mismo_intento_a_la_vez(integ, monkeypatch) -> None:
    """CC2: dos envíos a la vez del mismo intento: uno 200, el otro 409, y una paga."""
    _c, ana, retos = _preparar(integ, monkeypatch)
    reto, preguntas = retos[0]
    intento, _ = l1.intento(integ, ana, reto)
    _con_pausa(monkeypatch, formas_mod, "tiene_respuestas")
    juntas = l1.a_la_vez(_enviar(integ, ana, intento, preguntas),
                         _enviar(integ, ana, intento, preguntas))
    observado = {
        "estados": sorted(r.status_code for r in juntas),
        "pagas": l1.pagas(integ, reto), "saldo": integ.saldo("profile", ana),
        "cuenta_una_vez_para_la_racha": ra.hoy(integ, ana),
        "intentos_completados": int(integ.valor(
            "select count(*) from challenge_attempts where status = 'completed'")),
    }
    assert observado == {
        "estados": [200, 409], "pagas": [10], "saldo": 10,
        "cuenta_una_vez_para_la_racha": (3, 3, False), "intentos_completados": 1,
    }, f"CC2: {observado}"


def test_cc3_una_tanda_y_un_submit_a_la_vez(integ, monkeypatch) -> None:
    """CC3: la tanda y un `/submit` del mismo estudiante no se bloquean entre sí."""
    _c, ana, retos = _preparar(integ, monkeypatch)
    reto, preguntas = retos[2]
    intento, _ = l1.intento(integ, ana, reto)
    juntas = l1.a_la_vez(_pedir(integ, ana), _enviar(integ, ana, intento, preguntas))
    observado = {
        "estados": sorted(r.status_code for r in juntas),
        "tandas_de_hoy": _tandas_de_hoy(integ), "pagas": l1.pagas(integ, reto),
        "cuenta_para_la_racha": ra.hoy(integ, ana),
    }
    assert observado == {
        "estados": [200, 200], "tandas_de_hoy": 1, "pagas": [10],
        "cuenta_para_la_racha": (3, 3, False),
    }, f"CC3: {observado}"


def _fila(integ: Any, quien: UUID) -> Any:
    """(nivel, ancla, decisiones) GUARDADOS."""
    f = integ.fila("select nivel, ancla, decisiones from practice_levels "
                   "where profile_id = :p", p=quien)
    return None if f is None else tuple(f.values())


def test_ra1_set_confirma_despues_y_la_practica_se_reancla(integ, monkeypatch) -> None:
    """RA1: quien practicaba sin examen pasa a seguir el nivel de SET en cuanto existe."""
    ra.fijar_dia(monkeypatch, ra.dia(0))
    c = gr.colegio(integ, "9A", n=1)
    ana = c.estudiantes[0]
    a2 = [ay.reto(integ, c.profe, f"a2-{i}", 3, grupo=c.grupo, topic=f"a2-u0{i}")
          for i in (1, 2)]
    ay.reto(integ, c.profe, "a1-1", 3, grupo=c.grupo, nivel="A1", topic="a1-u01")
    b1 = ay.reto(integ, c.profe, "b1-1", 3, grupo=c.grupo, nivel="B1", topic="b1-u01")
    ay.reto(integ, c.profe, "b2-1", 3, grupo=c.grupo, nivel="B2", topic="b2-u01")
    for reto in a2:  # 6 de 6 al primer intento: sube a B1 (ventana rápida, sin examen)
        ra.jugar(integ, ana, *reto, "AAA")
    visto: dict[str, Any] = {"sin_examen_subio": (ay.nivel(integ, ana), _fila(integ, ana))}
    ay.confirmar_con_set(integ, c.tenant, ana, "A1")
    visto["la_lectura_ya_lo_dice_sin_escribir"] = (ay.nivel(integ, ana), _fila(integ, ana))
    visto["la_tanda_sale_del_nivel_de_set"] = ay.corta(ay.tanda(integ, ana))
    visto["la_fila_quedo_anclada"] = _fila(integ, ana)
    visto["la_ventana_se_vacio"] = bool(integ.valor(
        "select ventana_desde > timestamptz '2001-01-01' from practice_levels "
        "where profile_id = :p", p=ana))
    sql(integ, "update confirmed_levels set cefr = 'B2' where profile_id = :p", p=ana)
    visto["set_cambia_y_un_submit_reancla"] = (ra.jugar(integ, ana, *b1, "AAA"),
                                               _fila(integ, ana), ay.nivel(integ, ana))
    visto["la_practica_no_escribe_el_nivel"] = ay.niveles_confirmados(integ)
    assert visto == {
        "sin_examen_subio": (("B1", False), ("B1", None, 1)),
        "la_lectura_ya_lo_dice_sin_escribir": (("A1", True), ("B1", None, 1)),
        "la_tanda_sale_del_nivel_de_set": (
            "A1", True, (1, "nuevo", "A1", [("a1-1", P, 10)], 3, 0, False),
            1, False, False, False),
        "la_fila_quedo_anclada": ("A1", "A1", 1),
        "la_ventana_se_vacio": True,
        "set_cambia_y_un_submit_reancla": ((200, (True, 10)), ("B2", "B2", 1), ("B2", True)),
        "la_practica_no_escribe_el_nivel": [("B2", "set")],
    }, f"RA1: {visto}"
