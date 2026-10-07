"""Reglas PURAS de la cola de refuerzo — ESPEC_refuerzo §1.2 y §1.4.

No toca la base ni el reloj: recibe `ahora`. Los dos números de la regla de
"superado" llegan en `Regla` (salen de la configuración): LOS FIJA EL
PEDAGOGO (ERR-16); aquí no hay ningún valor escrito.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

EN_REFUERZO = "en_refuerzo"
POR_REPASAR = "por_repasar"
SUPERADO = "superado"
EN_ESPERA = "en_espera_de_contenido"  # se calcula al leer; no se guarda

ETAPA_REFUERZO = "refuerzo"
ETAPA_REPASO = "repaso"

ETIQUETAS = {EN_REFUERZO: "en refuerzo", POR_REPASAR: "por repasar", SUPERADO: "superado",
             EN_ESPERA: "en espera de contenido"}

# A qué forma de la familia se le da preferencia en cada etapa (la menor gana).
_ROLES = {
    ETAPA_REFUERZO: {"gemela": 0, "repaso": 1, "original": 2},
    ETAPA_REPASO: {"repaso": 0, "gemela": 1, "original": 2},
}
_SIN_ROL = 3


@dataclass(frozen=True)
class Regla:
    """Cuándo queda superado un nodo. Los valores vienen de la configuración."""

    aciertos_para_repaso: int
    dias_repaso: int


@dataclass(frozen=True)
class Estado:
    status: str
    hits: int
    next_due_at: datetime | None
    mastered_at: datetime | None


@dataclass(frozen=True)
class Forma:
    """Una pregunta candidata. `clave` es su identidad: el mismo ítem es la misma pregunta."""

    question_id: UUID
    clave: str
    familia: str | None
    rol: str | None


def clave_de_forma(item_ref: str | None, question_id: UUID | str) -> str:
    """La identidad de una pregunta: su `item_ref` del banco o, si no tiene, ella misma."""
    return item_ref if item_ref else f"q:{question_id}"


def etapa_de(status: str) -> str | None:
    return {EN_REFUERZO: ETAPA_REFUERZO, POR_REPASAR: ETAPA_REPASO}.get(status)


def toca(status: str, next_due_at: datetime | None, ahora: datetime) -> bool:
    """¿Hay que servirle una forma ahora? El repaso, solo cuando llega su fecha."""
    if status == EN_REFUERZO:
        return True
    if status == POR_REPASAR:
        return next_due_at is not None and next_due_at <= ahora
    return False


def transicion(estado: Estado, acerto: bool, ahora: datetime, regla: Regla) -> Estado:
    """El estado tras responder una forma no vista."""
    if estado.status == EN_REFUERZO:
        if not acerto:
            return Estado(EN_REFUERZO, 0, None, None)
        aciertos = estado.hits + 1
        if aciertos < regla.aciertos_para_repaso:
            return Estado(EN_REFUERZO, aciertos, None, None)
        return Estado(POR_REPASAR, 0, ahora + timedelta(days=regla.dias_repaso), None)
    if estado.status == POR_REPASAR:
        if acerto:
            return Estado(SUPERADO, 0, None, ahora)
        return Estado(EN_REFUERZO, 0, None, None)
    return estado  # superado: no se responde


def no_vistas(candidatas: Iterable[Forma], vistas: set[str]) -> list[Forma]:
    """Nunca la misma pregunta: fuera toda forma cuya identidad el estudiante ya vio."""
    return [f for f in candidatas if f.clave not in vistas]


def _orden(forma: Forma, familia: str | None, etapa: str) -> tuple[int, int, str]:
    de_la_familia = 0 if familia is not None and forma.familia == familia else 1
    return (de_la_familia, _ROLES[etapa].get(forma.rol or "", _SIN_ROL), forma.clave)


def elegir(candidatas: Iterable[Forma], vistas: set[str], *, familia: str | None,
           etapa: str, usadas: set[str]) -> Forma | None:
    """La forma a servir, o `None` si no queda ninguna que no haya visto.

    Primero la familia del ítem que falló (gemela o repaso según la etapa),
    después otras del mismo nodo. `usadas`: las ya dadas a otra entrada en la
    misma respuesta. Una misma identidad sembrada en dos retos cuenta una vez.
    """
    libres = [f for f in no_vistas(candidatas, vistas) if f.clave not in usadas]
    if not libres:
        return None
    return min(libres, key=lambda f: (*_orden(f, familia, etapa), str(f.question_id)))
