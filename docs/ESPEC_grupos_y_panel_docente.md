# ESPEC · Grupos y panel docente (MVP para un grupo real)

F4 · Creador · 2026-09-25 · preregistro. Rama `test/fixture-integ`, base `d77dcb4`. Brechas 1, 2 y 8 de `investigacion/paridad/01`, y la 4 solo en inscripción.

## 0. Medido (contenedor propio desechable, puerto 55499, `.venv` oficial)
- **163 passed**, **76** no-integ, ruff 0, mypy 0; **20** rutas APIRoute.
- Ningún router usa `require_admin` (`src/shared/deps.py:98`); `src/teachers/*.py` tienen 0 líneas.
- Estudiante ↔ grupo por `memberships.group_code` (`003_create_memberships.py:26`), con `UNIQUE (tenant_id, profile_id)` (`:31`): un grupo por colegio.
- `attendance_sessions.status` ∈ {active, expired, cancelled} (`008:34`). Un check-in sobre una sesión no `active` da 410 (`attendance.py:248`).
- `weak_skills` nunca se escribe: `grep weak src/` solo encuentra `models.py:512` y `:625`.
- `profiles.id` no tiene FK a `auth.users`. `python-multipart` no está instalado.
- **Hueco existente:** un docente del mismo colegio sin `teacher_groups` recibe 201 en `POST /core/attendance/sessions` y en `POST /challenges/` con el `group_id` de otro grupo. Desde otro colegio: 404 y `[]`.

## 1. Qué cambia (una cosa)
Nacen `/teachers` (6 rutas) y `/admin` (4 rutas) en `src/teachers/`, con `router.py`, `admin_router.py`, `schemas.py` y `service/{access,panel,roster}.py`, montados en `main.py`.

Toda la autorización pasa por **un solo punto**, `visible_groups(auth)`: grupos de `auth.tenant_id`, todos si `is_admin`, y si no, solo los que `teacher_groups` asigna a `auth.profile_id`. `authorize_group(db, auth, gid)` = ese filtro más `id = gid`; sin resultado, 404.

**Sin migración:** las tablas y el status `expired` ya existen, y el backend escribe como `service_role` (decisión 005).

## 2. Qué debe pasar
| # | Ruta | Contrato |
|---|---|---|
| T1 | `GET /teachers/groups` | `visible_groups`: id, group_code, n.º de estudiantes |
| T2 | `GET …/groups/{gid}/students` | profile_id, full_name, balance (criterio de `get_balance`, `coins.py:156`), current_streak y la última asistencia a sesiones de **ese** grupo. Sin `documento_id` ni `pin_hash`. No crea wallets |
| T3 | `POST …/{gid}/attendance-sessions` | `{duration_minutes}` → 201; reusa `create_session` sin tocarla |
| T4 | `POST …/attendance-sessions/{sid}/close` | `status='expired'`, `expires_at=now()`. Sesión de otro grupo → 404. El check-in posterior da 410 |
| T5 | `GET …/{gid}/attempts` | intentos de retos con `group_id=gid`: estudiante, reto, skill, status, score, is_correct, coins_earned, completed_at y `weak_skills` = `[skill]` si el intento está completo y falló; si no, `[]` (se deriva). Sin `answers` |
| T6 | `PUT …/{gid}/challenges/{cid}` | fija `group_id`. El reto debe ser del colegio y estar sin grupo o en un grupo visible; si no, 404 |
| M1 | `POST /admin/groups` | `{group_code, max_capacity?}` → 201; código repetido → 409 |
| M2 | `POST /admin/groups/{gid}/teachers` | `{documento_id}` con membresía `teacher` activa en el colegio → 201 (200 si ya estaba); si no, 404 |
| M3 | `POST …/{gid}/students` | `{documento_id, nombre_completo}`. Crea el perfil si falta (uuid4, `pin_hash=''`); si existe, lo reusa sin pisar el nombre. 201 inscrito · 200 ya estaba · 409 si está en otro grupo, con otro rol o inactivo. Solo devuelve profile_id, documento_id y resultado |
| M4 | `POST …/{gid}/students/import` | cuerpo `text/csv` UTF-8, BOM opcional, separador `,` o `;`. Cabecera `documento_id,nombre_completo` (`coins-mvp/app.js:3538`); el resto se ignora y `pin` nunca se guarda. ≤ 500 filas. **Todo o nada:** documento fuera de `^[A-Za-z0-9_-]{3,32}$` (`app.js:300-305`), nombre vacío, fila repetida o en otro grupo → 422 `[{fila, motivo}]` y 0 escrituras. Reimportar da `creados 0` |

T usa `require_teacher` más `authorize_group`; M usa `require_admin` más `authorize_group`. Rol equivocado → **403 exacto**; recurso de otro grupo o colegio → **404 exacto**.

## 3. Matriz rol × ruta (tests A por la API)
Actores:
- **D**: docente dueño de GA (colegio A);
- **E**: estudiante de GA;
- **DO**: docente de A sin GA;
- **DT**: docente de B;
- **DM**: D con membresía también en B, llamando con `X-Tenant-ID: B`;
- **AA** y **AB**: admin de A y de B.

| Ruta | Prohibidas (1 test cada una) | Control |
|---|---|---|
| T1 | E 403 · DO, DT, DM, AB: 200 **sin GA** | D |
| T2-T6 | E 403 · DO, DT, DM, AB 404 | D; AA en T2 |
| M1 | E 403 · D 403 | AA |
| M2-M4 | E 403 · D 403 · AB 404 | AA |

Son **41 prohibidas** (5 + 25 + 2 + 9) y **11 controles**. Cada escritura prohibida afirma además que no escribió nada.

**Tramposos y diagonal PREDICHA** (el código no existe; ERR-15):

| Tramposo | Rojo esperado |
|---|---|
| X1 `visible_groups` sin colegio | {DM, AB}×T1-T6, AB×M2-M4, F1 |
| X2 sin `teacher_groups` | DO×T1-T6, F1 |
| X3 `/teachers` con `get_current_user` | E×T1-T6, U4 |
| X4 `/admin` con `require_teacher` | D×M1-M4, U4 |
| X5 `close` no cambia el status | F4, F12 |
| X6 T5 sin filtro de grupo | F5 |
| X7 T6 no revisa el grupo actual | F6 |
| X8 CSV escribe antes de fallar | F11 |
| X9 T2 usa `get_wallet` | F2 |

Los 163 previos no importan código nuevo. **Antes de aceptar** se mide la matriz completa (9 × 68 tests nuevos = 612 celdas) y se escribe aquí; un cruce no previsto se corrige por ERR (regla 8).

## 4. Tests y cuentas
- **no-integ:**
  - U1: CSV válido (`,`, `;`, BOM);
  - U2: CSV con errores;
  - U3: `weak_skills` derivado;
  - U4: las 20 rutas previas idénticas, más las 10 nuevas con su guarda.
- **integ:**
  - F1-F6: T1-T6;
  - F7-F11: M1, M2, M3, M4 en lote idempotente y M4 inválido sin escrituras;
  - F12: humo;
  - 41 prohibidas, 11 controles y 9 tramposos.

Cuentas: **163 + 4 + (12 + 41 + 11 + 9) = 240 passed**, 0 failed, 0 xfail. No-integ: 76 + 4 = **80**. ruff 0, mypy 0, ningún archivo pasa de 400 líneas.

Ubicación: `tests/teachers/`, `tests/integ/test_humo_grupos.py` y `tests/tramposos/test_tramposos_grupos.py`. En `integ_ayudante.py` solo se agrega `afiliar(perfil, tenant, rol)`.

## 5. Humo y réplica
- **Humo (F12):** AA crea el grupo, asigna a D e importa 3 filas; D abre una sesión, un estudiante hace check-in y D la cierra. Escribe `tests/_salida/humo_grupos.json` = `{"inscritos":3,"docentes":1,"checkin":200,"checkin_tras_cierre":410,"con_asistencia":1}`, y el archivo va al `.gitignore`.
- **Réplica** (`ENGRAMA_REPLICA_GRUPOS=1`, entradas nuevas):
  - códigos de grupo con tilde y espacio;
  - un CSV de 40 filas con `;` y BOM;
  - D con 2 grupos;
  - **B con un grupo de código idéntico a GA**: T2 de GA no puede listar a los estudiantes de B.

## 6. Qué NO se toca
- `alembic/` (`git diff d77dcb4 -- alembic/` vacío), los 163 tests, `integ_db.py`, `models.py`, `/auth`, `/core`, `/challenges` y sus servicios, `pyproject.toml`, `poetry.lock` y `.venv` (ERR-11).
- **Fuera de alcance:** tienda, apuestas, anuncios, badges, panel web, IA, super admin, monedas manuales, mover o borrar grupos y `max_capacity`.
- **Para después:**
  - BUG-10: el hueco de §0, más `/challenges/all` y `/core/attendance/sessions/active`, que muestran todo el colegio;
  - **la cuenta de acceso** (Supabase Auth con `id = profile_id`). Sin ella, un inscrito no entra: esta espec **no basta sola** para usar el sistema en clase;
  - que el pedagogo valide la regla de `weak_skills`.

## 7. Orden de commits (cada uno con 0 failed y los previos idénticos)
1. `test`: `afiliar` + U4 con las 20 rutas.
2. `feat`: `access.py` + T1 + F1 + sus celdas + X1, X2 y X3.
3. T2 + F2 + celdas + X9.
4. T3 y T4 + F3 y F4 + celdas + X5.
5. T5 + U3 + F5 + celdas + X6.
6. T6 + F6 + celdas + X7.
7. M1 y M2 + F7 y F8 + celdas + X4.
8. M3 + F9 + celdas.
9. M4 + U1 y U2 + F10 y F11 + celdas + X8.
10. F12 + `.gitignore`. Después, un commit de docs con la matriz medida.

## 8. Verificación y veredicto
```
poetry run pytest -m "not integ"   # 80 passed
poetry run pytest                  # 240 passed
ENGRAMA_REPLICA_GRUPOS=1 poetry run pytest tests/teachers tests/integ/test_humo_grupos.py
poetry run ruff check . ; poetry run mypy .
```
- **FUNCIONA:** cuentas exactas, matriz medida = §3, réplica y humo en verde, `alembic/` y los 163 intactos.
- **HAY ALGO MODESTO:** la réplica falla solo en tests F.
- **NO:** una celda prohibida da 2xx o datos ajenos, cambia algo previo, aparece una migración o un tramposo queda en verde.
