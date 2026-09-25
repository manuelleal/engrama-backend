# ESPEC · BUG-2: recursión en la RLS de `memberships` (F4)

Creador · 2026-09-24 · base `a6a427d` · se commitea antes del código. Citas con `grep -n` en el momento (ERR-10).

## 0. La cadena (medida)
- `029:39`: `memberships` está en el patrón base, así que recibe `_base_select_sql` (`:61`) y `_base_insert_sql` (`:75`), aplicadas en `:364-365`.
- Esas políticas leen la propia tabla: `:63` → `:67` y `:77` → `:81`, con `FROM memberships`.
- 13 políticas especiales (`:102` a `:317`, 16 líneas) y 34 del patrón base consultan `memberships`; cada una expande su RLS, que vuelve a pedirla.

Medido como `authenticated` con las tablas **vacías**: `SELECT` sobre `memberships`, `coin_wallets`, `tenants` y `profiles` da `42P17: infinite recursion detected in policy for relation "memberships"` (`fireRIRrules`). Falla al reescribir: no depende de los datos.

## 1. Qué cambia (una cosa)
Una migración nueva, `alembic/versions/030_rls_sin_recursion.py`. La 029 no se edita: puede estar aplicada en engrama-2.0.

**upgrade**
1. `CREATE SCHEMA app_private`; `REVOKE ALL FROM PUBLIC`; `GRANT USAGE TO authenticated`.
2. `app_private.user_tenant_ids() RETURNS SETOF uuid LANGUAGE sql STABLE SECURITY DEFINER SET search_path = ''`, con el cuerpo `SELECT m.tenant_id FROM public.memberships m WHERE m.profile_id = auth.uid() AND m.is_active = TRUE`.
3. `REVOKE ALL ON FUNCTION ... FROM PUBLIC`; `GRANT EXECUTE TO authenticated`.
4. DROP y CREATE de **solo** las dos políticas de `memberships`, con el mismo nombre, comando y rol, y la condición `tenant_id IN (SELECT app_private.user_tenant_ids())`.

**downgrade:** recrea las dos políticas con el texto de `029:66-70` y `:80-84`, y luego hace `DROP FUNCTION` y `DROP SCHEMA`.

**Dueño de la función:** quien migra, que es el dueño de `memberships` y la tabla no tiene FORCE RLS. Medido: `postgres` es el dueño, con `rolbypassrls = t` y `relforcerowsecurity = f`.

| Alternativa | Por qué no |
|---|---|
| Claims JWT (`tenant_id`, `role`) | Hook de Auth (config de producción); una membresía revocada sigue en el token; un tenant por token. |
| Vista materializada | Refresco con ventana de acceso revocado; sin RLS propia. |
| `profile_id = auth.uid()` sin función | Medido: el docente pasa de ver 2 perfiles a 1 (rompe `029:137-152`). |

**ADR-003, los dos casos:**
- **Escritura directa:** el arreglo es necesario; BUG-3..9 usarán esta función.
- **Todo por el backend:** el backend se salta la RLS (`src/shared/db.py:4`), pero `authenticated` conserva sus GRANT (medido: UPDATE `coin_wallets` y INSERT `memberships` = `t`). Si la ADR revoca, la función queda inerte.

## 2. Qué debe pasar (medible)
Hoy: 122 passed y 15 xfailed.

**122 existentes + 1 (D3 sale del xfail) + 2 nuevos + 3 tramposos = 128.**

| Id | Comando | Esperado |
|---|---|---|
| A | `python -m pytest -q` | **128 passed, 14 xfailed, 0 failed, 0 error** |
| B | `python -m pytest -m "not integ" -q` | 74 passed, igual que hoy |
| C | `pytest tests/seguridad/test_aceptacion.py --runxfail --tb=line` | 14 failed, los 14 con `el ataque PASA (sin error, N fila(s))`; `grep -c 42P17` = 0 |
| D | `grep -c 'xfail_bug("BUG-2' tests/seguridad/test_aceptacion.py` | 0 |

**Cambios de estado declarados (ninguno más):**
- D3 pasa a PASSED: se borra su decorador (`test_aceptacion.py:267-268`).
- Los 14 xfail (`:250 :286 :301 :321 :339 :356 :387`) conservan su BUG. Su motivo pasa a `BUG-N: el ataque PASA (sin SQLSTATE, N fila(s))`; medido: D2 1, D5 2 y el resto 1.
- `tests/integ_db.py:65` pasa a `"030_rls_sin_recursion"`. Sin ese cambio se midió 1 failed, 75 passed y 61 errors. `politicas_public` sigue en 51 (medido).

**Nuevos (`tests/seguridad/test_bug2_funcion.py`):**
- `blindada`, en `pg_proc`: `prosecdef`, `provolatile='s'`, `proconfig=['search_path=""']`, dueño = el de `memberships`, sin FORCE RLS. `anon` sin EXECUTE ni USAGE; `authenticated` con EXECUTE, sin CREATE.
- `no_filtra`: alumno de T1 con membresía admin **inactiva** en T2: la función da exactamente `[T1]` y `memberships` solo T1. Control: `postgres` ve 2 tenants. `anon` recibe 42501.

## 3. Tramposos (`tests/tramposos/test_tramposos_bug2.py`)
Rompe, corre el test real con `pytest.raises(AssertionError, match=...)` y restaura en `finally`.

| Tramposo | Rompe | Rojo | Mensaje |
|---|---|---|---|
| `recursiva` | vuelve a la política SELECT de la 029 | D3 | `42P17` |
| `sin_search_path` | `ALTER FUNCTION ... RESET search_path` | `blindada` | `search_path` |
| `fuga` | quita `profile_id = auth.uid()` | `no_filtra` | `colegios ajenos` |

Medidos en rojo sobre un candidato del scratchpad (A = 128/14/0); ahí los *match* 2 y 3 eran más débiles.

## 4. Riesgos de SECURITY DEFINER

| Riesgo | Barrera | Prueba |
|---|---|---|
| Escalada (la función corre como `postgres`) | sin parámetros; filtra `auth.uid()` adentro | `no_filtra`, `fuga` |
| Secuestro por `search_path` | `''` y nombres calificados | `blindada`, `sin_search_path` |
| Objetos plantados en el esquema | sin CREATE (medido: `permission denied`) | `blindada` |
| Uso como RPC | fuera de `public`; `anon` sin EXECUTE | `blindada` |
| Fuga | devuelve solo los tenants activos propios | `no_filtra` |
| Otro dueño en engrama-2.0 | `blindada` exige que el dueño sea el de la tabla | verificar allá, con el sí de Christiam |

## 5. Humo
- `humo_integ.json`: `alembic_version` = `030_rls_sin_recursion`.
- `humo_seguridad.json`: D7 pasa de `42P17/rota` a `null, 1, pasa`, que es BUG-5 a la vista.

Sin archivos, no hay veredicto.

## 6. Réplica
- **Migración:** `upgrade`, `downgrade`, `upgrade`, con una foto de `pg_policies`, `pg_proc` (config, ACL y md5 del cuerpo) y la ACL del esquema. La foto de 029 debe ser igual a la de después del `downgrade`, y las dos de 030 iguales entre sí. Medido: se cumplen las dos igualdades.
- **Tests:** `ENGRAMA_REPLICA=1` debe dar los mismos conteos que A.

## 7. Qué NO se toca
- La 029.
- `src/`.
- `veredictos.py`.
- Las otras 49 políticas.
- BUG-3..9, D10 y los 10 tramposos existentes.

## 8. Veredicto por la letra
**VERDE** solo si se cumplen A, B, C y D, los 3 tramposos salen en rojo con su mensaje, la réplica da idéntico y existen los dos humos. Cualquier otra cifra es **ROJO**: se reporta y no se ajusta.
