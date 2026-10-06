"""HP2 — humo MANUAL contra un GoTrue real — `docs/ESPEC_login_piloto.md` §4.

pytest NO lo recoge (no empieza por `test_`) y no suma en las cuentas. Lo corre
quien tenga el permiso de Docker sobre el stack de PRUEBA del piloto (ERR-21),
nunca contra un volumen con personas reales:

    HP2_ES_STACK_DE_PRUEBA=1 DATABASE_URL=... GOTRUE_URL=... \\
    SUPABASE_SERVICE_ROLE_KEY=... BACKEND_URL=http://localhost:8000 \\
    python -m tests.manual.humo_login_piloto_gotrue

Todo llega por variable de entorno; nada se escribe en el repo salvo el
resultado, `tests/_salida/humo_login_piloto_gotrue.json` (en `.gitignore`),
que no trae ids, correos, claves ni contraseñas.

Qué mide, con UNA persona sintética en una institución sintética nueva
(`humo-hp2-<azar>`, 0 monedas), dada de alta con la CLI real:
  - P0: la cuenta nació con el `id` del perfil (`GET /admin/users/{id}`);
  - el login con contraseña da un JWT cuyo `sub` es `profiles.id`;
  - `/auth/me` dice `must_change_password: true` y `/challenges/` da 403;
  - `POST /auth/contrasena` da 204; la temporal ya no entra y la nueva sí;
  - 40 logins seguidos desde esta IP: cuántos 429 (una MEDICIÓN, no un
    criterio: el límite por IP es configuración del despliegue).

Al final borra la cuenta de GoTrue. La institución y el perfil sintéticos
quedan en la base del stack de prueba (no hay ruta para borrarlos).
"""
from __future__ import annotations

import asyncio
import base64
import csv
import json
import os
import secrets
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import text

from src.onboarding.__main__ import sesiones_del_entorno
from src.onboarding.alta import correr_alta
from src.onboarding.cuentas import gotrue_admin_del_entorno

RUTA = Path(__file__).resolve().parents[1] / "_salida" / "humo_login_piloto_gotrue.json"
CLAVE_NUEVA = "Sintetica-" + secrets.token_hex(6)
LOGINS = 40


def _sub(token: str) -> str:
    """El `sub` del JWT, sin verificar la firma (eso lo hace el backend)."""
    cuerpo = token.split(".")[1]
    datos = json.loads(base64.urlsafe_b64decode(cuerpo + "=" * (-len(cuerpo) % 4)))
    return str(datos.get("sub"))


async def _entrar(http: httpx.AsyncClient, gotrue: str, correo: str, clave: str,
                  ) -> httpx.Response:
    return await http.post(f"{gotrue}/token", params={"grant_type": "password"},
                           json={"email": correo, "password": clave})


async def medir() -> dict[str, Any]:
    gotrue = os.environ["GOTRUE_URL"].rstrip("/")
    backend = os.environ["BACKEND_URL"].rstrip("/")
    cuentas, sesiones = gotrue_admin_del_entorno(), sesiones_del_entorno()
    azar = secrets.token_hex(4)
    slug, correo = f"humo-hp2-{azar}", f"hp2.{azar}@engrama.test"
    fila = f"Humo HP2,{correo},{azar},CODIGO,HP2,estudiante"
    with tempfile.TemporaryDirectory() as carpeta:
        salida = Path(carpeta) / "credenciales.csv"
        resumen = await correr_alta(
            nombre="Institución Sintética HP2", slug=slug, monedas=0, salida=salida,
            contenido=("nombre,correo,documento,tipo_documento,grupo,rol\n" + fila).encode(),
            cuentas=cuentas, sesiones=sesiones)
        with salida.open(encoding="utf-8", newline="") as archivo:
            temporal = next(csv.DictReader(archivo))["contrasena_temporal"]
    async with sesiones() as db:
        perfil = UUID(str((await db.execute(
            text("select id from profiles where documento_id = :d"),
            {"d": f"{slug}_{azar}"})).scalar()))
    datos: dict[str, Any] = {"alta": {"cuentas_nuevas": resumen.cuentas_nuevas,
                                      "errores": len(resumen.errores)}}
    async with httpx.AsyncClient(timeout=15) as http:
        datos["p0_cuenta_con_id_del_perfil"] = await cuentas.buscar(perfil) == correo
        login = await _entrar(http, gotrue, correo, temporal)
        token = login.json().get("access_token", "") if login.status_code == 200 else ""
        cab = {"Authorization": f"Bearer {token}"}
        datos["login_temporal"] = login.status_code
        datos["sub_igual_perfil"] = bool(token) and _sub(token) == str(perfil)
        yo = await http.get(f"{backend}/auth/me", headers=cab)
        datos["me"] = [yo.status_code, yo.json().get("must_change_password")
                       if yo.status_code == 200 else None]
        datos["retos_bloqueados"] = (await http.get(f"{backend}/challenges/",
                                                    headers=cab)).status_code
        datos["cambio"] = (await http.post(f"{backend}/auth/contrasena", headers=cab,
                                           json={"nueva": CLAVE_NUEVA})).status_code
        datos["retos_despues"] = (await http.get(f"{backend}/challenges/",
                                                 headers=cab)).status_code
        datos["login_con_la_temporal"] = (await _entrar(http, gotrue, correo,
                                                        temporal)).status_code
        datos["login_con_la_nueva"] = (await _entrar(http, gotrue, correo,
                                                     CLAVE_NUEVA)).status_code
        inicio = time.monotonic()
        estados = [(await _entrar(http, gotrue, correo, CLAVE_NUEVA)).status_code
                   for _ in range(LOGINS)]
        datos["logins_seguidos"] = {"cuantos": LOGINS, "con_429": estados.count(429),
                                    "con_200": estados.count(200),
                                    "segundos": round(time.monotonic() - inicio, 1)}
        borrado = await http.delete(
            f"{gotrue}/admin/users/{perfil}",
            headers={"Authorization": f"Bearer {os.environ['SUPABASE_SERVICE_ROLE_KEY']}",
                     "apikey": os.environ["SUPABASE_SERVICE_ROLE_KEY"]})
        datos["cuenta_borrada"] = borrado.status_code
    return datos


ESPERADO = {"p0_cuenta_con_id_del_perfil": True, "login_temporal": 200, "sub_igual_perfil": True,
            "me": [200, True], "retos_bloqueados": 403, "cambio": 204, "retos_despues": 200,
            "login_con_la_temporal": 400, "login_con_la_nueva": 200}


def main() -> int:
    if os.environ.get("HP2_ES_STACK_DE_PRUEBA") != "1":
        print("HP2 crea una institución y una cuenta sintéticas: corre solo contra el stack de "
              "PRUEBA y con HP2_ES_STACK_DE_PRUEBA=1.", file=sys.stderr)
        return 2
    faltan = [v for v in ("DATABASE_URL", "GOTRUE_URL", "SUPABASE_SERVICE_ROLE_KEY",
                          "BACKEND_URL") if not os.environ.get(v)]
    if faltan:
        print(f"faltan variables de entorno: {', '.join(faltan)}", file=sys.stderr)
        return 2
    datos = asyncio.run(medir())
    RUTA.parent.mkdir(parents=True, exist_ok=True)
    RUTA.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    distinto = {k: datos.get(k) for k, v in ESPERADO.items() if datos.get(k) != v}
    print(json.dumps({"archivo": str(RUTA), "distinto_de_lo_esperado": distinto,
                      "logins_seguidos": datos["logins_seguidos"]}, ensure_ascii=False))
    return 1 if distinto else 0


if __name__ == "__main__":
    raise SystemExit(main())
