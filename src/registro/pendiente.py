"""¿Este perfil espera la aprobación de su profe? — `docs/ESPEC_autorregistro.md` §1.8.

Módulo aparte y mínimo: lo importa `src/shared/deps.py`, que no debe arrastrar
el resto del registro.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.models import SolicitudInscripcion

ESPERA_APROBACION = "pending_approval"
SIN_DECIDIR = ("creando", "pendiente")


async def espera_aprobacion(db: AsyncSession, profile_id: UUID) -> bool:
    """True si el perfil tiene una solicitud de inscripción todavía sin decidir.

    Solo se consulta cuando el perfil NO tiene membresías activas: el camino
    normal (con membresía) no paga esta consulta.
    """
    fila = (await db.execute(
        select(SolicitudInscripcion.id)
        .where(SolicitudInscripcion.profile_id == profile_id,
               SolicitudInscripcion.estado.in_(SIN_DECIDIR))
        .limit(1)
    )).scalar_one_or_none()
    return fila is not None
