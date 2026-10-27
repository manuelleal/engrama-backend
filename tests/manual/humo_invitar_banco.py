"""Humo de invitar profes contra un GoTrue REAL — `docs/ESPEC_invitar_profe.md` §6 (H1-H8).

pytest NO lo recoge (no empieza por `test_`). Levanta el banco desechable
`tests/manual/banco_invitar/` (GoTrue v2.196.0, Postgres de Supabase, Mailpit
haciendo de Brevo y la plantilla servida por Caddy), migra la base, arranca el
backend de ESTA rama con uvicorn contra ese banco, recorre el flujo y lo tumba
con `down -v`:

    poetry run python -m tests.manual.humo_invitar_banco             # el humo
    poetry run python -m tests.manual.humo_invitar_banco replica     # la réplica, a su archivo

Secretos, cuentas y correos: sintéticos y nuevos en cada corrida (la réplica es
volver a correrlo). Solo viven en el entorno de los procesos. Escribe
`tests/_salida/humo_invitar_banco.json` (o `..._replica.json`), sin tokens,
secretos ni correos.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
from jose import jwt

RAIZ = Path(__file__).resolve().parents[2]
COMPOSE = RAIZ / "tests" / "manual" / "banco_invitar" / "docker-compose.yml"
PROYECTO = "engrama-invitar-banco"
SALIDA = RAIZ / "tests" / "_salida"
PG, GOTRUE, MAILPIT, API = (18432, "http://127.0.0.1:18399", "http://127.0.0.1:18325",
                            "http://127.0.0.1:18300")
TOPE, ESPERA_S = 5, 2
CLAVE_PROFE = "Sintetica-" + secrets.token_hex(6)
CLAVE_AJENA = "Ajena-" + secrets.token_hex(6) + "x1"
DOMINIO = f"{secrets.token_hex(3)}.sintetico.test"


def correo(etiqueta: str) -> str:
    return f"{etiqueta}-{secrets.token_hex(3)}@{DOMINIO}"


# ============================================================ infraestructura
def compose(entorno: dict[str, str], *args: str) -> None:
    subprocess.run(["docker", "compose", "-p", PROYECTO, "-f", str(COMPOSE), *args],
                   check=True, env=entorno, capture_output=True)


def esperar(url: str, segundos: int = 120) -> None:
    fin = time.monotonic() + segundos
    while time.monotonic() < fin:
        try:
            if httpx.get(url, timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise RuntimeError(f"no respondió a tiempo: {url}")


def firmar(secreto: str, sub: str, rol: str = "authenticated") -> str:
    ahora = int(time.time())
    return jwt.encode({"sub": sub, "aud": "authenticated", "role": rol, "iat": ahora,
                       "exp": ahora + 3600}, secreto, algorithm="HS256")


def sql(url: str, sentencias: list[tuple[str, tuple[Any, ...]]]) -> None:
    import asyncio

    import asyncpg  # type: ignore[import-untyped]

    async def correr() -> None:
        conn = await asyncpg.connect(url)
        try:
            for s, p in sentencias:
                await conn.execute(s, *p)
        finally:
            await conn.close()
    asyncio.run(correr())


# ============================================================ la bandeja (Mailpit)
def correos_a(direccion: str) -> list[dict[str, Any]]:
    r = httpx.get(f"{MAILPIT}/api/v1/search", params={"query": f"to:{direccion}"}, timeout=10)
    return list(r.json().get("messages", []))


def esperar_correos(direccion: str, cuantos: int, segundos: float = 15) -> list[dict[str, Any]]:
    fin = time.monotonic() + segundos
    while time.monotonic() < fin:
        lista = correos_a(direccion)
        if len(lista) >= cuantos:
            return lista
        time.sleep(0.5)
    return correos_a(direccion)


def token_y_datos(mensaje: dict[str, Any]) -> tuple[str | None, str, bool]:
    m = httpx.get(f"{MAILPIT}/api/v1/message/{mensaje['ID']}", timeout=10).json()
    cuerpo = m.get("HTML", "") + m.get("Text", "")
    t = re.search(r"#/invitacion\?token_hash=([A-Za-z0-9_\-]+)", cuerpo)
    return (t.group(1) if t else None), str(m.get("Subject", "")), "Crear mi contraseña" in cuerpo


# ============================================================ el flujo
class Flujo:
    def __init__(self, jwt_secreto: str) -> None:
        self.s = jwt_secreto
        self.c = httpx.Client(timeout=20)

    def h(self, sub: UUID) -> dict[str, str]:
        return {"Authorization": f"Bearer {firmar(self.s, str(sub))}"}

    def invitar(self, admin: UUID, nombre: str, mail: str, grupo: UUID) -> tuple[httpx.Response, int]:
        t0 = time.monotonic()
        r = self.c.post(f"{API}/admin/invitaciones", headers=self.h(admin),
                        json={"nombre": nombre, "correo": mail, "group_id": str(grupo)})
        return r, round((time.monotonic() - t0) * 1000)

    def reenviar(self, admin: UUID, inv: int) -> httpx.Response:
        return self.c.post(f"{API}/admin/invitaciones/{inv}/reenviar", headers=self.h(admin))

    def lista(self, admin: UUID) -> list[dict[str, Any]]:
        return list(self.c.get(f"{API}/admin/invitaciones", headers=self.h(admin)).json())

    def verify(self, token: str | None) -> httpx.Response:
        return self.c.post(f"{GOTRUE}/verify", json={"type": "invite", "token_hash": token})

    def login(self, mail: str, clave: str) -> httpx.Response:
        return self.c.post(f"{GOTRUE}/token?grant_type=password",
                           json={"email": mail, "password": clave})


def sin_variables(cuerpo: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in cuerpo.items() if k not in ("id", "nombre", "correo", "enviada_en")}


def sembrar(url_pg: str, f: Flujo, servicio: str) -> dict[str, Any]:
    """Dos instituciones con su admin y su grupo, un segundo admin en A, y cuentas YA hechas en B."""
    a, b = uuid4(), uuid4()
    adm_a, adm_a2, adm_b = uuid4(), uuid4(), uuid4()
    ga, gb = uuid4(), uuid4()
    s: list[tuple[str, tuple[Any, ...]]] = []
    for t, slug in ((a, "a"), (b, "b")):
        s.append(("insert into tenants (id, name, slug) values ($1, $2, $3)",
                  (t, f"Institución {slug.upper()}", f"humo-{slug}-{t.hex[:6]}")))
    for p, t in ((adm_a, a), (adm_a2, a), (adm_b, b)):
        s.append(("insert into profiles (id, documento_id, full_name, pin_hash, role) "
                  "values ($1, $2, '', '', 'admin')", (p, f"adm_{p.hex[:20]}")))
        s.append(("insert into memberships (tenant_id, profile_id, role, is_active) "
                  "values ($1, $2, 'admin', true)", (t, p)))
    s.append(("insert into groups (id, tenant_id, group_code) values ($1, $2, 'GA')", (ga, a)))
    s.append(("insert into groups (id, tenant_id, group_code) values ($1, $2, 'GB')", (gb, b)))
    ajenas: list[tuple[str, UUID]] = []
    cab = {"Authorization": f"Bearer {servicio}", "apikey": servicio}
    for i in range(3):  # personas de B con su cuenta de GoTrue (el id es su perfil)
        pid, mail = uuid4(), correo(f"ajena{i}")
        r = f.c.post(f"{GOTRUE}/admin/users", headers=cab,
                     json={"id": str(pid), "email": mail, "password": CLAVE_AJENA,
                           "email_confirm": True})
        if r.status_code != 200:
            raise RuntimeError(f"no se pudo sembrar la cuenta ajena: {r.status_code}")
        s.append(("insert into profiles (id, documento_id, full_name, pin_hash, role) "
                  "values ($1, $2, '', '', 'teacher')", (pid, f"b_{pid.hex[:20]}")))
        s.append(("insert into memberships (tenant_id, profile_id, role, is_active, full_name) "
                  "values ($1, $2, 'teacher', true, 'Persona de B')", (b, pid)))
        ajenas.append((mail, pid))
    sql(url_pg, s)
    return {"a": a, "b": b, "adm_a": adm_a, "adm_a2": adm_a2, "adm_b": adm_b, "ga": ga,
            "gb": gb, "ajenas": ajenas}


def recorrer(f: Flujo, d: dict[str, Any]) -> dict[str, Any]:
    o: dict[str, Any] = {}
    p_mail, q_mail, r_mail = correo("profe-p"), correo("profe-q"), correo("profe-r")
    x_mail = d["ajenas"][0][0]
    # H1: correo nuevo -> 201 y llega UN correo con la plantilla
    r, ms_nuevo = f.invitar(d["adm_a"], "Profe P", p_mail, d["ga"])
    p_inv = r.json().get("id")
    cuerpo_nuevo = sin_variables(r.json())
    llegados = esperar_correos(p_mail, 1)
    token, asunto, boton = token_y_datos(llegados[0]) if llegados else (None, "", False)
    o["H1"] = {"status": r.status_code, "correos": len(llegados), "asunto": asunto,
               "boton": boton, "enlace_invitacion": token is not None}
    # H2: canje type invite -> POST /api/auth/contrasena con esa sesión -> 204
    v = f.verify(token)
    sesion = v.json().get("access_token") if v.status_code == 200 else None
    cambio = f.c.post(f"{API}/auth/contrasena", json={"nueva": CLAVE_PROFE},
                      headers={"Authorization": f"Bearer {sesion}"})
    o["H2"] = {"verify": v.status_code, "contrasena": cambio.status_code}
    # H3: login con la contraseña nueva -> /auth/me teacher en A con su grupo; lista: aceptada
    lg = f.login(p_mail, CLAVE_PROFE)
    tok = lg.json().get("access_token") if lg.status_code == 200 else ""
    me = f.c.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {tok}"}).json()
    grupos = f.c.get(f"{API}/teachers/groups", headers={"Authorization": f"Bearer {tok}"}).json()
    o["H3"] = {"login": lg.status_code, "must_change_password": me.get("must_change_password"),
               "rol": [m.get("role") for m in me.get("memberships", [])],
               "institucion_a": me.get("active_tenant_id") == str(d["a"]),
               "grupo_a": [g.get("id") for g in grupos] == [str(d["ga"])],
               "estado": [i["estado"] for i in f.lista(d["adm_a"]) if i["id"] == p_inv]}
    # H4: correo con cuenta en B -> mismo 201, 0 correos, la cuenta de B sigue entrando
    r2, ms_ajeno = f.invitar(d["adm_a"], "Profe X", x_mail.upper(), d["ga"])
    x_inv = r2.json().get("id")
    time.sleep(ESPERA_S + 0.5)
    re_x = f.reenviar(d["adm_a"], x_inv)
    time.sleep(3)
    o["H4"] = {"status": r2.status_code, "mismo_cuerpo": sin_variables(r2.json()) == cuerpo_nuevo,
               "reenvio": re_x.status_code, "correos_a_la_ajena": len(correos_a(x_mail)),
               "ajena_entra": f.login(x_mail, CLAVE_AJENA).status_code,
               "estado": [i["estado"] for i in f.lista(d["adm_a"]) if i["id"] == x_inv]}
    # H5: tiempos (la respuesta no espera a GoTrue): A y el segundo admin de A
    tiempos_nuevo, tiempos_ajeno = [ms_nuevo], [ms_ajeno]
    for i in range(2):
        tiempos_nuevo.append(f.invitar(d["adm_a2"], f"Profe T{i}", correo(f"t{i}"), d["ga"])[1])
        tiempos_ajeno.append(f.invitar(d["adm_a2"], f"Profe U{i}", d["ajenas"][i + 1][0],
                                       d["ga"])[1])
    o["H5"] = {"ms_correo_nuevo": tiempos_nuevo, "ms_correo_ajeno": tiempos_ajeno}
    # H6: la aceptada no se reenvía; B no ve las de A ni puede reenviarlas
    o["H6"] = {"reenviar_aceptada": f.reenviar(d["adm_a"], p_inv).status_code,
               "lista_de_b": len(f.lista(d["adm_b"])),
               "b_reenvia_la_de_a": f.reenviar(d["adm_b"], x_inv).status_code}
    # H8: reenvío -> otro correo; el enlace viejo 403 y el nuevo sirve
    r3, _ = f.invitar(d["adm_a"], "Profe Q", q_mail, d["ga"])
    q_inv = r3.json().get("id")
    primero = esperar_correos(q_mail, 1)
    time.sleep(ESPERA_S + 0.5)
    re_q = f.reenviar(d["adm_a"], q_inv)
    ambos = esperar_correos(q_mail, 2)
    tokens = [token_y_datos(m)[0] for m in ambos]  # el más reciente primero
    o["H8"] = {"alta": r3.status_code, "reenvio": re_q.status_code, "correos": len(ambos),
               "primero_llego": len(primero) == 1,
               "viejo": f.verify(tokens[-1]).status_code if len(tokens) == 2 else None,
               "nuevo": f.verify(tokens[0]).status_code if len(tokens) == 2 else None}
    # H7: el tope por admin (5): P, X, reenvío X, Q, reenvío Q ya contaron -> el 6.º da 429
    r4, _ = f.invitar(d["adm_a"], "Profe R", r_mail, d["ga"])
    o["H7"] = {"status": r4.status_code, "detail": r4.json().get("detail"),
               "retry_after": bool(r4.headers.get("retry-after")),
               "correos_a_r": len(correos_a(r_mail))}
    return o


ESPERADO = {
    "H1": {"status": 201, "correos": 1, "asunto": "ENGRAMA: crea tu contraseña de profe",
           "boton": True, "enlace_invitacion": True},
    "H2": {"verify": 200, "contrasena": 204},
    "H3": {"login": 200, "must_change_password": False, "rol": ["teacher"],
           "institucion_a": True, "grupo_a": True, "estado": ["aceptada"]},
    "H4": {"status": 201, "mismo_cuerpo": True, "reenvio": 202, "correos_a_la_ajena": 0,
           "ajena_entra": 200, "estado": ["enviada"]},
    "H6": {"reenviar_aceptada": 409, "lista_de_b": 0, "b_reenvia_la_de_a": 404},
    "H8": {"alta": 201, "reenvio": 202, "correos": 2, "primero_llego": True, "viejo": 403,
           "nuevo": 200},
    "H7": {"status": 429, "detail": "demasiadas_invitaciones", "retry_after": True,
           "correos_a_r": 0},
}


def correr() -> dict[str, Any]:
    pg_clave, jwt_secreto = secrets.token_hex(16), secrets.token_hex(32)
    entorno = {**os.environ, "BANCO_PG_CLAVE": pg_clave, "BANCO_JWT": jwt_secreto}
    servicio = firmar(jwt_secreto, "servicio", rol="service_role")
    url_pg = f"postgresql://postgres:{pg_clave}@127.0.0.1:{PG}/postgres"
    backend = None
    try:
        compose(entorno, "up", "-d")
        esperar(f"{GOTRUE}/health")
        env_be = {**os.environ, "DATABASE_URL": url_pg.replace("postgresql://",
                                                               "postgresql+asyncpg://"),
                  "SUPABASE_JWT_SECRET": jwt_secreto, "GOTRUE_URL": GOTRUE,
                  "SUPABASE_SERVICE_ROLE_KEY": servicio, "APP_ENV": "production",
                  "APP_DEBUG": "false", "INVITACIONES_POR_HORA": str(TOPE),
                  "INVITACION_ESPERA_REENVIO_S": str(ESPERA_S)}
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=RAIZ,
                       env=env_be, check=True, capture_output=True)
        backend = subprocess.Popen([sys.executable, "-m", "uvicorn", "src.main:app",
                                    "--host", "127.0.0.1", "--port", "18300"],
                                   cwd=RAIZ, env=env_be, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
        esperar(f"{API}/health")
        f = Flujo(jwt_secreto)
        return recorrer(f, sembrar(url_pg, f, servicio))
    finally:
        if backend is not None:
            backend.terminate()
            backend.wait(timeout=20)
        compose(entorno, "down", "-v")


def main() -> int:
    etiqueta = sys.argv[1] if len(sys.argv) > 1 else ""
    if etiqueta not in ("", "replica"):
        print("uso: python -m tests.manual.humo_invitar_banco [replica]", file=sys.stderr)
        return 2
    ruta = SALIDA / f"humo_invitar_banco{'_' + etiqueta if etiqueta else ''}.json"
    inicio = time.monotonic()
    datos = correr()
    difieren = {k: datos.get(k) for k, v in ESPERADO.items() if datos.get(k) != v}
    salida = {"datos": datos, "difieren_de_lo_esperado": difieren,
              "segundos": round(time.monotonic() - inicio)}
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(salida, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"escrito": str(ruta), "difieren_de_lo_esperado": difieren},
                     ensure_ascii=False))
    return 1 if difieren else 0


if __name__ == "__main__":
    raise SystemExit(main())
