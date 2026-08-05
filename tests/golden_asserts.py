"""Comparacion de un borrador contra lo que espera una conversacion dorada.

Compartido entre la corrida determinista y la que va contra el proveedor real,
para que las dos midan exactamente lo mismo.

La regla central: los campos estructurados se comparan exacto y los de texto
libre no. Que el modelo extraiga "Clase de calculo" o "Calculo" como nombre da
igual —las dos son lecturas razonables de "mi clase de calculo"— y asertar el
string exacto es la misma fragilidad que asertar el texto de las preguntas.
"""

import unicodedata

# Campos donde el usuario escribe prosa y el modelo la interpreta. Exigir una
# forma exacta aca mide el estilo del modelo, no si entendio.
CAMPOS_DE_TEXTO_LIBRE = {"name", "location"}


def _normalizar(texto: str) -> str:
    sin_tildes = "".join(
        c
        for c in unicodedata.normalize("NFD", str(texto).lower().strip())
        if unicodedata.category(c) != "Mn"
    )
    return " ".join(sin_tildes.split())


def coincide(campo: str, actual, esperado) -> bool:
    """Si el valor obtenido satisface lo que el caso pedia."""
    if campo not in CAMPOS_DE_TEXTO_LIBRE:
        return actual == esperado

    if actual is None or esperado is None:
        return actual == esperado

    # Basta con que uno contenga al otro: cubre tanto que el modelo agregue
    # contexto ("Clase de calculo") como que lo recorte ("Calculo").
    a, e = _normalizar(actual), _normalizar(esperado)
    return a in e or e in a


def verificar_draft(borrador, esperado: dict, donde: str) -> str | None:
    """None si cumple; si no, la descripcion del primer incumplimiento."""
    for campo, valor in (esperado or {}).items():
        actual = getattr(borrador, campo)
        if not coincide(campo, actual, valor):
            return f"{donde}: draft.{campo}={actual!r} no satisface {valor!r}"
    return None


def verificar_conservados(borrador, previo, campos: list[str], donde: str) -> str | None:
    """El aserto central: un turno no puede perder lo que ya se sabia.

    Perder, no cambiar. Que un campo pase de vacio a tener valor es la
    conversacion avanzando —is_fixed se deduce recien cuando aparece un
    horario— y exigir igualdad estricta lo marcaria como fallo.

    Lo que si es un fallo: que algo conocido se vuelva desconocido, o que se
    reemplace solo porque el turno no lo repitio.
    """
    for campo in campos or []:
        anterior, actual = getattr(previo, campo), getattr(borrador, campo)

        if anterior in (None, "", [], {}):
            continue

        if not coincide(campo, actual, anterior):
            return (
                f"{donde}: se perdio draft.{campo} ({anterior!r} -> {actual!r}). "
                "Esto es el 'se olvida'."
            )
    return None


def verificar_rangos(borrador, rangos: dict, donde: str) -> str | None:
    """Para valores donde varias lecturas son defendibles.

    "La tarde" puede empezar a las 12 o a las 14 segun a quien le preguntes.
    Exigir un minuto exacto mediria el criterio del modelo, no si entendio que
    hablabamos de la tarde.
    """
    for campo, (minimo, maximo) in (rangos or {}).items():
        actual = getattr(borrador, campo)
        if actual is None or not (minimo <= actual <= maximo):
            return (
                f"{donde}: draft.{campo}={actual!r} fuera del rango "
                f"[{minimo}, {maximo}]"
            )
    return None
