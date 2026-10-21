"""Las reglas PURAS de Dar, Corregir y el presupuesto — ESPEC_ola1_economia §1.2-1.3.

Sin base de datos: cada regla es una función chica que se prueba sola (los
unitarios OEU) y que un tramposo puede romper por separado (§3). Los números
salen de `settings` (todos provisionales, §6); aquí solo está la lógica.
"""
from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any

from fastapi import HTTPException, status

# Los motivos de una entrega: conductas de aprendizaje, NUNCA disciplina
# (informe 11 §O1-1; la lista final la decide el pedagogo).
MOTIVOS = ("participacion", "ayuda_companero", "tarea", "esfuerzo", "otro")
NOTA_MIN = 3
NOTA_MAX = 80


# Los mensajes de error, en español (contrato de la web, ADENDA 1 §A.1): la
# respuesta es `{"detail": "<mensaje>"}`. La clave es estable para el código; el
# texto es lo que ve la persona.
MENSAJES: dict[str, str] = {
    "tope_por_entrega": "Cada entrega va de 1 a {tope} monedas.",
    "motivo_invalido": "El motivo debe ser uno de: participacion, ayuda_companero, tarea, "
                       "esfuerzo, otro.",
    "nota_obligatoria": "Con el motivo 'otro' escribe una nota de al menos 3 letras.",
    "tope_semanal_estudiante": "Tope semanal: este estudiante ya recibió {recibido} de {tope} "
                               "monedas de los profes esta semana.",
    "presupuesto_insuficiente": "Presupuesto insuficiente: tu bolsillo tiene {saldo} monedas.",
    "estudiante_no_encontrado": "Estudiante no encontrado en tus grupos.",
    "llave_reutilizada": "Esa llave ya se usó para otra operación.",
    "entrega_no_encontrada": "Entrega no encontrada.",
    "plazo_vencido": "Plazo vencido: solo se corrige hasta {dias} días después de la entrega.",
    "ya_corregida": "Esa entrega ya se corrigió completa.",
    "excede_original": "Solo quedan {maximo} monedas por corregir de esa entrega.",
    "ya_gastado": "El estudiante ya gastó esas monedas: puedes corregir a lo sumo {maximo}.",
    "profe_no_encontrado": "Profe no encontrado en tu institución.",
    "tope_semanal_presupuesto": "Tope semanal: ese bolsillo ya recibió {recargado} de {tope} "
                                "monedas esta semana.",
    "bolsa_insuficiente": "La bolsa de la institución no alcanza: tiene {saldo} monedas.",
    "saldo_bolsillo": "El bolsillo solo tiene {saldo} monedas.",
    "sin_bolsillo": "No tienes un bolsillo en esta institución.",
    "precio_fuera_de_escalon": "El precio debe ser uno de: {escalones}.",
    "tipo_invalido": "El tipo debe ser privilegio o fisico.",
    "objeto_academico": "La tienda no vende nada que toque notas, exámenes, puntos, nivel o XP.",
    "objeto_no_encontrado": "Objeto no encontrado.",
    "inactivo": "Ese objeto no está a la venta.",
    "agotado": "Ese objeto está agotado.",
    "saldo_insuficiente": "No te alcanzan las monedas: tienes {saldo} y cuesta {precio}.",
    "solo_estudiantes": "Solo los estudiantes compran, pujan y tienen mochila.",
    "compra_no_encontrada": "Compra no encontrada.",
    "ya_devuelta": "Esa compra ya se devolvió.",
    "plazo_vencido_devuelto": "Pasaron {dias} días sin entregarla: se le devolvieron las "
                              "monedas al estudiante.",
    "plazo_vencido_sin_fondos": "Pasó el plazo de entrega y la bolsa no alcanza para devolver.",
    "grupo_no_encontrado": "Grupo no encontrado.",
    "grupo_con_subasta": "Ese grupo ya tiene una subasta activa.",
    "subasta_no_encontrada": "Subasta no encontrada.",
    "subasta_cerrada": "La subasta ya cerró.",
    "puja_minima": "La primera puja debe ser de al menos {minimo} monedas.",
    "incremento_invalido": "La puja debe subir 5, 10 o 25 sobre {actual}. Alguien pudo pujar "
                           "antes: vuelve a leer la subasta.",
    "sin_saldo_puja": "No te alcanzan las monedas para esa puja: tienes {saldo}.",
    "objeto_o_titulo": "Indica un objeto de la tienda o un título (uno de los dos).",
}


def rechazo(codigo_http: int, code: str, **extra: Any) -> HTTPException:
    """Un error con su mensaje en español: `{"detail": "<mensaje>"}`."""
    return HTTPException(status_code=codigo_http, detail=MENSAJES[code].format(**extra))


def validar_monto_entrega(monto: int, tope: int) -> None:
    """Una entrega va de 1 al tope (20): ninguna pesa más que el reto más caro."""
    if not 1 <= monto <= tope:
        raise rechazo(status.HTTP_422_UNPROCESSABLE_ENTITY, "tope_por_entrega", tope=tope)


def validar_motivo(motivo: str, nota: str | None) -> None:
    """Motivo de la lista cerrada; con `otro`, una nota de al menos 3 letras."""
    if motivo not in MOTIVOS:
        raise rechazo(status.HTTP_422_UNPROCESSABLE_ENTITY, "motivo_invalido",
                      motivos=list(MOTIVOS))
    if motivo == "otro" and len((nota or "").strip()) < NOTA_MIN:
        raise rechazo(status.HTTP_422_UNPROCESSABLE_ENTITY, "nota_obligatoria")


def inicio_semana(ahora_utc: datetime, desfase_horas: int) -> datetime:
    """El lunes 00:00 de la semana en la hora de la institución, como instante UTC.

    La semana de la casa va de lunes a domingo en la hora local (como la racha):
    el domingo a las 23:30 de Bogotá todavía es esta semana aunque en UTC ya sea lunes.
    """
    local = ahora_utc + timedelta(hours=desfase_horas)
    lunes = local.date() - timedelta(days=local.weekday())
    return datetime.combine(lunes, time(0), tzinfo=UTC) - timedelta(hours=desfase_horas)


def cabe_en_tope(acumulado: int, monto: int, tope: int) -> bool:
    """¿Lo que ya hay más este monto queda dentro del tope?"""
    return acumulado + monto <= tope


def dentro_del_plazo(creado: datetime, ahora: datetime, dias: int) -> bool:
    """Corregir solo hasta `dias` después de la entrega."""
    return ahora - creado <= timedelta(days=dias)


def corregible(original: int, ya_corregido: int) -> int:
    """Lo que todavía se puede deshacer de una entrega: nunca más que el original."""
    return max(original - ya_corregido, 0)
