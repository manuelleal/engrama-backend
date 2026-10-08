"""El `documento_id` de quien se registra, y sus variantes — `docs/ESPEC_autorregistro.md` §11.6.

Dos cosas distintas, a propósito:

  - Lo que se GUARDA: `<slug>_<código tal como se escribió>`, armado con la
    MISMA función que usa el CSV de alta (`documento_de`). Así quien entró por
    la lista de su institución y quien se registra son el mismo perfil.
  - Lo que se COMPARA para saber si el código ya está ocupado: la forma
    canónica del código (minúsculas, sin guiones, sin ceros a la izquierda).
    Sin esto, un compañero podía registrar `ab-0123` o `00AB0123` y quedar
    como otra persona con el código de `AB-0123` (auditoría 03).

Los perfiles que ya existen no se tocan: ni se renombran ni se fusionan.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.onboarding.csv_personas import TIPO_CODIGO, con_prefijo, documento_de
from src.shared.models import Profile


def del_registro(slug: str, codigo: str) -> str | None:
    """El `documento_id` de ese código en esa institución; `None` si no cabe (`DOC_ID_RE`)."""
    documento, _motivo = documento_de(slug, TIPO_CODIGO, codigo)
    return documento


def canonico(codigo: str) -> str:
    """La forma con la que se comparan dos códigos: `00AB-0123` y `ab0123` son el mismo."""
    return codigo.lower().replace("-", "").lstrip("0")


async def perfiles_con_ese_codigo(db: AsyncSession, slug: str, codigo: str) -> list[Profile]:
    """Los perfiles de esa institución cuyo código es ese, en cualquiera de sus escrituras.

    Se mira solo entre los documentos que empiezan por `<slug>_` (los códigos
    internos de esa institución). La forma canónica de lo guardado se calcula
    en la base, con las mismas tres reglas de `canonico`. No usa un índice
    propio: recorre los perfiles de la institución (cientos en el piloto).
    """
    prefijo = con_prefijo(slug, "")
    guardado = func.substr(Profile.documento_id, len(prefijo) + 1)
    forma = func.ltrim(func.replace(func.lower(guardado), "-", ""), "0")
    filas = await db.execute(
        select(Profile)
        .where(func.starts_with(Profile.documento_id, prefijo), forma == canonico(codigo))
        .order_by(Profile.documento_id))
    return list(filas.scalars().all())
