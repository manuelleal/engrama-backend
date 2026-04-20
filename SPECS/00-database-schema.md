# SPECS/00-database-schema.md — Engrama 2.0 Database Schema
# Estado: APROBADO | Fecha: 2026-04-19
# Para: Windsurf/Claude Code — genera migraciones Alembic
# NO tocar Lingo Coins DB

## 0. Principios
1. Todo en inglés
2. tenant_id UUID NOT NULL en toda tabla transaccional
3. Todo FK a profiles.id (UUID)
4. Un sistema de monedas: coin_wallets + coin_ledger
5. Una tabla de intentos: challenge_attempts
6. RLS habilitado en toda tabla
7. Tablas descartadas: coin_backfill_runs, feedback_messages, system_configs, credit_transactions, institution_credit_history

## 1. Orden de migraciones

001 tenants
002 profiles
003 memberships
004 groups
005 teacher_groups
006 coin_wallets
007 coin_ledger
008 attendance_sessions
009 attendance
010 challenges
011 challenge_questions
012 challenge_attempts
013 question_bank
014 student_progress
015 student_analytics
016 improvement_plans
017 shop_items
018 inventory
019 auctions
020 auction_bids
021 badges
022 badge_unlocks
023 bets
024 announcements
025 ai_usage_logs
026 audit_logs

## 2. DDL

-- 001
CREATE TABLE tenants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  slug TEXT NOT NULL UNIQUE,
  subscription_plan TEXT NOT NULL DEFAULT 'BASIC' CHECK (subscription_plan IN ('BASIC','PRO','PREMIUM','ENTERPRISE')),
  ai_credit_pool INTEGER NOT NULL DEFAULT 10,
  ai_credits_used INTEGER NOT NULL DEFAULT 0,
  active_ai_provider TEXT NOT NULL DEFAULT 'claude' CHECK (active_ai_provider IN ('claude','chatgpt','gemini')),
  coin_pool INTEGER NOT NULL DEFAULT 0,
  is_suspended BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 002
CREATE TABLE profiles (
  id UUID PRIMARY KEY,
  documento_id TEXT NOT NULL UNIQUE,
  full_name TEXT NOT NULL,
  pin_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'student' CHECK (role IN ('super_admin','admin','teacher','student')),
  current_streak INTEGER NOT NULL DEFAULT 0,
  longest_streak INTEGER NOT NULL DEFAULT 0,
  last_attendance_date DATE,
  xp INTEGER NOT NULL DEFAULT 0,
  level INTEGER NOT NULL DEFAULT 1,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  account_locked BOOLEAN NOT NULL DEFAULT FALSE,
  force_password_reset BOOLEAN NOT NULL DEFAULT FALSE,
  last_login_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 003
CREATE TABLE memberships (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  profile_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  group_code TEXT,
  role TEXT NOT NULL DEFAULT 'student' CHECK (role IN ('admin','teacher','student')),
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, profile_id)
);

-- 004
CREATE TABLE groups (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  group_code TEXT NOT NULL,
  max_capacity INTEGER,
  last_admin_lat DOUBLE PRECISION,
  last_admin_lng DOUBLE PRECISION,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, group_code)
);

-- 005
CREATE TABLE teacher_groups (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  teacher_id UUID NOT NULL REFERENCES profiles(id),
  group_id UUID NOT NULL REFERENCES groups(id),
  assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (teacher_id, group_id)
);

-- 006
CREATE TABLE coin_wallets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id),
  owner_type TEXT NOT NULL CHECK (owner_type IN ('system','tenant','profile')),
  owner_id UUID NOT NULL,
  currency TEXT NOT NULL DEFAULT 'COIN',
  balance BIGINT NOT NULL DEFAULT 0 CHECK (balance >= 0),
  metadata JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (owner_type, owner_id, currency)
);

-- 007
CREATE TABLE coin_ledger (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  from_wallet_id UUID REFERENCES coin_wallets(id),
  to_wallet_id UUID REFERENCES coin_wallets(id),
  amount BIGINT NOT NULL CHECK (amount > 0),
  action TEXT NOT NULL,
  created_by_profile_id UUID REFERENCES profiles(id),
  metadata JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 008
CREATE TABLE attendance_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  group_id UUID NOT NULL REFERENCES groups(id),
  session_code TEXT NOT NULL UNIQUE,
  qr_payload JSONB,
  admin_lat DOUBLE PRECISION,
  admin_lng DOUBLE PRECISION,
  starts_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL,
  created_by UUID NOT NULL REFERENCES profiles(id),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','expired','cancelled')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 009
CREATE TABLE attendance (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  session_id UUID NOT NULL REFERENCES attendance_sessions(id),
  student_id UUID NOT NULL REFERENCES profiles(id),
  attendance_date DATE NOT NULL DEFAULT CURRENT_DATE,
  latitude NUMERIC,
  longitude NUMERIC,
  geo_status TEXT,
  coins_awarded INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (session_id, student_id)
);

-- 010
CREATE TABLE challenges (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  group_id UUID REFERENCES groups(id),
  created_by UUID NOT NULL REFERENCES profiles(id),
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  challenge_type TEXT NOT NULL DEFAULT 'multiple_choice' CHECK (challenge_type IN ('multiple_choice','open','fill_blank','listening')),
  cefr_level TEXT CHECK (cefr_level IN ('A1','A1+','A2','A2+','B1-','B1','B1+','B2','B2+','C1','C1+')),
  skill TEXT,
  topic TEXT,
  specific_instructions TEXT,
  coins_reward INTEGER NOT NULL DEFAULT 10,
  xp_reward INTEGER NOT NULL DEFAULT 10,
  max_attempts INTEGER NOT NULL DEFAULT 2,
  max_winners INTEGER NOT NULL DEFAULT 10,
  current_winners INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','inactive','archived')),
  question_payload JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 011
CREATE TABLE challenge_questions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  challenge_id UUID NOT NULL REFERENCES challenges(id) ON DELETE CASCADE,
  question_type TEXT NOT NULL DEFAULT 'multiple_choice',
  question_text TEXT NOT NULL,
  options_json JSONB,
  correct_answer TEXT,
  order_index INTEGER NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 012
CREATE TABLE challenge_attempts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  challenge_id UUID NOT NULL REFERENCES challenges(id),
  student_id UUID NOT NULL REFERENCES profiles(id),
  status TEXT NOT NULL DEFAULT 'in_progress' CHECK (status IN ('in_progress','completed','abandoned')),
  current_question_index INTEGER NOT NULL DEFAULT 0,
  answers JSONB NOT NULL DEFAULT '[]',
  score_percent NUMERIC NOT NULL DEFAULT 0,
  is_correct BOOLEAN,
  coins_earned INTEGER NOT NULL DEFAULT 0,
  xp_earned INTEGER NOT NULL DEFAULT 0,
  streak_bonus INTEGER NOT NULL DEFAULT 0,
  weak_skills JSONB NOT NULL DEFAULT '[]',
  drako_feedback TEXT,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 013
CREATE TABLE question_bank (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id),
  module_type TEXT NOT NULL DEFAULT 'GENERAL',
  question_text TEXT NOT NULL DEFAULT '',
  options_json JSONB NOT NULL DEFAULT '[]',
  correct_answer TEXT,
  difficulty TEXT NOT NULL DEFAULT 'MEDIUM',
  cefr_level TEXT NOT NULL DEFAULT 'B1' CHECK (cefr_level IN ('A1','A1+','A2','A2+','B1-','B1','B1+','B2','B2+','C1','C1+')),
  pillar_type TEXT NOT NULL DEFAULT 'EXAM_PREP' CHECK (pillar_type IN ('CONTEXTUAL','EXAM_PREP','TECHNICAL')),
  exam_format TEXT NOT NULL DEFAULT 'NONE' CHECK (exam_format IN ('ICFES','IELTS','CAMBRIDGE_PET','TOEFL','NONE')),
  technical_domain TEXT NOT NULL DEFAULT 'NONE' CHECK (technical_domain IN ('SOFTWARE','MEDICINE','BUSINESS','NONE')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 014
CREATE TABLE student_progress (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  student_id UUID NOT NULL REFERENCES profiles(id),
  skill TEXT NOT NULL,
  cefr_level TEXT,
  total_attempts INTEGER NOT NULL DEFAULT 0,
  correct_attempts INTEGER NOT NULL DEFAULT 0,
  accuracy_percent NUMERIC NOT NULL DEFAULT 0,
  xp_total INTEGER NOT NULL DEFAULT 0,
  is_weak BOOLEAN NOT NULL DEFAULT FALSE,
  last_practiced_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, student_id, skill)
);

-- 015
CREATE TABLE student_analytics (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  student_id UUID NOT NULL REFERENCES profiles(id),
  topic TEXT NOT NULL,
  time_spent_seconds INTEGER NOT NULL DEFAULT 0,
  failed_attempts INTEGER NOT NULL DEFAULT 0,
  success_rate NUMERIC NOT NULL DEFAULT 0.0,
  last_assessed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 016
CREATE TABLE improvement_plans (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  student_id UUID NOT NULL REFERENCES profiles(id),
  teacher_id UUID NOT NULL REFERENCES profiles(id),
  focus_topic TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'ASSIGNED' CHECK (status IN ('ASSIGNED','IN_PROGRESS','COMPLETED')),
  entry_cost_coins INTEGER NOT NULL DEFAULT 5,
  reward_coins INTEGER NOT NULL DEFAULT 50,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ
);

-- 017
CREATE TABLE shop_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  name TEXT NOT NULL,
  description TEXT,
  item_type TEXT NOT NULL DEFAULT 'reward',
  price_coins INTEGER NOT NULL CHECK (price_coins >= 0),
  stock INTEGER,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 018
CREATE TABLE inventory (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  student_id UUID NOT NULL REFERENCES profiles(id),
  item_id UUID NOT NULL REFERENCES shop_items(id),
  source TEXT NOT NULL DEFAULT 'shop' CHECK (source IN ('shop','auction','reward')),
  status TEXT NOT NULL DEFAULT 'available' CHECK (status IN ('available','pending_delivery','delivered','expired','archived')),
  purchased_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  activated_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ,
  resolved_by UUID REFERENCES profiles(id),
  resolved_at TIMESTAMPTZ
);

-- 019
CREATE TABLE auctions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  group_id UUID REFERENCES groups(id),
  item_name TEXT NOT NULL,
  description TEXT,
  item_type TEXT NOT NULL DEFAULT 'auction',
  base_price INTEGER NOT NULL,
  current_bid INTEGER NOT NULL DEFAULT 0,
  highest_bidder_id UUID REFERENCES profiles(id),
  highest_bidder_name TEXT,
  winner_id UUID REFERENCES profiles(id),
  stock_quantity INTEGER NOT NULL DEFAULT 1,
  duration_seconds INTEGER NOT NULL DEFAULT 60,
  start_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','ended','cancelled')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 020
CREATE TABLE auction_bids (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  auction_id UUID NOT NULL REFERENCES auctions(id) ON DELETE CASCADE,
  bidder_id UUID NOT NULL REFERENCES profiles(id),
  bid_amount INTEGER NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 021
CREATE TABLE badges (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id),
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  description TEXT NOT NULL,
  icon_url TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 022
CREATE TABLE badge_unlocks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  student_id UUID NOT NULL REFERENCES profiles(id),
  badge_id UUID NOT NULL REFERENCES badges(id),
  unlocked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (student_id, badge_id)
);

-- 023
CREATE TABLE bets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  challenger_id UUID NOT NULL REFERENCES profiles(id),
  opponent_id UUID NOT NULL REFERENCES profiles(id),
  challenge_id UUID REFERENCES challenges(id),
  stake_coins INTEGER NOT NULL CHECK (stake_coins > 0),
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','accepted','in_progress','completed','cancelled')),
  winner_id UUID REFERENCES profiles(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at TIMESTAMPTZ
);

-- 024
CREATE TABLE announcements (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id),
  title TEXT,
  message TEXT NOT NULL,
  alert_type TEXT NOT NULL DEFAULT 'info' CHECK (alert_type IN ('info','warning','success','error')),
  target_group TEXT,
  links JSONB,
  expiry_date DATE NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 025
CREATE TABLE ai_usage_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  user_id UUID REFERENCES profiles(id),
  provider TEXT,
  model TEXT,
  tokens_used INTEGER NOT NULL DEFAULT 0,
  credits_charged INTEGER NOT NULL DEFAULT 0,
  cefr_level TEXT,
  skill TEXT,
  topic TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 026
CREATE TABLE audit_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID REFERENCES tenants(id),
  user_id UUID REFERENCES profiles(id),
  action_type TEXT NOT NULL,
  result TEXT,
  metadata JSONB NOT NULL DEFAULT '{}',
  ip_address TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

## 3. Índices

CREATE INDEX idx_memberships_tenant_profile ON memberships(tenant_id, profile_id);
CREATE INDEX idx_memberships_profile ON memberships(profile_id);
CREATE INDEX idx_attendance_session ON attendance(session_id);
CREATE INDEX idx_attendance_student ON attendance(student_id);
CREATE INDEX idx_attendance_date ON attendance(attendance_date);
CREATE INDEX idx_attempts_challenge ON challenge_attempts(challenge_id);
CREATE INDEX idx_attempts_student ON challenge_attempts(student_id);
CREATE INDEX idx_attempts_tenant ON challenge_attempts(tenant_id);
CREATE INDEX idx_ledger_tenant ON coin_ledger(tenant_id);
CREATE INDEX idx_ledger_from_wallet ON coin_ledger(from_wallet_id);
CREATE INDEX idx_ledger_to_wallet ON coin_ledger(to_wallet_id);
CREATE INDEX idx_ledger_created_at ON coin_ledger(created_at);
CREATE INDEX idx_profiles_documento ON profiles(documento_id);
CREATE INDEX idx_progress_student_skill ON student_progress(student_id, skill);

## 4. RLS

-- Patrón base para toda tabla con tenant_id:
ALTER TABLE <tabla> ENABLE ROW LEVEL SECURITY;
CREATE POLICY "tenant_isolation" ON <tabla>
  USING (
    tenant_id IN (
      SELECT tenant_id FROM memberships
      WHERE profile_id = auth.uid() AND is_active = TRUE
    )
  );

-- Tablas con política especial: profiles, coin_wallets, coin_ledger,
-- challenges, audit_logs, tenants → ver SPECS/00b-rls-policies.md

## 5. Notas Alembic

- async sessions (asyncpg)
- UUID: sqlalchemy.dialects.postgresql.UUID con as_uuid=True
- JSONB: sqlalchemy.dialects.postgresql.JSONB
- Primera migración (000): CREATE EXTENSION IF NOT EXISTS "uuid-ossp"; CREATE EXTENSION IF NOT EXISTS "pgcrypto";
- Convención: 001_create_tenants, 002_create_profiles, etc.

## 6. Checklist Windsurf

- [ ] 000_extensions
- [ ] 001-026 migraciones
- [ ] 027_indexes
- [ ] 028_enable_rls
- [ ] src/shared/models.py (modelos SQLAlchemy)
- [ ] alembic upgrade head sin errores
- [ ] alembic downgrade base sin errores
- [ ] commit: chore(db): initial schema migrations
