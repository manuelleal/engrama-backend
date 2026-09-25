# Antes de aplicar la migración 030 en engrama-2.0 (producción)

Origen: auditoría del arreglo de BUG-2, 2026-09-24. No se probó contra el remoto. **Todo esto requiere el sí de Christiam** (REGLAS §2).

- [ ] **Respaldo** del proyecto engrama-2.0 restaurado en local antes de migrar (decisión 003, fase 0).
- [ ] La config de PostgREST (`db-schemas` en el panel de Supabase) **no** incluye `app_private`. Si lo incluyera, la función quedaría expuesta como `/rest/v1/rpc/user_tenant_ids`.
- [ ] El rol que ejecuta `alembic upgrade` en producción es el **dueño de `memberships`**. La migración no fija `OWNER TO`: si el dueño es otro, la función vuelve a pasar por la RLS y la recursión regresa.
- [ ] `memberships` **no** tiene `FORCE ROW LEVEL SECURITY`. Si lo tuviera, `SECURITY DEFINER` no se salta la RLS ni siquiera para el dueño.
- [ ] La ADR-003 está decidida. Mientras el backend se conecte con `service_role` (`src/shared/db.py:4`), la función y las políticas nuevas no afectan el tráfico real: solo protegen el acceso directo a la base.
- [ ] Probar primero en un staging real de Supabase: la imagen de pruebas (`supabase/postgres:17.6.1.167`) puede no ser la versión exacta de engrama-2.0.
