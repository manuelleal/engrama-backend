"""Calificar UNA respuesta y armar su explicación — ESPEC_l1_correccion_por_pregunta. PURO.

Una sola función, `calificar`, para la respuesta por pregunta (`/answers`) y
para el repaso. No toca la base: el vocabulario ("palabra válida") llega como
un conjunto. `/submit` NO pasa por aquí: sigue con su regla vieja
(`attempts.grade_answers`), idéntico (§1.3).

La explicación sigue el formato del dictamen pedagógico 04 §1.5: la oración
completa correcta, la regla, por qué no la suya (solo si falló) y un ejemplo;
en español para A1 y A2 y en inglés desde B1 (§10.2).

Nada premia velocidad ni azar: aquí solo se compara texto.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

EXACTA, UNA_LETRA = "exacta", "1_letra"
TIPOS_DE_OPCION = ("multiple_choice", "listening")
# Una aceptada de 4 letras o menos se trata como exacta (decisión de F8).
LARGO_MINIMO_TOLERANTE = 5
ESPANOL, INGLES = "es", "en"
# Confirmado por el dueño (2026-10-12): la explicación va en español en A1 y A2.
NIVELES_EN_ESPANOL = ("A1", "A2")

_COMILLAS = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "“": '"', "”": '"'})
_ESPACIOS = re.compile(r"\s+")
_FINAL = re.compile(r"[.!?\s]+$")
_HUECO = re.compile(r"_{2,}")


@dataclass(frozen=True)
class Pregunta:
    """Lo que hace falta de una pregunta para calificarla (sin ORM)."""

    question_type: str
    correct_answer: str
    options: Sequence[Mapping[str, Any]] = ()
    accepted_answers: Sequence[str] = ()
    tolerancia: str = EXACTA
    pista_inicial: bool = False


def normalizar(texto: str) -> str:
    """NFC, comillas rectas, minúsculas, espacios y sin `.`, `!`, `?` al FINAL.

    La puntuación interna se queda: "it's" no es "its".
    """
    texto = unicodedata.normalize("NFC", texto).translate(_COMILLAS).lower()
    texto = _ESPACIOS.sub(" ", texto).strip()
    return _FINAL.sub("", texto).strip()


def a_distancia_uno(a: str, b: str) -> bool:
    """¿Se pasa de `a` a `b` con UNA letra cambiada, de más o de menos? (No iguales.)

    Una transposición ("recieve") son dos cambios: no cuenta.
    """
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(1 for x, y in zip(a, b, strict=True) if x != y) == 1
    corta, larga = (a, b) if len(a) < len(b) else (b, a)
    return any(larga[:i] + larga[i + 1:] == corta for i in range(len(larga)))


def _aceptadas(p: Pregunta) -> list[str]:
    return [n for n in dict.fromkeys(normalizar(x) for x in (p.correct_answer,
                                                              *p.accepted_answers)) if n]


def _acierta_texto(respuesta: str, aceptadas: Sequence[str], tolerancia: str,
                   vocabulario: Collection[str]) -> bool:
    """Una LECTURA de la respuesta contra las aceptadas; la tolerancia, una sola vez."""
    if respuesta in aceptadas:
        return True
    if tolerancia != UNA_LETRA or respuesta in vocabulario:
        return False  # otra palabra válida (fever/fewer) no es un error de tipeo
    return any(len(a) >= LARGO_MINIMO_TOLERANTE and a_distancia_uno(respuesta, a)
               for a in aceptadas)


def label_de(p: Pregunta, respuesta: str) -> str:
    """La label elegida. Si llegó el `value` de una opción, se traduce a su label."""
    dada = normalizar(respuesta)
    labels = {normalizar(str(o.get("label", ""))): str(o.get("label", "")) for o in p.options}
    if dada in labels:
        return labels[dada]
    for o in p.options:
        if dada and normalizar(str(o.get("value", ""))) == dada:
            return str(o.get("label", ""))
    return respuesta.strip()


def es_opcion_valida(p: Pregunta, respuesta: str) -> bool:
    """¿La respuesta es una de las opciones de la pregunta? (ESPEC_opcion_valida §1)

    Una pregunta con opciones (al menos una con `label`: opción múltiple, V/F/ND
    o cualquier otra que las traiga) solo admite su `label` o su `value`, con la
    misma normalización de la calificación ("V", " v ", "True"). Lo demás ("A"
    en una V/F/ND) no es un error del estudiante sino una petición mal hecha: la
    ruta la rechaza sin guardarla. Sin opciones (la escrita), todo texto vale.
    """
    if not any(str(o.get("label") or "").strip() for o in p.options):
        return True
    dada = normalizar(respuesta)
    validas = {normalizar(str(v)) for o in p.options for campo in ("label", "value")
               if (v := o.get(campo)) is not None}
    return bool(dada) and dada in validas


def calificar(p: Pregunta, respuesta: str, vocabulario: Collection[str] = ()) -> bool:
    """¿Acertó? Opción múltiple por label; escrita con normalización, tolerancia y pista."""
    if p.question_type in TIPOS_DE_OPCION:
        return bool(normalizar(label_de(p, respuesta))) and (
            normalizar(label_de(p, respuesta)) == normalizar(p.correct_answer))
    dada, aceptadas = normalizar(respuesta), _aceptadas(p)
    if not dada or not aceptadas:
        return False
    lecturas = [dada]
    if p.pista_inicial:  # el cliente mostró la inicial: vale el resto o la palabra entera
        lecturas += [a[0] + dada for a in aceptadas]
    return any(_acierta_texto(lectura, aceptadas, p.tolerancia, vocabulario)
               for lectura in dict.fromkeys(lecturas))


def pista_de(p: Pregunta) -> str | None:
    """La letra que el estudiante ve ANTES de responder ("c___"), o nada."""
    if not p.pista_inicial or p.question_type in TIPOS_DE_OPCION:
        return None
    aceptadas = _aceptadas(p)
    return aceptadas[0][0] if aceptadas else None


# ------------------------------------------------------------- la explicación
def idioma_de(nivel: str | None) -> str:
    """En qué idioma va la explicación de un reto de ese nivel: A1 y A2 en español,
    de B1 en adelante en inglés. Sin nivel, español (lo entiende cualquiera)."""
    if not nivel:
        return ESPANOL
    return ESPANOL if nivel[:2].upper() in NIVELES_EN_ESPANOL else INGLES


def texto_correcto(p: Pregunta) -> str:
    """El TEXTO de la correcta: en opción múltiple, el `value` de su opción (no la letra)."""
    if p.question_type in TIPOS_DE_OPCION:
        clave = normalizar(p.correct_answer)
        for o in p.options:
            if normalizar(str(o.get("label", ""))) == clave:
                return str(o.get("value", "")).strip()
    return p.correct_answer.strip()


def oracion_correcta(enunciado: str, p: Pregunta, del_banco: str | None = None) -> str:
    """La oración completa correcta (dictamen 04 §1.5, parte 1): no solo la letra.

    La del banco manda. Si no hay, el enunciado con su ÚNICO hueco (`___`)
    relleno; sin hueco o con varios, el texto de la correcta.
    """
    if del_banco and del_banco.strip():
        return del_banco.strip()
    correcta = texto_correcto(p)
    if correcta and len(_HUECO.findall(enunciado)) == 1:
        return _HUECO.sub(lambda _m: correcta, enunciado).strip()
    return correcta


def explicacion_para(explicacion: Mapping[str, Any] | None, *, elegida: str, acerto: bool,
                     nivel: str | None = None) -> dict[str, Any] | None:
    """La explicación que viaja tras responder: `por_opcion` SOLO de la elegida y solo si falló.

    `idioma`: el del banco si lo trae; si no, por el nivel del reto.
    """
    if not explicacion:
        return None
    por_opcion = explicacion.get("por_opcion")
    la_suya = None
    if not acerto and isinstance(por_opcion, Mapping):
        la_suya = next((str(texto) for label, texto in por_opcion.items()
                        if normalizar(str(label)) == normalizar(elegida)), None)
    idioma = explicacion.get("idioma")
    return {"idioma": idioma if idioma in (ESPANOL, INGLES) else idioma_de(nivel),
            "regla": explicacion.get("regla"), "por_opcion": la_suya,
            "ejemplo": explicacion.get("ejemplo")}
