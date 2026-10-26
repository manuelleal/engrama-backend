"""Tramposos XP1-XP8, XP10 y XP11 de invitar profes — `docs/ESPEC_invitar_profe.md` §4.1.

Una versión ROTA a propósito, inyectada con monkeypatch en el módulo donde se
USA; se corre el cuerpo del test real y se exige `AssertionError` con el mensaje
del mecanismo (la diagonal: cada tramposo contra SU test).
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any
from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext
from src.invitar import envio as envio_mod
from src.invitar import schemas as schemas_mod
from src.invitar import service as service_mod
from src.main import app
from src.registro.cuentas import get_cuentas_de_invitacion
from src.shared.models import Group, InvitacionDocente, Membership, Profile
from tests.invitar import _ayuda as ay
from tests.invitar import test_invitar as ti

pytestmark = pytest.mark.integ

Aplicar = Callable[[pytest.MonkeyPatch], None]


@pytest.fixture(autouse=True)
def _soltar_dobles() -> Iterator[None]:
    yield
    ay.soltar()


def _parche(modulo: Any, nombre: str, valor: Any) -> Aplicar:
    return lambda mp: mp.setattr(modulo, nombre, valor)


# --- XP1: la lista sin el filtro de institución ---------------------------------
def _consulta_sin_tenant(auth: AuthContext):  # type: ignore[no-untyped-def]
    return (
        select(InvitacionDocente, Profile.force_password_reset, Membership.full_name,
               Group.group_code)
        .join(Profile, Profile.id == InvitacionDocente.profile_id)
        .join(Group, Group.id == InvitacionDocente.group_id)
        .outerjoin(Membership, (Membership.profile_id == InvitacionDocente.profile_id)
                   & (Membership.tenant_id == InvitacionDocente.tenant_id))
        .execution_options(populate_existing=True)
    )


# --- XP2 y XP10: invitar sin respetar la cuenta ajena -------------------------------
async def _invita_aunque_sea_ajena(cuentas: Any, pedido: envio_mod.PedidoDeEnvio) -> str:
    """XP2: con `correo_en_uso` sigue y pide la invitación igual."""
    if await cuentas.estado_de_cuenta(pedido.profile_id) is None:
        await cuentas.crear_invitado(pedido.profile_id, pedido.correo)
    return str(await cuentas.invitar(pedido.correo))


async def _invita_sin_mirar_el_id(cuentas: Any, pedido: envio_mod.PedidoDeEnvio) -> str:
    """XP10: pide la invitación por correo sin comprobar de quién es la cuenta (P9)."""
    return str(await cuentas.invitar(pedido.correo))


# --- XP3: el alta pregunta a GoTrue y delata la cuenta ajena -----------------------
_EXIGIR_CORREO_NUEVO = service_mod._exigir_correo_nuevo


async def _delata_la_ajena(db: AsyncSession, auth: AuthContext, correo: str) -> None:
    await _EXIGIR_CORREO_NUEVO(db, auth, correo)
    cuentas = app.dependency_overrides[get_cuentas_de_invitacion]()
    if cuentas is not None and cuentas._id_de(correo) is not None:
        raise HTTPException(status_code=409, detail="correo_con_cuenta")


# --- XP4 y XP5: sin tope y sin espera ----------------------------------------------
async def _sin_tope(db: AsyncSession, auth: AuthContext) -> None:
    return None


async def _sin_espera(db: AsyncSession, invitacion_id: int) -> None:
    return None


# --- XP7: el grupo por id, sin la barrera de institución ----------------------------
class _AccesoSinBarrera:
    @staticmethod
    async def authorize_group(db: AsyncSession, auth: AuthContext, group_id: UUID) -> Group:
        return (await db.execute(select(Group).where(Group.id == group_id))).scalar_one()


# --- XP8: el correo se pide ANTES de responder --------------------------------------
_INVITAR = service_mod.invitar


async def _envia_antes_de_responder(db: AsyncSession, auth: AuthContext,
                                    datos: Any) -> service_mod.Resultado:
    resultado = await _INVITAR(db, auth, datos)
    await envio_mod.enviar(app.dependency_overrides[get_cuentas_de_invitacion](),
                           resultado.pedido)
    return resultado


TRAMPOSOS: dict[str, tuple[Aplicar, Callable[..., None], str]] = {
    "XP1": (_parche(service_mod, "_consulta", _consulta_sin_tenant),
            ti.test_ip4_solo_el_admin_de_esa_institucion, r"IP4: \{'lista_de_b': \[\{"),
    "XP2": (_parche(envio_mod, "_enviar", _invita_aunque_sea_ajena),
            ti.test_ip3_correo_de_otra_institucion_se_ve_igual,
            r"'correo_a_la_ajena': \[\('invitar', 'ajena@sintetico\.test'\)"),
    "XP3": (_parche(service_mod, "_exigir_correo_nuevo", _delata_la_ajena),
            ti.test_ip3_correo_de_otra_institucion_se_ve_igual, r"IP3: \{'status': \(201, 409\)"),
    "XP4": (_parche(service_mod, "_exigir_tope", _sin_tope), ti.test_ip6_tope_por_admin,
            r"'cuarto': \(201, None, False\)"),
    "XP5": (_parche(service_mod, "_exigir_espera", _sin_espera),
            ti.test_ip7_espera_del_reenvio_y_aceptada, r"IP7: \{'inmediato': \(202, None"),
    "XP6": (_parche(service_mod, "estado_de", lambda bandera: schemas_mod.ENVIADA),
            ti.test_ip2_el_profe_acepta_y_entra_con_su_rol,
            r"'estado_en_la_lista': \['enviada'\]"),
    "XP7": (_parche(service_mod, "access", _AccesoSinBarrera),
            ti.test_ip4_solo_el_admin_de_esa_institucion, r"'b_invita_al_grupo_de_a': 201"),
    "XP8": (_parche(service_mod, "invitar", _envia_antes_de_responder),
            ti.test_ip12_gotrue_se_llama_despues_de_responder,
            r"'eventos': \['gotrue:estado_de_cuenta', 'gotrue:crear_invitado', "
            r"'gotrue:invitar', 'respuesta_enviada'"),
    "XP10": (_parche(envio_mod, "_enviar", _invita_sin_mirar_el_id),
             ti.test_ip3_correo_de_otra_institucion_se_ve_igual,
             r"'correo_a_la_ajena': \[\('invitar', 'ajena@sintetico\.test'\)"),
    # XP11: el correo sin pasar a minúsculas. Lo para el CHECK de la base antes que
    # la comparación (defensa en profundidad): la versión en MAYÚSCULAS da 500.
    "XP11": (_parche(schemas_mod.InvitacionIn, "correo_normalizado", lambda self: self.correo),
             ti.test_ip5_mismo_correo_dos_veces_en_la_misma_institucion,
             r"IP5: \{'status': \(201, 500\)"),
}


@pytest.mark.parametrize("clave", list(TRAMPOSOS))
def test_tramposo_pone_rojo_su_test(integ: Any, monkeypatch: pytest.MonkeyPatch,
                                    clave: str) -> None:
    aplicar, test_real, motivo = TRAMPOSOS[clave]
    aplicar(monkeypatch)
    with pytest.raises(AssertionError, match=motivo):
        test_real(integ)
