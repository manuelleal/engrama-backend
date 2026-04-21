# SPECS/00b-rls-policies.md — Engrama 2.0 RLS Policies
# Estado: APROBADO | Fecha: 2026-04-19
# Para: Windsurf — genera migración 029_rls_policies
# Prerequisito: 028_enable_rls ya aplicado

## 0. Contexto

RLS (Row Level Security) garantiza que cada usuario solo ve datos
de su propio tenant. El backend usa dos roles:

- `authenticated` — usuario normal (estudiante, profesor, admin)
  → JWT de Supabase Auth, auth.uid() = profiles.id
- `service_role` — backend FastAPI para operaciones admin/sistema
  → bypasea RLS automáticamente, nunca exponer al frontend

## 1. Patrón base — tenant_isolation

Aplica a todas las tablas con tenant_id EXCEPTO las listadas en sección 2.

```sql
-- SELECT: solo ves filas de tus tenants
CREATE POLICY "tenant_isolation_select" ON <tabla>
  FOR SELECT TO authenticated
  USING (
    tenant_id IN (
      SELECT tenant_id FROM memberships
      WHERE profile_id = auth.uid()
      AND is_active = TRUE
    )
  );

-- INSERT: solo puedes insertar en tus tenants
CREATE POLICY "tenant_isolation_insert" ON <tabla>
  FOR INSERT TO authenticated
  WITH CHECK (
    tenant_id IN (
      SELECT tenant_id FROM memberships
      WHERE profile_id = auth.uid()
      AND is_active = TRUE
    )
  );

-- UPDATE/DELETE: solo tus tenants (backend maneja esto via service_role)
-- No crear políticas UPDATE/DELETE para authenticated en tablas transaccionales
-- El frontend nunca actualiza/borra directamente
```

Tablas que usan patrón base (sin modificaciones):
- memberships
- groups
- teacher_groups
- attendance_sessions
- attendance
- challenge_questions
- challenge_attempts
- question_bank
- student_progress
- student_analytics
- improvement_plans
- shop_items
- inventory
- auctions
- auction_bids
- badge_unlocks
- bets
- announcements
- ai_usage_logs

## 2. Políticas especiales

### 2.1 profiles

```sql
-- SELECT: ves tu propio perfil siempre
CREATE POLICY "profiles_select_own" ON profiles
  FOR SELECT TO authenticated
  USING (id = auth.uid());

-- SELECT: teachers ven perfiles de estudiantes de su grupo
CREATE POLICY "profiles_select_teacher" ON profiles
  FOR SELECT TO authenticated
  USING (
    EXISTS (
      SELECT 1 FROM memberships m_teacher
      JOIN memberships m_student ON m_student.tenant_id = m_teacher.tenant_id
        AND m_student.group_code = m_teacher.group_code  -- mismo grupo
      WHERE m_teacher.profile_id = auth.uid()
        AND m_teacher.role = 'teacher'
        AND m_student.profile_id = profiles.id
        AND m_teacher.is_active = TRUE
    )
  );

-- SELECT: admins ven todos los perfiles de su tenant
CREATE POLICY "profiles_select_admin" ON profiles
  FOR SELECT TO authenticated
  USING (
    EXISTS (
      SELECT 1 FROM memberships
      WHERE profile_id = auth.uid()
        AND role IN ('admin', 'super_admin')
        AND is_active = TRUE
    )
  );

-- UPDATE: solo tu propio perfil
CREATE POLICY "profiles_update_own" ON profiles
  FOR UPDATE TO authenticated
  USING (id = auth.uid())
  WITH CHECK (id = auth.uid());
```

---

### 2.2 tenants

```sql
-- SELECT: solo admins/super_admins ven su tenant
CREATE POLICY "tenants_select_admin" ON tenants
  FOR SELECT TO authenticated
  USING (
    id IN (
      SELECT tenant_id FROM memberships
      WHERE profile_id = auth.uid()
        AND role IN ('admin', 'super_admin')
        AND is_active = TRUE
    )
  );

-- No INSERT/UPDATE/DELETE para authenticated — solo service_role
```

---

### 2.3 coin_wallets

```sql
-- SELECT: ves solo tu propia wallet
CREATE POLICY "coin_wallets_select_own" ON coin_wallets
  FOR SELECT TO authenticated
  USING (
    (owner_type = 'profile' AND owner_id = auth.uid())
    OR
    -- teachers/admins ven wallets de su tenant
    (
      tenant_id IN (
        SELECT tenant_id FROM memberships
        WHERE profile_id = auth.uid()
          AND role IN ('teacher', 'admin', 'super_admin')
          AND is_active = TRUE
      )
    )
  );

-- No INSERT/UPDATE para authenticated — solo service_role maneja balances
```

---

### 2.4 coin_ledger

```sql
-- SELECT: ves transacciones donde tu wallet está involucrada
CREATE POLICY "coin_ledger_select_own" ON coin_ledger
  FOR SELECT TO authenticated
  USING (
    from_wallet_id IN (
      SELECT id FROM coin_wallets
      WHERE owner_type = 'profile' AND owner_id = auth.uid()
    )
    OR
    to_wallet_id IN (
      SELECT id FROM coin_wallets
      WHERE owner_type = 'profile' AND owner_id = auth.uid()
    )
    OR
    -- teachers/admins ven todo el ledger de su tenant
    tenant_id IN (
      SELECT tenant_id FROM memberships
      WHERE profile_id = auth.uid()
        AND role IN ('teacher', 'admin', 'super_admin')
        AND is_active = TRUE
    )
  );

-- No INSERT para authenticated — solo service_role escribe en el ledger
```

---

### 2.5 challenges

```sql
-- SELECT: estudiantes ven challenges activos de su grupo o tenant
CREATE POLICY "challenges_select_student" ON challenges
  FOR SELECT TO authenticated
  USING (
    status = 'active'
    AND tenant_id IN (
      SELECT tenant_id FROM memberships
      WHERE profile_id = auth.uid() AND is_active = TRUE
    )
    AND (
      group_id IS NULL  -- disponible para todo el tenant
      OR
      group_id IN (     -- o del grupo del estudiante
        SELECT g.id FROM groups g
        JOIN memberships m ON m.group_code = g.group_code
          AND m.tenant_id = g.tenant_id
        WHERE m.profile_id = auth.uid() AND m.is_active = TRUE
      )
    )
  );

-- SELECT: teachers/admins ven todos los challenges de su tenant
CREATE POLICY "challenges_select_teacher" ON challenges
  FOR SELECT TO authenticated
  USING (
    tenant_id IN (
      SELECT tenant_id FROM memberships
      WHERE profile_id = auth.uid()
        AND role IN ('teacher', 'admin', 'super_admin')
        AND is_active = TRUE
    )
  );

-- INSERT: solo teachers/admins crean challenges
CREATE POLICY "challenges_insert_teacher" ON challenges
  FOR INSERT TO authenticated
  WITH CHECK (
    tenant_id IN (
      SELECT tenant_id FROM memberships
      WHERE profile_id = auth.uid()
        AND role IN ('teacher', 'admin', 'super_admin')
        AND is_active = TRUE
    )
    AND created_by = auth.uid()
  );
```

---

### 2.6 audit_logs

```sql
-- SELECT: solo teachers y admins
CREATE POLICY "audit_logs_select_staff" ON audit_logs
  FOR SELECT TO authenticated
  USING (
    tenant_id IN (
      SELECT tenant_id FROM memberships
      WHERE profile_id = auth.uid()
        AND role IN ('teacher', 'admin', 'super_admin')
        AND is_active = TRUE
    )
  );

-- No INSERT para authenticated — solo service_role escribe audit logs
```

---

### 2.7 badges (catálogo global)

```sql
-- SELECT: todos los usuarios autenticados ven el catálogo de badges
CREATE POLICY "badges_select_all" ON badges
  FOR SELECT TO authenticated
  USING (
    tenant_id IS NULL  -- badges globales
    OR
    tenant_id IN (
      SELECT tenant_id FROM memberships
      WHERE profile_id = auth.uid() AND is_active = TRUE
    )
  );
```

---

### 2.8 question_bank

```sql
-- SELECT: preguntas globales (tenant_id NULL) o del propio tenant
CREATE POLICY "question_bank_select" ON question_bank
  FOR SELECT TO authenticated
  USING (
    tenant_id IS NULL
    OR
    tenant_id IN (
      SELECT tenant_id FROM memberships
      WHERE profile_id = auth.uid() AND is_active = TRUE
    )
  );
```

---

## 3. Checklist para Windsurf

Crea UN SOLO archivo: `alembic/versions/029_rls_policies.py`

```python
# upgrade() — aplica todas las políticas de este doc en orden:
# 1. Patrón base (tenant_isolation_select + insert) para las 19 tablas de sección 1
# 2. Políticas especiales secciones 2.1 a 2.8
# Usar op.execute() para cada CREATE POLICY

# downgrade() — DROP POLICY IF EXISTS para cada política creada
```

Luego:
- [ ] `poetry run alembic upgrade head` (solo debe correr 029)
- [ ] verificar en Supabase: Table Editor → cualquier tabla → RLS → debe mostrar las políticas
- [ ] commit: `chore(db): add RLS policies migration 029`

## 4. Verificación post-migración

Correr este SQL en Supabase SQL Editor para confirmar:

```sql
SELECT schemaname, tablename, policyname, roles, cmd
FROM pg_policies
WHERE schemaname = 'public'
ORDER BY tablename, policyname;
```

Debe devolver 40+ filas.

---

**Próxima spec:** SPECS/01-auth.md
**Generada por:** Claude Sonnet 4.6
**Implementación:** Windsurf (migración 029)
