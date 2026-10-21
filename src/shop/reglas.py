"""Las reglas PURAS de la tienda — ESPEC_ola1_economia §1.4.

La tienda vende privilegios de clase y objetos físicos, NUNCA ventajas
académicas: nada de nota, examen, nivel ni XP. Las reglas viven aquí (en la
API) y no como CHECK en la base, porque el ataque D11 de seguridad inserta
precios 0 y 10 directo en `shop_items` (`tests/seguridad/modulos.py`).
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta

from fastapi import status

from src.bolsillo.reglas import rechazo

# Tipos cerrados (informe 11 §O1-3). No existe un tipo "nota": la API lo rechaza.
TIPOS = ("privilegio", "fisico")

# Palabras que delatan un objeto académico, sin tildes y en minúscula, como
# palabra completa. Lista provisional: la decide el pedagogo (ESPEC §11).
PALABRAS_ACADEMICAS = (
    "nota", "notas", "examen", "examenes", "exam", "punto", "puntos",
    "calificacion", "calificaciones", "decima", "decimas", "quiz", "parcial",
    "parciales", "evaluacion", "evaluaciones", "grade", "grades", "bonus", "xp", "nivel",
)
_PATRON = re.compile(r"\b(" + "|".join(PALABRAS_ACADEMICAS) + r")\b")


def normalizar(texto: str) -> str:
    """Minúsculas y sin tildes: "Calificación" y "calificacion" son lo mismo."""
    sin_tildes = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in sin_tildes if not unicodedata.combining(c)).lower()


def es_academico(*textos: str | None) -> bool:
    """¿Alguno de los textos nombra una ventaja académica?"""
    return any(_PATRON.search(normalizar(t)) for t in textos if t)


def validar_precio(precio: int, escalones: list[int]) -> None:
    """Solo los escalones (40 / 120 / 300 / 600): nada de precios a la medida."""
    if precio not in escalones:
        raise rechazo(status.HTTP_422_UNPROCESSABLE_ENTITY, "precio_fuera_de_escalon",
                      escalones=", ".join(str(e) for e in escalones))


def validar_tipo(tipo: str) -> None:
    if tipo not in TIPOS:
        raise rechazo(status.HTTP_422_UNPROCESSABLE_ENTITY, "tipo_invalido", tipos=list(TIPOS))


def validar_textos(nombre: str | None, descripcion: str | None) -> None:
    if es_academico(nombre, descripcion):
        raise rechazo(status.HTTP_422_UNPROCESSABLE_ENTITY, "objeto_academico")


def corte_devolucion(ahora: datetime, dias: int) -> datetime:
    """Lo comprado ANTES de este instante (o justo en él) y sin entregar se devuelve."""
    return ahora - timedelta(days=dias)


def vence_el(comprado: datetime, dias: int) -> datetime:
    """La fecha límite de entrega que ve el estudiante y el profe."""
    return comprado + timedelta(days=dias)
