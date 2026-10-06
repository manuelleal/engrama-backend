"""HA2 — humo MANUAL del autorregistro contra un GoTrue real — `docs/ESPEC_autorregistro.md` §4.

pytest NO lo recoge (no empieza por `test_`) y no suma en las cuentas. Lo corre
quien tenga el permiso de Docker sobre el stack de PRUEBA del piloto (ERR-21),
nunca contra un volumen con personas reales:

    HA2_ES_STACK_DE_PRUEBA=1 GOTRUE_URL=... SUPABASE_SERVICE_ROLE_KEY=... \\
    python -m tests.manual.humo_autorregistro_gotrue

Todo llega por variable de entorno; nada se escribe en el repo salvo el
resultado, `tests/_salida/humo_autorregistro_gotrue.json` (en `.gitignore`),
que no trae ids, correos, claves ni contraseñas.

Qué mide, con UNA cuenta sintética (los supuestos de la espec que el doble
`tests/cuentas_falsas.py` solo imita):
  - `crear` con un `id` elegido devuelve `creada` (P0, otra vez);
  - el login con la contraseña da un JWT cuyo `sub` es ese `id`;
  - `crear` con OTRO id y el MISMO correo devuelve `correo_en_uso` (y no un error);
  - cuánto tarda `crear` cuando crea y cuando el correo ya existe (el canal
    lateral de tiempo que la espec declara sin medir);
  - `borrar` responde sin error; `borrar` otra vez (ya no existe), también;
  - después de borrar, el login falla.

No toca la base de ENGRAMA: solo la API admin de GoTrue.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from src.onboarding.cuentas import ErrorCuenta, gotrue_admin_del_entorno

RUTA = Path(__file__).resolve().parents[1] / "_salida" / "humo_autorregistro_gotrue.json"


def _sub(token: str) -> str:
    """El `sub` del JWT, sin verificar la firma (eso lo hace el backend)."""
    cuerpo = token.split(".")[1]
    datos = json.loads(base64.urlsafe_b64decode(cuerpo + "=" * (-len(cuerpo) % 4)))
    return str(datos.get("sub"))


async def _login(url: str, correo: str, clave: str) -> tuple[int, str | None]:
    async with httpx.AsyncClient(timeout=15) as cliente:
        r = await cliente.post(f"{url}/token?grant_type=password",
                               json={"email": correo, "password": clave})
    token = r.json().get("access_token") if r.status_code == 200 else None
    return r.status_code, (_sub(token) if token else None)


async def _medir(funcion: Any) -> tuple[Any, int]:
    inicio = time.monotonic()
    try:
        resultado = await funcion()
    except ErrorCuenta as exc:
        resultado = f"ErrorCuenta: {exc}"
    return resultado, round((time.monotonic() - inicio) * 1000)


async def correr() -> dict[str, Any]:
    admin = gotrue_admin_del_entorno()
    url = os.environ["GOTRUE_URL"].rstrip("/")
    cuenta, otra = uuid4(), uuid4()
    correo = f"humo-ha2-{secrets.token_hex(6)}@sintetico.test"
    clave = "Sintetica-" + secrets.token_hex(8)

    creada, ms_crear = await _medir(lambda: admin.crear(cuenta, correo, clave))
    estado, sub = await _login(url, correo, clave)
    repetida, ms_repetida = await _medir(lambda: admin.crear(otra, correo, clave))
    borrar_1, _ = await _medir(lambda: admin.borrar(cuenta))
    borrar_2, _ = await _medir(lambda: admin.borrar(cuenta))
    await _medir(lambda: admin.borrar(otra))  # por si GoTrue la hubiera creado
    despues, _ = await _login(url, correo, clave)
    return {
        "crear_con_id": creada, "login": estado, "sub_igual_al_id": sub == str(cuenta),
        "crear_con_correo_repetido": repetida,
        "ms_crear": ms_crear, "ms_correo_repetido": ms_repetida,
        "borrar": "ok" if borrar_1 is None else borrar_1,
        "borrar_otra_vez": "ok" if borrar_2 is None else borrar_2,
        "login_despues_de_borrar": despues,
    }


ESPERADO = {"crear_con_id": "creada", "login": 200, "sub_igual_al_id": True,
            "crear_con_correo_repetido": "correo_en_uso", "borrar": "ok",
            "borrar_otra_vez": "ok", "login_despues_de_borrar": 400}


def main() -> int:
    if os.environ.get("HA2_ES_STACK_DE_PRUEBA") != "1":
        print("HA2: solo contra el stack de PRUEBA (HA2_ES_STACK_DE_PRUEBA=1).", file=sys.stderr)
        return 2
    datos = asyncio.run(correr())
    RUTA.parent.mkdir(parents=True, exist_ok=True)
    RUTA.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    difieren = {k: datos.get(k) for k, v in ESPERADO.items() if datos.get(k) != v}
    print(json.dumps({"escrito": str(RUTA), "difieren_de_lo_supuesto": difieren},
                     ensure_ascii=False))
    return 1 if difieren else 0


if __name__ == "__main__":
    raise SystemExit(main())
