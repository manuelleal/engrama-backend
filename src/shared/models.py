"""SQLAlchemy 2.x models — Engrama 2.0 (async).

Una clase por tabla del schema definido en `SPECS/00-database-schema.md`.
Se usa para:
  - alembic autogenerate / target_metadata.
  - ORM async en los services de cada dominio.

Convenciones:
  - UUID        -> postgresql.UUID(as_uuid=True).
  - JSONB       -> postgresql.JSONB.
  - TIMESTAMPTZ -> DateTime(timezone=True).
  - DOUBLE PRECISION -> Float (postgresql.DOUBLE_PRECISION sería equivalente).

NO se añaden relationships para mantener el módulo `shared/` libre
de acoplamiento entre dominios (ver regla de dependencias en WINDSURF.md §2).
Los dominios que necesiten joins los arman en su `service.py`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base declarativa común para todos los modelos del backend."""


# -----------------------------------------------------------------------------
# 001 — tenants
# -----------------------------------------------------------------------------
class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    subscription_plan: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'BASIC'")
    )
    ai_credit_pool: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("10")
    )
    ai_credits_used: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    active_ai_provider: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'claude'")
    )
    coin_pool: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    is_suspended: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("FALSE")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "subscription_plan IN ('BASIC','PRO','PREMIUM','ENTERPRISE')",
            name="tenants_subscription_plan_check",
        ),
        CheckConstraint(
            "active_ai_provider IN ('claude','chatgpt','gemini')",
            name="tenants_active_ai_provider_check",
        ),
    )


# -----------------------------------------------------------------------------
# 002 — profiles
# -----------------------------------------------------------------------------
class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True)
    documento_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    pin_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'student'"))
    current_streak: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    longest_streak: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_attendance_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    xp: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    level: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    account_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("FALSE")
    )
    force_password_reset: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("FALSE")
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('super_admin','admin','teacher','student')",
            name="profiles_role_check",
        ),
        Index("idx_profiles_documento", "documento_id"),
    )


# -----------------------------------------------------------------------------
# 003 — memberships
# -----------------------------------------------------------------------------
class Membership(Base):
    __tablename__ = "memberships"

    id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    profile_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    group_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'student'"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "profile_id", name="memberships_tenant_profile_key"),
        CheckConstraint(
            "role IN ('admin','teacher','student')", name="memberships_role_check"
        ),
        Index("idx_memberships_tenant_profile", "tenant_id", "profile_id"),
        Index("idx_memberships_profile", "profile_id"),
    )


# -----------------------------------------------------------------------------
# 004 — groups
# -----------------------------------------------------------------------------
class Group(Base):
    __tablename__ = "groups"

    id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    group_code: Mapped[str] = mapped_column(Text, nullable=False)
    max_capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_admin_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_admin_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "group_code", name="groups_tenant_code_key"),
    )


# -----------------------------------------------------------------------------
# 005 — teacher_groups
# -----------------------------------------------------------------------------
class TeacherGroup(Base):
    __tablename__ = "teacher_groups"

    id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    teacher_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=False
    )
    group_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), ForeignKey("groups.id"), nullable=False
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("teacher_id", "group_id", name="teacher_groups_teacher_group_key"),
    )


# -----------------------------------------------------------------------------
# 006 — coin_wallets
# -----------------------------------------------------------------------------
class CoinWallet(Base):
    __tablename__ = "coin_wallets"

    id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[Any | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True
    )
    owner_type: Mapped[str] = mapped_column(Text, nullable=False)
    owner_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'COIN'"))
    balance: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    coin_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "owner_type IN ('system','tenant','profile')",
            name="coin_wallets_owner_type_check",
        ),
        CheckConstraint("balance >= 0", name="coin_wallets_balance_nonneg_check"),
        UniqueConstraint(
            "owner_type", "owner_id", "currency", name="coin_wallets_owner_currency_key"
        ),
    )


# -----------------------------------------------------------------------------
# 007 — coin_ledger
# -----------------------------------------------------------------------------
class CoinLedger(Base):
    __tablename__ = "coin_ledger"

    id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    from_wallet_id: Mapped[Any | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("coin_wallets.id"), nullable=True
    )
    to_wallet_id: Mapped[Any | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("coin_wallets.id"), nullable=True
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_profile_id: Mapped[Any | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=True
    )
    ledger_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("amount > 0", name="coin_ledger_amount_pos_check"),
        Index("idx_ledger_tenant", "tenant_id"),
        Index("idx_ledger_from_wallet", "from_wallet_id"),
        Index("idx_ledger_to_wallet", "to_wallet_id"),
        Index("idx_ledger_created_at", "created_at"),
    )


# -----------------------------------------------------------------------------
# 008 — attendance_sessions
# -----------------------------------------------------------------------------
class AttendanceSession(Base):
    __tablename__ = "attendance_sessions"

    id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    group_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), ForeignKey("groups.id"), nullable=False
    )
    session_code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    qr_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    admin_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    admin_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    starts_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('active','expired','cancelled')",
            name="attendance_sessions_status_check",
        ),
    )


# -----------------------------------------------------------------------------
# 009 — attendance
# -----------------------------------------------------------------------------
class Attendance(Base):
    __tablename__ = "attendance"

    id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    session_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), ForeignKey("attendance_sessions.id"), nullable=False
    )
    student_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=False
    )
    attendance_date: Mapped[date] = mapped_column(
        Date, nullable=False, server_default=text("CURRENT_DATE")
    )
    latitude: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    geo_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    coins_awarded: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("session_id", "student_id", name="attendance_session_student_key"),
        Index("idx_attendance_session", "session_id"),
        Index("idx_attendance_student", "student_id"),
        Index("idx_attendance_date", "attendance_date"),
    )


# -----------------------------------------------------------------------------
# 010 — challenges
# -----------------------------------------------------------------------------
class Challenge(Base):
    __tablename__ = "challenges"

    id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    group_id: Mapped[Any | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("groups.id"), nullable=True
    )
    created_by: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    challenge_type: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'multiple_choice'")
    )
    cefr_level: Mapped[str | None] = mapped_column(Text, nullable=True)
    skill: Mapped[str | None] = mapped_column(Text, nullable=True)
    topic: Mapped[str | None] = mapped_column(Text, nullable=True)
    specific_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    coins_reward: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("10")
    )
    xp_reward: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("10"))
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("2")
    )
    max_winners: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("10")
    )
    current_winners: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    question_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "challenge_type IN ('multiple_choice','open','fill_blank','listening')",
            name="challenges_type_check",
        ),
        CheckConstraint(
            "cefr_level IS NULL OR cefr_level IN "
            "('A1','A1+','A2','A2+','B1-','B1','B1+','B2','B2+','C1','C1+')",
            name="challenges_cefr_check",
        ),
        CheckConstraint(
            "status IN ('active','inactive','archived')", name="challenges_status_check"
        ),
    )


# -----------------------------------------------------------------------------
# 011 — challenge_questions
# -----------------------------------------------------------------------------
class ChallengeQuestion(Base):
    __tablename__ = "challenge_questions"

    id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    challenge_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("challenges.id", ondelete="CASCADE"),
        nullable=False,
    )
    question_type: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'multiple_choice'")
    )
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    options_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    correct_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_index: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# -----------------------------------------------------------------------------
# 012 — challenge_attempts
# -----------------------------------------------------------------------------
class ChallengeAttempt(Base):
    __tablename__ = "challenge_attempts"

    id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    challenge_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), ForeignKey("challenges.id"), nullable=False
    )
    student_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'in_progress'")
    )
    current_question_index: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    answers: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    score_percent: Mapped[float] = mapped_column(
        Numeric, nullable=False, server_default=text("0")
    )
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    coins_earned: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    xp_earned: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    streak_bonus: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    weak_skills: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    drako_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('in_progress','completed','abandoned')",
            name="challenge_attempts_status_check",
        ),
        Index("idx_attempts_challenge", "challenge_id"),
        Index("idx_attempts_student", "student_id"),
        Index("idx_attempts_tenant", "tenant_id"),
    )


# -----------------------------------------------------------------------------
# 013 — question_bank
# -----------------------------------------------------------------------------
class QuestionBank(Base):
    __tablename__ = "question_bank"

    id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[Any | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True
    )
    module_type: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'GENERAL'")
    )
    question_text: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("''")
    )
    options_json: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    correct_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    difficulty: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'MEDIUM'")
    )
    cefr_level: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'B1'")
    )
    pillar_type: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'EXAM_PREP'")
    )
    exam_format: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'NONE'")
    )
    technical_domain: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'NONE'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "cefr_level IN ('A1','A1+','A2','A2+','B1-','B1','B1+','B2','B2+','C1','C1+')",
            name="question_bank_cefr_check",
        ),
        CheckConstraint(
            "pillar_type IN ('CONTEXTUAL','EXAM_PREP','TECHNICAL')",
            name="question_bank_pillar_check",
        ),
        CheckConstraint(
            "exam_format IN ('ICFES','IELTS','CAMBRIDGE_PET','TOEFL','NONE')",
            name="question_bank_exam_format_check",
        ),
        CheckConstraint(
            "technical_domain IN ('SOFTWARE','MEDICINE','BUSINESS','NONE')",
            name="question_bank_technical_domain_check",
        ),
    )


# -----------------------------------------------------------------------------
# 014 — student_progress
# -----------------------------------------------------------------------------
class StudentProgress(Base):
    __tablename__ = "student_progress"

    id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    student_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=False
    )
    skill: Mapped[str] = mapped_column(Text, nullable=False)
    cefr_level: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    correct_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    accuracy_percent: Mapped[float] = mapped_column(
        Numeric, nullable=False, server_default=text("0")
    )
    xp_total: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    is_weak: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("FALSE")
    )
    last_practiced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "student_id", "skill", name="student_progress_tenant_student_skill_key"
        ),
        Index("idx_progress_student_skill", "student_id", "skill"),
    )


# -----------------------------------------------------------------------------
# 015 — student_analytics
# -----------------------------------------------------------------------------
class StudentAnalytics(Base):
    __tablename__ = "student_analytics"

    id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    student_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=False
    )
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    time_spent_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    failed_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    success_rate: Mapped[float] = mapped_column(
        Numeric, nullable=False, server_default=text("0.0")
    )
    last_assessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# -----------------------------------------------------------------------------
# 016 — improvement_plans
# -----------------------------------------------------------------------------
class ImprovementPlan(Base):
    __tablename__ = "improvement_plans"

    id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    student_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=False
    )
    teacher_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=False
    )
    focus_topic: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'ASSIGNED'")
    )
    entry_cost_coins: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("5")
    )
    reward_coins: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("50")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('ASSIGNED','IN_PROGRESS','COMPLETED')",
            name="improvement_plans_status_check",
        ),
    )


# -----------------------------------------------------------------------------
# 017 — shop_items
# -----------------------------------------------------------------------------
class ShopItem(Base):
    __tablename__ = "shop_items"

    id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    item_type: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'reward'")
    )
    price_coins: Mapped[int] = mapped_column(Integer, nullable=False)
    stock: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("price_coins >= 0", name="shop_items_price_nonneg_check"),
    )


# -----------------------------------------------------------------------------
# 018 — inventory
# -----------------------------------------------------------------------------
class Inventory(Base):
    __tablename__ = "inventory"

    id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    student_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=False
    )
    item_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shop_items.id"), nullable=False
    )
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'shop'"))
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'available'")
    )
    purchased_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[Any | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "source IN ('shop','auction','reward')", name="inventory_source_check"
        ),
        CheckConstraint(
            "status IN ('available','pending_delivery','delivered','expired','archived')",
            name="inventory_status_check",
        ),
    )


# -----------------------------------------------------------------------------
# 019 — auctions
# -----------------------------------------------------------------------------
class Auction(Base):
    __tablename__ = "auctions"

    id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    group_id: Mapped[Any | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("groups.id"), nullable=True
    )
    item_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    item_type: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'auction'")
    )
    base_price: Mapped[int] = mapped_column(Integer, nullable=False)
    current_bid: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    highest_bidder_id: Mapped[Any | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=True
    )
    highest_bidder_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    winner_id: Mapped[Any | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=True
    )
    stock_quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    duration_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("60")
    )
    start_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('active','ended','cancelled')", name="auctions_status_check"
        ),
    )


# -----------------------------------------------------------------------------
# 020 — auction_bids
# -----------------------------------------------------------------------------
class AuctionBid(Base):
    __tablename__ = "auction_bids"

    id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    auction_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("auctions.id", ondelete="CASCADE"),
        nullable=False,
    )
    bidder_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=False
    )
    bid_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# -----------------------------------------------------------------------------
# 021 — badges
# -----------------------------------------------------------------------------
class Badge(Base):
    __tablename__ = "badges"

    id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[Any | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True
    )
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    icon_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# -----------------------------------------------------------------------------
# 022 — badge_unlocks
# -----------------------------------------------------------------------------
class BadgeUnlock(Base):
    __tablename__ = "badge_unlocks"

    id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    student_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=False
    )
    badge_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), ForeignKey("badges.id"), nullable=False
    )
    unlocked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("student_id", "badge_id", name="badge_unlocks_student_badge_key"),
    )


# -----------------------------------------------------------------------------
# 023 — bets
# -----------------------------------------------------------------------------
class Bet(Base):
    __tablename__ = "bets"

    id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    challenger_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=False
    )
    opponent_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=False
    )
    challenge_id: Mapped[Any | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("challenges.id"), nullable=True
    )
    stake_coins: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    winner_id: Mapped[Any | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint("stake_coins > 0", name="bets_stake_pos_check"),
        CheckConstraint(
            "status IN ('pending','accepted','in_progress','completed','cancelled')",
            name="bets_status_check",
        ),
    )


# -----------------------------------------------------------------------------
# 024 — announcements
# -----------------------------------------------------------------------------
class Announcement(Base):
    __tablename__ = "announcements"

    id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[Any | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    alert_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'info'"))
    target_group: Mapped[str | None] = mapped_column(Text, nullable=True)
    links: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    expiry_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "alert_type IN ('info','warning','success','error')",
            name="announcements_alert_type_check",
        ),
    )


# -----------------------------------------------------------------------------
# 025 — ai_usage_logs
# -----------------------------------------------------------------------------
class AIUsageLog(Base):
    __tablename__ = "ai_usage_logs"

    id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    user_id: Mapped[Any | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=True
    )
    provider: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokens_used: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    credits_charged: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    cefr_level: Mapped[str | None] = mapped_column(Text, nullable=True)
    skill: Mapped[str | None] = mapped_column(Text, nullable=True)
    topic: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# -----------------------------------------------------------------------------
# 026 — audit_logs
# -----------------------------------------------------------------------------
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[Any | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True
    )
    user_id: Mapped[Any | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id"), nullable=True
    )
    action_type: Mapped[str] = mapped_column(Text, nullable=False)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    audit_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    ip_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# -----------------------------------------------------------------------------
# Export explícito (para `from src.shared.models import *`).
# -----------------------------------------------------------------------------
__all__ = [
    "Base",
    "Tenant",
    "Profile",
    "Membership",
    "Group",
    "TeacherGroup",
    "CoinWallet",
    "CoinLedger",
    "AttendanceSession",
    "Attendance",
    "Challenge",
    "ChallengeQuestion",
    "ChallengeAttempt",
    "QuestionBank",
    "StudentProgress",
    "StudentAnalytics",
    "ImprovementPlan",
    "ShopItem",
    "Inventory",
    "Auction",
    "AuctionBid",
    "Badge",
    "BadgeUnlock",
    "Bet",
    "Announcement",
    "AIUsageLog",
    "AuditLog",
]
