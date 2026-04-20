"""extensions: uuid-ossp + pgcrypto

Revision ID: 000_ext
Revises:
Create Date: 2026-04-19

Habilita las extensiones de PostgreSQL necesarias para el schema:
  - uuid-ossp: funciones uuid_generate_v4() (compat).
  - pgcrypto:  funciones gen_random_uuid() usada como DEFAULT de los PKs.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "000_ext"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto";')


def downgrade() -> None:
    # No se hace DROP EXTENSION: otras partes del proyecto Supabase
    # (auth, storage) pueden depender de estas extensiones.
    # Si quisieras forzarlo, usar: DROP EXTENSION IF EXISTS "pgcrypto" CASCADE;
    pass
