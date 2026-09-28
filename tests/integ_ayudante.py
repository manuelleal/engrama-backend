"""`Integ`: acceso a la base de prueba + fábricas de datos sintéticos.

Se separó de `tests/integ_db.py` para bajar su tamaño (espec CI y deudas, C2).
`Integ` hereda `como` de `tests.seguridad.como.ComoMixin` (el ataque con RLS);
el resto de constantes, Docker, base y humo se quedaron en `integ_db.py`, que
importa esta clase dentro de la fixture `integ` para no formar un ciclo
(este módulo, a su vez, importa `guarda_url` de `integ_db` a nivel de módulo).
"""
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from tests.integ_db import guarda_url
from tests.seguridad.como import ComoMixin


class Integ(ComoMixin):
    """Acceso a la base de prueba + fábricas de datos sintéticos.

    Todas las fábricas son síncronas (usan asyncio.run) para que los tests
    puedan mezclar llamadas HTTP con TestClient y consultas a la base sin
    pelear con el event loop de pytest-asyncio.
    """

    def __init__(self, url: str) -> None:
        from sqlalchemy.ext.asyncio import (
            AsyncSession,
            async_sessionmaker,
            create_async_engine,
        )
        from sqlalchemy.pool import NullPool

        guarda_url(url)
        self.url = url
        self.engine = create_async_engine(url, poolclass=NullPool)
        # Mismos parámetros que src/shared/db.py para no cambiar el comportamiento.
        self.Session = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

    # ------------------------------------------------------------ utilidades
    @staticmethod
    def run(coro: Any) -> Any:
        """Corre una corrutina en un loop propio y devuelve su resultado."""
        return asyncio.run(coro)

    @asynccontextmanager
    async def sesion(self):  # type: ignore[no-untyped-def]
        async with self.Session() as db:
            yield db

    async def _get_db_override(self):  # type: ignore[no-untyped-def]
        """Reemplazo de src.shared.db.get_db (misma semántica de rollback)."""
        async with self.Session() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    def valor(self, sql: str, **params: Any) -> Any:
        """Primer valor de la primera fila de una consulta SQL."""
        from sqlalchemy import text

        async def _q() -> Any:
            async with self.Session() as db:
                return (await db.execute(text(sql), params)).scalar()

        return self.run(_q())

    def fila(self, sql: str, **params: Any) -> dict[str, Any] | None:
        """Primera fila como dict (o None)."""
        from sqlalchemy import text

        async def _q() -> dict[str, Any] | None:
            async with self.Session() as db:
                row = (await db.execute(text(sql), params)).mappings().first()
                return dict(row) if row is not None else None

        return self.run(_q())

    def _insertar(self, *objs: Any) -> None:
        async def _ins() -> None:
            async with self.Session() as db:
                for o in objs:
                    db.add(o)
                    await db.flush()
                await db.commit()

        self.run(_ins())

    def truncar_todo(self) -> None:
        """TRUNCATE de todas las tablas del modelo (antes de cada test)."""
        from sqlalchemy import text

        from src.shared.models import Base

        tablas = ", ".join(t.name for t in Base.metadata.sorted_tables)

        async def _t() -> None:
            async with self.engine.begin() as conn:
                await conn.execute(text(f"TRUNCATE {tablas} RESTART IDENTITY CASCADE"))

        self.run(_t())

    # ------------------------------------------------------------ fábricas
    def crear_tenant(self, *, pool: int = 1000) -> UUID:
        """Tenant + su wallet (banco central) con `pool` monedas."""
        from src.shared.models import CoinWallet, Tenant

        tid = uuid4()
        self._insertar(
            Tenant(id=tid, name=f"Colegio {tid.hex[:6]}", slug=f"t-{tid.hex[:12]}",
                   coin_pool=pool),
            CoinWallet(tenant_id=tid, owner_type="tenant", owner_id=tid,
                       currency="COIN", balance=pool),
        )
        return tid

    def crear_perfil(
        self,
        tenant_id: UUID,
        *,
        rol: str = "student",
        group_code: str | None = None,
        racha: int = 0,
        ultima_asistencia: date | None = None,
        saldo: int | None = None,
    ) -> UUID:
        """Perfil + membership activa en el tenant. `saldo` crea su wallet."""
        from src.shared.models import CoinWallet, Membership, Profile

        pid = uuid4()
        objs: list[Any] = [
            Profile(
                id=pid,
                documento_id=f"doc-{pid.hex[:12]}",
                full_name=f"Persona {pid.hex[:6]}",
                pin_hash="sintetico",
                role=rol,
                current_streak=racha,
                longest_streak=racha,
                last_attendance_date=ultima_asistencia,
            ),
            Membership(tenant_id=tenant_id, profile_id=pid, role=rol,
                       group_code=group_code, is_active=True),
        ]
        if saldo is not None:
            objs.append(CoinWallet(tenant_id=tenant_id, owner_type="profile",
                                   owner_id=pid, currency="COIN", balance=saldo))
        self._insertar(*objs)
        return pid

    def afiliar(
        self,
        perfil: UUID,
        tenant_id: UUID,
        rol: str = "teacher",
        *,
        group_code: str | None = None,
    ) -> None:
        """Agrega una membership MÁS a un perfil ya existente, en otro tenant.

        Para el actor DM de docs/ESPEC_grupos_y_panel_docente.md §3: un docente
        con membresía también en un segundo colegio. `Membership` solo exige
        UNIQUE (tenant_id, profile_id) — nada impide una fila por tenant.
        """
        from src.shared.models import Membership

        self._insertar(
            Membership(tenant_id=tenant_id, profile_id=perfil, role=rol,
                       group_code=group_code, is_active=True)
        )

    def crear_grupo(
        self,
        tenant_id: UUID,
        codigo: str,
        *,
        lat: float | None = None,
        lng: float | None = None,
    ) -> UUID:
        from src.shared.models import Group

        gid = uuid4()
        self._insertar(Group(id=gid, tenant_id=tenant_id, group_code=codigo,
                             last_admin_lat=lat, last_admin_lng=lng))
        return gid

    def crear_sesion_asistencia(
        self,
        tenant_id: UUID,
        group_id: UUID,
        creador_id: UUID,
        *,
        expira_en: timedelta = timedelta(minutes=15),
        lat: float | None = None,
        lng: float | None = None,
    ) -> str:
        """Sesión QR 'active'. `expira_en` negativo = ya expirada. Devuelve el código."""
        from src.engrama_core.service.attendance import generate_session_code
        from src.shared.models import AttendanceSession

        ahora = datetime.now(UTC)
        codigo = generate_session_code()
        self._insertar(
            AttendanceSession(
                tenant_id=tenant_id,
                group_id=group_id,
                session_code=codigo,
                qr_payload={"session_code": codigo},
                admin_lat=lat,
                admin_lng=lng,
                starts_at=ahora - timedelta(hours=1),
                expires_at=ahora + expira_en,
                created_by=creador_id,
                status="active",
            )
        )
        return codigo

    def crear_challenge(
        self,
        tenant_id: UUID,
        creador_id: UUID,
        *,
        respuestas: tuple[str, ...] = ("A", "B"),
        coins: int = 20,
        xp: int = 15,
        max_attempts: int = 2,
        max_winners: int = 10,
        current_winners: int = 0,
        group_id: UUID | None = None,
        status: str = "active",
        tipo: str = "multiple_choice",
        titulo: str | None = None,
        skill: str | None = None,
        cefr_level: str | None = None,
    ) -> tuple[UUID, list[UUID]]:
        """Challenge + una pregunta por respuesta correcta. Devuelve (id, [ids preguntas]).

        `skill` y `cefr_level` son opcionales (ERR-16, §4): sin ellos el
        challenge nace igual que antes de esta espec (ambos NULL).
        """
        from src.shared.models import Challenge, ChallengeQuestion

        cid = uuid4()
        qids = [uuid4() for _ in respuestas]
        objs: list[Any] = [
            Challenge(
                id=cid, tenant_id=tenant_id, group_id=group_id, created_by=creador_id,
                title=titulo or f"Reto {cid.hex[:6]}", description="sintético",
                challenge_type=tipo, coins_reward=coins, xp_reward=xp,
                max_attempts=max_attempts, max_winners=max_winners,
                current_winners=current_winners, status=status,
                skill=skill, cefr_level=cefr_level,
            )
        ]
        for i, (qid, resp) in enumerate(zip(qids, respuestas, strict=True), start=1):
            objs.append(
                ChallengeQuestion(
                    id=qid, challenge_id=cid, question_type=tipo,
                    question_text=f"Pregunta {i}",
                    # Opciones fijas que NO contienen la respuesta: así un test
                    # puede buscar el valor de correct_answer en el JSON sin
                    # confundirlo con el texto de una opción.
                    options_json=[{"label": "A", "value": "opcion uno"},
                                  {"label": "B", "value": "opcion dos"}],
                    correct_answer=resp, order_index=i,
                )
            )
        self._insertar(*objs)
        return cid, qids

    def crear_intento(
        self,
        tenant_id: UUID,
        challenge_id: UUID,
        alumno_id: UUID,
        *,
        status: str = "completed",
        answers: list[Any] | None = None,
        completed_at: datetime | None = None,
    ) -> UUID:
        """Intento ya registrado (por defecto 'completed', sin premio).

        `answers` y `completed_at` son opcionales (ERR-16, §4, para T5/T7):
        sin ellos, `answers=[]` y `completed_at=now()` — idéntico a antes.
        """
        from src.shared.models import ChallengeAttempt

        aid = uuid4()
        resuelto_completed_at = completed_at
        if resuelto_completed_at is None and status == "completed":
            resuelto_completed_at = datetime.now(UTC)
        self._insertar(
            ChallengeAttempt(
                id=aid, tenant_id=tenant_id, challenge_id=challenge_id,
                student_id=alumno_id, status=status, score_percent=0,
                is_correct=False if status == "completed" else None,
                answers=answers if answers is not None else [],
                completed_at=resuelto_completed_at,
            )
        )
        return aid

    @staticmethod
    def headers(profile_id: UUID) -> dict[str, str]:
        """Authorization: Bearer <JWT HS256 firmado con el secreto de pruebas>."""
        from jose import jwt

        from tests.conftest import TEST_JWT_SECRET

        ahora = int(time.time())
        token = jwt.encode(
            {
                "sub": str(profile_id),
                "email": f"{str(profile_id)[:8]}@engrama.test",
                "aud": "authenticated",
                "iat": ahora,
                "exp": ahora + 3600,
                "role": "authenticated",
            },
            TEST_JWT_SECRET,
            algorithm="HS256",
        )
        return {"Authorization": f"Bearer {token}"}

    # ------------------------------------------------------------ lecturas comunes
    def saldo(self, owner_type: str, owner_id: UUID) -> int | None:
        """Balance de la wallet (None si no existe)."""
        v = self.valor(
            "select balance from coin_wallets "
            "where owner_type = :t and owner_id = :o and currency = 'COIN'",
            t=owner_type, o=owner_id,
        )
        return None if v is None else int(v)
