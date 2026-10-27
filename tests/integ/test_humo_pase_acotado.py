"""HPA1 (humo) y RPA1 (réplica) del pase acotado — `docs/ESPEC_pase_acotado.md` §3.

HPA1: con `random.Random(46)`, dos instituciones, cuatro estudiantes (una en las
dos) y una docente con dos grupos. Cada persona pide un pase por audiencia y se
canjean todos; se reintenta uno (elegido con la semilla), se cruza uno de
audiencia, se vence uno y uno se prueba como Bearer en `/auth/me` antes de
canjearlo. Escribe `tests/_salida/humo_pase_acotado.json` (en `.gitignore`)
ANTES de afirmar.

RPA1 solo corre con `ENGRAMA_REPLICA_PASE=1` (sin ella se salta), con entradas
que no se usaron al desarrollar: una docente en TRES instituciones que pide el
pase en la tercera, 10 pases canjeados en orden inverso, un nombre con ñ y
tildes, y un pase con un carácter cambiado (401, y el verdadero sigue sirviendo).
Escribe `tests/_salida/humo_pase_acotado_replica.json`.
"""
from __future__ import annotations

import json
import os
import random
from datetime import timedelta
from typing import Any

import pytest

from src.shared.models import Membership, TeacherGroup
from tests.anillo import test_pase as tp
from tests.integ_db import RAIZ_BACKEND
from tests.seguridad.veredictos import sembrar

pytestmark = pytest.mark.integ

SALIDA = RAIZ_BACKEND / "tests" / "_salida"
RUTA_HUMO = SALIDA / "humo_pase_acotado.json"
RUTA_REPLICA = SALIDA / "humo_pase_acotado_replica.json"
SEMILLA = 46
REPLICA = os.environ.get("ENGRAMA_REPLICA_PASE") == "1"

# Contenido exacto (ESPEC §3). Si difiere se reporta; no se ajusta para que pase.
HUMO_ESPERADO: dict[str, Any] = {
    "alembic_version": "050_invitaciones_docente", "semilla": 46,
    "emitidos_201": 13, "canjes_200": 11, "canjes_401": 3, "canjes_403": 0,
    "reintento": 401, "cruzado": 401, "vencido": 401, "bearer_en_auth_me": 401,
    "filas": 13, "gastadas": 13, "el_pase_en_la_base": False,
    "la_de_dos_entra_por_b": True, "grupos_de_la_docente": ["H-1", "H-2"],
}


def _escribir(ruta: Any, datos: dict[str, Any]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def _el_pase_en_la_base(integ: Any, pases: list[str]) -> bool:
    todo = str(integ.valor("select coalesce(string_agg(row_to_json(p)::text, ' '), '') "
                           "from anillo_pases p"))
    return any(p in todo or p[len("pa1_"):] in todo for p in pases)


def test_hpa1_humo_pase_acotado(integ) -> None:
    rng = random.Random(SEMILLA)
    a, b = integ.crear_tenant(), integ.crear_tenant()
    estudiantes = [integ.crear_perfil(a, group_code="H-1", creada_hace=timedelta(days=2)),
                   integ.crear_perfil(a, group_code="H-2"), integ.crear_perfil(b),
                   integ.crear_perfil(b)]
    la_de_dos = estudiantes[0]
    integ._insertar(Membership(tenant_id=b, profile_id=la_de_dos, role="student",
                               is_active=True, full_name="La de dos"))
    profe = integ.crear_perfil(a, rol="teacher")
    for codigo in ("H-2", "H-1"):
        integ._insertar(TeacherGroup(tenant_id=a, teacher_id=profe,
                                     group_id=integ.crear_grupo(a, codigo)))

    emitidos: list[int] = []
    canjes: list[int] = []
    pases: list[str] = []

    def pedir(perfil: Any, audiencia: str, tenant: Any = None) -> str:
        r = tp.emitir(integ, perfil, audiencia, tenant)
        emitidos.append(r.status_code)
        pase = str(r.json().get("pase", "")) if r.status_code == 201 else ""
        pases.append(pase)
        return pase

    def canje(pase: str, audiencia: str) -> Any:
        r = tp.canjear(pase, audiencia)
        canjes.append(r.status_code)
        return r

    carnes: dict[tuple[Any, str], dict[str, Any]] = {}
    personas = [*estudiantes, profe]
    for persona in personas:
        for audiencia in ("eva", "set"):
            pase = pedir(persona, audiencia, b if persona == la_de_dos else None)
            r = canje(pase, audiencia)
            carnes[(persona, audiencia)] = r.json() if r.status_code == 200 else {}
    al_azar = pases[rng.randrange(len(pases))]
    reintento = canje(al_azar, "eva" if pases.index(al_azar) % 2 == 0 else "set").status_code
    cruzado = canje(pedir(estudiantes[1], "eva"), "set").status_code
    para_vencer = pedir(estudiantes[2], "set")
    sembrar(integ, "update anillo_pases set expira_en = now() - interval '1 second' "
                   "where hash = :h", h=tp.sha(para_vencer))
    vencido = canje(para_vencer, "set").status_code
    para_bearer = pedir(estudiantes[3], "eva")
    bearer = tp.client.get("/auth/me", headers={"Authorization": f"Bearer {para_bearer}"})
    canje(para_bearer, "eva")

    datos = {
        "alembic_version": integ.valor("select version_num from alembic_version"),
        "semilla": SEMILLA,
        "emitidos_201": emitidos.count(201),
        "canjes_200": canjes.count(200), "canjes_401": canjes.count(401),
        "canjes_403": canjes.count(403),
        "reintento": reintento, "cruzado": cruzado, "vencido": vencido,
        "bearer_en_auth_me": bearer.status_code,
        "filas": integ.valor("select count(*) from anillo_pases"),
        "gastadas": integ.valor("select count(*) from anillo_pases where usado_en is not null"),
        "el_pase_en_la_base": _el_pase_en_la_base(integ, [p for p in pases if p]),
        "la_de_dos_entra_por_b": carnes[(la_de_dos, "set")].get("active_tenant_id") == str(b),
        "grupos_de_la_docente": carnes[(profe, "set")].get("grupos_docente"),
    }
    _escribir(RUTA_HUMO, datos)  # primero el archivo, después la afirmación
    assert datos == HUMO_ESPERADO, f"HPA1: {datos}"


@pytest.mark.skipif(not REPLICA, reason="réplica: ENGRAMA_REPLICA_PASE=1")
def test_rpa1_replica_pase_acotado(integ) -> None:
    t1, t2, t3 = integ.crear_tenant(), integ.crear_tenant(), integ.crear_tenant()
    profe = integ.crear_perfil(t1, rol="teacher", creada_hace=timedelta(days=3))
    integ.afiliar(profe, t2, rol="teacher", creada_hace=timedelta(days=2))
    integ.afiliar(profe, t3, rol="teacher")
    en_la_tercera = tp.canjear(tp.pase_de(integ, profe, "eva", t3), "eva").json()

    est = integ.crear_perfil(t1)
    sembrar(integ, "update memberships set full_name = :n where profile_id = :p",
            n="Íñigo Peña Ñáñez", p=est)
    diez = [tp.pase_de(integ, est, "set") for _ in range(10)]
    al_reves = [tp.canjear(p, "set").status_code for p in reversed(diez)]
    nombre = None
    otro = tp.pase_de(integ, est, "eva")
    cambiado = otro[:-1] + ("A" if otro[-1] != "A" else "B")
    con_un_caracter_cambiado = tp.detalle(tp.canjear(cambiado, "eva"))
    verdadero = tp.canjear(otro, "eva")
    if verdadero.status_code == 200:
        nombre = verdadero.json().get("full_name")

    datos = {
        "tercera_activa": en_la_tercera.get("active_tenant_id") == str(t3),
        "tercera_sola": [m.get("tenant_id") == str(t3)
                         for m in en_la_tercera.get("memberships", [])],
        "diez_al_reves": al_reves,
        "con_un_caracter_cambiado": con_un_caracter_cambiado,
        "el_verdadero_sigue_sirviendo": verdadero.status_code,
        "nombre": nombre,
        "el_pase_en_la_base": _el_pase_en_la_base(integ, [*diez, otro]),
    }
    _escribir(RUTA_REPLICA, datos)
    assert datos == {
        "tercera_activa": True, "tercera_sola": [True], "diez_al_reves": [200] * 10,
        "con_un_caracter_cambiado": tp.INVALIDO, "el_verdadero_sigue_sirviendo": 200,
        "nombre": "Íñigo Peña Ñáñez", "el_pase_en_la_base": False,
    }, f"RPA1: {datos}"
