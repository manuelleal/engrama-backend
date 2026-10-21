"""OEU: las reglas puras de la ola 1, sin base de datos — `docs/ESPEC_ola1_economia.md` §2.

Corren siempre (sin Docker). Cada una tiene su tramposo en
`tests/tramposos/test_tramposos_ola1_unit.py`.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from src.bolsillo import reglas
from src.shop import reglas as tienda

BOGOTA = -5


def _codigo(exc: pytest.ExceptionInfo[HTTPException]) -> tuple[int, str]:
    """(estado, clave del mensaje): el `detail` es el texto en español de `MENSAJES`."""
    detalle = str(exc.value.detail)
    clave = next((k for k, v in reglas.MENSAJES.items()
                  if detalle.startswith(v.split("{")[0])), detalle)
    return exc.value.status_code, clave


def test_oeu1_lunes_local_y_no_utc() -> None:
    """Domingo 23:30 de Bogotá (lunes 04:30 UTC) sigue en la semana; lunes 00:00 local abre otra."""
    domingo_noche = datetime(2026, 10, 26, 4, 30, tzinfo=UTC)  # dom 25 23:30 en Bogotá
    lunes_cero = datetime(2026, 10, 26, 5, 0, tzinfo=UTC)  # lun 26 00:00 en Bogotá
    observado = {
        "domingo": reglas.inicio_semana(domingo_noche, BOGOTA),
        "lunes": reglas.inicio_semana(lunes_cero, BOGOTA),
        "miercoles": reglas.inicio_semana(datetime(2026, 10, 21, 17, 0, tzinfo=UTC), BOGOTA),
    }
    assert observado == {
        "domingo": datetime(2026, 10, 19, 5, 0, tzinfo=UTC),
        "lunes": datetime(2026, 10, 26, 5, 0, tzinfo=UTC),
        "miercoles": datetime(2026, 10, 19, 5, 0, tzinfo=UTC),
    }, f"OEU1: semanas {observado}"


def test_oeu2_monto_de_una_entrega() -> None:
    reglas.validar_monto_entrega(1, 20)
    reglas.validar_monto_entrega(20, 20)
    rotos = []
    for monto in (0, 21, -5):
        with pytest.raises(HTTPException) as exc:
            reglas.validar_monto_entrega(monto, 20)
        rotos.append(_codigo(exc))
    assert rotos == [(422, "tope_por_entrega")] * 3, f"OEU2: {rotos}"


def test_oeu3_motivo_cerrado_y_nota_con_otro() -> None:
    for motivo in ("participacion", "ayuda_companero", "tarea", "esfuerzo"):
        reglas.validar_motivo(motivo, None)
    reglas.validar_motivo("otro", "leyó en voz alta")
    rotos = []
    for motivo, nota in (("disciplina", None), ("otro", None), ("otro", "  ok ")):
        with pytest.raises(HTTPException) as exc:
            reglas.validar_motivo(motivo, nota)
        rotos.append(_codigo(exc))
    assert rotos == [(422, "motivo_invalido"), (422, "nota_obligatoria"),
                     (422, "nota_obligatoria")], f"OEU3: {rotos}"


def test_oeu4_plazo_tope_y_corregible() -> None:
    ahora = datetime(2026, 10, 21, 12, tzinfo=UTC)
    observado = {
        "13_dias": reglas.dentro_del_plazo(ahora - timedelta(days=13), ahora, 14),
        "14_dias_justos": reglas.dentro_del_plazo(ahora - timedelta(days=14), ahora, 14),
        "14_dias_y_1_min": reglas.dentro_del_plazo(ahora - timedelta(days=14, minutes=1),
                                                   ahora, 14),
        "tope_40_con_20_mas_20": reglas.cabe_en_tope(20, 20, 40),
        "tope_40_con_40_mas_1": reglas.cabe_en_tope(40, 1, 40),
        "corregible_15_menos_10": reglas.corregible(15, 10),
        "corregible_nunca_negativo": reglas.corregible(15, 20),
    }
    assert observado == {
        "13_dias": True, "14_dias_justos": True, "14_dias_y_1_min": False,
        "tope_40_con_20_mas_20": True, "tope_40_con_40_mas_1": False,
        "corregible_15_menos_10": 5, "corregible_nunca_negativo": 0,
    }, f"OEU4: {observado}"


def test_oeu5_tienda_escalones_tipos_y_palabras() -> None:
    escalones = [40, 120, 300, 600]
    for precio in escalones:
        tienda.validar_precio(precio, escalones)
    tienda.validar_tipo("privilegio")
    tienda.validar_tipo("fisico")
    rotos = []
    for llamada in (lambda: tienda.validar_precio(50, escalones),
                    lambda: tienda.validar_tipo("nota"),
                    lambda: tienda.validar_textos("+1 punto en el examen", None),
                    lambda: tienda.validar_textos("Subir la NOTA", None),
                    lambda: tienda.validar_textos("Premio", "una décima en la calificación")):
        with pytest.raises(HTTPException) as exc:
            llamada()
        rotos.append(_codigo(exc))
    sanos = [tienda.es_academico(t) for t in ("Elegir la canción", "Cinco minutos de pausa",
                                              "Ser capitán de la clase", "Notable libreta")]
    assert (rotos, sanos) == (
        [(422, "precio_fuera_de_escalon"), (422, "tipo_invalido"), (422, "objeto_academico"),
         (422, "objeto_academico"), (422, "objeto_academico")],
        [False, False, False, False]), f"OEU5: {rotos} {sanos}"


def test_oeu6_corte_de_la_devolucion() -> None:
    ahora = datetime(2026, 10, 21, 12, tzinfo=UTC)
    corte = tienda.corte_devolucion(ahora, 14)
    observado = {
        "corte": corte,
        "comprado_hace_15_se_devuelve": ahora - timedelta(days=15) <= corte,
        "comprado_hace_13_no": ahora - timedelta(days=13) <= corte,
        "vence": tienda.vence_el(ahora, 14),
    }
    assert observado == {
        "corte": datetime(2026, 10, 7, 12, tzinfo=UTC),
        "comprado_hace_15_se_devuelve": True, "comprado_hace_13_no": False,
        "vence": datetime(2026, 11, 4, 12, tzinfo=UTC),
    }, f"OEU6: {observado}"
