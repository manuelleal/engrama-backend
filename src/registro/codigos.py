"""El código de inscripción de un grupo — `docs/ESPEC_autorregistro.md` §1.2.

El código en claro existe en dos sitios y en ninguno más: la respuesta de
crearlo (el profe lo ve UNA vez) y el cuerpo del registro del estudiante. En la
base vive solo su huella.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.config import settings
from src.shared.models import CodigoInscripcion, Group

# 31 símbolos: sin I, L, O, 0 ni 1 (se confunden al copiarlos del tablero).
ALFABETO = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
LARGO = 8
HORAS_POR_DEFECTO = 48
CUPO_POR_DEFECTO = 40
_ETIQUETA = b"engrama:codigo-inscripcion:v1"
_SEPARADORES = " -\t"


def generar() -> str:
    """8 símbolos al azar con `secrets` (31^8, unas 8,5 x 10^11 combinaciones)."""
    return "".join(secrets.choice(ALFABETO) for _ in range(LARGO))


def mostrar(codigo: str) -> str:
    """`ABCDEFGH` -> `ABCD-EFGH`, como lo ve el profe."""
    return f"{codigo[:4]}-{codigo[4:]}"


def normalizar(texto: str) -> str:
    """Mayúsculas, sin espacios ni guiones: `abcd-efgh` es `ABCDEFGH`."""
    return "".join(c for c in texto.upper() if c not in _SEPARADORES)


def _llave() -> bytes:
    """La llave de la huella, derivada del secreto que el proceso ya tiene.

    No es el secreto JWT tal cual: se deriva con una etiqueta, para que la
    huella de un código no sirva para nada más.
    """
    return hmac.new(settings.supabase_jwt_secret.encode(), _ETIQUETA, hashlib.sha256).digest()


def huella(codigo: str) -> str:
    """HMAC-SHA256 del código normalizado, en hexadecimal (64 caracteres).

    Con llave y no un SHA-256 a secas: el espacio de códigos (31^8) se recorre
    en segundos, así que con un volcado de la base un hash sin llave
    devolvería todos los códigos.
    """
    return hmac.new(_llave(), normalizar(codigo).encode(), hashlib.sha256).hexdigest()


async def apagar(db: AsyncSession, group: Group) -> None:
    """Apaga el código activo del grupo, si lo hay. No hace commit."""
    await db.execute(
        update(CodigoInscripcion)
        .where(CodigoInscripcion.group_id == group.id, CodigoInscripcion.activo.is_(True))
        .values(activo=False)
    )


async def crear(db: AsyncSession, group: Group, creador: UUID, *, horas: int | None,
                cupo: int | None) -> tuple[str, CodigoInscripcion]:
    """Apaga el anterior y crea un código nuevo. Devuelve (código en claro, fila).

    La fecha de vencimiento la calcula la base (`now() + horas`), igual que la
    comprobación de vigencia: las dos usan el mismo reloj.
    """
    await apagar(db, group)
    codigo = generar()
    fila = CodigoInscripcion(
        tenant_id=group.tenant_id, group_id=group.id, codigo_hash=huella(codigo),
        expires_at=func.now() + func.make_interval(0, 0, 0, 0, horas or HORAS_POR_DEFECTO),
        cupo=cupo or group.max_capacity or CUPO_POR_DEFECTO, created_by=creador,
    )
    db.add(fila)
    await db.flush()
    await db.refresh(fila)
    return codigo, fila


async def estado(db: AsyncSession, group: Group) -> tuple[CodigoInscripcion, bool] | None:
    """(el código activo del grupo, ¿sigue vigente?) o `None` si no hay."""
    fila = (await db.execute(
        select(CodigoInscripcion, CodigoInscripcion.expires_at > func.now())
        .where(CodigoInscripcion.group_id == group.id, CodigoInscripcion.activo.is_(True))
    )).first()
    return None if fila is None else (fila[0], bool(fila[1]))
