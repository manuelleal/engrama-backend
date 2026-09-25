"""Aceptación de seguridad: los ataques de coins-mvp contra el backend.

Espec: docs/ESPEC_aceptacion_seguridad.md. Un test por ataque; cada test AFIRMA
EL RECHAZO. A1-A7 van por la API; D1-D11, directo en la base con
`Integ.como(perfil, sql)` (rol y JWT de un usuario real de Supabase, en una
transacción que se deshace). Lo que hoy pasa queda en xfail estricto con su
BUG (desde la 030, ya ninguno cae por 42P17: BUG-2 corregido). Controles y juicios: veredictos.py.
Réplica: `ENGRAMA_REPLICA=1`. Tramposos: tests/tramposos/test_tramposos_seguridad.py.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from src.main import app
from tests.seguridad.modulos import INSERTS_MODULOS, parametros, sembrar_modulos
from tests.seguridad.veredictos import (
    colegios,
    control_dueno,
    control_postgres,
    identidad,
    par,
    rechazado,
    registrar_humo,
    sembrar,
    xfail_bug,
)

pytestmark = pytest.mark.integ
client = TestClient(app)


def _respuestas(pares: list[tuple[object, str]]) -> list[dict[str, str]]:
    return [{"question_id": str(q), "answer": a} for q, a in pares]


# =============================================================================
# A · por la API (hoy todos rechazan)
# =============================================================================
def test_a1_auth_me_no_expone_pin_hash(integ) -> None:
    """E1/H-1/H-2: /auth/me y /auth/session no devuelven el hash del PIN."""
    tenant = integ.crear_tenant()
    alumno = integ.crear_perfil(tenant)
    secreto = f"hash-secreto-{uuid4().hex}"
    sembrar(integ, "update profiles set pin_hash = :h where id = :p", h=secreto, p=alumno)
    assert integ.valor("select pin_hash from profiles where id = :p", p=alumno) == secreto

    for r in (client.get("/auth/me", headers=integ.headers(alumno)),
              client.post("/auth/session", headers=integ.headers(alumno))):
        assert r.status_code == 200, r.text
        assert r.json()["id"] == str(alumno)  # control: es su propio perfil
        assert "pin_hash" not in r.json()
        assert secreto not in r.text, "el hash del PIN sale en la respuesta"


def test_a2_core_coins_es_solo_lectura(integ) -> None:
    """E2/H-3: ninguna ruta de /core/coins escribe el saldo; PATCH -> 405."""
    tenant = integ.crear_tenant()
    alumno = integ.crear_perfil(tenant, saldo=50)
    h = integ.headers(alumno)
    rutas = {(r.path, frozenset(r.methods)) for r in app.routes
             if isinstance(r, APIRoute) and r.path.startswith("/core/coins")}
    assert rutas == {
        ("/core/coins/balance", frozenset({"GET"})),
        ("/core/coins/history", frozenset({"GET"})),
    }, f"rutas de /core/coins: {sorted(rutas)}"
    for ruta in ("/core/coins/balance", "/core/coins/history"):
        for metodo in ("PATCH", "PUT", "POST", "DELETE"):
            r = client.request(metodo, ruta, headers=h, json={"balance": 999999})
            assert r.status_code == 405, f"{metodo} {ruta} -> {r.status_code}"
    ok = client.get("/core/coins/balance", headers=h)  # control: GET sí responde
    assert ok.status_code == 200 and ok.json()["balance"] == 50, ok.text
    assert integ.saldo("profile", alumno) == 50


def test_a3_reto_no_revela_correct_answer(integ) -> None:
    """E3: lista, detalle e inicio de intento sin el valor de correct_answer."""
    tenant = integ.crear_tenant()
    profe = integ.crear_perfil(tenant, rol="teacher")
    alumno = integ.crear_perfil(tenant)
    secretos = (f"clave-{uuid4().hex[:12]}", f"clave-{uuid4().hex[:12]}")
    cid, qids = integ.crear_challenge(tenant, profe, respuestas=secretos)
    h = integ.headers(alumno)
    lista = client.get("/challenges/", headers=h)
    detalle = client.get(f"/challenges/{cid}", headers=h)
    intento = client.post(f"/challenges/{cid}/attempt", headers=h)
    assert (lista.status_code, detalle.status_code, intento.status_code) == (200, 200, 201)
    # Control: las preguntas SÍ viajan (si no viajara nada, no probaría nada).
    esperadas = {str(q) for q in qids}
    assert {q["id"] for q in detalle.json()["questions"]} == esperadas
    assert {q["id"] for q in intento.json()["challenge"]["questions"]} == esperadas
    assert str(cid) in lista.text
    for r in (lista, detalle, intento):
        assert "correct_answer" not in r.text
        for s in secretos:
            assert s not in r.text, f"la respuesta correcta sale en {r.url}"


def test_a4_submit_no_acepta_premios_del_cliente(integ) -> None:
    """E4: campos extra -> 422 y saldo intacto; todo mal -> 0 monedas."""
    tenant = integ.crear_tenant(pool=1000)
    profe = integ.crear_perfil(tenant, rol="teacher")
    alumno = integ.crear_perfil(tenant)
    cid, qids = integ.crear_challenge(tenant, profe, respuestas=("A", "B"), coins=20, xp=15)
    h = integ.headers(alumno)
    intento = client.post(f"/challenges/{cid}/attempt", headers=h).json()["attempt_id"]
    ruta = f"/challenges/attempts/{intento}/submit"
    malas = _respuestas([(qids[0], "Z"), (qids[1], "Z")])
    extra = client.post(ruta, headers=h, json={"answers": malas, "coins_earned": 9999})
    assert extra.status_code == 422, extra.text
    assert any(e["loc"][-1] == "coins_earned" and e["type"] == "extra_forbidden"
               for e in extra.json()["detail"])
    con_is_correct = [{**malas[0], "is_correct": True}, malas[1]]
    assert client.post(ruta, headers=h, json={"answers": con_is_correct}).status_code == 422
    assert integ.valor("select status from challenge_attempts where id = :a",
                       a=intento) == "in_progress"

    # Control: el mismo envío sin extras se acepta; todo mal no cobra.
    ok = client.post(ruta, headers=h, json={"answers": malas})
    assert ok.status_code == 200, ok.text
    assert [ok.json()[k] for k in ("is_correct", "coins_earned", "xp_earned")] == [False, 0, 0]
    assert integ.saldo("profile", alumno) in (None, 0)
    assert integ.saldo("tenant", tenant) == 1000
    assert integ.valor("select count(*) from coin_ledger") == 0


def test_a5_no_se_envia_el_intento_ajeno(integ) -> None:
    """R1: B envía el intento de A -> 404; el intento sigue in_progress."""
    tenant = integ.crear_tenant(pool=1000)
    profe = integ.crear_perfil(tenant, rol="teacher")
    intruso, dueno = par(integ.crear_perfil(tenant), integ.crear_perfil(tenant))
    cid, qids = integ.crear_challenge(tenant, profe, respuestas=("A",), coins=20)
    intento = client.post(f"/challenges/{cid}/attempt",
                          headers=integ.headers(dueno)).json()["attempt_id"]
    cuerpo = {"answers": _respuestas([(qids[0], "A")])}
    ruta = f"/challenges/attempts/{intento}/submit"
    r = client.post(ruta, headers=integ.headers(intruso), json=cuerpo)
    assert r.status_code == 404, r.text
    assert integ.valor("select status from challenge_attempts where id = :a",
                       a=intento) == "in_progress"
    assert integ.valor("select count(*) from coin_ledger") == 0

    ok = client.post(ruta, headers=integ.headers(dueno), json=cuerpo)  # control
    assert ok.status_code == 200 and ok.json()["coins_earned"] == 20, ok.text
    assert integ.saldo("profile", intruso) is None


def test_a6_rol_del_perfil_no_da_permisos(integ) -> None:
    """R4/H-6: profiles.role='super_admin' con membresía de alumno -> 403."""
    tenant = integ.crear_tenant()
    profe = integ.crear_perfil(tenant, rol="teacher")
    alumno = integ.crear_perfil(tenant)
    sembrar(integ, "update profiles set role = 'super_admin' where id = :p", p=alumno)
    for ruta in ("/challenges/all", "/core/attendance/sessions/active"):
        assert client.get(ruta, headers=integ.headers(profe)).status_code == 200  # control
        r = client.get(ruta, headers=integ.headers(alumno))
        assert r.status_code == 403, f"{ruta} -> {r.status_code}"
    nuevo = {"title": "Trampa", "description": "x",
             "questions": [{"question_text": "?", "correct_answer": "A"}]}
    assert client.post("/challenges/", headers=integ.headers(alumno),
                       json=nuevo).status_code == 403
    assert integ.valor("select count(*) from challenges") == 0


def test_a7_otro_colegio_no_se_ve(integ) -> None:
    """Aislamiento por tenant: X-Tenant-ID ajeno -> 403; reto ajeno -> 404."""
    propio, ajeno = colegios(integ)
    alumno = integ.crear_perfil(propio)
    cid_propio, _ = integ.crear_challenge(propio, integ.crear_perfil(propio, rol="teacher"))
    cid_ajeno, _ = integ.crear_challenge(ajeno, integ.crear_perfil(ajeno, rol="teacher"))
    h = integ.headers(alumno)
    r = client.get("/challenges/", headers={**h, "X-Tenant-ID": str(ajeno)})
    assert r.status_code == 403, r.text
    ok = client.get("/challenges/", headers={**h, "X-Tenant-ID": str(propio)})  # control
    assert ok.status_code == 200 and [c["id"] for c in ok.json()] == [str(cid_propio)]

    assert client.get(f"/challenges/{cid_propio}", headers=h).status_code == 200  # control
    assert client.get(f"/challenges/{cid_ajeno}", headers=h).status_code == 404
    assert client.post(f"/challenges/{cid_ajeno}/attempt", headers=h).status_code == 404
    assert integ.valor("select count(*) from challenge_attempts") == 0


# =============================================================================
# D · directo en la base (RLS). Hoy rechazan: D1, D3, D4, D10.
# =============================================================================
def test_d1_anon_no_lee_ni_escribe(integ) -> None:
    """E1/H-1: `anon` no ve perfiles (0 filas) ni los crea (42501)."""
    tenant = integ.crear_tenant()
    alumno = integ.crear_perfil(tenant)
    identidad(integ, None)
    leer, p_leer = "select id, pin_hash from profiles where id = :p", {"p": alumno}
    control_postgres(integ.como(None, leer, p_leer, rol="postgres"), "postgres lee el perfil")
    res = integ.como(None, leer, p_leer)
    registrar_humo("D1-select", "anon", res)
    rechazado(res, "anon SELECT profiles")
    crear = ("insert into profiles (id, documento_id, full_name, pin_hash) "
             "values (:i, :d, 'Intruso', 'x')")
    nuevo = uuid4()
    p_crear = {"i": nuevo, "d": f"doc-{nuevo.hex[:12]}"}
    control_postgres(integ.como(None, crear, p_crear, rol="postgres"), "postgres crea un perfil")
    res = integ.como(None, crear, p_crear)
    registrar_humo("D1-insert", "anon", res)
    rechazado(res, "anon INSERT profiles", solo_42501=True)


def test_d4_nadie_escribe_el_ledger(integ) -> None:
    """E6: un alumno no inserta movimientos en coin_ledger (42501)."""
    tenant = integ.crear_tenant(pool=1000)
    alumno = integ.crear_perfil(tenant, saldo=0)
    identidad(integ, alumno)
    carteras = {
        "t": tenant,
        "desde": integ.valor("select id from coin_wallets where owner_id = :o", o=tenant),
        "hacia": integ.valor("select id from coin_wallets where owner_id = :o", o=alumno),
    }
    sql = ("insert into coin_ledger (tenant_id, from_wallet_id, to_wallet_id, amount, action) "
           "values (:t, :desde, :hacia, 500, 'challenge')")
    control_postgres(integ.como(None, sql, carteras, rol="postgres"), "postgres escribe el ledger")
    res = integ.como(alumno, sql, carteras)
    registrar_humo("D4", "authenticated", res)
    rechazado(res, "alumno INSERT coin_ledger", solo_42501=True)
    assert integ.valor("select count(*) from coin_ledger") == 0


def test_d10_ninguna_politica_abierta(integ) -> None:
    """H-5: 0 políticas `true` y 0 políticas para `anon` o `public`."""
    # Control: la consulta sí lee pg_policies (ve una política conocida).
    assert integ.valor(
        "select count(*) from pg_policies where schemaname = 'public' "
        "and tablename = 'profiles' and policyname = 'profiles_select_own'"
    ) == 1
    abiertas = integ.valor(
        "select string_agg(tablename || '.' || policyname, ', ' "
        "                  order by tablename, policyname) "
        "from pg_policies where schemaname = 'public' and ("
        "  coalesce(qual, '') = 'true' or coalesce(with_check, '') = 'true'"
        "  or 'anon' = any(roles) or 'public' = any(roles))"
    )
    assert abiertas is None, f"políticas abiertas: {abiertas}"


# =============================================================================
# D · directo en la base. Tras BUG-2 (030) el ataque PASA: cada uno queda en su BUG.
# =============================================================================


@xfail_bug("BUG-8: el ataque PASA (sin SQLSTATE, 1 fila): profiles_select_admin no "
        "filtra tenant y el admin de otro colegio lee pin_hash")
def test_d2_pin_hash_ajeno_invisible(integ) -> None:
    """E1b: el admin o el docente de OTRO colegio no leen el pin_hash (0 filas)."""
    propio, ajeno = colegios(integ)
    admin = integ.crear_perfil(propio, rol="admin")
    profe = integ.crear_perfil(propio, rol="teacher")
    victima = integ.crear_perfil(ajeno)
    leer, p = "select id, pin_hash from profiles where id = :v", {"v": victima}
    control_postgres(integ.como(None, leer, p, rol="postgres"), "postgres lee a la víctima")
    for quien, pid in (("admin", admin), ("docente", profe)):
        identidad(integ, pid)
        rechazado(integ.como(pid, leer, p), f"{quien} de otro colegio lee pin_hash")
    control_dueno(integ.como(victima, "select id from profiles where id = auth.uid()"),
                  "la víctima lee su perfil")


def test_d3_alumno_no_edita_saldos(integ) -> None:
    """E2: UPDATE coin_wallets (propia y del colegio) -> UPDATE 0, valores intactos."""
    tenant = integ.crear_tenant(pool=1000)
    alumno = integ.crear_perfil(tenant, saldo=10)
    identidad(integ, alumno)
    for dueno, tipo, valor in ((alumno, "profile", 999999), (tenant, "tenant", 0)):
        sql = ("update coin_wallets set balance = :v "
               "where owner_type = :tipo and owner_id = :o")
        p = {"v": valor, "tipo": tipo, "o": dueno}
        control_postgres(integ.como(None, sql, p, rol="postgres"), f"postgres edita {tipo}")
        rechazado(integ.como(alumno, sql, p), f"alumno UPDATE wallet {tipo}")
    assert (integ.saldo("profile", alumno), integ.saldo("tenant", tenant)) == (10, 1000)
    control_dueno(integ.como(alumno, "select balance from coin_wallets "
                                     "where owner_type = 'profile' and owner_id = auth.uid()"),
                  "el dueño lee su wallet")


@xfail_bug("BUG-3: el ataque PASA (sin SQLSTATE, 2 filas): tenant_isolation_select "
        "deja leer correct_answer")
def test_d5_alumno_no_lee_correct_answer(integ) -> None:
    """E3: SELECT correct_answer de challenge_questions -> 0 filas o 42501."""
    tenant = integ.crear_tenant()
    alumno = integ.crear_perfil(tenant)
    cid, _ = integ.crear_challenge(tenant, integ.crear_perfil(tenant, rol="teacher"))
    sql, p = "select correct_answer from challenge_questions where challenge_id = :c", {"c": cid}
    control_postgres(integ.como(None, sql, p, rol="postgres"), "postgres lee las claves", filas=2)
    identidad(integ, alumno)
    rechazado(integ.como(alumno, sql, p), "alumno lee correct_answer")
    control_dueno(integ.como(alumno, "select id from challenges where id = :c", p),
                  "el alumno ve el reto activo de su colegio")


@xfail_bug("BUG-4: el ataque PASA (sin SQLSTATE, 1 fila): tenant_isolation_insert "
        "solo mira el tenant y el alumno inserta un intento ganado")
def test_d6_alumno_no_inserta_intentos(integ) -> None:
    """E4/R1: INSERT de un intento 'ganado', propio o a nombre de otro -> 42501."""
    tenant = integ.crear_tenant()
    atacante, victima = par(integ.crear_perfil(tenant), integ.crear_perfil(tenant))
    cid, _ = integ.crear_challenge(tenant, integ.crear_perfil(tenant, rol="teacher"))
    sql = ("insert into challenge_attempts (tenant_id, challenge_id, student_id, status, "
           "score_percent, is_correct, coins_earned, xp_earned, completed_at) "
           "values (:t, :c, :s, 'completed', 100, true, 999, 999, now())")
    identidad(integ, atacante)
    for quien, alumno in (("propio", atacante), ("ajeno", victima)):
        p = {"t": tenant, "c": cid, "s": alumno}
        control_postgres(integ.como(None, sql, p, rol="postgres"), f"postgres, intento {quien}")
        rechazado(integ.como(atacante, sql, p), f"INSERT intento {quien}", solo_42501=True)
    assert integ.valor("select count(*) from challenge_attempts") == 0
    control_dueno(integ.como(atacante, "select id from challenges where id = :c", {"c": cid}),
                  "el alumno ve el reto")


@xfail_bug("BUG-5: el ataque PASA (sin SQLSTATE, 1 fila): un alumno da membresía "
        "admin a otro perfil")
def test_d7_alumno_no_crea_membresia_admin(integ) -> None:
    """E5: INSERT memberships role='admin' para otro perfil -> 42501. Escribe humo."""
    propio, ajeno = colegios(integ)
    alumno = integ.crear_perfil(propio)
    otro = integ.crear_perfil(ajeno)  # sin membresía en `propio`: no choca con el UNIQUE
    sql = "insert into memberships (tenant_id, profile_id, role) values (:t, :p, 'admin')"
    p = {"t": propio, "p": otro}
    control_postgres(integ.como(None, sql, p, rol="postgres"), "postgres crea la membresía")
    identidad(integ, alumno)
    res = integ.como(alumno, sql, p)
    registrar_humo("D7", "authenticated", res)
    rechazado(res, "alumno INSERT memberships admin", solo_42501=True)
    control_dueno(integ.como(alumno, "select id from memberships where profile_id = auth.uid()"),
                  "el alumno lee su membresía")


@xfail_bug("BUG-6: el ataque PASA (sin SQLSTATE, 1 fila): profiles_update_own deja "
        "editar current_streak, xp y role")
def test_d8_alumno_no_edita_racha_xp_ni_rol(integ) -> None:
    """E2b: UPDATE de la propia current_streak, xp o role -> no editable."""
    tenant = integ.crear_tenant()
    alumno = integ.crear_perfil(tenant, racha=2)
    identidad(integ, alumno)
    for columna, valor in (("current_streak", 999), ("xp", 999999), ("role", "super_admin")):
        sql, p = f"update profiles set {columna} = :v where id = :p", {"v": valor, "p": alumno}
        control_postgres(integ.como(None, sql, p, rol="postgres"), f"postgres edita {columna}")
        rechazado(integ.como(alumno, sql, p), f"alumno UPDATE profiles.{columna}")
    assert integ.fila("select current_streak, xp, role from profiles where id = :p",
                      p=alumno) == {"current_streak": 2, "xp": 0, "role": "student"}
    control_dueno(integ.como(alumno, "select id from profiles where id = auth.uid()"),
                  "el alumno lee su perfil")


@xfail_bug("BUG-7: el ataque PASA (sin SQLSTATE, 1 fila): el alumno crea su sesión "
        "y marca su asistencia")
def test_d9_alumno_no_crea_sesion_ni_marca_asistencia(integ) -> None:
    """Nuevo: INSERT attendance_sessions y attendance -> 42501; el código -> 404."""
    tenant = integ.crear_tenant(pool=1000)
    profe = integ.crear_perfil(tenant, rol="teacher", group_code="G1")
    alumno = integ.crear_perfil(tenant, group_code="G1", saldo=0)
    grupo = integ.crear_grupo(tenant, "G1")
    legitimo = integ.crear_sesion_asistencia(tenant, grupo, profe)
    sesion = integ.valor("select id from attendance_sessions where session_code = :c", c=legitimo)
    falso = f"TRAMPA{uuid4().hex[:6].upper()}"
    ataques = (
        ("attendance_sessions", "insert into attendance_sessions (tenant_id, group_id, "
         "session_code, expires_at, created_by) "
         "values (:t, :g, :c, now() + make_interval(hours => 1), :yo)"),
        ("attendance", "insert into attendance (tenant_id, session_id, student_id, "
         "coins_awarded) values (:t, :s, :yo, 999)"),
    )
    identidad(integ, alumno)
    todos = {"t": tenant, "g": grupo, "c": falso, "s": sesion, "yo": alumno}
    for tabla, sql in ataques:
        p = parametros(sql, todos)
        control_postgres(integ.como(None, sql, p, rol="postgres"), f"postgres inserta {tabla}")
        rechazado(integ.como(alumno, sql, p), f"alumno INSERT {tabla}", solo_42501=True)
    h = integ.headers(alumno)
    r = client.post("/core/attendance/check-in", headers=h, json={"session_code": falso})
    assert r.status_code == 404, r.text
    ok = client.post("/core/attendance/check-in", headers=h, json={"session_code": legitimo})
    assert ok.status_code == 200, ok.text  # control: el check-in legítimo funciona


@xfail_bug("BUG-9: el ataque PASA (sin SQLSTATE, 1 fila): el alumno escribe en "
        "tablas de módulos sin código")
@pytest.mark.parametrize("tabla", sorted(INSERTS_MODULOS))
def test_d11_alumno_no_escribe_tablas_de_modulos(integ, tabla: str) -> None:
    """D11: INSERT del alumno en 8 tablas de módulos vacíos -> 42501."""
    tenant = integ.crear_tenant()
    alumno, otro = par(integ.crear_perfil(tenant), integ.crear_perfil(tenant))
    sql = INSERTS_MODULOS[tabla]
    p = parametros(sql, sembrar_modulos(integ, tenant, alumno, otro))
    control_postgres(integ.como(None, sql, p, rol="postgres"), f"postgres inserta en {tabla}")
    identidad(integ, alumno)
    rechazado(integ.como(alumno, sql, p), f"alumno INSERT {tabla}", solo_42501=True)
