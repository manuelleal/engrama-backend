"""Rutas del panel (ESPEC_panel_super_admin §1.4). Las tres son GET y de solo lectura.

  - `super_`: `/super/clientes` y `/super/clientes/{tenant_id}`, SOLO super admin
    (`require_super_admin`, que sale de `profiles.role`).
  - `admin`: `/admin/metricas`, del admin de la institución ACTIVA de su contexto
    (`require_admin` + `auth.tenant_id`). No recibe ningún tenant por parámetro:
    no hay manera de pedir las cifras de otro cliente.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext
from src.panel import servicio
from src.panel.acceso import require_super_admin
from src.panel.schemas import ClienteDetalle, PanelAdmin, PanelSuper
from src.shared.db import get_db
from src.shared.deps import require_admin

super_ = APIRouter()
admin = APIRouter()

CLIENTE_NO_EXISTE = "cliente_no_existe"


@super_.get("/clientes", response_model=PanelSuper)
async def listar_clientes(
    _super: UUID = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> PanelSuper:
    """Todos los clientes con sus cifras, los totales y las series de todo ENGRAMA."""
    return await servicio.panel_super(db)


@super_.get("/clientes/{tenant_id}", response_model=ClienteDetalle)
async def ver_cliente(
    tenant_id: UUID,
    _super: UUID = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
) -> ClienteDetalle:
    """Un cliente con sus series. 404 si no existe."""
    cliente = await servicio.detalle(db, tenant_id)
    if cliente is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CLIENTE_NO_EXISTE)
    return cliente


@admin.get("/metricas", response_model=PanelAdmin)
async def metricas_de_mi_institucion(
    auth: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> PanelAdmin:
    """Las cifras de la institución activa del admin, sin nombre."""
    return await servicio.panel_admin(db, auth.tenant_id)
