"""Lo puro del autorregistro (sin base) — `docs/ESPEC_autorregistro.md` C12, C13 y C14.

  SR1  C12  la clave de servicio, cercada: solo `config.py` y `registro/cuentas.py`.
  UR1  C13  el código: formato, normalización y huella con llave.
  UR2  C14  una sola política de contraseña; `mayor_de_edad` solo admite `True`.
  UR3  C21  (auditoría 03) la contraseña se acota en 72 BYTES, no en caracteres.

Las funciones se llaman por el módulo para que un tramposo que las reemplace
ahí (ZR20, ZR21, ZR23) las alcance.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.auth import schemas as auth_schemas
from src.registro import codigos
from src.registro import schemas as registro_schemas

RAIZ_SRC = Path(__file__).resolve().parents[2] / "src"

# Qué se busca en cada archivo de `src/` y dónde se permite (rutas relativas a `src/`).
CERCA: dict[str, set[str]] = {
    # El atributo de la configuración: quién LEE la clave en el proceso web.
    "supabase_service_role_key": {"shared/config.py", "registro/cuentas.py"},
    # Quién construye el adaptador de la API admin de GoTrue.
    "GoTrueAdmin(": {"onboarding/cuentas.py", "registro/cuentas.py"},
    # La variable de entorno por su nombre: la CLI del operador.
    "SUPABASE_SERVICE_ROLE_KEY": {"onboarding/cuentas.py", "onboarding/__main__.py",
                                  "onboarding/alta.py", "onboarding/restablecer.py"},
}


def leer_fuentes() -> dict[str, str]:
    """`{ruta relativa a src: contenido}` de todos los `.py` de `src/`."""
    return {p.relative_to(RAIZ_SRC).as_posix(): p.read_text(encoding="utf-8")
            for p in sorted(RAIZ_SRC.rglob("*.py"))}


def fuera_de_la_cerca(fuentes: dict[str, str]) -> dict[str, list[str]]:
    """Por cada texto vigilado, los archivos que lo traen SIN estar permitidos."""
    return {texto: sorted(ruta for ruta, contenido in fuentes.items()
                          if texto in contenido and ruta not in permitidos)
            for texto, permitidos in CERCA.items()}


def test_sr1_la_clave_de_servicio_esta_cercada() -> None:
    """SR1 (C12): ningún módulo fuera de la cerca nombra la clave ni arma el adaptador."""
    fuentes = leer_fuentes()
    usan = {texto: sorted(ruta for ruta, contenido in fuentes.items() if texto in contenido)
            for texto in ("supabase_service_role_key", "GoTrueAdmin(")}
    observado = {"fuera": fuera_de_la_cerca(fuentes), "usan": usan}
    assert observado == {
        "fuera": dict.fromkeys(CERCA, []),
        # El control: la búsqueda SÍ encuentra los dos sitios permitidos.
        "usan": {"supabase_service_role_key": ["registro/cuentas.py", "shared/config.py"],
                 "GoTrueAdmin(": ["onboarding/cuentas.py", "registro/cuentas.py"]},
    }, f"SR1: {observado}"


def test_ur1_el_codigo_puro() -> None:
    """UR1 (C13): 200 códigos bien formados y distintos; la huella lleva llave."""
    generados = [codigos.generar() for _ in range(200)]
    escrituras = ("ABCDEFGH", "abcd-efgh", " AbCd EfGh ")
    huellas = {codigos.huella(e) for e in escrituras}
    una = next(iter(huellas))
    observado = {
        "forma": all(re.fullmatch(f"[{codigos.ALFABETO}]{{8}}", c) for c in generados),
        "distintos": len(set(generados)),
        "sin_confusos": not set("ILO01") & set(codigos.ALFABETO),
        "mostrar": codigos.mostrar("ABCDEFGH"),
        "normalizar": sorted({codigos.normalizar(e) for e in escrituras}),
        "una_sola_huella": len(huellas),
        "huella_de_64_hex": bool(re.fullmatch(r"[0-9a-f]{64}", una)),
        "es_sha256_a_secas": una == hashlib.sha256(b"ABCDEFGH").hexdigest(),
        "otro_codigo_otra_huella": codigos.huella("ABCDEFGJ") != una,
    }
    assert observado == {
        "forma": True, "distintos": 200, "sin_confusos": True, "mostrar": "ABCD-EFGH",
        "normalizar": ["ABCDEFGH"], "una_sola_huella": 1, "huella_de_64_hex": True,
        "es_sha256_a_secas": False, "otro_codigo_otra_huella": True,
    }, f"UR1: {observado}"


def _limites(modelo: type, campo: str) -> tuple[int | None, int | None]:
    metadatos = modelo.model_fields[campo].metadata  # type: ignore[attr-defined]
    minimo = next((m.min_length for m in metadatos if hasattr(m, "min_length")), None)
    maximo = next((m.max_length for m in metadatos if hasattr(m, "max_length")), None)
    return minimo, maximo


def _acepta_mayor(valor: object) -> bool:
    try:
        registro_schemas.RegistroIn.model_validate({
            "codigo": "ABCDEFGH", "nombre": "Ana", "correo": "a@b.co",
            "codigo_estudiantil": "1", "contrasena": "x" * 10, "mayor_de_edad": valor,
            "aviso_version": "v1"})
    except ValidationError:
        return False
    return True


def test_ur2_una_sola_politica_de_contrasena() -> None:
    """UR2 (C14): el registro y el cambio de clave leen las mismas dos constantes."""
    observado = {
        "constantes": (auth_schemas.CLAVE_MIN, auth_schemas.CLAVE_MAX),
        "registro": _limites(registro_schemas.RegistroIn, "contrasena"),
        "cambio_de_clave": _limites(auth_schemas.CambioDeClaveIn, "nueva"),
        "mayor_de_edad": {repr(v): _acepta_mayor(v) for v in (True, False, 1, "true", None)},
    }
    assert observado == {
        "constantes": (10, 72), "registro": (10, 72), "cambio_de_clave": (10, 72),
        "mayor_de_edad": {"True": True, "False": False, "1": False, "'true'": False,
                          "None": False},
    }, f"UR2: {observado}"


def _error_de_clave(clave: str) -> str | None:
    """`None` si la contraseña pasa; si no, el mensaje del primer error."""
    try:
        registro_schemas.RegistroIn.model_validate({
            "codigo": "ABCDEFGH", "nombre": "Ana", "correo": "a@b.co",
            "codigo_estudiantil": "1", "contrasena": clave, "mayor_de_edad": True,
            "aviso_version": "v1"})
    except ValidationError as exc:
        return str(exc.errors()[0].get("msg"))
    return None


def test_ur3_la_contrasena_se_acota_en_bytes() -> None:
    """UR3 (C21): 36 eñes (72 bytes) pasan; 37 (74 bytes, 37 caracteres) no."""
    de_74_bytes = _error_de_clave("ñ" * 37)
    observado = {
        "72_x": _error_de_clave("x" * 72),
        "36_enes_72_bytes": _error_de_clave("ñ" * 36),
        "37_enes_74_bytes_nombra_los_72_bytes": de_74_bytes is not None
        and "72 bytes" in de_74_bytes,
        "73_x_el_error_de_siempre": "at most 72 characters" in (_error_de_clave("x" * 73) or ""),
        "18_emojis_72_bytes": _error_de_clave("🙂" * 18),
        "19_emojis_76_bytes": _error_de_clave("🙂" * 19) is not None,
    }
    assert observado == {
        "72_x": None, "36_enes_72_bytes": None, "37_enes_74_bytes_nombra_los_72_bytes": True,
        "73_x_el_error_de_siempre": True, "18_emojis_72_bytes": None,
        "19_emojis_76_bytes": True,
    }, f"UR3: {observado}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
