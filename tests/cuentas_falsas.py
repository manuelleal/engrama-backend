"""`CuentasFalsas`: el doble de la API admin de GoTrue — ESPEC_login_piloto §1.7.

No empieza por `test_`: pytest no lo recolecta. Lo usan `tests/onboarding/`,
el humo HP1 y la réplica.

Se comporta como GoTrue en lo que el alta necesita:
  - `crear` con un `id` que ya existe lanza `ErrorCuenta("id_en_uso")`
    (predicho para GoTrue; la CLI lo atrapa por fila y sale con 1);
  - `crear` SIN `id` inventa un `uuid4`, como GoTrue cuando elige el `sub`
    (para el tramposo ZP1);
  - `crear` con un correo que ya es de otra cuenta devuelve `correo_en_uso`.

Dos ayudas para OP8 (C24, "la bandera antes que la cuenta"):
  - `fallar_en`: documentos para los que `crear` falla (`ErrorCuenta`);
  - `observador`: una corrutina que se llama AL ENTRAR a `crear`, con el `id`
    pedido. `observar_bandera(sesiones)` lee `force_password_reset` de ese
    perfil desde OTRA conexión (el engine `NullPool` del fixture): solo ve lo
    que ya está commiteado.

Todo es sintético: ninguna contraseña de aquí sirve en ningún sistema.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from src.onboarding.cuentas import CORREO_EN_USO, CREADA, ErrorCuenta

Observador = Callable[[UUID | None], Awaitable[Any]]


def observar_bandera(sesiones: Any) -> Observador:
    """Observador que lee `profiles.force_password_reset` en una sesión NUEVA."""
    async def leer(perfil_id: UUID | None) -> Any:
        if perfil_id is None:
            return None
        async with sesiones() as db:
            return (await db.execute(
                text("select force_password_reset from profiles where id = :p"),
                {"p": perfil_id})).scalar()
    return leer


class CuentasFalsas:
    """Cuentas en memoria: `id -> {"correo", "clave"}`, y el registro de llamadas."""

    def __init__(self, *, sesiones: Any = None, fallar_en: set[str] | None = None,
                 observador: Observador | None = None, espera_crear: float = 0.0) -> None:
        # Segundos que tarda `crear`, como un GoTrue real (hashea la contraseña).
        # Solo lo usa la medición de tiempo del registro (AR18); 0 para todos los demás.
        self.espera_crear = espera_crear
        # Para el autorregistro: con `fallar_crear` o `fallar_borrar`, esa
        # llamada falla como un GoTrue caído (`ErrorCuenta`).
        self.fallar_crear = False
        self.fallar_borrar = False
        self.borradas: list[UUID] = []                       # cada `borrar` pedido
        self.cuentas: dict[UUID, dict[str, str]] = {}
        self.creadas: list[tuple[UUID | None, str]] = []    # (id pedido, correo), cada intento
        self.cambios: list[tuple[UUID, str]] = []            # (id, clave nueva)
        self.observado: list[Any] = []                       # lo que vio el observador
        self.sesiones = sesiones
        self.fallar_en = fallar_en if fallar_en is not None else set()
        self.observador = observador

    # ------------------------------------------------------------ el puerto
    async def buscar(self, id: UUID) -> str | None:
        cuenta = self.cuentas.get(id)
        return None if cuenta is None else cuenta["correo"]

    async def crear(self, id: UUID | None, correo: str, clave: str) -> str:
        self.creadas.append((id, correo))
        if self.espera_crear:
            await asyncio.sleep(self.espera_crear)
        if self.observador is not None:
            self.observado.append(await self.observador(id))
        if self.fallar_crear:
            raise ErrorCuenta("fallo sintético de crear")
        if self.fallar_en and await self._documento_de(id) in self.fallar_en:
            raise ErrorCuenta("fallo sintético de crear")
        if id is not None and id in self.cuentas:
            raise ErrorCuenta("id_en_uso")
        if any(c["correo"] == correo for c in self.cuentas.values()):
            return CORREO_EN_USO
        self.cuentas[id if id is not None else uuid4()] = {"correo": correo, "clave": clave}
        return CREADA

    async def borrar(self, id: UUID) -> None:
        """Como GoTrue: borrar una cuenta que no existe no es un error."""
        self.borradas.append(id)
        if self.fallar_borrar:
            raise ErrorCuenta("fallo sintético de borrar")
        self.cuentas.pop(id, None)

    async def cambiar_clave(self, id: UUID, clave: str) -> None:
        if id not in self.cuentas:
            raise ErrorCuenta("la cuenta no existe")
        self.cuentas[id]["clave"] = clave
        self.cambios.append((id, clave))

    # ------------------------------------------------------------ lecturas para los tests
    async def _documento_de(self, perfil_id: UUID | None) -> str | None:
        if perfil_id is None or self.sesiones is None:
            return None
        async with self.sesiones() as db:
            valor = (await db.execute(
                text("select documento_id from profiles where id = :p"),
                {"p": perfil_id})).scalar()
        return None if valor is None else str(valor)

    def id_de(self, correo: str) -> UUID | None:
        """El `id` de la cuenta de ese correo: el `sub` que GoTrue pondría en su JWT."""
        for cuenta_id, cuenta in self.cuentas.items():
            if cuenta["correo"] == correo:
                return cuenta_id
        return None

    def claves(self) -> set[str]:
        return {c["clave"] for c in self.cuentas.values()}
