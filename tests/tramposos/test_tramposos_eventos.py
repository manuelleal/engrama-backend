"""Tramposos ZE1-ZE19 de los eventos del anillo — `docs/ESPEC_eventos_anillo.md` §3 y §4.

Una versión ROTA a propósito, inyectada con monkeypatch en el módulo donde se
USA; se corre el cuerpo del test real y se exige `AssertionError` con el
mensaje del mecanismo. Aquí se automatiza la DIAGONAL; la matriz completa se
mide aparte (ERR-15, 19 y 23). ZE18, ZE19 y ZE20 (§12) son no-integ (no piden `integ`).
"""
from __future__ import annotations

import inspect
import json
import threading
from collections.abc import Callable, Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.engrama_core.service import coins as coins_mod
from src.engrama_core.service import level as level_mod
from src.shared import config as config_mod
from src.shared import events as events_mod
from src.shared.models import ConfirmedLevel, LearningEvent
from src.webhooks import efectos as efectos_mod
from src.webhooks import router as router_mod
from src.webhooks import service as service_mod
from src.webhooks.schemas import ResumenOut
from tests.webhooks import _ayuda as ay
from tests.webhooks import test_efectos as te
from tests.webhooks import test_lote as tl
from tests.webhooks import test_unit as tu

Aplicar = Callable[[pytest.MonkeyPatch], None]

_YA_ESTABA = service_mod._ya_estaba
_GUARDAR = service_mod._guardar
_APLICAR = efectos_mod.aplicar
_VERIFICAR = events_mod.verificar
_REGISTRAR_NIVEL = level_mod.record_confirmed_level


@pytest.fixture(autouse=True)
def _apagar_los_secretos_al_terminar() -> Iterator[None]:
    yield
    ay.soltar()


def _parche(modulo: Any, nombre: str, valor: Any) -> Aplicar:
    return lambda mp: mp.setattr(modulo, nombre, valor)


def _varios(*aplicar: Aplicar) -> Aplicar:
    def todos(mp: pytest.MonkeyPatch) -> None:
        for uno in aplicar:
            uno(mp)
    return todos


# --- ZE2: toda fila es nueva ---------------------------------------------------
async def _guardar_siempre(db: AsyncSession, origen: str, lote: Any, evento: Any, huella: str,
                           session_id: str | None) -> int | None:
    """La llave de la fila lleva sal: nunca choca, así que nada es duplicado."""
    con_sal = evento.model_copy(update={"event_id": f"{evento.event_id}#{uuid4().hex[:8]}"})
    return await _GUARDAR(db, origen, lote, con_sal, huella, session_id)


# --- ZE3: los duplicados repiten el efecto, y la paga va sin llave -----------
async def _duplicado_con_efecto(db: AsyncSession, evento: Any, huella: str) -> Any:
    resultado = await _YA_ESTABA(db, evento, huella)
    if resultado.que == service_mod.DUPLICADO:
        await _APLICAR(db, evento, service_mod._payload(evento), 0)
    return resultado


async def _pagar_sin_llave(db: AsyncSession, evento: Any, datos: Any) -> str:
    await coins_mod.award_coins(db, student_id=evento.subject_id, tenant_id=evento.tenant_id,
                                amount=datos.amount, action="live", metadata={})
    return efectos_mod.ACREDITADO


# --- ZE4: la firma se comprueba sobre el JSON vuelto a escribir ---------------
def _firma_sobre_el_json_reescrito(secreto: str, timestamp: str, cuerpo: bytes,
                                   firma: str) -> bool:
    try:
        reescrito = json.dumps(json.loads(cuerpo)).encode()
    except ValueError:
        return False
    return _VERIFICAR(secreto, timestamp, reescrito, firma, ahora=router_mod._ahora())


# --- ZE7: el conflicto sobrescribe ---------------------------------------------
async def _conflicto_sobrescribe(db: AsyncSession, evento: Any, huella: str) -> Any:
    await db.execute(update(LearningEvent)
                     .where(LearningEvent.tenant_id == evento.tenant_id,
                            LearningEvent.event_id == evento.event_id)
                     .values(payload=evento.payload, body_hash=huella))
    return service_mod.Resultado(service_mod.ACEPTADO, evento.event_id)


# --- ZE8: lote todo o nada -----------------------------------------------------
async def _todo_o_nada(db: AsyncSession, origen: str, lote: Any) -> ResumenOut:
    for crudo in lote.events:
        evento = service_mod._leer(crudo)
        if evento is None or service_mod._motivo_de_forma(origen, evento) is not None:
            raise HTTPException(status_code=422, detail="lote rechazado entero")
    return service_mod.resumir([await service_mod.procesar_evento(db, origen, lote, c)
                                for c in lote.events])


# --- ZE9: comprobar y después insertar, sin ON CONFLICT ------------------------
def _comprobar_e_insertar() -> Aplicar:
    barrera = threading.Barrier(2, timeout=3)

    async def guardar(db: AsyncSession, origen: str, lote: Any, evento: Any, huella: str,
                      session_id: str | None) -> int | None:
        existe = (await db.execute(select(LearningEvent.id).where(
            LearningEvent.tenant_id == evento.tenant_id,
            LearningEvent.event_id == evento.event_id))).scalar_one_or_none()
        if existe is not None:
            return None
        try:
            barrera.wait()  # los dos lotes ya comprobaron: ninguno vio al otro
        except threading.BrokenBarrierError:
            pass
        return int((await db.execute(pg_insert(LearningEvent).values(
            tenant_id=evento.tenant_id, event_id=evento.event_id, origin=origen,
            source=evento.source, type=evento.type, subject_id=evento.subject_id,
            item_ref=evento.item_ref, payload=evento.payload, occurred_at=evento.occurred_at,
            schema_version=1, body_hash=huella, batch_id=lote.batch_id, instance=lote.instance,
            session_id=session_id).returning(LearningEvent.id))).scalar_one())

    return _parche(service_mod, "_guardar", guardar)


# --- ZE10 a ZE14: el nivel -----------------------------------------------------
async def _cualquier_sujeto(db: AsyncSession, tenant_id: UUID, subject_id: UUID | None,
                            sujeto: str) -> bool:
    return True


async def _el_ultimo_que_llega_gana(db: AsyncSession, **datos: Any) -> bool:
    """ZE11: sin mirar la fecha, el evento que llega pisa el nivel."""
    await db.execute(update(ConfirmedLevel)
                     .where(ConfirmedLevel.tenant_id == datos["tenant_id"],
                            ConfirmedLevel.profile_id == datos["profile_id"])
                     .values(assessed_at=datos["assessed_at"]))
    return await _REGISTRAR_NIVEL(db, **datos)


def _regla_de_cualquier_origen(origen: str, tipo: str) -> Any:
    """ZE12: si algún origen puede emitir ese tipo, todos pueden."""
    for reglas in events_mod.PERMITIDOS.values():
        if tipo in reglas:
            return reglas[tipo]
    return None


async def _nivel_sin_institucion(db: AsyncSession, profile_id: UUID,
                                 tenant_id: UUID) -> ConfirmedLevel | None:
    return (await db.execute(select(ConfirmedLevel).where(
        ConfirmedLevel.profile_id == profile_id).limit(1))).scalar_one_or_none()


async def _los_aciertos_en_vivo_suben_el_nivel(db: AsyncSession, evento: Any, payload: Any,
                                               fila_id: int) -> tuple[str, int]:
    """ZE14: un acierto en la clase en vivo "confirma" C2."""
    if evento.type == events_mod.ANSWER_SUBMITTED and evento.payload.get("correct"):
        await _REGISTRAR_NIVEL(
            db, tenant_id=evento.tenant_id, profile_id=evento.subject_id, cefr="C2",
            source="set", provisional=False, score=None, assessed_at=evento.occurred_at,
            event_row_id=fila_id)
    return await _APLICAR(db, evento, payload, fila_id)


# --- ZE16: la bolsa agotada tumba el evento ------------------------------------
async def _pagar_sin_savepoint(db: AsyncSession, evento: Any, datos: Any) -> str:
    await coins_mod.award_coins(
        db, student_id=evento.subject_id, tenant_id=evento.tenant_id, amount=datos.amount,
        action="live", metadata={}, idempotency_key=f"event:{evento.event_id}")
    return efectos_mod.ACREDITADO


# --- ZE17: el 401 delata el secreto --------------------------------------------
def _no_autorizado_con_pista(origen: str) -> HTTPException:
    return HTTPException(status_code=401,
                         detail=f"se esperaba la firma con {router_mod._secreto_de(origen)!r}")


# --- ZE19: `set` también acredita monedas --------------------------------------
def _set_tambien_acredita(mp: pytest.MonkeyPatch) -> None:
    permitidos = {origen: dict(reglas) for origen, reglas in events_mod.PERMITIDOS.items()}
    permitidos["set"]["coins.granted"] = permitidos["live"]["coins.granted"]
    mp.setattr(events_mod, "PERMITIDOS", permitidos)


TRAMPOSOS: dict[str, tuple[Aplicar, Callable[..., None], str]] = {
    "ZE1": (_parche(router_mod, "_firma_valida", lambda *_: True),
            tl.test_ev3_la_firma_y_la_ventana,
            r"EV3: \{'respuestas': \{'firma_falsa': \(200, "),
    "ZE2": (_parche(service_mod, "_guardar", _guardar_siempre),
            tl.test_ev1_un_lote_entra_y_reenviarlo_no_repite_nada,
            r"'segunda': \{'respuesta': \(200, 5, 0, \[\], \[\]\), 'filas': 10, 'saldo': 3"),
    "ZE3": (_varios(_parche(service_mod, "_ya_estaba", _duplicado_con_efecto),
                    _parche(efectos_mod, "_pagar", _pagar_sin_llave)),
            tl.test_ev1_un_lote_entra_y_reenviarlo_no_repite_nada,
            r"'segunda': \{'respuesta': \(200, 0, 5, \[\], \[\]\), 'filas': 5, 'saldo': 6"),
    "ZE4": (_parche(router_mod, "_firma_valida", _firma_sobre_el_json_reescrito),
            tl.test_ev3_la_firma_y_la_ventana,
            r"'controles': \{'otro_orden_firmado_sobre_sus_bytes': 401"),
    "ZE5": (_parche(events_mod, "VENTANA_S", 10**9), tl.test_ev3_la_firma_y_la_ventana,
            r"'de_hace_10_minutos': \(200, "),
    "ZE6": (_parche(router_mod, "MAX_EVENTOS", 10**6), tl.test_ev5_topes_y_raiz,
            r"EV5: \{'casos': \{'de_201': 200"),
    "ZE7": (_parche(service_mod, "_ya_estaba", _conflicto_sobrescribe),
            tl.test_ev6_conflicto_gana_el_primero,
            r"'otro_contenido': \(200, 1, 0, \[\], \[\]\), "
            r"'la_fila_y_el_saldo_son_del_primero': \('5', 3\)"),
    "ZE8": (_parche(service_mod, "procesar_lote", _todo_o_nada),
            tl.test_ev7_uno_malo_no_tumba_el_lote,
            r"EV7: \{'respuesta': \(422, \{'detail': 'lote rechazado entero'\}\), 'filas': 0"),
    "ZE9": (_comprobar_e_insertar(), tl.test_ev9_dos_lotes_iguales_a_la_vez,
            r"EV9: \{'estados': \[200, 500\]"),
    "ZE10": (_parche(service_mod, "_sujeto_valido", _cualquier_sujeto),
             te.test_nv3_a_quien_le_toca_y_que_emite_cada_origen,
             r"NV3: \{'sujetos': \{'de_otra_institucion': \(200, 1, 0, \[\], \[\]\)"),
    "ZE11": (_parche(level_mod, "record_confirmed_level", _el_ultimo_que_llega_gana),
             te.test_nv1_set_confirma_el_nivel_y_gana_el_mas_reciente,
             r"'uno_anterior': \(\(200, 1, 0, \[\], \[\]\), \('A2', 'set', True\)\)"),
    "ZE12": (_parche(events_mod, "regla_de", _regla_de_cualquier_origen),
             te.test_nv3_a_quien_le_toca_y_que_emite_cada_origen,
             r"'set_emite_monedas_como_live': \(200, 1, 0, \[\], \[\]\)"),
    "ZE13": (_parche(level_mod, "read_confirmed_level", _nivel_sin_institucion),
             te.test_nv3_a_quien_le_toca_y_que_emite_cada_origen,
             r"'ana_desde_b': \{'cefr': 'B1'"),
    "ZE14": (_parche(efectos_mod, "aplicar", _los_aciertos_en_vivo_suben_el_nivel),
             te.test_nv5_el_juego_y_la_clase_en_vivo_no_mueven_el_nivel,
             r"'nivel_identico': False, 'el_que_no_tenia': \{'cefr': 'C2'"),
    "ZE15": (_parche(efectos_mod, "TOPE_POR_SESION", 10**6),
             te.test_mc1_bolsa_agotada_y_tope_por_sesion,
             r"'uno_mas': \(\(200, 1, 0, \[\], \[\]\), 21\)"),
    "ZE16": (_parche(efectos_mod, "_pagar", _pagar_sin_savepoint),
             te.test_mc1_bolsa_agotada_y_tope_por_sesion,
             r"MC1: \{'bolsa': \{'de_10_con_5_en_la_bolsa': \(402, "),
    "ZE17": (_parche(router_mod, "_no_autorizado", _no_autorizado_con_pista),
             tl.test_ev3_la_firma_y_la_ventana,
             r"'el_secreto_en_respuestas_o_logs': True"),
    "ZE18": (_parche(events_mod, "verificar", lambda *_, **__: True),
             tu.test_ue1_la_firma_y_el_catalogo, r"'otro_cuerpo': True"),
    "ZE19": (_set_tambien_acredita, tu.test_ue1_la_firma_y_el_catalogo,
             r"'tipos_de_set': \['coins.granted', 'level.assessed'\]"),
    # Auditoría 03, S-11 (ESPEC §12): la comprobación de arranque no encuentra nada.
    "ZE20": (_parche(config_mod, "problemas_de_secretos", lambda live, set_, jwt: []),
             tu.test_ue3_los_secretos_de_eventos_se_validan_al_arrancar,
             r"'live_de_31': \[\], 'iguales': \[\], 'set_igual_al_jwt': \[\], 'todo_mal': 0"),
}
SIN_BASE = ("ZE18", "ZE19", "ZE20")


def correr(test_real: Callable[..., None], disponibles: dict[str, Any]) -> None:
    pedidas = inspect.signature(test_real).parameters
    test_real(**{nombre: disponibles[nombre] for nombre in pedidas})


@pytest.mark.integ
@pytest.mark.parametrize("clave", [c for c in TRAMPOSOS if c not in SIN_BASE])
def test_tramposo_pone_rojo_su_test(integ, monkeypatch, caplog, clave: str) -> None:
    aplicar, test_real, motivo = TRAMPOSOS[clave]
    aplicar(monkeypatch)
    with pytest.raises(AssertionError, match=motivo):
        correr(test_real, {"integ": integ, "monkeypatch": monkeypatch, "caplog": caplog})


@pytest.mark.parametrize("clave", SIN_BASE)
def test_tramposo_puro_pone_rojo_su_test(monkeypatch, clave: str) -> None:
    aplicar, test_real, motivo = TRAMPOSOS[clave]
    aplicar(monkeypatch)
    with pytest.raises(AssertionError, match=motivo):
        correr(test_real, {"monkeypatch": monkeypatch})
