"""La regla de COMPOSICIÓN de la contraseña, en un solo sitio — ESPEC_autorregistro §12.1.

La contraseña que una persona se pone debe tener al menos una letra y al menos
un dígito o un símbolo. El largo (10 a 72) vive aparte, en `CLAVE_MIN` y
`CLAVE_MAX` de `auth/schemas.py`.

Por qué existe aquí y no solo en GoTrue: GoTrue aplica esta regla cuando la
persona CAMBIA su contraseña (`PUT /user`), pero el autorregistro crea la
cuenta por la API de administración (`POST /admin/users`), que no la aplica.
Medido en el despliegue (§15.22 de la espec del anillo): una contraseña de
solo letras daba 201 en el registro. Aquí se pone la misma regla para que las
dos puertas pidan lo mismo.

OJO, esta lista es una COPIA de `GOTRUE_PASSWORD_REQUIRED_CHARACTERS` del
despliegue (`despliegue/docker-compose.yml`): si allá cambian los símbolos,
hay que cambiarlos aquí a mano. El test UR4 fija la lista actual para que el
cambio no pase en silencio.
"""
from __future__ import annotations

# Los símbolos que GoTrue del piloto reconoce (el `$$` del compose es un `$`).
SIMBOLOS = "-_.!@#$%&*+"

# El texto del 422. La web lo puede mostrar tal cual, junto al campo.
MENSAJE_COMPOSICION = (
    "la contraseña debe tener al menos una letra y al menos un número o un símbolo "
    f"({' '.join(SIMBOLOS)})"
)


def _es_digito(caracter: str) -> bool:
    """Solo `0` a `9`: `str.isdigit()` aceptaría también `²` y los dígitos árabes."""
    return "0" <= caracter <= "9"


def cumple_composicion(clave: str) -> bool:
    """¿Trae al menos una letra y al menos un dígito o símbolo?

    Una letra es cualquiera para la que `isalpha()` sea verdadero: la `ñ` y las
    tildes cuentan (a diferencia de GoTrue, que solo cuenta las ASCII; ver
    §12.1, "límite declarado"). Un símbolo es uno de `SIMBOLOS`: otros
    caracteres (espacios, `?`, `/`) no cuentan como símbolo ni como letra.
    """
    hay_letra = any(c.isalpha() for c in clave)
    hay_digito_o_simbolo = any(_es_digito(c) or c in SIMBOLOS for c in clave)
    return hay_letra and hay_digito_o_simbolo
