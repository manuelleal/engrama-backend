"""Tramposos ZR1-ZR19 del autorregistro — `docs/ESPEC_autorregistro.md` §3 (y §11: ZR24+).

Una versión ROTA a propósito, inyectada con monkeypatch en el módulo donde se
USA; se corre el cuerpo del test real y se exige `AssertionError` con el
mensaje del mecanismo. Aquí se automatiza la DIAGONAL; la matriz completa se
mide aparte (ERR-15, 19 y 23).

ZR9 reemplaza la `APIRoute` (el modelo del cuerpo queda fijado al decorar la
ruta), igual que XC2 del consentimiento. ZR10 reusa la fuente única de la
barrera de grupo (`access._requiere_asignacion`, el X2 de grupos; ERR-26).
"""
from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Callable, Iterator
from typing import Any
from uuid import UUID

import pytest
from fastapi import Depends, HTTPException, Request
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import politica_clave as politica_mod
from src.main import app
from src.registro import codigos as codigos_mod
from src.registro import decision as decision_mod
from src.registro import documento as documento_mod
from src.registro import limite as limite_mod
from src.registro import piso as piso_mod
from src.registro import router as router_mod
from src.registro import service as service_mod
from src.registro.cuentas import get_cuentas_de_registro
from src.registro.schemas import RegistroOut
from src.shared import deps as deps_mod
from src.shared.config import settings
from src.shared.db import get_db
from src.shared.models import CodigoInscripcion, Group, SolicitudInscripcion, Tenant
from src.teachers.service import access as access_mod
from src.teachers.service import roster as roster_mod
from tests.registro import _ayuda as ay
from tests.registro import test_auditoria03 as ta
from tests.registro import test_codigo as tc
from tests.registro import test_limite as tl
from tests.registro import test_piso as tp
from tests.registro import test_registro as tr
from tests.registro import test_solicitudes as ts

pytestmark = pytest.mark.integ

Aplicar = Callable[[pytest.MonkeyPatch], None]
_RUTA = "/auth/registro"


@pytest.fixture(autouse=True)
def _soltar_el_doble_al_terminar() -> Iterator[None]:
    """El doble de GoTrue no puede quedar puesto para el resto de la suite."""
    yield
    ay.soltar()


def _parche(modulo: Any, nombre: str, valor: Any) -> Aplicar:
    return lambda mp: mp.setattr(modulo, nombre, valor)


# --- ZR1 y ZR2: el código vale aunque no deba ---------------------------------
def _sin_mirar_vigencia(codigo: CodigoInscripcion, vigente: bool) -> str | None:
    return "sin_cupo" if codigo.usos >= codigo.cupo else None


def _sin_mirar_cupo(codigo: CodigoInscripcion, vigente: bool) -> str | None:
    if not codigo.activo:
        return "apagado"
    return None if vigente else "vencido"


# --- ZR4: la IP es lo primero que escribió el visitante -----------------------
def _ip_del_primer_valor(client_host: str | None, x_forwarded_for: str | None,
                         saltos: int) -> str:
    valores = [v.strip() for v in (x_forwarded_for or "").split(",") if v.strip()]
    return valores[0] if valores else (client_host or "desconocida")


# --- ZR5: la cuenta sin el id del perfil -------------------------------------
async def _crear_sin_id(cuentas: Any, profile_id: UUID, correo: str, clave: str) -> str:
    return str(await cuentas.crear(None, correo, clave))


# --- ZR6: un código estudiantil ya registrado sigue adelante ------------------
async def _nunca_ocupado(db: AsyncSession, cuentas: Any, slug: str, codigo: str) -> bool:
    return False


# --- ZR9: la ruta no exige la mayoría de edad ni el aviso --------------------
class _RegistroSinDeclarar(BaseModel):
    model_config = ConfigDict(extra="ignore")

    codigo: str
    nombre: str
    correo: str
    codigo_estudiantil: str
    contrasena: str
    mayor_de_edad: Any = True
    aviso_version: str = "sin-aviso"

    def correo_normalizado(self) -> str:
        return self.correo.lower()


async def _registra_sin_declarar(payload: Any, request: Request,
                                 cuentas: Any = Depends(get_cuentas_de_registro),
                                 db: AsyncSession = Depends(get_db)) -> Any:
    payload.mayor_de_edad = True
    return await router_mod.registrarse(payload, request, cuentas, db)


# Las anotaciones se fijan a mano: con `from __future__ import annotations`
# FastAPI no podría resolver el modelo creado aquí.
_registra_sin_declarar.__annotations__ = {
    "payload": _RegistroSinDeclarar, "request": Request, "cuentas": Any, "db": AsyncSession,
    "return": Any}


def _ruta_sin_declarar(mp: pytest.MonkeyPatch) -> None:
    rutas = list(app.router.routes)
    i = next(i for i, r in enumerate(rutas) if isinstance(r, APIRoute)
             and r.path == _RUTA and r.methods == {"POST"})
    rutas[i] = APIRoute(_RUTA, _registra_sin_declarar, methods=["POST"],
                        response_model=RegistroOut, status_code=201,
                        dependency_overrides_provider=app.router.dependency_overrides_provider)
    mp.setattr(app.router, "routes", rutas)


# --- ZR11: la solicitud se busca sin mirar de qué grupo es -------------------
async def _solicitud_de_cualquier_grupo(db: AsyncSession, group: Group,
                                        solicitud_id: int) -> SolicitudInscripcion | None:
    return (await db.execute(select(SolicitudInscripcion).where(
        SolicitudInscripcion.id == solicitud_id))).scalar_one_or_none()


# --- ZR12: la matrícula va al primer grupo de la institución -----------------
async def _primer_grupo(db: AsyncSession, codigo: CodigoInscripcion) -> tuple[Group, Tenant]:
    group = (await db.execute(select(Group).where(Group.tenant_id == codigo.tenant_id)
                              .order_by(Group.group_code).limit(1))).scalar_one()
    tenant = (await db.execute(select(Tenant).where(Tenant.id == codigo.tenant_id))).scalar_one()
    return group, tenant


# --- ZR13 y ZR15: la respuesta depende de lo que pasó ------------------------
def _respuesta_con_correo(resultado: str, payload: Any) -> dict[str, Any]:
    return {"estado": "pendiente", "correo": payload.correo}


def _respuesta_que_delata(resultado: str, payload: Any) -> dict[str, Any]:
    if resultado == service_mod.CORREO_EN_USO:
        raise HTTPException(status_code=409, detail="correo_en_uso")
    return {"estado": "pendiente"}


# --- ZR14 y ZR18: no se deshace / no se borra la cuenta ----------------------
async def _no_deshace(db: AsyncSession, cuentas: Any, reserva: Any, *,
                      puede_haber_cuenta: bool) -> None:
    return None


async def _no_borra_la_cuenta(cuentas: Any, profile_id: UUID) -> None:
    return None


# --- ZR17: nadie "espera aprobación" ------------------------------------------
async def _nadie_espera(db: AsyncSession, profile_id: UUID) -> bool:
    return False


# --- ZR19: el cupo se lee sin candado ----------------------------------------
async def _codigo_sin_candado(db: AsyncSession, huella_del_codigo: str,
                              ) -> tuple[CodigoInscripcion, bool] | None:
    fila = (await db.execute(
        select(CodigoInscripcion, CodigoInscripcion.expires_at > func.now())
        .where(CodigoInscripcion.codigo_hash == huella_del_codigo)
        .execution_options(populate_existing=True)
    )).first()
    return None if fila is None else (fila[0], bool(fila[1]))


# --- ZR24 (auditoría 03, S-7): la confirmación sin proteger, como antes ------
async def _confirma_sin_proteger(db: AsyncSession, cuentas: Any, reserva: Any,
                                 datos: Any) -> None:
    await service_mod._confirmar(db, reserva, datos)


# --- ZR25 (auditoría 03, S-3): se cuenta todo intento, sin saber si sirve ------
_ANOTAR_CODIGO_BUENO = limite_mod.anotar_codigo


def _anota_sin_saber_si_sirve(huella_del_codigo: str, *, valido: bool) -> None:
    _ANOTAR_CODIGO_BUENO(huella_del_codigo, valido=True)


# --- ZR27 (auditoría 03): "ocupado" compara el texto crudo, como antes -------
async def _solo_el_texto_exacto(db: AsyncSession, slug: str, codigo: str) -> list[Any]:
    perfil = await roster_mod.get_profile_by_documento(db, f"{slug}_{codigo}")
    return [] if perfil is None else [perfil]


# --- ZR32 y ZR33 (S-5): el piso de tiempo solo en un camino, o ninguno ---------
async def _sin_piso(inicio: float, **_: Any) -> float:
    """ZR33: la ruta no espera nada (el código de antes)."""
    return 0.0


def _piso_solo_en_ocupado(mp: pytest.MonkeyPatch) -> None:
    """ZR32: alguien rellenó la rama `ocupado` (la rápida) y se olvidó de las demás."""
    registrar_bueno = service_mod.registrar

    async def registrar_con_piso_en_uno(db: AsyncSession, cuentas: Any, datos: Any) -> str:
        inicio = time.perf_counter()
        resultado = await registrar_bueno(db, cuentas, datos)
        if resultado == service_mod.OCUPADO:
            await asyncio.sleep(max(0.0, settings.registro_piso_ms / 1000
                                    - (time.perf_counter() - inicio)))
        return resultado

    mp.setattr(piso_mod, "esperar", _sin_piso)
    mp.setattr(service_mod, "registrar", registrar_con_piso_en_uno)


def _varios(*aplicar: Aplicar) -> Aplicar:
    def todos(mp: pytest.MonkeyPatch) -> None:
        for uno in aplicar:
            uno(mp)
    return todos


# =============================================================================
# Registro: id -> (cómo romper, test real, mensaje con el que debe caer)
# =============================================================================
TRAMPOSOS: dict[str, tuple[Aplicar, Callable[..., None], str]] = {
    "ZR1": (_parche(service_mod, "_rechazo", _sin_mirar_vigencia),
            tc.test_ar3_codigo_no_valido_una_sola_respuesta,
            r"'vencido': \(201, \{'estado': 'pendiente'\}\), "
            r"'apagado': \(201, \{'estado': 'pendiente'\}\)"),
    "ZR2": (_parche(service_mod, "_rechazo", _sin_mirar_cupo),
            tc.test_ar4_el_cupo_no_se_pasa, r"AR4: \{'seguidos': \[201, 201, 500\]"),
    "ZR3": (_parche(limite_mod, "revisar", lambda ip, huella: 0),
            tl.test_ar10_limite_de_intentos, r"'el_61': \(403, 'codigo_no_valido', False\)"),
    "ZR4": (_parche(limite_mod, "ip_del_visitante", _ip_del_primer_valor),
            tl.test_ar10_limite_de_intentos, r"'con_encabezados_falsos': \[403\]"),
    "ZR5": (_parche(service_mod, "_crear_cuenta", _crear_sin_id),
            tr.test_ar2_registro_normal,
            r"'crear': \[\(False, 'ana\.sintetica@sintetico\.test'\)\], "
            r"'cuenta_con_el_id_del_perfil': False"),
    "ZR6": (_parche(service_mod, "_ocupado", _nunca_ocupado),
            tr.test_ar7_no_revela_ni_duplica,
            r"'matriculado_por_lista': \{'respuesta': \(201, \{'estado': 'pendiente'\}\), "
            r"'membresia': \('student', False, 'G1', 'Por Lista'\), 'cuenta': True"),
    "ZR7": (_parche(service_mod, "detalle_de_rechazo", lambda motivo: f"codigo_{motivo}"),
            tc.test_ar3_codigo_no_valido_una_sola_respuesta,
            r"'vencido': \(403, \{'detail': 'codigo_vencido'\}\)"),
    "ZR8": (_parche(service_mod, "NACE_ACTIVA", True),
            ts.test_ar5_pendiente_no_entra_y_aprobado_si,
            r"AR5: \{'antes': \[\(200, None\), \(200, None\)\]"),
    "ZR9": (_ruta_sin_declarar, tr.test_ar9_cuerpo_invalido_da_422_sin_escribir,
            r"AR9: \{'invalidos': \{'menor': 201, 'sin_declarar': 201"),
    "ZR10": (_parche(access_mod, "_requiere_asignacion", lambda auth, *, only_assigned: False),
             ts.test_ar6_quien_decide_y_que_deja_el_rechazo,
             r"'docente_sin_ese_grupo': 200"),
    "ZR11": (_parche(decision_mod, "_solicitud_del_grupo", _solicitud_de_cualquier_grupo),
             ts.test_ar6_quien_decide_y_que_deja_el_rechazo,
             r"'la_de_g2_por_la_ruta_de_g1': \[200, 404\]"),
    "ZR12": (_parche(service_mod, "_grupo_del_codigo", _primer_grupo),
             tr.test_ar11_el_codigo_inscribe_solo_en_su_grupo,
             r"'membresia_en_a': \('student', False, 'G0', 'Persona Sintética 1'\)"),
    "ZR13": (_parche(router_mod, "_respuesta_uniforme", _respuesta_con_correo),
             tr.test_ar2_registro_normal,
             r"'clave_o_correo_en_la_respuesta': True"),
    "ZR14": (_parche(service_mod, "_deshacer", _no_deshace),
             tr.test_ar8_compensacion_y_huerfano,
             r"AR8: \{'crear_falla': \{'respuesta': \(502, \{'detail': "
             r"'registro_no_disponible'\}\), 'perfil': UUID\("),
    "ZR15": (_parche(router_mod, "_respuesta_uniforme", _respuesta_que_delata),
             tr.test_ar7_no_revela_ni_duplica,
             r"AR7: \{'correo_en_uso': \{'respuesta': \(409, \{'detail': 'correo_en_uso'\}\)"),
    "ZR16": (_parche(codigos_mod, "huella", codigos_mod.normalizar),
             tc.test_ar1_el_profe_crea_reemplaza_y_apaga_el_codigo,
             r"AR1: \{'crear': \{'respuesta': \(500, False, None, None, \[\]\)"),
    "ZR17": (_parche(deps_mod, "espera_aprobacion", _nadie_espera),
             ts.test_ar5_pendiente_no_entra_y_aprobado_si,
             r"AR5: \{'antes': \[\(403, 'User has no active tenant memberships'\)"),
    "ZR18": (_varios(_parche(decision_mod, "_borrar_cuenta", _no_borra_la_cuenta)),
             ts.test_ar6_quien_decide_y_que_deja_el_rechazo,
             r"'borrar_en_gotrue': False, 'cuenta': True"),
    "ZR19": (_parche(service_mod, "_codigo_con_candado", _codigo_sin_candado),
             tc.test_ar4_el_cupo_no_se_pasa,
             r"'carrera': \{'estados': \[201, 201\], 'usos': 1, 'solicitudes': 2, 'cuentas': 2"),
    # --- Auditoría 03 (ESPEC §11) ---
    "ZR24": (_parche(service_mod, "_confirmar_o_deshacer", _confirma_sin_proteger),
             ta.test_ar12_si_falla_la_confirmacion_no_queda_cuenta,
             r"AR12: \{'t2_falla': \{'respuesta': \(500, None\), "
             r"'borrar_la_cuenta_del_perfil': False, 'cuenta': True"),
    "ZR25": (_parche(limite_mod, "anotar_codigo", _anota_sin_saber_si_sirve),
             ta.test_ar13_los_codigos_inventados_no_agotan_el_registro,
             r"AR13: \{'basura': \[403, 403, 403, 429, 429\], "
             r"'llaves_por_codigo_tras_la_basura': 3"),
    "ZR26": (_parche(router_mod, "_exigir_aviso_configurado", lambda: None),
             ta.test_ar15_sin_lista_de_avisos_el_registro_no_abre,
             r"AR15: \{'lista_vacia': \(201, \{'estado': 'pendiente'\}\)"),
    "ZR27": (_parche(documento_mod, "perfiles_con_ese_codigo", _solo_el_texto_exacto),
             ta.test_ar16_las_variantes_de_un_codigo_ocupado_no_entran,
             r"'tras_las_variantes': \{'otro_crear': 4, 'perfiles': 5, 'usos': 5"),
    # --- Cierre de S-6 (ESPEC §12.1): el esquema de antes, sin regla de composición ---
    "ZR31": (_parche(politica_mod, "cumple_composicion", lambda clave: True),
             ta.test_ar17_la_contrasena_sin_letra_o_sin_numero_da_422,
             r"AR17: \{'estados': \{'solo_letras': 201, 'solo_digitos': 201\}"),
    # --- Cierre de S-5 (ESPEC §12.2): el piso de tiempo en un solo camino, o ninguno ---
    "ZR32": (_piso_solo_en_ocupado, tp.test_ar18_el_201_y_el_403_del_registro_no_delatan_por_tiempo,
             r"'con_piso_pegados': False"),
    "ZR33": (_parche(piso_mod, "esperar", _sin_piso),
             tp.test_ar18_el_201_y_el_403_del_registro_no_delatan_por_tiempo,
             r"'con_piso_pegados': False, 'nadie_bajo_el_piso': False"),
}


def correr(test_real: Callable[..., None], integ: Any, mp: pytest.MonkeyPatch,
           caplog: pytest.LogCaptureFixture) -> None:
    """Corre el cuerpo de un test real, con las fixtures que pida además de `integ`."""
    disponibles = {"integ": integ, "monkeypatch": mp, "caplog": caplog}
    pedidas = inspect.signature(test_real).parameters
    test_real(**{nombre: disponibles[nombre] for nombre in pedidas})


@pytest.mark.parametrize("clave", list(TRAMPOSOS))
def test_tramposo_pone_rojo_su_test(integ, monkeypatch, caplog, clave: str) -> None:
    aplicar, test_real, motivo = TRAMPOSOS[clave]
    aplicar(monkeypatch)
    with pytest.raises(AssertionError, match=motivo):
        correr(test_real, integ, monkeypatch, caplog)
