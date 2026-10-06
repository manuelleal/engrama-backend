"""UH11 y sus tramposos — `docs/ESPEC_endurecimiento_piloto.md`, H-11.

No-integ. El archivo de credenciales:
  - NACE con permiso 0600 (`os.open(..., 0o600)`), no con el umask;
  - nunca se escribe dentro de un repositorio git, sea el del backend o cualquier otro.

Las funciones se llaman por el módulo (`salida.…`) para que los tramposos las alcancen.
"""
from __future__ import annotations

import csv
import os
import stat
from pathlib import Path
from typing import Any

import pytest

from src.onboarding import salida

_OS_OPEN = os.open


def _anotar(ruta: Path, nombre: str = "Ana Sintética") -> None:
    salida.anotar(ruta, nombre=nombre, correo="ana@sintetico.test", rol="student",
                  grupos=("G1",), clave="abcd-efgh-jkmn")


def test_uh11_el_archivo_nace_cerrado_y_fuera_de_todo_repo(tmp_path, monkeypatch) -> None:
    """UH11 (H-11): `os.open` con 0600 al crear; `.git` arriba = dentro de un repo."""
    modos: list[int] = []

    def espia(ruta: Any, flags: int, mode: int = 0o777, **kw: Any) -> int:
        modos.append(mode)
        return _OS_OPEN(ruta, flags, mode, **kw)

    monkeypatch.setattr(salida.os, "open", espia)
    credenciales = tmp_path / "fuera" / "credenciales.csv"
    _anotar(credenciales)
    _anotar(credenciales, "Beto Sintético")
    with credenciales.open(encoding="utf-8", newline="") as archivo:
        filas = list(csv.reader(archivo))
    permiso = stat.S_IMODE(credenciales.stat().st_mode)

    repo = tmp_path / "un_repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "ignorada" / "salida").mkdir(parents=True)
    observado = {
        "modos_de_os_open": modos,
        "permiso_en_posix": permiso == 0o600 if os.name == "posix" else "no aplica",
        "filas": [f[0] for f in filas],
        "dentro": {
            "raiz_de_un_repo_ajeno": salida.dentro_del_repo(repo / "credenciales.csv"),
            "subcarpeta_ignorada": salida.dentro_del_repo(repo / "ignorada" / "salida" / "c.csv"),
            "con_puntos": salida.dentro_del_repo(tmp_path / "fuera" / ".." / "un_repo" / "c.csv"),
            "el_backend": salida.dentro_del_repo(salida.RAIZ_BACKEND / "tests" / "_salida"
                                                 / "c.csv"),
            "sin_git_arriba": salida.dentro_del_repo(credenciales),
        },
    }
    assert observado == {
        "modos_de_os_open": [0o600, 0o600],
        "permiso_en_posix": True if os.name == "posix" else "no aplica",
        "filas": ["nombre", "Ana Sintética", "Beto Sintético"],
        "dentro": {"raiz_de_un_repo_ajeno": True, "subcarpeta_ignorada": True,
                   "con_puntos": True, "el_backend": True, "sin_git_arriba": False},
    }, f"UH11: {observado}"


def _anotar_de_antes(ruta: Path, *, nombre: str, correo: str, rol: str, grupos: tuple[str, ...],
                     clave: str) -> None:
    """ZH11a: el archivo nace con el umask (`open("a")`) y se cierra después."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    nuevo = not ruta.exists() or ruta.stat().st_size == 0
    with ruta.open("a", encoding="utf-8", newline="") as archivo:
        escritor = csv.writer(archivo)
        if nuevo:
            escritor.writerow(salida.COLUMNAS_SALIDA)
        escritor.writerow([nombre, correo, rol, " | ".join(grupos), clave, "fecha"])
    os.chmod(ruta, 0o600)


def test_zh11a_tramposo_el_archivo_nace_con_el_umask(tmp_path, monkeypatch) -> None:
    """ZH11a: con el `open("a")` de antes, nadie llama a `os.open` con 0600."""
    monkeypatch.setattr(salida, "anotar", _anotar_de_antes)
    with pytest.raises(AssertionError, match=r"UH11: \{'modos_de_os_open': \[\]"):
        test_uh11_el_archivo_nace_cerrado_y_fuera_de_todo_repo(tmp_path, monkeypatch)


def test_zh11b_tramposo_solo_mira_el_repo_del_backend(tmp_path, monkeypatch) -> None:
    """ZH11b: con la guarda de antes, un repo ajeno (toda INGLES lo es) deja escribir."""
    monkeypatch.setattr(salida, "_tiene_git_arriba", lambda ruta: False)
    with pytest.raises(AssertionError, match=r"'raiz_de_un_repo_ajeno': False"):
        test_uh11_el_archivo_nace_cerrado_y_fuera_de_todo_repo(tmp_path, monkeypatch)
