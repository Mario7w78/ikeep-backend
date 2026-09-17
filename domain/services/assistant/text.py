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


# Frases que piden una confirmacion que el usuario no puede dar.
#
# La unica forma de confirmar es el boton de la tarjeta de propuesta. Si el
# modelo dice "la creo en cuanto me confirmes" y no llamo a proponer_actividad,
# no hay nada que tocar: el usuario escribe "Confirmo" y no pasa nada.
_INVITACIONES = (
    re.compile(r"\bconf[íi]rm|confirm(a|as|ame|arme|es|e|arlo|arla)\b", re.IGNORECASE),
    re.compile(r"\bquieres que la\s+\w+", re.IGNORECASE),
    re.compile(r"\bte parece\b", re.IGNORECASE),
    re.compile(r"\bla creo\b", re.IGNORECASE),
)


def invita_a_confirmar(texto: str | None) -> bool:
    """Pide el texto una confirmacion.

    Solo importa cuando el turno no lleva propuesta: ahi la invitacion es un
    callejon sin salida, porque el boton que la respondería no existe.
    """
    if not texto:
        return False
    return any(patron.search(texto) for patron in _INVITACIONES)


# Promesas de que algo se va a crear ahora mismo.
#
# "Voy a crearla" no es una mentira como "la creé": no dice que ya paso. Pero
# si el turno termina en texto sin llamar a proponer_actividad, la promesa es
# el mismo callejon sin salida que la invitacion: el usuario leeria que la
# tarjeta va a aparecer y no habria nada que confirmar. Con el borrador
# completo la respuesta correcta no es corregir al modelo, es mostrarle la
# tarjeta al usuario.
_PROMESAS_DE_CREACION = (
    # "voy a crear", "te voy a añadir", "la voy a agendar".
    re.compile(
        r"\bvoy\s+a\s+(cre[ae]r|agregar|a[ñn]adir|registrar|programar|agendar|guardar)\b",
        re.IGNORECASE,
    ),
    # "crearé", "registraré", "te la agregaré".
    re.compile(
        r"\b(crear[ée]|agregar[ée]|a[ñn]adir[ée]|registrar[ée]|programar[ée]|agendar[ée]|guardar[ée])\b",
        re.IGNORECASE,
    ),
    # Presente con intencion de crear ("la creo", "te la creo", "¿La creo?",
    # "quieres que la cree"). "la creen" (creer el verbo) no coincide: se exige
    # fin de palabra despues de cre[eo].
    re.compile(r"\b(te\s+)?la\s+(voy\s+a\s+)?cre[eo]\b", re.IGNORECASE),
)


def promete_crear(texto: str | None) -> bool:
    """Promete el texto crear algo sin haberlo propuesto aun.

    Solo importa cuando el turno no lleva propuesta. A diferencia de
    afirma_haber_actuado, el futuro es legitimo si el borrador sigue
    incompleto: "cuando tenga los dias, te la creo" describe lo que va a
    pasar. La promesa se vuelve un problema recien cuando el borrador esta
    completo y la tarjeta no aparece; de eso se encarga el bucle.
    """
    if not texto:
        return False
    return any(patron.search(texto) for patron in _PROMESAS_DE_CREACION)
