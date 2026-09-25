# ESPEC · BUG-3..9: sin acceso directo a `public` (decisión 005)

F4 · Creador · 2026-09-24 · preregistro. Base: cierre de `ESPEC_ci_y_deudas.md` (144 ids = 130 passed + 14 xfailed).

## 0. Medido
Contenedor desechable, puerto 55441, 30 migraciones. El REVOKE se aplicó con SQL a mano, no con Alembic.
- `public` tiene 27 tablas (26 + `alembic_version`), 0 secuencias y 0 funciones. `anon` y `authenticated` tienen todo en 27/27.
- `pg_default_acl`: `postgres` y `supabase_admin` dan ALL en `public` a `anon`, `authenticated` y `service_role`. `postgres` no es superusuario: `ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin` → 42501.
- Tras el REVOKE: `anon` y `authenticated` reciben `42501 permission denied for table profiles`, incluso sobre su propia fila. `service_role` lee. `app_private.user_tenant_ids()` sigue ejecutando.
- **Re-otorgar sigue dando 42501, pero con otro mensaje:**
  - `GRANT SELECT` en `profiles` → falla **en memberships**, porque las políticas la consultan.
  - `GRANT INSERT` en `coin_ledger` → *new row violates row-level security policy*.

  Aceptar cualquier 42501, o 0 filas, dejaría pasar el tramposo.
- El 42P17 salta antes del chequeo de privilegios: el tramposo `recursiva` de BUG-2 sigue válido.
- Una función nueva en `public` la ejecuta `anon` vía PUBLIC. No se puede quitar por esquema.
- Downgrade: las ACL quedan iguales como conjunto (`aclexplode` ordenado); cambia el orden textual en 27 filas. up/down/up: 0 diferencias.

## 1. Qué cambia (una cosa)
Nace `alembic/versions/031_sin_acceso_directo.py`, que revisa la 030. Su upgrade:

```sql
REVOKE ALL ON ALL {TABLES|SEQUENCES|ROUTINES} IN SCHEMA public FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  REVOKE ALL ON {TABLES|SEQUENCES|ROUTINES} FROM anon, authenticated;
```

Son 6 sentencias. El downgrade las repite en orden inverso con `GRANT ALL … TO anon, authenticated`: primero los DEFAULT y después los objetos.

**El EXECUTE de `authenticated` en `app_private.user_tenant_ids()` se mantiene:**
- solo devuelve los colegios del que llama; no sale por PostgREST;
- `test_bug2_funcion.py:59` lo exige;
- si algún día se abre una tabla (EVAGAME), la RLS funciona sin recursión.

Las funciones futuras en `public` hacen `REVOKE … FROM PUBLIC` explícito, como la 030. D12 detecta el olvido.

## 2. Tests
**`sin_acceso(res, tabla)`** en `veredictos.py`:

| Resultado | Veredicto |
|---|---|
| 42501 con `permission denied for table {tabla}` | Pasa (único válido) |
| 42P17, otro 42501, o sin error | AssertionError |
| Otro SQLSTATE | PruebaRota |

"0 filas" no vale, aunque el encargo lo aceptaba, porque la RLS también las produce.

**Control positivo:** `control_postgres`, más la misma sentencia como `service_role`. Esto agrega `service_role` a `ROLES_COMO` (`como.py:21`).

| Id | Afirma |
|---|---|
| D1-D9, D11 (mismos ids) | Cada ataque, como `anon` y como `authenticated`, cae en `sin_acceso`. `control_dueno` también pasa a `sin_acceso`. Se quitan los 7 `@xfail_bug` (14 ids). D9 conserva su parte por la API |
| D10 | Sin cambios |
| **D12** | Catálogo: 0 tablas, vistas o secuencias de `public` con algún privilegio para `anon` o `authenticated`, y 0 funciones ejecutables. Control: ve 27 tablas, y `service_role` tiene SELECT/INSERT/UPDATE/DELETE en 27/27 |
| **D13** | `postgres` crea una tabla y una secuencia en una transacción que se deshace: los clientes no tienen privilegios. Control: `service_role` sí |
| `bug2_no_filtra` | Su bloque de `memberships` (`test_bug2_funcion.py:81-82`) pasa a `sin_acceso(…, "memberships")` |

`HUMO_ESPERADO` (`integ_db.py:66`) pasa a `031_sin_acceso_directo`. `politicas_public` sigue en 51.

**Cuenta:**
- ids: 144 + 2 tests (D12, D13) + 17 tramposos (D12, D13 y 15 `regrant`) = **163**.
- Resultado: 130 + 14 antes xfail + 19 = **163 passed / 0 xfailed / 0 failed**.
- Sin integ: **76**.

## 3. Tramposos (`test_tramposos_seguridad.py`)
| Tramposo | Rojo en |
|---|---|
| D1: `GRANT SELECT ON profiles TO authenticated` | D1, D12 |
| D4: `GRANT INSERT ON coin_ledger TO authenticated` | D4, D12 |
| D12: `CREATE FUNCTION public.trampa()` | D12 |
| D13: quitar el DEFAULT (`… GRANT ALL ON TABLES TO anon, authenticated`) | D13 |
| `regrant[x]`: `GRANT ALL` en la tabla atacada; x = D2, D3, D5-D9, D11×8 | x, D12 |
| D10 y `recursiva`: sin cambios | D10; D3 (42P17) |

D12 fuera de la diagonal está documentado (ERR-10) y se verifica una vez a mano. Cualquier otro rojo fuera de la diagonal es fallo.

## 4. La API sigue funcionando
La suite completa queda en verde: A1-A7 y los flujos de `auth`, `challenge_engine` y `engrama_core`. `src/` no hace `SET ROLE` ni usa `request.jwt` (grep), así que **no se toca**.

## 5. Producción
Agregar a `docs/PRODUCCION_030.md` la sección **"Antes de aplicar la 031"**:
- **Supabase sí otorga por defecto.** En el respaldo restaurado en local, listar `pg_default_acl` y los dueños de las tablas. La 031 solo cubre lo que crea `postgres`: lo que cree `supabase_admin` nacerá abierto.
- `alembic` migra como `postgres`.
- `select current_user` desde el backend: no es un rol de cliente.
- Inventario de lo que corre como cliente sobre `public`: triggers de `auth.users`, storage, realtime y RPC. Tras la 031 dan 42501.
- Después de aplicar, la consulta de D12 en el remoto da 0 y 0.
- Aparte: quitar `public` de los esquemas expuestos de la Data API.

## 6. Humo y réplica
- **Humo:** `pytest tests/seguridad -k "d1 or d4 or d7"` escribe `humo_seguridad.json`, todo en 42501 y "rechaza" (D7 antes decía "pasa"). `humo_integ.json` registra la 031.
- **Réplica:** en un contenedor nuevo, con Alembic, correr upgrade, downgrade a la 030 y upgrade. El snapshot de ACL (`aclexplode` ordenado de `relacl`, `proacl` y `defaclacl`) debe cumplir 030 = downgrade y 031 = 031. `ENGRAMA_REPLICA=1`: misma cuenta.

## 7. Qué NO se toca
`src/**`, las migraciones 000-030, las políticas, `app_private`, `service_role`, `postgres`, el USAGE de `public`, `.venv`, coins-mvp, `engrama-test-pg` y Supabase remoto.

Se implementa después del commit de CI y deudas: los dos tocan `integ_db.py` y los tramposos.

## 8. Veredicto por la letra
- **FUNCIONA:** 163/0/0; 76 sin integ; los tramposos en su diagonal; la réplica idéntica; los humos escritos.
- **HAY ALGO MODESTO:** el desarrollo pasa y la réplica difiere.
- **NO:** cae un A o un flujo; un tramposo sale verde; D12 ≠ 0; cambia alguno de los 130; o se toca `src/`.
