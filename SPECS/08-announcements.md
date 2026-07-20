# SPEC 08 — Announcements

> **Módulo:** `src/announcements/`
> **Estado:** 📝 spec listo — pendiente de implementación
> **Depende de:** `shared/models.py` (Announcement, Membership). NO importa otros dominios.

---

## 1. Objetivo

CRUD de anuncios por teacher/admin, con visualización filtrada para el estudiante. Los anuncios tienen alcance de grupo o tenant completo y expiran automáticamente por `expires_at`.

---

## 2. Schemas (`schemas.py`)

Pydantic v2 strict (`model_config = ConfigDict(strict=True, extra="forbid")`).

### Entrada

| Schema | Campos |
|---|---|
| `AnnouncementCreate` | `title: str (max=120)`, `message: str (min_length=1, max_length=2000)`, `alert_type: Literal['info','warning','danger','success']`, `target_group: str \| None = None`, `expires_at: datetime`, `links: list[LinkItem] \| None = None` |
| `AnnouncementUpdate` | Todos los campos de `AnnouncementCreate` opcionales (`\| None`) |
| `LinkItem` | `label: str (max=80)`, `url: AnyHttpUrl` |

### Salida

| Schema | Campos |
|---|---|
| `AnnouncementOut` | `id: UUID`, `tenant_id: UUID`, `title: str \| None`, `message: str`, `alert_type: str`, `target_group: str \| None`, `expires_at: datetime`, `links: list[LinkItem] \| None`, `created_at: datetime` |

> **Divergencia de modelo detectada:** la columna del modelo `Announcement` se llama `expiry_date: Date` (solo fecha, sin hora) y `alert_type` admite `'error'` en el CheckConstraint del modelo, pero el MVP usa `'danger'`. Ver §7.

---

## 3. Lógica (`service.py`)

### `create_announcement(db, creator_id, tenant_id, data: AnnouncementCreate)` → `AnnouncementOut`

```
# Validaciones:
# - Si data.target_group presente → verificar que el grupo pertenece al tenant
#   (SELECT Group WHERE group_code=X AND tenant_id=Y → 404 si no existe)
# - expires_at > now() → 422 "La fecha de expiración debe ser futura"
# INSERT Announcement(tenant_id=tenant_id, created_by=creator_id, ...)
# Retorna: AnnouncementOut
```

### `list_announcements_for_student(db, student_id, tenant_id)` → `list[AnnouncementOut]`

```
# 1. Obtener group_code del estudiante:
#    SELECT Membership.group_code WHERE profile_id=student_id AND tenant_id=tenant_id
# 2. SELECT Announcement WHERE tenant_id=tenant_id
#      AND expires_at > now()
#      AND (target_group IS NULL OR target_group = student_group_code)
#    ORDER BY created_at DESC
# Retorna: list[AnnouncementOut]
```

### `list_announcements_admin(db, tenant_id, *, include_expired=False)` → `list[AnnouncementOut]`

```
# SELECT Announcement WHERE tenant_id=tenant_id
#   AND (include_expired OR expires_at > now())
# ORDER BY created_at DESC, LIMIT 100
```

### `update_announcement(db, ann_id, tenant_id, data: AnnouncementUpdate)` → `AnnouncementOut`

```
# SELECT Announcement WHERE id=ann_id AND tenant_id=tenant_id → 404 si no existe
# PATCH campos no-nulos de data
# Si expires_at nuevo → validar > now()
# Retorna: AnnouncementOut actualizado
```

### `delete_announcement(db, ann_id, tenant_id)` → `None`

```
# SELECT Announcement WHERE id=ann_id AND tenant_id=tenant_id → 404 si no existe
# DELETE
```

---

## 4. Permisos

| Operación | Roles permitidos |
|---|---|
| Crear anuncio | `teacher`, `admin` |
| Editar / eliminar | `admin`; `teacher` solo si es `created_by` propio |
| Listar todos (incluye expirados) | `admin` |
| Listar vigentes | `student`, `teacher`, `admin` |

---

## 5. Endpoints (`router.py`) — prefijo `/v1/announcements`

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| POST | `/v1/announcements/` | `require_teacher` | Crear anuncio |
| GET | `/v1/announcements/` | `get_current_user` | Listar vigentes (estudiante: filtrado por grupo; admin: todos) |
| GET | `/v1/announcements/all` | `require_admin` | Listar todos incluyendo expirados |
| PATCH | `/v1/announcements/{ann_id}` | `require_teacher` | Editar anuncio |
| DELETE | `/v1/announcements/{ann_id}` | `require_teacher` | Eliminar anuncio |

`GET /v1/announcements/` resuelve el scope automáticamente: si el caller es `student` aplica el filtro de grupo; si es `teacher` o `admin` devuelve todos los vigentes del tenant.

---

## 6. Tests (`tests/announcements/`)

- **Contractuales HTTP:** `POST /v1/announcements/` sin auth → 401; con JWT student → 403; body sin `message` → 422; `alert_type` inválido → 422.
- **Unitarios:** `list_for_student` excluye anuncios expirados; incluye anuncios con `target_group=None`; excluye anuncios de otro grupo.
- **Integración (skip):** crear → listar como student → verificar filtro expires_at; aislamiento cross-tenant.

---

## 7. Migración requerida

| Campo | Tabla | Cambio | Justificación |
|---|---|---|---|
| `expires_at TIMESTAMPTZ` | `announcements` | Renombrar/cambiar `expiry_date DATE` → `expires_at TIMESTAMPTZ NOT NULL` | El filtro `expires_at > now()` requiere timestamp con zona; la spec y el MVP usan `expires_at`, el modelo actual usa `expiry_date: Date` |
| `alert_type` CHECK | `announcements` | Cambiar `'error'` por `'danger'` en la lista permitida | El MVP usa `'danger'` (alineado con CSS Bootstrap), no `'error'` |
| `created_by UUID` | `announcements` | Agregar columna `created_by UUID REFERENCES profiles(id)` | Necesario para control de edición teacher-propio; ausente en modelo actual |
| `tenant_id NOT NULL` | `announcements` | Cambiar `nullable=True` → `NOT NULL` | El campo es nullable en el modelo actual pero toda fila debe tener tenant |

---

## 8. Registro en `main.py`

```python
from src.announcements.router import router as announcements_router
app.include_router(announcements_router, tags=["announcements"])
```
