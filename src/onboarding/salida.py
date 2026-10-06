"""La contraseña temporal y el archivo de credenciales — `docs/ESPEC_login_piloto.md` §1.7.

`--salida` es el ÚNICO lugar donde queda una contraseña temporal: un CSV que
el operador entrega a mano y después borra. Reglas:
  - Columnas `nombre, correo, rol, grupo, contrasena_temporal, creado_en`.
    SIN documento (dato mínimo, Ley 1581).
  - Se abre en modo *append*: una corrida nueva no borra lo anterior.
  - Cada cuenta se anota apenas se crea, para que una caída a mitad de camino
    no deje una cuenta cuya contraseña nadie conoce.
  - Si la ruta queda DENTRO del repo del backend o de cualquier repositorio
    git, la CLI sale con 2 antes de escribir nada: una contraseña nunca debe
    poder terminar en un commit.
  - El archivo nace con permiso 0600.
"""
from __future__ import annotations

import csv
import os
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path

RAIZ_BACKEND = Path(__file__).resolve().parents[2]

COLUMNAS_SALIDA = ("nombre", "correo", "rol", "grupo", "contrasena_temporal", "creado_en")
# Sin 0/o ni 1/l/i: se dicta y se copia sin errores.
ALFABETO_CLAVE = "abcdefghjkmnpqrstuvwxyz23456789"
# El rol de la membresía -> como lo escribe el CSV de entrada.
ROL_EN_ESPANOL = {"student": "estudiante", "teacher": "profe", "admin": "admin"}


# H-12: un campo que empieza así, Excel lo ejecuta como fórmula al abrir el CSV.
_EMPIEZA_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def neutralizar(celda: str) -> str:
    """Antepone `'` si el campo empezaría una fórmula (`=HYPERLINK(...)` en un nombre)."""
    return "'" + celda if celda.startswith(_EMPIEZA_FORMULA) else celda


def clave_temporal() -> str:
    """3 bloques de 4 caracteres: 14 con los guiones (el mínimo de la API es 10)."""
    return "-".join("".join(secrets.choice(ALFABETO_CLAVE) for _ in range(4))
                    for _ in range(3))


def _tiene_git_arriba(ruta: Path) -> bool:
    """¿Alguna carpeta, desde la del archivo hacia la raíz, tiene un `.git`?"""
    return any((carpeta / ".git").exists() for carpeta in ruta.parents)


def dentro_del_repo(ruta: Path) -> bool:
    """¿La ruta, ya resuelta, cae dentro del backend o de CUALQUIER repositorio git?

    H-11: sin excepción para rutas ignoradas. Saber si una ruta está ignorada
    exige ejecutar git y confiar en un `.gitignore` que puede cambiar; lo
    simple y seguro es que las contraseñas nunca vivan dentro de un repo.
    """
    resuelta = ruta.resolve()
    return resuelta.is_relative_to(RAIZ_BACKEND) or _tiene_git_arriba(resuelta)


def anotar(ruta: Path, *, nombre: str, correo: str, rol: str, grupos: tuple[str, ...],
           clave: str) -> None:
    """Agrega UNA fila al archivo de credenciales (con cabecera si el archivo nace)."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    nuevo = not ruta.exists() or ruta.stat().st_size == 0
    # H-11: el archivo NACE con permiso 0600 (antes nacía con el umask y se
    # cerraba después). En Windows el modo no restringe; en el servidor, sí.
    descriptor = os.open(ruta, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with open(descriptor, "a", encoding="utf-8", newline="") as archivo:
        escritor = csv.writer(archivo)
        if nuevo:
            escritor.writerow(COLUMNAS_SALIDA)
        fila = [nombre, correo, ROL_EN_ESPANOL.get(rol, rol), " | ".join(grupos),
                clave, datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")]
        escritor.writerow([neutralizar(celda) for celda in fila])
    try:
        os.chmod(ruta, 0o600)  # en Windows no restringe; en el servidor (Linux), sí
    except OSError as exc:  # no es motivo para perder la credencial ya escrita
        print(f"aviso: no se pudo restringir el permiso de {ruta.name}: {exc}", file=sys.stderr)
