# Antes de aplicar la migración 030 en engrama-2.0 (producción)

Origen: auditoría del arreglo de BUG-2, 2026-09-24. No se probó contra el remoto. **Todo esto requiere el sí de Christiam** (REGLAS §2).

- [ ] **Respaldo** del proyecto engrama-2.0 restaurado en local antes de migrar (decisión 003, fase 0).
- [ ] La config de PostgREST (`db-schemas` en el panel de Supabase) **no** incluye `app_private`. Si lo incluyera, la función quedaría expuesta como `/rest/v1/rpc/user_tenant_ids`.
- [ ] El rol que ejecuta `alembic upgrade` en producción es el **dueño de `memberships`**. La migración no fija `OWNER TO`: si el dueño es otro, la función vuelve a pasar por la RLS y la recursión regresa.
- [ ] `memberships` **no** tiene `FORCE ROW LEVEL SECURITY`. Si lo tuviera, `SECURITY DEFINER` no se salta la RLS ni siquiera para el dueño.
- [ ] La ADR-003 está decidida. Mientras el backend se conecte con `service_role` (`src/shared/db.py:4`), la función y las políticas nuevas no afectan el tráfico real: solo protegen el acceso directo a la base.
- [ ] Probar primero en un staging real de Supabase: la imagen de pruebas (`supabase/postgres:17.6.1.167`) puede no ser la versión exacta de engrama-2.0.

# Antes de aplicar la 031 (sin acceso directo de clientes)

Origen: `docs/ESPEC_bug3a9_sin_acceso_directo.md` §5 y la decisión 005, 2026-09-25. Medido solo en la imagen local (`supabase/postgres:17.6.1.167`); **nada de esto se probó contra el remoto**. Todo requiere el sí de Christiam.

La 031 quita a `anon` y `authenticated` todo privilegio sobre las tablas, secuencias y funciones de `public`, y cambia los DEFAULT PRIVILEGES **de `postgres`** en `public` para que lo nuevo tampoco nazca abierto. No toca `service_role`, `postgres`, las políticas, `app_private` ni el USAGE de `public`.

- [ ] **Supabase sí otorga por defecto.** En el respaldo restaurado en local, listar los DEFAULT y los dueños:
  ```sql
  select d.defaclrole::regrole as dueno, n.nspname as esquema, d.defaclobjtype as tipo, d.defaclacl
  from pg_default_acl d left join pg_namespace n on n.oid = d.defaclnamespace
  order by 1, 2, 3;

  select tableowner, count(*) from pg_tables where schemaname = 'public' group by 1;
  ```
  En local, `postgres` y `supabase_admin` dan ALL en `public` a `anon`, `authenticated` y `service_role`. **La 031 solo cubre lo que crea `postgres`**: lo que cree `supabase_admin` en `public` nacerá abierto para los clientes. `postgres` no es superusuario y no puede cambiar los DEFAULT de `supabase_admin` (`ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin` → 42501). Si alguna tabla de `public` es de otro dueño (p. ej. `supabase_admin`), el REVOKE de la 031 puede **no** quitar lo que otorgó ese dueño: según la documentación de PostgreSQL, un usuario solo revoca lo que otorgó él, y si no puede revocar nada da un WARNING, no un error, así que la migración "pasa" igual. No se midió (en local las 27 tablas son de `postgres`); la consulta de D12 de abajo lo detecta.
- [ ] **`alembic` migra como `postgres`.** Es el rol cuyos DEFAULT cambia la 031 y el dueño que exige la 030.
- [ ] **El backend no es un rol de cliente.** Desde el backend desplegado, `select current_user` no debe dar `anon` ni `authenticated`. Si diera uno de ellos, tras la 031 todas las rutas fallarían con 42501.
- [ ] **Inventario de lo que corre como cliente sobre `public`:** triggers sobre `auth.users` (p. ej. el que crea el perfil al registrarse), políticas de storage que consulten tablas de `public`, suscripciones de realtime y funciones llamadas por RPC. Tras la 031, todo lo que corra como `anon` o `authenticated` sobre `public` da 42501. Lo que sea SECURITY DEFINER de `postgres` sigue funcionando.
- [ ] **Después de aplicar**, la consulta de D12 en el remoto da 0 y 0 (las dos devuelven NULL):
  ```sql
  -- Relaciones de public con algún privilegio para clientes (debe dar NULL)
  select string_agg(c.relname || '(' || r.rol || ')', ', ')
  from pg_class c join pg_namespace n on n.oid = c.relnamespace
  cross join (values ('anon'), ('authenticated')) as r(rol)
  where n.nspname = 'public' and c.relkind in ('r', 'p', 'v', 'm', 'f', 'S')
    and case when c.relkind = 'S'
             then has_sequence_privilege(r.rol, c.oid, 'USAGE,SELECT,UPDATE')
             else has_table_privilege(r.rol, c.oid,
                    'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN')
                  or has_any_column_privilege(r.rol, c.oid, 'SELECT,INSERT,UPDATE,REFERENCES')
        end;

  -- Funciones de public que un cliente puede ejecutar (debe dar NULL)
  select string_agg(p.oid::regprocedure::text || '(' || r.rol || ')', ', ')
  from pg_proc p join pg_namespace n on n.oid = p.pronamespace
  cross join (values ('anon'), ('authenticated')) as r(rol)
  where n.nspname = 'public' and has_function_privilege(r.rol, p.oid, 'EXECUTE');
  ```
  Si la segunda da algo, es una función con el EXECUTE de PUBLIC: hay que hacerle `REVOKE ALL ON FUNCTION … FROM PUBLIC` en una migración aparte, como la 030. La 031 no puede quitar eso por esquema.
- [ ] **Aparte:** quitar `public` de los esquemas expuestos de la Data API (`db-schemas` en el panel). Con la 031 ya no hay nada que exponer, y así la API de datos de Supabase no publica ni la lista de tablas.
- [ ] **El downgrade de la 031 reabre todo** (devuelve GRANT ALL a `anon` y `authenticated`). No es un rollback seguro en producción: si hay que volver atrás, se decide aparte.
