"""Lo que ve el profe: quién refuerza qué, y los huecos de contenido — ESPEC_refuerzo §1.6.

Es SOLO del panel del profe (la ruta pide el grupo asignado y responde con
`Cache-Control: no-store`): nunca va a una pantalla proyectable. Las etiquetas
dicen qué está practicando cada quien; no califican a nadie.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.foco import service as foco_service
from src.refuerzo import reglas
from src.refuerzo import service as refuerzo_service
from src.refuerzo.schemas import (
    EstudianteEnColaOut,
    HuecoOut,
    MetodoOut,
    NodoEnColaOut,
    PanelOut,
    PorNodoOut,
)
from src.shared.models import Group
from src.teachers.service import panel as panel_service

ESTADOS = (reglas.EN_REFUERZO, reglas.POR_REPASAR, reglas.SUPERADO, reglas.EN_ESPERA)


def metodo() -> MetodoOut:
    regla = refuerzo_service.regla()
    return MetodoOut(
        aciertos_para_repaso=regla.aciertos_para_repaso, dias_para_repaso=regla.dias_repaso,
        pendiente_del_pedagogo=True,
        regla="superado = acierta una forma no vista y otra en un repaso espaciado")


async def build_response(db: AsyncSession, group: Group, *, ahora: datetime) -> PanelOut:
    """Por estudiante activo del grupo y por nodo. `en_espera_de_contenido` se calcula aquí
    con la misma función que le sirve al estudiante (`planear`)."""
    roster = await panel_service.roster(db, group)
    cola = await refuerzo_service.entradas(db, group.tenant_id, [s.profile_id for s in roster])
    plan = await refuerzo_service.planear(db, tenant_id=group.tenant_id,
                                          group_code=group.group_code, cola=cola, ahora=ahora)
    nodos = {n.id: n for n in await foco_service.nodos_a_esquema(
        db, sorted({e.node_id for e in cola}))}
    por_estudiante: dict[object, list[NodoEnColaOut]] = defaultdict(list)
    conteo: dict[str, Counter[str]] = defaultdict(Counter)
    for e in cola:
        en_espera = e.id in plan and plan[e.id] is None
        estado = reglas.EN_ESPERA if en_espera else e.status
        conteo[e.node_id][estado] += 1
        por_estudiante[e.profile_id].append(NodoEnColaOut(
            nodo=nodos[e.node_id], estado=estado, etiqueta=reglas.ETIQUETAS[estado],
            origen=e.origin, fallos=e.failures, desde=e.entered_at,
            proxima_fecha=e.next_due_at))
    en_orden = sorted(conteo)
    return PanelOut(
        method=metodo(),
        estudiantes=[EstudianteEnColaOut(profile_id=s.profile_id, full_name=s.full_name,
                                         nodos=por_estudiante.get(s.profile_id, []))
                     for s in roster],
        por_nodo=[PorNodoOut(nodo=nodos[n], en_refuerzo=conteo[n][reglas.EN_REFUERZO],
                             por_repasar=conteo[n][reglas.POR_REPASAR],
                             superado=conteo[n][reglas.SUPERADO],
                             en_espera_de_contenido=conteo[n][reglas.EN_ESPERA])
                  for n in en_orden],
        huecos=[HuecoOut(nodo=nodos[n], estudiantes_en_espera=conteo[n][reglas.EN_ESPERA])
                for n in sorted(en_orden, key=lambda n: (-conteo[n][reglas.EN_ESPERA], n))
                if conteo[n][reglas.EN_ESPERA] > 0])
