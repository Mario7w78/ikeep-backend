"""Lo que el asistente dice, verificado en codigo.

El prompt le pide al modelo que no escriba markdown y que no diga que guardo
nada. Pedirlo alcanza casi siempre, y "casi siempre" no sirve: el usuario ve
`**Nombre:**` con los asteriscos, o lee que su tarea "quedo actualizada"
cuando no se guardo nada.

Un prompt es una peticion; esto es una garantia. Lo que el modelo no puede
hacer no se le pide: se le impide.
"""

import re

_ENFASIS = re.compile(r"(\*\*|__|\*|_|`)")
_ENCABEZADO = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)
_VINETA = re.compile(r"^\s{0,3}[-*+]\s+", re.MULTILINE)
_ENLACE = re.compile(r"\[([^\]]+)\]\([^)]*\)")


def limpiar_markdown(texto: str | None) -> str:
    """Deja el texto como el chat lo va a mostrar.

    No convierte a otro formato: quita las marcas. La burbuja del chat es
    texto plano, asi que un asterisco solo es un asterisco.
    """
    if not texto:
        return ""

    limpio = _ENLACE.sub(r"\1", texto)
    limpio = _ENCABEZADO.sub("", limpio)
    # Las vinetas se cambian por un punto medio en vez de borrarse: sin nada
    # delante, tres lineas seguidas se leen como una sola frase cortada.
    limpio = _VINETA.sub("• ", limpio)
    limpio = _ENFASIS.sub("", limpio)

    # El modelo suele dejar tres saltos donde habia un encabezado.
    limpio = re.sub(r"\n{3,}", "\n\n", limpio)
    return limpio.strip()


# Solo primera persona y pasado. "Voy a crearla" o "quieres que la cree" son
# legitimas: hablan de algo que todavia no paso.
#
# El acento es lo unico que separa las dos cosas: "cree" es subjuntivo —"que
# la cree"— y "creé" es pasado. Se exige acentuado a proposito. Pierde alguna
# afirmacion mal escrita, pero al reves silenciaria frases legitimas, y un
# asistente que no puede ofrecerse a crear algo es peor que uno que a veces se
# pasa de listo.
_AFIRMACIONES = (
    re.compile(
        r"\b(creé|guardé|actualicé|modifiqué|eliminé|borré"
        r"|agregué|a[ñn]adí|registré|programé)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bhe\s+(creado|guardado|actualizado|modificado|eliminado|borrado"
        r"|agregado|a[ñn]adido|registrado|programado)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(qued[óo]|qued[óo]\s+ya|ya\s+qued[óo]|ya\s+est[áa])\s+"
        r"(creada?|guardada?|actualizada?|modificada?|registrada?|lista?"
        r"|agregada?|a[ñn]adida?|eliminada?|borrada?|programada?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bse\s+(cre[óo]|guard[óo]|actualiz[óo]|modific[óo]|elimin[óo]"
        r"|borr[óo]|agreg[óo]|registr[óo])\b",
        re.IGNORECASE,
    ),
)


def afirma_haber_actuado(texto: str | None) -> bool:
    """Dice el texto que algo ya se creo, guardo, cambio o borro.

    Nada se persiste hasta que el usuario confirma una propuesta, asi que una
    afirmacion de este tipo en un turno sin propuesta es siempre falsa. No es
    una cuestion de estilo: es el asistente mintiendole al usuario sobre el
    estado de sus datos.
    """
    if not texto:
        return False
    return any(patron.search(texto) for patron in _AFIRMACIONES)
