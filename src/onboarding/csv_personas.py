"""El CSV del alta: lectura y validación, sin base — `docs/ESPEC_login_piloto.md` §1.7.

`leer_csv` es una función PURA: recibe los bytes del archivo y el `slug` de la
institución, y devuelve las filas válidas y TODOS los errores juntos, cada uno
con su número de fila. Quien la llama no escribe nada si hay un solo error.

Columnas: `nombre, correo, documento, tipo_documento, grupo, rol`.
  - UTF-8 con o sin BOM, o cp1252 (el "CSV" que guarda Excel en Windows).
  - Separador `,` o `;`, según la cabecera.
  - `tipo_documento`: `CC`, `TI` y `CE` son documentos nacionales (se quitan
    puntos y espacios; después, solo dígitos). `CODIGO` es un código interno:
    el alta le antepone el prefijo de la institución (`<slug>_<código>`).
  - `rol`: `estudiante` (por defecto), `profe` o `admin`. Estudiante y profe
    exigen `grupo`. Un profe con dos grupos va en dos filas.

D1 (§1.6): `documento_id` es OPACO. El prefijo se pone aquí, al dar de alta, y
el backend nunca lo vuelve a leer ni a separar. El resultado cumple siempre
`DOC_ID_RE`, la misma regex de M3 y M4.

El número de fila cuenta las filas de DATOS desde 1 (sin la cabecera ni las
líneas vacías), como M4 (`roster.validate_syntax`).
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass

from src.teachers.service.roster import DOC_ID_RE, ErrorFila

COLUMNAS = ("nombre", "correo", "documento", "tipo_documento", "grupo", "rol")
TIPOS_NACIONALES = ("CC", "TI", "CE")
TIPO_CODIGO = "CODIGO"
# El rol del CSV (en español, lo escribe una persona) -> el rol de la membresía.
ROLES = {"estudiante": "student", "profe": "teacher", "admin": "admin"}
ROL_POR_DEFECTO = "estudiante"

_SOLO_DIGITOS = re.compile(r"^[0-9]+$")
_PUNTOS_Y_ESPACIOS = re.compile(r"[.\s]")


@dataclass(frozen=True)
class FilaPersona:
    """Una fila válida del CSV, ya normalizada."""

    fila: int
    nombre: str
    correo: str
    documento_id: str  # el definitivo: dígitos, o `<slug>_<código>`
    rol: str           # 'student' | 'teacher' | 'admin'
    grupo: str | None


def decodificar(contenido: bytes) -> str:
    """UTF-8 (con o sin BOM); si no es UTF-8 válido, cp1252."""
    try:
        return contenido.decode("utf-8-sig")
    except UnicodeDecodeError:
        return contenido.decode("cp1252")


def con_prefijo(slug: str, codigo: str) -> str:
    """El código interno con el prefijo de su institución: `sena` + `7` -> `sena_7`.

    Sin el prefijo, el `001` de una institución sería el mismo perfil que el
    `001` de otra (el `documento_id` es global).
    """
    return f"{slug}_{codigo}"


def documento_de(slug: str, tipo: str, crudo: str) -> tuple[str | None, str | None]:
    """(documento_id, None) o (None, motivo del rechazo)."""
    tipo = tipo.strip().upper()
    if tipo in TIPOS_NACIONALES:
        limpio = _PUNTOS_Y_ESPACIOS.sub("", crudo)
        if not _SOLO_DIGITOS.match(limpio):
            return None, f"documento {tipo} con algo que no es un dígito: {crudo.strip()!r}"
        documento = limpio
    elif tipo == TIPO_CODIGO:
        codigo = crudo.strip()
        if not codigo:
            return None, "código vacío"
        documento = con_prefijo(slug, codigo)
    else:
        return None, f"tipo_documento inválido: {tipo!r} (CC, TI, CE o CODIGO)"
    if not DOC_ID_RE.fullmatch(documento):
        return None, (f"documento inválido: {documento!r} "
                      "(3 a 32 letras, dígitos, '_' o '-')")
    return documento, None


def _filas_crudas(contenido: bytes) -> tuple[list[dict[str, str]], list[ErrorFila]]:
    """Las filas de datos como dicts, con las claves en minúscula y sin espacios."""
    lineas = [linea for linea in decodificar(contenido).splitlines() if linea.strip()]
    if not lineas:
        return [], [ErrorFila(fila=0, motivo="el CSV está vacío (falta la cabecera)")]
    separador = ";" if ";" in lineas[0] else ","
    lector = csv.reader(io.StringIO("\n".join(lineas)), delimiter=separador)
    cabecera = [c.strip().lower() for c in next(lector)]
    faltan = [c for c in COLUMNAS if c not in cabecera]
    if faltan:
        return [], [ErrorFila(fila=0, motivo=f"faltan columnas: {', '.join(faltan)}")]
    return [dict(zip(cabecera, (v.strip() for v in valores), strict=False))
            for valores in lector], []


def _leer_fila(i: int, cruda: dict[str, str], slug: str) -> FilaPersona | ErrorFila:
    """Valida UNA fila por sí sola (los cruces entre filas van en `_cruces`)."""
    nombre = cruda.get("nombre") or ""
    correo = (cruda.get("correo") or "").lower()
    rol_csv = (cruda.get("rol") or ROL_POR_DEFECTO).lower()
    grupo = cruda.get("grupo") or None
    if not nombre:
        return ErrorFila(fila=i, motivo="nombre vacío")
    if correo.count("@") != 1 or " " in correo or correo.startswith("@") or correo.endswith("@"):
        return ErrorFila(fila=i, motivo=f"correo inválido: {correo!r}")
    if rol_csv not in ROLES:
        return ErrorFila(fila=i, motivo=f"rol inválido: {rol_csv!r} (estudiante, profe o admin)")
    documento, motivo = documento_de(slug, cruda.get("tipo_documento") or "",
                                     cruda.get("documento") or "")
    if documento is None:
        return ErrorFila(fila=i, motivo=motivo or "documento inválido")
    rol = ROLES[rol_csv]
    if rol == "admin":
        grupo = None  # el admin es de toda la institución
    elif grupo is None:
        return ErrorFila(fila=i, motivo=f"{rol_csv} sin grupo")
    return FilaPersona(fila=i, nombre=nombre, correo=correo, documento_id=documento,
                       rol=rol, grupo=grupo)


def _cruces(filas: list[FilaPersona]) -> tuple[list[FilaPersona], list[ErrorFila]]:
    """Lo que solo se ve mirando varias filas: una persona es UN documento y UN correo."""
    validas: list[FilaPersona] = []
    errores: list[ErrorFila] = []
    por_documento: dict[str, FilaPersona] = {}
    documento_del_correo: dict[str, str] = {}
    vistas: set[tuple[str, str | None]] = set()
    for f in filas:
        primera = por_documento.get(f.documento_id)
        motivo: str | None = None
        if documento_del_correo.get(f.correo, f.documento_id) != f.documento_id:
            motivo = "el correo ya está en otra fila con otro documento"
        elif primera is not None and primera.rol != f.rol:
            motivo = f"el documento ya está en la fila {primera.fila} con otro rol"
        elif primera is not None and primera.correo != f.correo:
            motivo = f"el documento ya está en la fila {primera.fila} con otro correo"
        elif (f.documento_id, f.grupo) in vistas:
            motivo = f"fila repetida (igual a la fila {primera.fila if primera else 0})"
        elif primera is not None and f.rol == "student":
            motivo = f"el estudiante ya está en la fila {primera.fila} con otro grupo"
        if motivo is not None:
            errores.append(ErrorFila(fila=f.fila, motivo=motivo))
            continue
        por_documento.setdefault(f.documento_id, f)
        documento_del_correo[f.correo] = f.documento_id
        vistas.add((f.documento_id, f.grupo))
        validas.append(f)
    return validas, errores


def leer_csv(contenido: bytes, slug: str) -> tuple[list[FilaPersona], list[ErrorFila]]:
    """Bytes del CSV -> (filas válidas, todos los errores, ordenados por fila).

    Una fila con error NO entra en las válidas. El alta no escribe nada si la
    lista de errores no está vacía (todo o nada, §1.7).
    """
    crudas, errores = _filas_crudas(contenido)
    solas: list[FilaPersona] = []
    for i, cruda in enumerate(crudas, start=1):
        leida = _leer_fila(i, cruda, slug)
        if isinstance(leida, ErrorFila):
            errores.append(leida)
        else:
            solas.append(leida)
    validas, de_cruce = _cruces(solas)
    return validas, sorted(errores + de_cruce, key=lambda e: e.fila)


@dataclass(frozen=True)
class Persona:
    """Una persona del CSV: sus filas juntas (un profe puede traer varios grupos)."""

    fila: int
    nombre: str
    correo: str
    documento_id: str
    rol: str
    grupos: tuple[str, ...]


def personas(filas: list[FilaPersona]) -> list[Persona]:
    """Una `Persona` por documento, en el orden de su primera fila."""
    juntas: dict[str, Persona] = {}
    for f in filas:
        previa = juntas.get(f.documento_id)
        grupos = (previa.grupos if previa else ()) + ((f.grupo,) if f.grupo else ())
        juntas[f.documento_id] = Persona(
            fila=previa.fila if previa else f.fila,
            nombre=previa.nombre if previa else f.nombre,
            correo=f.correo, documento_id=f.documento_id, rol=f.rol, grupos=grupos,
        )
    return list(juntas.values())
