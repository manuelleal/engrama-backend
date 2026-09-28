"""BUG-11: el nombre del estudiante vive en la membresía — `docs/ESPEC_bug11.md` §2, §3.

El hueco (ESPEC §0): el colegio A matricula el documento D con el nombre N1,
el colegio B matricula el MISMO D con N2. Hoy M3/M4 reusan el perfil global
de D y descartan N2 en silencio, así que el colegio B ve N1 (un dato que
escribió OTRO colegio) en T2 y en T5.

  A1  C1 + C5  M3 en A y en B -> cada T2 muestra SOLO su nombre; `profiles` sin nombre.
  A2  C2       lo mismo en T5 (`students[].full_name`).
  A3  C3       lo mismo por CSV (M4); reimportar en B no pisa el nombre de B.
  A4  C4       el orden alfabético usa el nombre de ESE colegio.
  S1  C6       identidad del caso sin cruce: un colegio, 3 estudiantes por M4,
               T2 y T5 byte a byte contra el snapshot congelado en `84ce99a`.

A1-A4 afirman por la API (solo A1 mira además `profiles`) y NUNCA nombran
`memberships.full_name`: por eso corren sobre el código viejo con
`xfail(strict=True, raises=AssertionError)` — el hueco se ve en rojo. Si el
hueco se cerrara sin quitar el xfail, el estricto se pone rojo (XPASS).

Datos sintéticos (ESPEC §3): documentos `SINT-B11-0001`, `-0101`, `-0102`,
`-0201`. Los nombres de un colegio llevan `Alfa` y los del otro `Beta`;
ninguno es subcadena de otro. Cada test arranca con la base truncada
(fixture `integ`), así que S1 puede reusar documentos de A1 y A4.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.shared.models import TeacherGroup
from tests.seguridad.veredictos import PruebaRota
from tests.teachers._actores import Escuela, armar

pytestmark = pytest.mark.integ
client = TestClient(app)

# Se quita en el commit 2 de ESPEC §10 (el `fix`): ahí A1-A4 pasan a verde.
XFAIL_BUG11 = pytest.mark.xfail(strict=True, raises=AssertionError, reason="BUG-11")

RUTA_SNAPSHOT = Path(__file__).with_name("snapshot_bug11_un_colegio.json")


# =============================================================================
# Siembra y llamadas
# =============================================================================
def _sembrar(integ: Any) -> Escuela:
    """`armar` + DT como docente de GB (ESPEC §3), para que B tenga quien vea T2/T5."""
    esc = armar(integ)
    integ._insertar(TeacherGroup(tenant_id=esc.tenant_b, teacher_id=esc.dt,
                                 group_id=esc.grupo_b))
    return esc


def _exigir(r: Any, status: int, que: str) -> None:
    """Arnés: otro status es `PruebaRota`, NO AssertionError.

    Así, con el xfail estricto de A1-A4, una siembra rota sale en rojo y no
    se confunde con el hueco (mismo criterio que `tests/seguridad/veredictos.py`).
    """
    if r.status_code != status:
        raise PruebaRota(f"{que}: se esperaba {status} y llegó {r.status_code}: {r.text}")


def _m3(integ: Any, esc: Escuela, admin: UUID, grupo: UUID, doc: str, nombre: str) -> str:
    """M3 que debe dar 201 `inscrito`. Devuelve el `profile_id`."""
    r = client.post(f"/admin/groups/{grupo}/students", headers=esc.h(integ, admin),
                    json={"documento_id": doc, "nombre_completo": nombre})
    _exigir(r, 201, f"M3 {doc}")
    if r.json()["resultado"] != "inscrito":
        raise PruebaRota(f"M3 {doc}: 201 sin `inscrito`: {r.text}")
    return str(r.json()["profile_id"])


def _m4(integ: Any, esc: Escuela, admin: UUID, grupo: UUID,
        filas: list[tuple[str, str]]) -> dict[str, int]:
    """M4 con CSV de `,`; exige 201 y devuelve el cuerpo."""
    csv_texto = "documento_id,nombre_completo\n" + "".join(f"{d},{n}\n" for d, n in filas)
    r = client.post(f"/admin/groups/{grupo}/students/import",
                    headers={**esc.h(integ, admin), "Content-Type": "text/csv"},
                    content=csv_texto.encode("utf-8"))
    _exigir(r, 201, "M4")
    cuerpo: dict[str, int] = r.json()
    return cuerpo


def _t2(integ: Any, esc: Escuela, docente: UUID, grupo: UUID) -> tuple[list[dict[str, Any]], str]:
    r = client.get(f"/teachers/groups/{grupo}/students", headers=esc.h(integ, docente))
    _exigir(r, 200, "T2")
    return r.json(), r.text


def _t5(integ: Any, esc: Escuela, docente: UUID, grupo: UUID) -> tuple[list[dict[str, Any]], str]:
    r = client.get(f"/teachers/groups/{grupo}/achievement", headers=esc.h(integ, docente))
    _exigir(r, 200, "T5")
    return r.json()["students"], r.text


def _nombre_de(filas: list[dict[str, Any]], pid: str) -> str:
    """El `full_name` con el que ese listado muestra a `pid` (AssertionError si no está)."""
    nombres = [f["full_name"] for f in filas if f["profile_id"] == pid]
    assert len(nombres) == 1, f"{pid} aparece {len(nombres)} veces en el listado"
    return str(nombres[0])


def _aislado(filas: list[dict[str, Any]], texto: str, pid: str, propio: str,
             ajenos: tuple[str, ...], donde: str) -> None:
    """`donde` muestra a `pid` con SU nombre y ningún nombre de otro colegio sale en el cuerpo."""
    assert _nombre_de(filas, pid) == propio, (
        f"{donde}: muestra {_nombre_de(filas, pid)!r} en lugar de {propio!r} (BUG-11)"
    )
    for ajeno in ajenos:
        assert ajeno not in texto, f"{donde}: sale {ajeno!r}, que escribió otro colegio"


# =============================================================================
# A1-A4 — el hueco, por la API
# =============================================================================
N1, N2 = "Ana Prueba Alfa", "Ana Prueba Beta"
DOC_D = "SINT-B11-0001"


def _mismo_doc_en_dos_colegios(integ: Any, esc: Escuela) -> str:
    """AA matricula D con N1 en GA; AB, el mismo D con N2 en GB. Mismo `profile_id`."""
    pid_a = _m3(integ, esc, esc.aa, esc.grupo_a, DOC_D, N1)
    pid_b = _m3(integ, esc, esc.ab, esc.grupo_b, DOC_D, N2)
    assert pid_a == pid_b, "la identidad es global (ESPEC §1): un solo profile_id"
    return pid_a


@XFAIL_BUG11
def test_a1_t2_cada_colegio_ve_su_nombre(integ) -> None:
    """A1 (C1 + C5): T2 de GA muestra N1 y no N2; T2 de GB, N2 y no N1; `profiles` = ''."""
    esc = _sembrar(integ)
    pid = _mismo_doc_en_dos_colegios(integ, esc)

    filas_a, texto_a = _t2(integ, esc, esc.d, esc.grupo_a)
    _aislado(filas_a, texto_a, pid, N1, (N2,), "T2 de GA")
    filas_b, texto_b = _t2(integ, esc, esc.dt, esc.grupo_b)
    _aislado(filas_b, texto_b, pid, N2, (N1,), "T2 de GB")

    # C5: nada del colegio en `profiles`, y una sola fila con ese documento.
    assert integ.valor("select count(*) from profiles where documento_id = :d", d=DOC_D) == 1
    assert integ.valor("select full_name from profiles where id = :p", p=pid) == "", (
        "un nombre puesto por un colegio quedó en profiles.full_name"
    )


@XFAIL_BUG11
def test_a2_t5_cada_colegio_ve_su_nombre(integ) -> None:
    """A2 (C2): lo mismo que A1 en T5 (`students[].full_name`)."""
    esc = _sembrar(integ)
    pid = _mismo_doc_en_dos_colegios(integ, esc)

    filas_a, texto_a = _t5(integ, esc, esc.d, esc.grupo_a)
    _aislado(filas_a, texto_a, pid, N1, (N2,), "T5 de GA")
    filas_b, texto_b = _t5(integ, esc, esc.dt, esc.grupo_b)
    _aislado(filas_b, texto_b, pid, N2, (N1,), "T5 de GB")


@XFAIL_BUG11
def test_a3_csv_cada_colegio_ve_su_nombre_y_reimportar_no_pisa(integ) -> None:
    """A3 (C3): M4 en A (Alfa) y en B (Beta); reimportar en B con Gamma no pisa Beta."""
    esc = _sembrar(integ)
    doc = "SINT-B11-0201"
    alfa, beta, gamma = "Beto Prueba Alfa", "Beto Prueba Beta", "Beto Prueba Gamma"

    assert _m4(integ, esc, esc.aa, esc.grupo_a, [(doc, alfa)]) == {
        "creados": 1, "ya_estaban": 0, "total": 1}
    assert _m4(integ, esc, esc.ab, esc.grupo_b, [(doc, beta)]) == {
        "creados": 1, "ya_estaban": 0, "total": 1}
    assert _m4(integ, esc, esc.ab, esc.grupo_b, [(doc, gamma)]) == {
        "creados": 0, "ya_estaban": 1, "total": 1}
    pid = str(integ.valor("select id from profiles where documento_id = :d", d=doc))

    filas_a, texto_a = _t2(integ, esc, esc.d, esc.grupo_a)
    _aislado(filas_a, texto_a, pid, alfa, (beta, gamma), "T2 de GA")
    filas_b, texto_b = _t2(integ, esc, esc.dt, esc.grupo_b)
    _aislado(filas_b, texto_b, pid, beta, (alfa, gamma), "T2 de GB")


@XFAIL_BUG11
def test_a4_orden_alfabetico_con_el_nombre_de_cada_colegio(integ) -> None:
    """A4 (C4): P y Q en los dos colegios con órdenes opuestos; cada uno ve el suyo.

    Se filtra por sufijo (`Alfa` en A, `Beta` en B) porque GA también tiene a E.
    """
    esc = _sembrar(integ)
    p = _m3(integ, esc, esc.aa, esc.grupo_a, "SINT-B11-0101", "Ana Orden Alfa")
    q = _m3(integ, esc, esc.aa, esc.grupo_a, "SINT-B11-0102", "Zoe Orden Alfa")
    assert _m3(integ, esc, esc.ab, esc.grupo_b, "SINT-B11-0101", "Zoe Orden Beta") == p
    assert _m3(integ, esc, esc.ab, esc.grupo_b, "SINT-B11-0102", "Ana Orden Beta") == q

    for ver, nombre in ((_t2, "T2"), (_t5, "T5")):
        filas_a, _ = ver(integ, esc, esc.d, esc.grupo_a)
        filas_b, _ = ver(integ, esc, esc.dt, esc.grupo_b)
        orden_a = [f["profile_id"] for f in filas_a if f["full_name"].endswith(" Alfa")]
        orden_b = [f["profile_id"] for f in filas_b if f["full_name"].endswith(" Beta")]
        assert orden_a == [p, q], f"{nombre} de GA: orden {orden_a}, se esperaba [P, Q]"
        assert orden_b == [q, p], f"{nombre} de GB: orden {orden_b}, se esperaba [Q, P]"


# =============================================================================
# S1 — regresión = identidad del caso sin cruce
# =============================================================================
S1_FILAS = [("SINT-B11-0001", "Ana Prueba Alfa"), ("SINT-B11-0101", "Beto Prueba Alfa"),
            ("SINT-B11-0102", "Caro Prueba Alfa")]


def capturar_s1(integ: Any) -> dict[str, str]:
    """Un colegio (A), un grupo solo para S1 (GS, docente D), 3 estudiantes por M4.

    GS y no GA: GA ya trae a E, cuyo nombre es aleatorio (`Persona <hex>`) y
    rompería el byte a byte. Devuelve los cuerpos CRUDOS de T2 y T5 con cada
    `profile_id` reemplazado por `P<posición en T2>` (ESPEC §2, C6).
    """
    esc = armar(integ)
    grupo_s = integ.crear_grupo(esc.tenant_a, "GS")
    integ._insertar(TeacherGroup(tenant_id=esc.tenant_a, teacher_id=esc.d, group_id=grupo_s))
    assert _m4(integ, esc, esc.aa, grupo_s, S1_FILAS) == {
        "creados": 3, "ya_estaban": 0, "total": 3}

    filas_t2, texto_t2 = _t2(integ, esc, esc.d, grupo_s)
    _, texto_t5 = _t5(integ, esc, esc.d, grupo_s)
    for i, fila in enumerate(filas_t2, start=1):
        texto_t2 = texto_t2.replace(fila["profile_id"], f"P{i}")
        texto_t5 = texto_t5.replace(fila["profile_id"], f"P{i}")
    return {"t2": texto_t2, "t5": texto_t5}


def test_s1_un_colegio_identico_al_snapshot(integ) -> None:
    """S1 (C6): T2 y T5 de D, byte a byte, contra `snapshot_bug11_un_colegio.json`."""
    congelado = json.loads(RUTA_SNAPSHOT.read_text(encoding="utf-8"))
    actual = capturar_s1(integ)
    assert actual["t2"] == congelado["t2"], "T2 cambió en el caso sin cruce (regresión)"
    assert actual["t5"] == congelado["t5"], "T5 cambió en el caso sin cruce (regresión)"
