"""Ayudas de los tests de `/grader` (no empieza por `test_`: no se recolecta).

Un "colegio" sintético: institución, un grupo, su profe y N estudiantes con la
fecha de matrícula EXPLÍCITA (el orden de la lista no depende del reloj del
contenedor de pruebas). Y un Grader simulado: arma el examen y las hojas como
los mandaría el Grader real, con su `event_id` determinista.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient

from src.main import app
from src.shared.models import TeacherGroup

client = TestClient(app, raise_server_exceptions=False)

HUELLA = "a" * 64
OTRA_HUELLA = "b" * 64
CODIGO = "48210377"
CALIFICADO = "2026-10-06T15:04:05Z"


@dataclass(frozen=True)
class Colegio:
    tenant: UUID
    grupo: UUID
    codigo_grupo: str
    profe: UUID
    estudiantes: list[UUID]


def matricular(integ: Any, tenant: UUID, codigo_grupo: str, *, hace_dias: int) -> UUID:
    """Un estudiante en el grupo, matriculado hace `hace_dias` días (más días = antes)."""
    return integ.crear_perfil(tenant, group_code=codigo_grupo,
                              creada_hace=timedelta(days=hace_dias))


def colegio(integ: Any, codigo_grupo: str = "11A", n: int = 3) -> Colegio:
    tenant = integ.crear_tenant()
    grupo = integ.crear_grupo(tenant, codigo_grupo)
    profe = integ.crear_perfil(tenant, rol="teacher")
    integ._insertar(TeacherGroup(tenant_id=tenant, teacher_id=profe, group_id=grupo))
    estudiantes = [matricular(integ, tenant, codigo_grupo, hace_dias=1000 - i)
                   for i in range(n)]
    return Colegio(tenant, grupo, codigo_grupo, profe, estudiantes)


def _json(r: Any) -> Any:
    try:
        return r.json()
    except ValueError:
        return None


def lista(integ: Any, quien: UUID, codigo_grupo: str) -> tuple[int, list[tuple[int, str]]]:
    """`GET /grader/grupos/{codigo}/lista`: (estado, [(numero, student_id)])."""
    r = client.get(f"/grader/grupos/{codigo_grupo}/lista", headers=integ.headers(quien))
    cuerpo = _json(r) or {}
    return r.status_code, [(e["numero"], e["student_id"])
                           for e in cuerpo.get("estudiantes", [])] if r.status_code == 200 else []


def ids_de_items(n: int) -> list[str]:
    return [f"b1-u01-f{i:02d}-1" for i in range(1, n + 1)]


def item(item_id: str, **cambios: Any) -> dict[str, Any]:
    return {"item_id": item_id, "origen": "oficial", "nivel": "B1", "destreza": "gramatica",
            "tema": "tema sintético", "enunciado": f"Enunciado de {item_id}",
            "correcta_texto": "has worked", "explicacion": "Explicación corta.", **cambios}


def examen(codigo_grupo: str, n: int = 15, *, codigo: str = CODIGO, huella: str = HUELLA,
           **cambios: Any) -> dict[str, Any]:
    return {"codigo": codigo, "huella": huella, "titulo": "Examen sintético", "nivel": "B1",
            "group_code": codigo_grupo, "n_items": n,
            "items": [item(i) for i in ids_de_items(n)], **cambios}


def registrar(integ: Any, quien: UUID, cuerpo: dict[str, Any], *,
              en_la_ruta: str | None = None) -> tuple[int, Any]:
    """`PUT /grader/examenes/{codigo}`: (estado, `creado` o el detalle del error)."""
    ruta = en_la_ruta if en_la_ruta is not None else cuerpo.get("codigo", CODIGO)
    r = client.put(f"/grader/examenes/{ruta}", headers=integ.headers(quien), json=cuerpo)
    cuerpo_r = _json(r) or {}
    if r.status_code in (200, 201):
        return r.status_code, cuerpo_r.get("creado")
    detalle = cuerpo_r.get("detail")
    return r.status_code, detalle if isinstance(detalle, (str, dict)) else None


def item_de_hoja(item_id: str, *, estado: str = "marcada", correcta: bool = True,
                 **cambios: Any) -> dict[str, Any]:
    return {"item_id": item_id, "estado": estado, "correcta": correcta,
            "elegida_texto": "has worked" if correcta else "worked", "resuelta_por": None,
            **cambios}


def hoja(numero: int, n: int = 15, *, codigo: str = CODIGO, malas: tuple[int, ...] = (),
         vacias: tuple[int, ...] = (), dobles: tuple[int, ...] = (), forma: str = "A",
         **cambios: Any) -> dict[str, Any]:
    """Una hoja HONESTA: `aciertos` y `total` salen de sus ítems. `cambios` la rompe.

    `malas`, `vacias` y `dobles` son posiciones (desde 0) de los ítems fallados.
    """
    items = []
    for i, item_id in enumerate(ids_de_items(n)):
        if i in vacias:
            items.append(item_de_hoja(item_id, estado="vacia", correcta=False,
                                      elegida_texto=None))
        elif i in dobles:
            items.append(item_de_hoja(item_id, estado="doble", correcta=False,
                                      elegida_texto=None))
        else:
            items.append(item_de_hoja(item_id, correcta=i not in malas))
    aciertos = sum(1 for it in items if it["estado"] == "marcada" and it["correcta"])
    return {"event_id": f"grd:{codigo}:{numero}", "numero": numero, "forma": forma,
            "calificado_en": CALIFICADO, "items": items, "aciertos": aciertos, "total": n,
            **cambios}


def enviar(integ: Any, quien: UUID, codigo_grupo: str, hojas: list[dict[str, Any]], *,
           codigo: str = CODIGO, huella: str = HUELLA, **extra: Any) -> tuple[int, Any]:
    """`POST /grader/resultados`: (estado, (recibidas, reemplazadas, [(numero, motivo)]) o detalle)."""
    cuerpo = {"codigo": codigo, "huella": huella, "group_code": codigo_grupo, "hojas": hojas,
              **extra}
    r = client.post("/grader/resultados", headers=integ.headers(quien), json=cuerpo)
    c = _json(r) or {}
    if r.status_code != 200:
        detalle = c.get("detail") if isinstance(c, dict) else None
        return r.status_code, detalle if isinstance(detalle, str) else None
    return 200, (c["recibidas"], c["reemplazadas"],
                 [(x["numero"], x["motivo"]) for x in c["rechazadas"]])


def cuenta(integ: Any, tabla: str) -> int:
    """Filas de una tabla del Grader (el nombre es una constante del test)."""
    return int(integ.valor(f"select count(*) from {tabla}"))


def filas(integ: Any) -> tuple[int, int, int, int]:
    """(exámenes, ítems de examen, hojas, ítems de hoja)."""
    return (cuenta(integ, "grader_exams"), cuenta(integ, "grader_exam_items"),
            cuenta(integ, "grader_sheets"), cuenta(integ, "grader_sheet_items"))


def hoja_guardada(integ: Any, numero: int, codigo: str = CODIGO) -> Any:
    """(aciertos, total, ítems con `correcta`) de la hoja de ese número, o None."""
    fila = integ.fila(
        "select s.aciertos, s.total, "
        "(select count(*) from grader_sheet_items i where i.sheet_id = s.id and i.correcta) "
        "as correctas from grader_sheets s join grader_exams e on e.id = s.exam_id "
        "where e.codigo = :c and s.numero = :n", c=codigo, n=numero)
    return None if fila is None else (fila["aciertos"], fila["total"], int(fila["correctas"]))
