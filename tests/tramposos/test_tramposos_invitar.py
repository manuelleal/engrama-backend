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
from sqlalchemy import true as sa_true
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext
from src.bolsillo import consultas as consultas_mod
from src.invitar import cancelar as cancelar_mod
from src.invitar import envio as envio_mod
from src.invitar import schemas as schemas_mod
from src.invitar import service as service_mod
from src.main import app
from src.registro.cuentas import get_cuentas_de_invitacion
from src.shared.models import Group, InvitacionDocente, Membership, Profile
from tests.integ import test_migracion_050 as tm50
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
async def _invita_aunque_sea_ajena(cuentas: Any, pedido: envio_mod.PedidoDeEnvio,
                                   sesiones: Any = None) -> str:
    """XP2: con `correo_en_uso` sigue y pide la invitación igual."""
    if await cuentas.estado_de_cuenta(pedido.profile_id) is None:
        await cuentas.crear_invitado(pedido.profile_id, pedido.correo)
    return str(await cuentas.invitar(pedido.correo))


async def _invita_sin_mirar_el_id(cuentas: Any, pedido: envio_mod.PedidoDeEnvio,
                                  sesiones: Any = None) -> str:
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


async def _sin_tope_global(db: AsyncSession) -> None:
    return None


async def _borra_aunque_haya_aceptado(db: AsyncSession, perfil: object) -> bool:
    """XP22: el DELETE de antes, sin mirar la bandera."""
    await db.execute(select(Profile.id).where(Profile.id == perfil))
    from sqlalchemy import delete as _delete
    await db.execute(_delete(Profile).where(Profile.id == perfil))
    return True


async def _siempre_sigue(sesiones: Any, invitacion_id: int) -> bool:
    """XP23: el envío no mira si la invitación se canceló."""
    return True


async def _borra_sin_mirar(cuentas: Any, inv: Any) -> bool:
    """XP18: borra la cuenta del id de la invitación sin mirar si es nuestra ni si está confirmada."""
    await cuentas.borrar(inv.profile_id)
    return True


def _acepta_cancelar_sin_mirar(mp: pytest.MonkeyPatch) -> None:
    """XP19: cancelar no mira si se aceptó, ni antes ni al borrar (la segunda barrera es la del delta H-1)."""
    mp.setattr(cancelar_mod, "service", _ServiceAceptaCancelar)
    mp.setattr(cancelar_mod, "_borrar_perfil_si_sigue_pendiente", _borra_aunque_haya_aceptado)


class _ServiceAceptaCancelar:
    """XP19: cancelar no mira si la invitación ya se aceptó."""

    ACEPTADA = "nunca"
    YA_ACEPTADA = service_mod.YA_ACEPTADA
    una = staticmethod(service_mod.una)


async def _no_guarda(sesiones: Any, invitacion_id: int, resultado: str) -> None:
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
    # XP16 y XP17 (H-3): sin tope global; el resultado del envío no se guarda.
    "XP16": (_parche(service_mod, "_exigir_tope_global", _sin_tope_global),
             ti.test_ip15_tope_global_de_todas_las_instituciones,
             r"'cuarta_de_b': \(201, None, False\)"),
    "XP17": (_parche(envio_mod, "_guardar_resultado", _no_guarda),
             ti.test_ip14_el_resultado_del_envio_queda_solo_para_el_operador,
             r"IP14: \{'resultados': \[None, None, None, None\]"),
    # XP18 a XP20 (H-4).
    "XP18": (_parche(cancelar_mod, "_borrar_cuenta_si_es_nuestra", _borra_sin_mirar),
             ti.test_ip16_cancelar_una_invitacion_no_aceptada, r"'llamadas_borrar': \[[^]]+, "),
    "XP19": (_acepta_cancelar_sin_mirar,
             ti.test_ip16_cancelar_una_invitacion_no_aceptada, r"'codigos': \[204, 204, 204, 204\]"),
    "XP20": (_parche(consultas_mod, "sin_invitacion_pendiente", sa_true),
             ti.test_ip17_los_invitados_pendientes_no_entran_al_reparto,
             r"IP17: \{'antes': \[True, True, True, True\]"),
    # XP22 y XP23 (auditoría del delta, H-1 y H-2).
    "XP22": (_parche(cancelar_mod, "_borrar_perfil_si_sigue_pendiente", _borra_aunque_haya_aceptado),
             ti.test_ip18_cancelar_no_borra_si_el_profe_acepta_en_medio,
             r"IP18: \{'cancelar': \(204, None\)"),
    "XP23": (_parche(envio_mod, "_sigue", _siempre_sigue),
             ti.test_ip19_el_envio_no_hace_nada_si_la_invitacion_se_cancelo,
             r"IP19: \{'antes': \('enviada', \['estado_de_cuenta', 'crear_invitado', 'invitar'\]\)"),
    # XP14 (H-1): la 050 sin el REVOKE: con privilegios por defecto abiertos, los clientes leerían los correos.
    "XP14": (_parche(tm50.M050, "SQL_SUBIR", tuple(s for s in tm50.M050.SQL_SUBIR
                                                  if not s.startswith("REVOKE"))),
             tm50.test_mg50b_cerrada_aunque_los_privilegios_por_defecto_la_abran,
             r"MG50b: \{'privilegios_de_clientes': 'anon:DELETE,anon:INSERT"),
}


@pytest.mark.parametrize("clave", list(TRAMPOSOS))
def test_tramposo_pone_rojo_su_test(integ: Any, monkeypatch: pytest.MonkeyPatch,
                                    clave: str) -> None:
    aplicar, test_real, motivo = TRAMPOSOS[clave]
    aplicar(monkeypatch)
    with pytest.raises(AssertionError, match=motivo):
        test_real(integ)
