"""Eventos del anillo: el catálogo y la firma — `docs/ESPEC_eventos_anillo.md` §1.2 y §1.5.

Todo aquí es PURO (sin base ni HTTP), para que lo usen la puerta de entrada
(`src/webhooks/`) y, más adelante, quien emita eventos desde el backend.

  - `PERMITIDOS`: qué tipos puede emitir cada ORIGEN, con qué `source` y con
    qué clase de sujeto. Es una lista de permitidos: lo que no está, no entra.
  - `firmar` / `verificar`: `sha256=<hex>` de
    `HMAC_SHA256(secreto, timestamp + "." + cuerpo crudo)`, con ventana de
    tiempo. Se firma lo que viajó, no el JSON vuelto a escribir.
  - `huella_del_evento`: la igualdad de contenido para la idempotencia.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any

ORIGEN_LIVE, ORIGEN_SET = "live", "set"
ESTUDIANTE, STAFF, SIN_SUJETO = "student", "staff", "none"

COINS_GRANTED = "coins.granted"
LEVEL_ASSESSED = "level.assessed"
ANSWER_SUBMITTED = "answer.submitted"

VENTANA_S = 300
SECRETO_MINIMO = 32
PREFIJO = "sha256="


@dataclass(frozen=True)
class Regla:
    """Con qué `source` y con qué sujeto llega un tipo de evento."""

    source: str
    sujeto: str


# Origen (el encabezado `X-Engrama-Source`) -> tipo -> regla.
PERMITIDOS: dict[str, dict[str, Regla]] = {
    ORIGEN_LIVE: {
        "live.session.started": Regla("teacher", STAFF),
        "item.exposed": Regla("live", SIN_SUJETO),
        ANSWER_SUBMITTED: Regla("live", ESTUDIANTE),
        COINS_GRANTED: Regla("live", ESTUDIANTE),
        "live.session.closed": Regla("teacher", STAFF),
    },
    # SET mide el nivel y NADA más: no puede acreditar monedas.
    ORIGEN_SET: {
        LEVEL_ASSESSED: Regla("set", ESTUDIANTE),
    },
}


def regla_de(origen: str, tipo: str) -> Regla | None:
    """La regla de ese tipo para ese origen, o `None` si no le está permitido."""
    return PERMITIDOS.get(origen, {}).get(tipo)


def firmar(secreto: str, timestamp: str, cuerpo: bytes) -> str:
    """La firma que debe viajar en `X-Engrama-Signature`."""
    mensaje = timestamp.encode() + b"." + cuerpo
    return PREFIJO + hmac.new(secreto.encode(), mensaje, hashlib.sha256).hexdigest()


def verificar(secreto: str, timestamp: str, cuerpo: bytes, firma: str, *, ahora: float) -> bool:
    """¿La firma es de ese secreto, para ESOS bytes y dentro de la ventana?

    Falso también si el secreto tiene menos de 32 caracteres (un origen sin
    secreto está apagado: nunca se acepta un secreto vacío), si el timestamp
    no es un entero o si a la firma le falta el prefijo.
    """
    if len(secreto) < SECRETO_MINIMO or not firma.startswith(PREFIJO):
        return False
    try:
        enviado = int(timestamp)
    except ValueError:
        return False
    if abs(ahora - enviado) > VENTANA_S:
        return False
    return hmac.compare_digest(firmar(secreto, timestamp, cuerpo), firma)


def huella_del_evento(evento: dict[str, Any]) -> str:
    """SHA-256 del evento con las claves ordenadas: el orden y los espacios no cuentan."""
    canonico = json.dumps(evento, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonico.encode()).hexdigest()
