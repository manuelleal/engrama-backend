# Guía de la Base de Datos — Engrama 2.0

> **Para quién es esto:** para ti (Christiam) o cualquiera que nunca haya visto
> el código antes. Está escrito **paso a paso, en español**, asumiendo que no
> sabes programación. El objetivo es que puedas **entender qué hicimos, correrlo,
> y arreglarlo si algo falla**, sin llamar a nadie.

---

## 1. ¿Qué es todo esto en una frase?

Creamos la **estructura de la base de datos** de Engrama 2.0 (las 26 tablas
donde se guardan alumnos, retos, monedas, etc.) de una manera que se puede
**crear, borrar y recrear con UN comando**, sin abrir el dashboard de Supabase.

La herramienta que hace esa magia se llama **Alembic**.

---

## 2. Glosario mínimo (en palabras humanas)

| Palabra | Qué significa |
|---|---|
| **Base de datos (DB)** | Un excel gigante donde se guarda todo: usuarios, retos, monedas. La nuestra vive en Supabase (la nube). |
| **Tabla** | Una "hoja" del excel. Ej: la tabla `profiles` guarda los usuarios. Tenemos 26. |
| **Columna** | Una "casilla" de cada hoja. Ej: `full_name`, `documento_id`. |
| **Migración** | Un archivo de instrucciones que le dice a la DB *"crea esta tabla así"*. Como una receta. |
| **Alembic** | El programa que lee nuestras recetas (migraciones) y las aplica a la DB en orden. |
| **SQLAlchemy** | El traductor entre nuestro código Python y la DB. Cuando el código dice *"dame todos los alumnos"*, SQLAlchemy lo convierte a un idioma que la DB entiende (SQL). |
| **RLS (Row Level Security)** | Un candado por fila: hace que un profesor del colegio A nunca vea datos del colegio B, aunque estén en la misma tabla. |
| **Tenant** | Un colegio/cliente. Engrama es multi-cliente, así que cada fila dice a qué tenant pertenece. |
| **`.env`** | Archivo de texto con las contraseñas y URLs secretas. **NO se sube a GitHub.** |
| **Poetry** | El gestor que instala las librerías de Python que el proyecto necesita. |

---

## 3. Mapa: qué archivo hace qué

```
engrama-backend/
├── .env                        ← SECRETOS (password de la DB, etc.). NO subir.
├── .env.example                ← Plantilla pública sin secretos.
├── alembic.ini                 ← Config de Alembic (no tiene secretos).
├── pyproject.toml              ← Lista de librerías que el proyecto usa.
├── poetry.lock                 ← Versiones exactas de esas librerías.
│
├── SPECS/
│   └── 00-database-schema.md   ← EL DISEÑO. Describe las 26 tablas en español/SQL.
│                                  Esto es el "plano del arquitecto".
│
├── alembic/                    ← Todo lo relacionado con migraciones.
│   ├── env.py                  ← El "arrancador" de Alembic. Lee .env y conecta a la DB.
│   ├── script.py.mako          ← Plantilla para crear nuevas migraciones.
│   ├── README.md               ← Resumen rápido (apunta a este archivo).
│   └── versions/               ← ¡Aquí viven las recetas!
│       ├── 000_extensions.py           ← Activa UUIDs en Postgres.
│       ├── 001_create_tenants.py       ← Crea la tabla "tenants" (colegios).
│       ├── 002_create_profiles.py      ← Crea la tabla "profiles" (usuarios).
│       ├── ... (23 más, una por tabla) ...
│       ├── 026_create_audit_logs.py
│       ├── 027_indexes.py              ← Crea índices (aceleradores de búsqueda).
│       └── 028_enable_rls.py           ← Activa el candado RLS en las 26 tablas.
│
└── src/shared/
    └── models.py               ← Los 26 modelos SQLAlchemy. Cada clase = una tabla.
                                  Se usa cuando el código escribe/lee datos.
```

### ¿Por qué tantos archivos para algo tan simple?

Porque la filosofía es: **una migración por tabla, por separado**. Así, si algo
falla en la tabla 17, sabes exactamente qué archivo revisar, y no tienes que
leer 500 líneas juntas.

---

## 4. Cómo funciona, paso a paso

Cuando ejecutas `poetry run alembic upgrade head`, pasa esto:

1. **Alembic** lee `alembic.ini` para saber su configuración básica.
2. Ejecuta `alembic/env.py`, que:
   - Abre el archivo `.env`.
   - Saca la línea `DATABASE_URL=...` (la dirección + contraseña de la DB).
   - Si falta el prefijo `+asyncpg`, lo agrega automáticamente (para que use
     el driver rápido y moderno).
   - Se conecta a Supabase.
3. Alembic revisa qué migraciones ya se aplicaron (guarda un registro en una
   tabla oculta llamada `alembic_version`).
4. Corre las que faltan **en orden**: `000 → 001 → 002 → ... → 028`.
5. Cada archivo ejecuta su `def upgrade():` y su SQL crea una tabla.
6. Al final, tu DB tiene 26 tablas + índices + RLS activado.

Cuando ejecutas `poetry run alembic downgrade base`, pasa lo mismo **al revés**:
corre los `def downgrade():` de cada archivo en orden inverso (`028 → 027 → ...
→ 000`) y borra todo.

---

## 5. Comandos que necesitas saber (cookbook)

Abre una terminal y ubícate en el proyecto:

```bash
cd ~/projects/engrama/engrama-backend
```

### Ver en qué migración está la DB

```bash
poetry run alembic current
```

Te dice algo como `028_enable_rls (head)` (todo al día) o vacío (DB vacía).

### Aplicar TODAS las migraciones (crear/actualizar todo)

```bash
poetry run alembic upgrade head
```

Úsalo la primera vez, o cuando hay migraciones nuevas en el repo.

### Borrar TODO (tablas, datos, esquema)

```bash
poetry run alembic downgrade base
```

⚠️ **Esto borra los datos.** Úsalo solo en desarrollo o para resetear.

### Ver el historial de migraciones

```bash
poetry run alembic history
```

### Bajar solo UN paso (no todo)

```bash
poetry run alembic downgrade -1
```

### Subir solo UN paso

```bash
poetry run alembic upgrade +1
```

### Crear una migración NUEVA (para cuando agreguemos una tabla)

```bash
poetry run alembic revision -m "create new_table"
```

Te crea un archivo vacío en `alembic/versions/` que tú llenarás.

---

## 6. El archivo `.env` (el más delicado)

Este archivo tiene los secretos. Vive en `engrama-backend/.env` y **no se
sube a GitHub** (está en `.gitignore`).

Formato:

```env
APP_ENV=development
APP_DEBUG=true
APP_PORT=8000

SUPABASE_URL=https://xxxxxxx.supabase.co
SUPABASE_ANON_KEY=eyJh...
SUPABASE_SERVICE_ROLE_KEY=eyJh...
SUPABASE_JWT_SECRET=...

DATABASE_URL=postgresql://postgres.xxxxxxx:TU_PASSWORD@aws-1-us-east-2.pooler.supabase.com:5432/postgres

REDIS_URL=redis://redis:6379/0
ANTHROPIC_API_KEY=sk-ant-...
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
```

### ⚠️ Tres errores típicos con `DATABASE_URL`

Los vimos en carne propia al configurar el proyecto. Si vuelven a aparecer,
esta es la receta:

#### Error 1: `Network is unreachable` (Errno 101)

- **Síntoma:** alembic falla al conectar. El error dice "IPv6" o "Network
  unreachable".
- **Causa:** usaste el host directo de Supabase (`db.xxxxx.supabase.co`), que
  es solo IPv6. Tu red local no tiene IPv6.
- **Arreglo:** cambia al **Session Pooler**. En Supabase dashboard →
  **Project Settings → Database → Connection string → "Session pooler"**.
  Copia esa URL. Termina en `pooler.supabase.com:5432`.

#### Error 2: `ModuleNotFoundError: No module named 'psycopg2'`

- **Síntoma:** alembic se queja de que falta `psycopg2`.
- **Causa:** tu URL empieza con `postgresql://` en vez de
  `postgresql+asyncpg://`. Python intenta usar el driver viejo (psycopg2)
  y no está instalado.
- **Arreglo:** **ya está resuelto automáticamente** por `alembic/env.py`
  (normaliza el scheme). Pero si vuelve a pasar en otro contexto, añade
  `+asyncpg` a mano:
  ```
  DATABASE_URL=postgresql+asyncpg://postgres.xxx:PASSWORD@...
  ```

#### Error 3: `InvalidPasswordError: password authentication failed`

- **Síntoma:** conexión OK pero password rechazado.
- **Causa más común:** dejaste los **corchetes** `[ ]` alrededor del password
  cuando copiaste la URL del dashboard (Supabase muestra `[YOUR-PASSWORD]`
  como placeholder y a veces se copia tal cual).
- **Arreglo:** edita `.env` y quita los corchetes. Debe ser
  `:MiPassword@` y NO `:[MiPassword]@`.
- **Otras causas:** password cambiado en Supabase, usuario mal formado
  (debe ser `postgres.<project-ref>` en el pooler).

### Cómo editar `.env` de forma segura

```bash
nano ~/projects/engrama/engrama-backend/.env
```

Guarda con `Ctrl+O`, `Enter`, y sal con `Ctrl+X`.

### Cómo verificar que `.env` está bien formado (sin revelar el password)

```bash
cd ~/projects/engrama/engrama-backend
python3 -c "
import re
from pathlib import Path
for line in Path('.env').read_text().splitlines():
    if line.startswith('DATABASE_URL='):
        url = line.split('=',1)[1].strip()
        m = re.match(r'^(postgres[^:]*)://([^:]+):([^@]*)@([^:/]+):(\d+)/(\w+)', url)
        s,u,p,h,port,db = m.groups()
        print('scheme:',s,'| user:',u,'| pwd_len:',len(p),'| host:',h,'| port:',port,'| db:',db)
"
```

Si imprime todo OK y `pwd_len` > 0, estás bien.

---

## 7. La spec (`SPECS/00-database-schema.md`)

Ese archivo es **el plano del arquitecto**. Describe:

- La lista de 26 tablas en orden.
- Cada tabla con sus columnas, tipos y restricciones (CHECK, UNIQUE, FK).
- Los índices (sección 3).
- El patrón de RLS (sección 4).

**Regla de oro:** si el spec dice que una tabla tiene 10 columnas, nuestras
migraciones deben crear exactamente 10 columnas, ni una más ni una menos.
Nosotros **no inventamos**. Si el spec está incompleto, paramos y
avisamos al humano.

---

## 8. ¿Y si quiero agregar una tabla nueva?

Nunca edites una migración ya aplicada (rompería el historial). En su lugar:

1. Actualiza el spec (`SPECS/00-database-schema.md`) con la tabla nueva.
2. Crea una nueva migración:
   ```bash
   poetry run alembic revision -m "create new_table_name"
   ```
3. Edita el archivo que te creó en `alembic/versions/` y llena `upgrade()` y
   `downgrade()` mirando cómo lo hicimos para `001_create_tenants.py` (usamos
   `op.execute("""CREATE TABLE ...""")` con SQL puro).
4. Agrega la clase correspondiente en `src/shared/models.py`.
5. Ejecuta:
   ```bash
   poetry run alembic upgrade head
   ```
6. Si todo corre, commitea:
   ```bash
   git add alembic/versions/XXX_create_new_table.py src/shared/models.py SPECS/
   git commit -m "feat(db): add new_table_name table"
   ```

---

## 9. Flujo típico de desarrollo diario

```bash
# 1. Entrar al proyecto
cd ~/projects/engrama/engrama-backend

# 2. (Una sola vez al inicio, si el venv no existe) Instalar dependencias
poetry install --no-root

# 3. Ver en qué migración está la DB
poetry run alembic current

# 4. Si hay migraciones nuevas en el repo, aplicarlas
poetry run alembic upgrade head

# 5. Trabajar normalmente (editar código, correr la API, etc.)

# 6. (Al final del día) Guardar cambios en git
git status
git add <archivos>
git commit -m "mensaje"
git push origin main
```

---

## 10. Estado actual (19 abril 2026)

✅ **Lo que YA está hecho y funcionando:**

- Alembic configurado con async + asyncpg.
- 29 migraciones creadas (000–028).
- Las 26 tablas existen en la DB de Supabase.
- RLS activado (pero **sin políticas aún** — eso viene en la próxima tarea).
- `src/shared/models.py` tiene los 26 modelos SQLAlchemy.
- Commit inicial: `chore(db): initial schema migrations` (hash `93c102c`).
- Ya está pusheado a `origin/main` en GitHub.

⏳ **Lo que falta (próximas tareas):**

- Escribir `SPECS/00b-rls-policies.md` con las políticas de seguridad
  (quién puede leer/escribir qué).
- Crear la migración `029_rls_policies` que aplique esas políticas.
- Poblar los archivos vacíos en `src/shared/` (db.py, config.py, deps.py).
- Empezar los módulos de dominio (`auth/`, `billing/`, etc.).

---

## 11. Si algo se rompe y no entiendes qué pasa

1. **Lee el último mensaje de error completo** (suele decir la causa al final).
2. **Revisa la sección 6 de esta guía** (los 3 errores típicos).
3. **Revisa el estado de la DB:**
   ```bash
   poetry run alembic current
   ```
4. **Intenta desde cero** (solo en desarrollo, nunca en producción):
   ```bash
   poetry run alembic downgrade base
   poetry run alembic upgrade head
   ```
5. Si nada funciona, dale a Cascade/Claude este comando para reproducir el
   error y pégale el output completo:
   ```bash
   poetry run alembic upgrade head 2>&1 | tail -40
   ```

---

## 12. Reglas sagradas (no las rompas)

1. **Nunca edites una migración que ya fue aplicada y commiteada.** Crea una
   nueva.
2. **Nunca subas `.env` a GitHub.** El `.gitignore` lo evita, pero verifica.
3. **Nunca hardcodees contraseñas en el código.** Siempre vía `.env`.
4. **Nunca inventes tablas/columnas** que no estén en el spec.
5. **Antes de cualquier cambio grande en la DB, haz un backup** desde el
   dashboard de Supabase (Database → Backups).

---

*Última actualización: 2026-04-19. Si agregas cambios, actualiza la sección 10.*
