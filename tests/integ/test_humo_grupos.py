"""F12 — Humo de `/teachers` y `/admin` de punta a punta — ESPEC §5.

AA crea el grupo, asigna a D e importa 3 filas; D abre una sesión, un
estudiante hace check-in y D la cierra. Escribe `tests/_salida/humo_grupos.json`
(en `.gitignore`) y afirma que su contenido es exactamente el esperado.
"""
from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.main import app
from tests.integ_db import RAIZ_BACKEND

pytestmark = pytest.mark.integ
client = TestClient(app)

RUTA_HUMO_GRUPOS = RAIZ_BACKEND / "tests" / "_salida" / "humo_grupos.json"

HUMO_ESPERADO: dict[str, Any] = {
    "inscritos": 3,
    "docentes": 1,
    "checkin": 200,
    "checkin_tras_cierre": 410,
    "con_asistencia": 1,
}


def test_f12_humo_grupos_de_punta_a_punta(integ) -> None:
    tenant = integ.crear_tenant(pool=1000)
    aa = integ.crear_perfil(tenant, rol="admin")
    d = integ.crear_perfil(tenant, rol="teacher")

    # 1. AA crea el grupo.
    r_grupo = client.post("/admin/groups", headers=integ.headers(aa),
                           json={"group_code": "HUMO-G1"})
    assert r_grupo.status_code == 201, r_grupo.text
    gid = r_grupo.json()["id"]

    # 2. AA asigna a D.
    doc_d = integ.fila("select documento_id from profiles where id = :p", p=d)["documento_id"]
    r_asigna = client.post(f"/admin/groups/{gid}/teachers", headers=integ.headers(aa),
                            json={"documento_id": doc_d})
    assert r_asigna.status_code == 201, r_asigna.text
    docentes = integ.valor(
        "select count(*) from teacher_groups where group_id = :g", g=gid
    )

    # 3. AA importa 3 filas.
    csv_texto = "documento_id,nombre_completo\nhumo-1,Uno\nhumo-2,Dos\nhumo-3,Tres\n"
    r_import = client.post(f"/admin/groups/{gid}/students/import",
                            headers={**integ.headers(aa), "Content-Type": "text/csv"},
                            content=csv_texto.encode("utf-8"))
    assert r_import.status_code == 201, r_import.text
    inscritos = r_import.json()["creados"]

    # 4. D abre una sesión.
    r_sesion = client.post(f"/teachers/groups/{gid}/attendance-sessions",
                            headers=integ.headers(d), json={"duration_minutes": 15})
    assert r_sesion.status_code == 201, r_sesion.text
    codigo = r_sesion.json()["session_code"]
    sid = r_sesion.json()["id"]

    # 5. Un estudiante importado hace check-in.
    estudiante = integ.valor(
        "select id from profiles where documento_id = 'humo-1'"
    )
    r_checkin = client.post("/core/attendance/check-in", headers=integ.headers(estudiante),
                             json={"session_code": codigo})
    checkin = r_checkin.status_code

    # 6. D cierra la sesión.
    r_cierra = client.post(f"/teachers/attendance-sessions/{sid}/close", headers=integ.headers(d))
    assert r_cierra.status_code == 200, r_cierra.text

    # 7. Check-in tras el cierre.
    r_checkin_2 = client.post("/core/attendance/check-in", headers=integ.headers(estudiante),
                               json={"session_code": codigo})
    checkin_tras_cierre = r_checkin_2.status_code

    con_asistencia = integ.valor(
        "select count(distinct student_id) from attendance where session_id = :s", s=sid
    )

    datos = {
        "inscritos": inscritos,
        "docentes": int(docentes),
        "checkin": checkin,
        "checkin_tras_cierre": checkin_tras_cierre,
        "con_asistencia": int(con_asistencia),
    }
    RUTA_HUMO_GRUPOS.parent.mkdir(parents=True, exist_ok=True)
    RUTA_HUMO_GRUPOS.write_text(
        json.dumps(datos, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    assert datos == HUMO_ESPERADO, f"humo_grupos: {datos} != {HUMO_ESPERADO}"
    en_disco = json.loads(RUTA_HUMO_GRUPOS.read_text(encoding="utf-8"))
    assert en_disco == datos
