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

# Antes de aplicar la 032 (nombre del estudiante por membresía, BUG-11)

Origen: `docs/ESPEC_bug11.md` §7, 2026-09-28. Medido solo en la imagen local (`supabase/postgres:17.6.1.167`); **nada de esto se probó contra el remoto**. engrama-2.0 está pausado. **Nada de esto se corre contra un Supabase real sin el sí de Christiam en esa sesión** (REGLAS §2).

La 032 agrega `memberships.full_name` (nullable), le copia a cada membresía `student` el nombre de su perfil (backfill) y agrega el CHECK `memberships_student_full_name_check`: un `student` no puede quedar sin nombre. No toca `profiles`, las políticas, los privilegios de la 031 ni `app_private`.

- [ ] **Respaldo restaurado en local** y, sobre él, cuántos estudiantes comparten perfil entre colegios:
  ```sql
  select count(*) from (select profile_id from memberships where role = 'student'
    group by profile_id having count(distinct tenant_id) > 1) s;
  ```
  - Si da más de 0, el backfill le copia a cada colegio el nombre del **primero**: el que quedó en `profiles.full_name`. El nombre que escribió cada uno de los otros colegios (N2) nunca se guardó y **no se puede recuperar**. Christiam decide si esos colegios vuelven a escribir los nombres.
  - Se espera 0, porque ningún grupo real se matriculó mientras BUG-11 seguía abierto (`ESPEC_grupos_y_panel_docente.md` §6), pero **no está verificado**.
- [ ] **La migración y el código van juntos**, en el mismo despliegue:
  - el código viejo con la 032 aplicada da 23514 (500) en M3 y M4, porque crea la membresía sin nombre;
  - el código nuevo sin la 032 falla porque la columna no existe;
  - M3 y M4 no se usan en producción hoy.
- [ ] **Bloqueos.** `ADD COLUMN` sin default es solo metadato. El UPDATE del backfill y el `ADD CONSTRAINT` recorren `memberships` con bloqueo exclusivo. Con el tamaño actual no importa; si la tabla crece, se usa `ADD CONSTRAINT … NOT VALID` y después `VALIDATE CONSTRAINT`.
- [ ] **Sin downgrade en producción.** El downgrade de la 032 pierde datos: se queda solo con el nombre del colegio más antiguo de cada perfil y descarta el de los demás (`ESPEC_bug11.md` §1). Si hay que volver atrás, **se restaura el respaldo**; no se corre `alembic downgrade`.
- [ ] **Después de aplicar:**
  - la consulta de D12 (sección de la 031, arriba) da 0 y 0 (las dos devuelven NULL);
  - `select count(*) from pg_policies where schemaname = 'public'` da 51;
  - `memberships_student_full_name_check` existe:
    ```sql
    select pg_get_constraintdef(oid) from pg_constraint
    where conname = 'memberships_student_full_name_check';
    -- esperado: CHECK (((role <> 'student'::text) OR (full_name IS NOT NULL)))
    ```
- **Medido en local** (contenedor desechable del fixture, 2026-09-28): `alembic upgrade head` → `downgrade 031_sin_acceso_directo` → `upgrade head` corre sin errores. En las dos subidas, las columnas de `memberships` (nombre, tipo, nulabilidad y default) y sus restricciones coinciden. D12 da 0 y 0 y hay 51 políticas en las tres etapas. La posición física de `full_name` cambia de 8 a 9 tras bajar y volver a subir: PostgreSQL no reutiliza la ranura de una columna borrada. La prueba se hizo con `memberships` vacía; el backfill con datos lo cubren B1 y B2 (`tests/integ/test_migracion_032.py`).

# Antes de aplicar la 033 (una sola paga por reto, BUG-13)

Origen: `docs/ESPEC_bug13a15.md` §7, 2026-09-28. Medido solo en la imagen local (`supabase/postgres:17.6.1.167`); **nada de esto se probó contra el remoto**. engrama-2.0 está pausado. **Todo lo de esta sección está condicionado al sí de Christiam en esa sesión** (REGLAS §2): nada se corre contra un Supabase real sin él.

Qué hace la 033:
- agrega `coin_ledger.idempotency_key` (TEXT, nullable);
- le pone su llave `challenge:<reto>:<estudiante>` a la fila de reto **más antigua** de cada (tenant, reto, estudiante);
- agrega el UNIQUE `coin_ledger_idempotency_key (tenant_id, idempotency_key)`.

No crea tablas, vistas, secuencias ni funciones. No toca las políticas, los privilegios de la 031 ni `app_private`. BUG-14 y BUG-15 no tienen migración.

- [ ] **Respaldo restaurado en local** y, sobre él, las dobles pagas históricas (la consulta de `ESPEC_bug13a15.md` §7):
  ```sql
  select count(*) from (select l.tenant_id, l.metadata->>'challenge_id', w.owner_id
    from coin_ledger l join coin_wallets w on w.id = l.to_wallet_id and w.owner_type = 'profile'
   where l.action = 'challenge' group by 1, 2, 3 having count(*) > 1) s;
  ```
  - Si da más de 0: la 033 deja las filas repetidas con la llave en NULL y **no devuelve monedas**.
  - **Revertir esas dobles pagas lo decide Christiam**: una fila inversa por cada una, y toca saldos de estudiantes.
  - Se espera 0, pero **no está verificado**.
- [ ] **La migración va antes del código, o junto con él. Nunca después.**
  - Medido en local, quitando la columna y el UNIQUE: el código nuevo sin la 033 da 500 por **42703** (`column "idempotency_key" … does not exist`) en tres rutas: la victoria de un reto, el **check-in** y `GET /core/coins/history`. El ledger queda con 0 filas, así que no se paga nada. Rompe todo lo que toca el ledger, no solo los retos.
  - El código viejo con la 033 aplicada **no se midió**. Por lectura funciona igual que hoy: su modelo no nombra la columna, así que no pasa llave y sigue con el hueco, pero no rompe nada.
  - BUG-14 y BUG-15 no necesitan migración, pero en la rama van encima de BUG-13: desplegar esa rama exige la 033 antes.
- [ ] **Bloqueos.**
  - `ADD COLUMN` sin default es solo metadato.
  - El UPDATE del backfill y el `ADD CONSTRAINT UNIQUE`, que construye el índice, bloquean `coin_ledger`.
  - Con el tamaño actual no importa. Si la tabla crece, se hace `CREATE UNIQUE INDEX CONCURRENTLY` fuera de la transacción y después `ADD CONSTRAINT … USING INDEX`.
- [ ] **Sin downgrade en producción.**
  - Con el código nuevo desplegado, bajar la 033 deja la base sin la columna: victorias, check-in e historial dan 500 (el mismo 42703 medido arriba).
  - Además se pierden las llaves. Si se vuelve a subir, el backfill solo las recalcula para las filas de reto.
  - Si hay que volver atrás, **se restaura el respaldo**; no se corre `alembic downgrade`.
- [ ] **Después de aplicar:**
  - la consulta de D12 (sección de la 031, arriba) da 0 y 0 (las dos devuelven NULL);
  - `select count(*) from pg_policies where schemaname = 'public'` da 51;
  - el UNIQUE existe:
    ```sql
    select pg_get_constraintdef(oid) from pg_constraint
    where conname = 'coin_ledger_idempotency_key';
    -- esperado: UNIQUE (tenant_id, idempotency_key)
    ```
- **Medido en local** (contenedor desechable del fixture, 2026-09-28, sobre `7451dc1`): `alembic upgrade head`, `downgrade 032_nombre_por_membresia` y `upgrade head` corren sin errores (rc 0 en los dos pasos de Alembic).
  - En las dos subidas coinciden las columnas de `coin_ledger` (nombre, tipo, nulabilidad y default), la definición de cada restricción (`pg_get_constraintdef`) y los índices (`pg_indexes`). No se compara `ordinal_position` (ERR-24).
  - En la bajada no existen ni la columna, ni el UNIQUE, ni su índice.
  - D12 da 0 y 0 y hay 51 políticas en las tres etapas.
  - La prueba se hizo con `coin_ledger` vacío; el backfill con datos lo cubren B1 y B2 (`tests/integ/test_migracion_033.py`).

# Antes del piloto con estudiantes reales (login del piloto, `ESPEC_login_piloto.md` §7)

**El piloto con estudiantes reales ES producción.** Nada de esto se hace en el servidor de la UIS ni con datos reales sin **el sí de Christiam en esa sesión**: construir el backend desde esta rama, correr `python -m src.onboarding` con el CSV real y fondear las billeteras.

- [ ] **Ley 1581.**
  - UIS, SENA y UNAD son responsables del dato y ENGRAMA es encargado: hace falta un acuerdo de encargo con cada una y la autorización de los titulares.
  - Dato mínimo: nombre, correo institucional y documento. El documento **no sale** en el archivo de credenciales.
  - Lo revisa un abogado antes del primer estudiante real. Esto no es un concepto jurídico.
- [ ] **Secretos.**
  - `SUPABASE_SERVICE_ROLE_KEY` solo en el entorno del operador, y solo mientras corre la CLI. **El proceso web no la necesita**: `POST /auth/contrasena` usa el Bearer del propio usuario.
  - `SUPABASE_JWT_SECRET` solo en el `.env` del servidor.
  - El backend necesita `GOTRUE_URL` (en el piloto, `http://gotrue:9999`). Sin ella y sin `SUPABASE_URL`, `POST /auth/contrasena` responde 503 y nadie puede salir de la contraseña temporal.
- [ ] **El archivo de credenciales (`--salida`).**
  - Se genera en el servidor, **fuera del repo** (la CLI sale con 2 si la ruta cae dentro del repo del backend), se entrega a mano y se borra.
  - Es el único lugar donde queda una contraseña temporal: no está en la base, ni en el resumen, ni en los logs.
- [ ] **Las monedas de cada institución (`--monedas`).** No tiene valor por defecto: la cifra la decide Christiam (hoy 200.000, provisional) y la revisa el pedagogo. Solo se usa cuando la institución nace; una segunda corrida **no** recarga la billetera. Si se agota, el check-in da 402 y el estudiante lo ve.
- [ ] **Base limpia.** El volumen de pruebas tiene perfiles stub (`documento_id = sub[:8]`) del respaldo que ya no existe. No se migran: el piloto real arranca con un volumen nuevo.
- [ ] **Respaldo (`pg_dump`) antes de cada alta** y de cada actualización del backend. El alta es todo o nada en la base, pero las cuentas de GoTrue se crean después del commit y no se deshacen solas.
- [ ] **Signup cerrado en GoTrue** y `/auth/v1/admin*` cerrado en el proxy. Con el signup abierto, cualquiera crea una cuenta; el backend le responde 403 `Account has no ENGRAMA profile`, pero no debe poder crearla.
- [ ] **Límite de login por IP medido** con `tests/manual/humo_login_piloto_gotrue.py` (HP2) contra el stack de prueba, antes de la primera clase: un salón entero entra desde una sola IP. Si da algún 429, es un bloqueo del despliegue.
- [ ] **HP2 corrido contra el GoTrue de la versión del piloto.** El adaptador `GoTrueAdmin` solo está probado contra un doble: P0 (la cuenta con el `id` del perfil) se midió a mano, pero la CLI completa contra un GoTrue real no.
- [ ] **Ningún estudiante real antes de que cierren BUG-13, 14 y 15** (cerrados en `c9fd7d3`).
- [ ] **Un perfil por documento, en todas las instituciones.** La racha, el XP y la billetera son globales por perfil: un estudiante de UIS y de SENA verá una sola racha y un solo saldo. Y una CE y una CC con los mismos dígitos son **el mismo perfil** (`ESPEC_login_piloto.md` §1.6): revisar el CSV antes de correr el alta.
- [ ] **Después del alta:**
  - el resumen JSON trae `errores: []` y la salida del proceso es 0;
  - el archivo de credenciales tiene una fila por cada cuenta nueva (`cuentas_nuevas`);
  - `select count(*) from profiles where force_password_reset` es igual a las cuentas creadas que aún no cambiaron su contraseña;
  - una segunda corrida con el mismo CSV da `cuentas_nuevas: 0` y `membresias_nuevas: 0`.
- **Medido en local** (contenedor desechable del fixture y el doble de GoTrue; `tests/integ/test_humo_login_piloto.py`, semilla 8): 3 instituciones, 19 cuentas con `id == profiles.id`, 19 primeros ingresos bloqueados con 403 y desbloqueados tras cambiar la contraseña, y la segunda corrida sin cambios.

# Antes de aplicar la 034 (registro del consentimiento, `ESPEC_consentimiento.md`)

**Aplicarla en el piloto es producción: necesita el sí de Christiam en esa sesión.**

- [ ] **Respaldo previo** (`pg_dump`).
- [ ] **La migración va antes del código, o junto con él. Nunca después.** Con el código nuevo y sin la tabla, `/auth/me` consulta `consentimientos` y da 500: **nadie entra**. (Por lectura; no se midió con la tabla quitada.)
- [ ] **Sin downgrade en producción.** Bajar la 034 borra la tabla y, con ella, la prueba de quién aceptó qué. Si hay que volver atrás, se restaura el respaldo.
- [ ] **El texto del aviso, el responsable y el contacto** los revisa un abogado antes del primer estudiante real. El backend solo guarda la versión que el cliente le manda (`AVISO_VERSION`); **no valida** que sea la vigente.
- [ ] **Una versión nunca se reutiliza.** Si `AVISO_VERSION` vuelve a un valor ya usado, quien aceptó una posterior no podrá entrar (repetir una versión vieja no la vuelve "la última").
- [ ] **El servidor no bloquea por falta de consentimiento.** Lo exige la web. Quien llame a la API sin la web puede usarla sin aceptar; para el piloto se aceptó así (`ESPEC_consentimiento.md` §1.4).
- [ ] **Después de aplicar:**
  - `select version_num from alembic_version` da `034_consentimiento`;
  - la consulta de D12 (sección de la 031) da 0 y 0;
  - `select count(*) from pg_policies where schemaname = 'public'` sigue en 51;
  - `select relrowsecurity from pg_class where relname = 'consentimientos'` da `true`.
- **Medido en local** (contenedor desechable del fixture, 2026-10-06): `alembic downgrade 033_una_paga_por_reto` y `alembic upgrade head` corren con rc 0; antes y después hay 51 políticas, 27 tablas con RLS, 0 privilegios de clientes sobre la tabla y 7 de `service_role`. La prueba se hizo con la tabla vacía.
