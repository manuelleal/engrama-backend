"""Configuración global de la aplicación — carga desde .env.

Usa pydantic-settings para tipar y validar las variables de entorno.
Se expone una sola instancia singleton `settings` que los demás módulos
importan:

    from src.shared.config import settings
    secret = settings.supabase_jwt_secret

Diseño:
  - Solo cargamos variables realmente usadas por el backend; si falta
    una obligatoria, la app falla al arranque con un error claro.
  - `DATABASE_URL` se normaliza a `postgresql+asyncpg://` igual que en
    `alembic/env.py`, para aceptar tanto el formato canónico de Supabase
    (`postgresql://...`) como el formato async explícito.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración runtime del backend Engrama 2.0."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # ignora variables del .env que no usemos aquí
        case_sensitive=False,
    )

    # --- App ---
    app_env: str = Field(default="development", description="development | production")
    app_debug: bool = Field(default=True)
    app_port: int = Field(default=8000)

    # --- Supabase ---
    supabase_url: str = Field(default="", description="URL del proyecto Supabase")
    supabase_jwt_secret: str = Field(
        ..., description="Secreto HS256 para validar JWTs emitidos por Supabase Auth"
    )
    supabase_service_role_key: str = Field(default="")
    supabase_anon_key: str = Field(default="")
    # GoTrue, para `POST /auth/contrasena` (ESPEC_login_piloto §1.5). Vacía:
    # se usa `supabase_url + "/auth/v1"`. En el piloto: http://gotrue:9999.
    # Para cambiar la contraseña NO se usa la clave de servicio: se usa el
    # mismo Bearer del usuario. La clave de servicio la usa UN solo módulo,
    # `src/registro/cuentas.py` (ESPEC_autorregistro §1.9); sin ella,
    # `POST /auth/registro` responde 503 y lo demás funciona igual.
    gotrue_url: str = Field(default="")
    # Cuántos proxies PROPIOS hay delante del backend (Caddy = 1). Con 0 no se
    # lee `X-Forwarded-For`; con n, la IP del visitante es el valor n-ésimo
    # desde el final (ESPEC_autorregistro §1.6). La usa el límite de intentos.
    proxies_de_confianza: int = Field(default=0, ge=0, le=5)
    # H-13: versiones del aviso de datos que se aceptan, separadas por comas
    # (p. ej. "2026-10-v1"). Vacía = sin restricción (desarrollo). En el
    # despliegue debe contener el AVISO_VERSION del cliente: si no, nadie
    # puede aceptar el aviso.
    aviso_versiones_validas: str = Field(default="")
    # Secretos HMAC de la puerta de eventos del anillo, UNO POR ORIGEN
    # (ESPEC_eventos_anillo §1.2): EVA firma como `live` y SET como `set`. 32
    # caracteres o más, al azar. Vacío = ese origen está apagado (401). No son
    # el secreto JWT ni la clave de servicio. Si están puestos y son cortos,
    # iguales entre sí o iguales al secreto JWT, el servicio NO arranca
    # (`exigir_secretos_de_eventos`, más abajo).
    events_secret_live: str = Field(default="")
    events_secret_set: str = Field(default="")
    # El generador viejo de retos con IA (`POST /challenges/generate`) nace
    # APAGADO (ESPEC_generador_apagado; decisión 012, D6): no revisa créditos
    # ni calidad. Apagado responde 503 `generador_apagado` sin llamar a la IA.
    challenges_generate_enabled: bool = Field(default=False)
    # El día de calendario de la institución: UTC + estas horas (Colombia = -5).
    # Lo usa el foco del grupo, que va por días y no por instantes
    # (ESPEC_foco_grupo §1.2). Una sola para toda la instalación.
    engrama_utc_offset_hours: int = Field(default=-5, ge=-12, le=14)
    # La regla de "superado" de la cola de refuerzo (ESPEC_refuerzo §1.4). LOS
    # FIJA EL PEDAGOGO (ERR-16): estos valores son la propuesta de la decisión
    # 012 §6, no una decisión. Cuántos aciertos en formas no vistas hacen falta
    # para pasar al repaso, y a cuántos días va el repaso.
    refuerzo_aciertos_para_repaso: int = Field(default=1, ge=1, le=5)
    refuerzo_dias_repaso: int = Field(default=7, ge=1, le=60)
    # Cuántas entradas de la cola se sirven a la vez.
    refuerzo_max_por_vez: int = Field(default=5, ge=1, le=20)

    # La asistencia (ESPEC_economia_oleada0 §1.1 y §5). TODOS ESTOS NÚMEROS SON
    # PROVISIONALES del arquitecto y Christiam puede vetarlos: por eso viven aquí
    # y no enterrados en el código. Se paga `base` por asistir y `puntualidad`
    # más si el check-in ocurre a `minutos_puntualidad` minutos o menos de que
    # el profe abrió la sesión. La racha ya no multiplica nada.
    asistencia_monedas_base: int = Field(default=5, ge=0, le=50)
    asistencia_monedas_puntualidad: int = Field(default=5, ge=0, le=50)
    asistencia_minutos_puntualidad: int = Field(default=5, ge=0, le=60)
    # Lo máximo que puede valer un reto (ESPEC_economia_oleada0 §1.4): el reto
    # individual vale 10 y el tope de una sesión en vivo de EVA es 20; con el
    # tope en 20 ningún reto individual paga más que una sesión entera de EVA.
    # Provisional; se valida al crear y se aplica al pagar y al mostrar.
    reto_monedas_tope: int = Field(default=20, ge=1, le=1000)
    # Cuántos pueden cobrar un reto cuando quien lo crea no indica `max_winners`
    # (ESPEC_economia_oleada0 §1.5): tantos como estudiantes activos tenga el
    # grupo, pero NUNCA menos que este piso. El piso existe porque un grupo se
    # siembra a veces vacío (los estudiantes entran después por el autorregistro)
    # y el tamaño daría 0 o 1: volvería la carrera por cupo. Ponerlo en 1 lo veta.
    reto_ganadores_piso: int = Field(default=40, ge=1, le=10000)
    # Lo máximo que el operador puede recargar a la bolsa de una institución en
    # UNA orden (ESPEC_economia_oleada0 §1.6). Es un freno contra el dedazo (un
    # cero de más), no un límite de negocio: provisional. OJO: la orden
    # `python -m src.onboarding recargar` no carga esta clase (la CLI no
    # necesita el secreto JWT); lee la MISMA variable del entorno en
    # `src/onboarding/recarga.py`, y un test (UE7) exige que los dos defectos
    # coincidan.
    bolsa_recarga_maxima: int = Field(default=1_000_000, ge=1, le=100_000_000)
    # La alerta de bolsa baja (ESPEC_economia_oleada0 §1.7): la bolsa está "en
    # alerta" cuando su saldo queda por DEBAJO de este porcentaje de lo emitido
    # (`tenants.coin_pool`). Al cruzarlo, `award_coins` escribe una línea WARNING
    # `bolsa_baja` en el logger `engrama.economia`; NUNCA bloquea una paga. Con 0
    # la alerta queda apagada. Provisional. Igual que la de arriba, la orden
    # `python -m src.onboarding bolsa` lee la misma variable del entorno (UE5
    # exige que los dos defectos coincidan).
    bolsa_umbral_alerta_pct: int = Field(default=10, ge=0, le=100)

    # --- Database ---
    database_url: str = Field(
        ..., description="DSN Postgres; se normaliza a postgresql+asyncpg:// internamente"
    )

    # --- Redis / Celery (no usado todavía, pero declarado) ---
    redis_url: str = Field(default="redis://redis:6379/0")

    # --- External APIs (opcional en dev) ---
    anthropic_api_key: str = Field(default="")
    stripe_secret_key: str = Field(default="")
    stripe_webhook_secret: str = Field(default="")

    # ---------------------------------------------------------------- helpers
    @field_validator("database_url")
    @classmethod
    def _normalize_async_scheme(cls, value: str) -> str:
        """Garantiza que SQLAlchemy use el driver asyncpg."""
        if value.startswith("postgresql+asyncpg://"):
            return value
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        return value


# El mínimo de un secreto de eventos. Es el mismo número que `events.SECRETO_MINIMO`
# (un test, UE3, exige que coincidan): aquí no se importa `events` para que la
# configuración no dependa de ningún otro módulo.
EVENTS_SECRET_MINIMO = 32


class ConfiguracionInvalida(RuntimeError):
    """La configuración no deja arrancar. El mensaje NUNCA lleva el valor de un secreto."""


def problemas_de_secretos(live: str, set_: str, jwt: str) -> list[str]:
    """Por qué los secretos de eventos no sirven; lista vacía si están bien.

    Auditoría 03, S-11 (ESPEC_eventos_anillo §12). Un secreto VACÍO no es un
    problema: significa "ese origen apagado" (401). Pero si está puesto debe:
      - medir 32 o más: uno corto dejaba el origen apagado EN SILENCIO;
      - ser distinto del otro: el origen no va dentro de lo firmado, así que
        con un secreto compartido un lote de SET valdría como si fuera de EVA;
      - ser distinto del secreto JWT: cada secreto abre una sola puerta.
    Los mensajes nombran la variable y el motivo; nunca el valor ni su largo.
    """
    puestos = {"EVENTS_SECRET_LIVE": live, "EVENTS_SECRET_SET": set_}
    problemas = [f"{nombre} mide menos de {EVENTS_SECRET_MINIMO} caracteres"
                 for nombre, valor in puestos.items()
                 if valor and len(valor) < EVENTS_SECRET_MINIMO]
    if live and live == set_:
        problemas.append("EVENTS_SECRET_LIVE y EVENTS_SECRET_SET son iguales")
    problemas += [f"{nombre} es igual a SUPABASE_JWT_SECRET"
                  for nombre, valor in puestos.items() if valor and valor == jwt]
    return problemas


def exigir_secretos_de_eventos(config: Settings) -> None:
    """Si un secreto de eventos está puesto y no sirve, el servicio NO arranca.

    No es un validador de pydantic a propósito: su error imprime los valores
    de entrada, y aquí los valores son secretos.
    """
    problemas = problemas_de_secretos(config.events_secret_live, config.events_secret_set,
                                      config.supabase_jwt_secret)
    if problemas:
        raise ConfiguracionInvalida(
            "Secretos de eventos inválidos: " + "; ".join(problemas)
            + ". Genera secretos nuevos (32 o más, al azar, distintos entre sí) o deja "
              "vacía la variable para apagar ese origen.")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton cacheado. Se usa tanto en deps FastAPI como en tests.

    Corre al importar la aplicación: si la configuración no sirve, uvicorn
    termina con el error antes de escuchar.
    """
    config = Settings()  # type: ignore[call-arg]
    exigir_secretos_de_eventos(config)
    return config


# Exportamos una instancia lista para usar en imports directos.
# En tests, se puede invalidar con `get_settings.cache_clear()`.
settings = get_settings()
