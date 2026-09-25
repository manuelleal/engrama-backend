# ESPEC · CI y deudas del arnés (F4)

Rama `test/fixture-integ`, base `f1fef55`. Cinco commits, uno por cambio; cada uno exige el anterior en verde.

## 0. Medido hoy
Con `.venv`: Python 3.14.2, ruff 0.6.9, mypy 1.11.2 y pytest 9.0.3.

- **pytest:** 128 passed / 14 xfailed / 0 failed (142 ids); sin integ, 74 passed.
- **ruff:** 1 error, F401 en `src/shared/models.py:35`.
- **`mypy .`:** 4 errores en 3 archivos.
  - Tres son de jose: `src/auth/service.py:23`, `tests/auth/conftest.py:8` y `tests/integ_db.py:582`.
  - Uno es de asyncpg: `tests/integ_db.py:163`.
  - mypy 1.20.1 da los mismos 4; con `types-python-jose`, 1.
- **`tests/integ_db.py`:** 729 líneas.

**Desfase:** `.venv` no sale de `poetry.lock`. El lock trae mypy 1.20.1, pytest 8.4.2 y pytest-asyncio 0.24.0: es lo que instala el CI.

**Paso 0, sin commit:** con Python 3.12 y `poetry install --with dev`, volver a medir. Si no da 128/14 y 4 errores, se detiene todo y es candidato a ERR.

## C1 · Lint y tipos a 0
- Quitar `String` del import. Es el único cambio en `src/`.
- `poetry add --group dev types-python-jose`. El lock solo debe sumar ese paquete, `types-pyasn1` y el hash.
- `# type: ignore[import-untyped]` en `tests/integ_db.py:163`, porque asyncpg no publica tipos.
- **Pasa:** `poetry run ruff check .` da `All checks passed!`, `poetry run mypy .` da `Success` y pytest sigue en 128/14.
- **Rojo:** revertir cualquiera de los tres cambios devuelve su error.

## C2 · Partir `tests/integ_db.py` sin cambiar el comportamiento
Mover solo `como` deja unas 630 líneas, y el máximo es 400. Se parte en tres archivos:
- `tests/integ_db.py` (~340): constantes, Docker, base, humo y fixtures.
- `tests/integ_ayudante.py` (~250): la clase `Integ`.
- `tests/seguridad/como.py` (~120): `ROLES_COMO`, `Resultado`, `_sqlstate` y un mixin con `como`, que `Integ` hereda.

Solo cambian los imports de `veredictos.py` y `modulos.py`; `integ_db` importa `Integ` dentro de la fixture (sin ciclo).

**Identidad:** antes y después se guarda la salida de este comando:

`pytest -q -rA -p no:cacheprovider | grep -E "^(PASSED|XFAIL|FAILED|ERROR) " | sort > tests/_salida/resultados_<antes|despues>.txt`

- el `diff` debe salir vacío, con 142 líneas;
- `humo_integ.json` queda idéntico;
- ningún archivo pasa de 400 líneas;
- ruff y mypy siguen en 0.

## C3 · `como` rechaza `rol="anon"` con perfil
Hoy da un `auth.uid()` con usuario en sesión anónima, algo que Supabase no produce. Ninguna llamada la usa.
- **Cambio:** `validar_identidad(rol, perfil)` en `como.py` lanza `ValueError`. `como` la llama a través del módulo.
- **Test, sin Docker:** `tests/seguridad/test_como.py::test_como_rechaza_anon_con_perfil` verifica que se lance `ValueError`.
- **Tramposo:** `tests/tramposos/test_tramposos_como.py` sustituye la validación por una que la omite, y exige que el test falle con `match="DID NOT RAISE"`.
- **Cuentas:** 128 + 1 + 1 = **130 passed / 14 xfailed / 0 failed**; sin integ, 74 + 2 = **76**.

## C4 · Dos textos desactualizados
- `tests/integ/test_humo_integ.py:4-5`: "029" pasa a "030".
- `tests/tramposos/test_tramposos_seguridad.py:22`: los xfail quedan en "D2, D5-D9, D11". D3 salió con BUG-2.
- **Pasa:** el `-rA` sale idéntico al de C3, y el auditor coteja las líneas con `grep -n`.

## C5 · `.github/workflows/ci.yml`
**Reglas:**
- se dispara en `push` y en `pull_request`;
- `permissions: contents: read` y `persist-credentials: false`;
- acciones fijadas por SHA;
- ningún `secrets.*` ni clave en el YAML.

**Instalación común:** ubuntu-latest, Python 3.12, poetry fijo, `poetry check --lock` y `poetry install --with dev`.

**Jobs:**
- **`calidad`:** `ruff check .`, `mypy .` y `pytest -m "not integ"`. Debe dar 76 passed.
- **`integ`:**
  - `docker pull` de `integ_db.IMAGEN` antes de la suite, para que la descarga no se coma el timeout de 120 s de la fixture;
  - `pytest` completo, que debe dar 130/14;
  - sube `humo_integ.json` como artefacto;
  - `timeout-minutes: 15`.
  - Tiempo estimado, no medido: la imagen pesa 370 MB y la suite tarda 46 s en local con caché. Espero 5 min o menos; si pasa de 10, va a "Después".
- **`secretos`:** el binario de gitleaks (licencia MIT), con versión fija y SHA-256 verificado. Usa `fetch-depth: 0` y `gitleaks git --redact --exit-code 1` sobre los 34 commits.
  - No se usa `gitleaks-action`: pide licencia a las organizaciones, y la ADR-003 eligió el binario.
  - Un script propio copiaría solo parte de las reglas; H1 sigue como barrera local.
  - Antes del commit se corre una línea base en local. Un hallazgo sintético va a `.gitleaks.toml`, justificado; uno real detiene todo y se avisa a Christiam.

**`lint-imports` queda fuera:** no hay configuración de import-linter. Va a "Después".

**Tramposo del CI, en local:**
- Sin `act`: no está instalado, y dentro de él `127.0.0.1:55432` no llegaría a Postgres.
- La sintaxis se valida con `actionlint` en Docker, que debe dar 0 hallazgos.
- Los `run:` del YAML se corren a mano, copiados tal cual:
  1. un `import os` sin uso en `src/` hace que `ruff` salga con 1; `git restore` lo devuelve a 0;
  2. una clave falsa con forma de AWS (`AKIA` + 16 caracteres de `[A-Z2-7]`, generada en el momento, en un archivo sin versionar) hace que `gitleaks dir` salga con 1; al borrarla, vuelve a 0.
- Esto prueba los comandos, **no** el cableado del workflow. El cableado solo se prueba con un push, que necesita el sí de Christiam: la rama `ci/tramposo` debe salir en rojo, y el commit que la revierte, en verde.

## Réplica
- **C2:** una segunda corrida, con un contenedor nuevo, da el mismo `-rA`.
- **C5:** un F841 y un secreto con forma `ghp_` también salen en rojo.

## Qué NO se toca
- `src/`, salvo `models.py:35`;
- `alembic/` y las migraciones;
- los nombres y cuerpos de los tests;
- `HUMO_ESPERADO`;
- los xfail (esperan la ADR-003);
- `.venv` y el remoto.

## Veredicto por la letra
- **FUNCIONA:** C1-C4 con sus cuentas exactas y sus tramposos en rojo, y C5 verde en GitHub con su tramposo en rojo.
- **HAY ALGO MODESTO:** C5 solo verificado en local (lo esperado sin push).
- **NO:** un id cambia en C2, ruff o mypy no dan 0, o gitleaks halla un secreto real.

## Cuentas (ERR-10)
- **Hoy:** 142 ids = 74 sin integ + 68 integ (54 passed + 14 xfailed).
- **Después de C3:** 144 ids = 130 passed + 14 xfailed.
