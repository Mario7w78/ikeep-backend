"""Acumulacion del borrador de actividad.

Determinista y del lado del servidor a proposito. El modelo extrae; decidir
como se combina lo extraido con lo que ya se sabia es logica, y la logica no
se le delega a algo probabilistico.
"""

from schemas.assistant import Borrador, BorradorPatch

# El horario se reemplaza entero, nunca se mezcla. Mezclar por indice es el
# origen de los bugs de "cambie el lunes y se duplico el miercoles": el bloque
# nuevo se aplica sobre el primero de la lista vieja, que no tiene por que ser
# el mismo dia.
_CAMPOS_DE_REEMPLAZO_TOTAL = {"schedule"}


def aplicar_patch(borrador: Borrador, patch: BorradorPatch) -> Borrador:
    """Devuelve un borrador nuevo con el parche aplicado.

    Un campo ausente del parche no se toca; uno presente se reemplaza, incluso
    si viene en null. exclude_unset es lo que permite distinguir "no lo
    mencione" de "lo estoy negando".

    No muta el borrador recibido: si un turno falla a mitad de camino, el
    estado anterior sigue intacto.
    """
    # Se leen los atributos y no model_dump(): volcar convierte los modelos
    # anidados en diccionarios, y como Pydantic no valida al asignar, los
    # bloques horarios quedarian como dicts hasta reventar mucho mas lejos.
    cambios = {campo: getattr(patch, campo) for campo in patch.model_fields_set}

    for campo in _CAMPOS_DE_REEMPLAZO_TOTAL:
        # Un null en un campo de lista significa "vacialo", no "dejalo".
        if campo in cambios and cambios[campo] is None:
            cambios[campo] = []

    actualizado = borrador.model_copy(update=cambios, deep=True)
    return _inferir_lo_deducible(actualizado)


def _duracion_del_bloque(bloque) -> int:
    """Largo en minutos, contemplando el cruce de medianoche."""
    if bloque.end_time >= bloque.start_time:
        return bloque.end_time - bloque.start_time
    return (1440 - bloque.start_time) + bloque.end_time


def _inferir_lo_deducible(borrador: Borrador) -> Borrador:
    """Completa lo que se sigue de los datos, en vez de preguntarlo.

    Todas estas deducciones salieron de correr las conversaciones doradas
    contra modelos reales: acertaban el dato pero se olvidaban de marcar la
    consecuencia, y el borrador quedaba incompleto para siempre mientras el
    asistente preguntaba algo cuya respuesta ya tenia delante.

    Van aca y no en el prompt porque son deducciones, no criterios. Pedirle al
    modelo que ademas de entender saque la conclusion es delegar logica en
    algo probabilistico, teniendo la logica a mano.

    Casi ninguna pisa una decision explicita: completan lo que quedo vacio.
    La excepcion esta abajo, y esta justificada ahi.
    """
    cambios = {}

    if borrador.schedule:
        # Dar dia y hora concretos ES la definicion de actividad fija, y esto
        # SI pisa un `is_fixed=False` anterior.
        #
        # Caso real: "va a variar, son martes y sabados" y a continuacion "el
        # martes es de 8 a 10 de la noche y el sabado de 10 a 1". El usuario
        # no se contradice —precisa—, pero el borrador se quedaba con lo vago
        # y proponia una actividad flexible de un solo dia, perdiendo el
        # sabado entero.
        #
        # Un borrador flexible CON horario concreto es incoherente de todos
        # modos: lo flexible se expresa con ventana preferida y duracion, no
        # con bloques. Entre las dos frases, la especifica es la que manda.
        if borrador.is_fixed is not True:
            cambios["is_fixed"] = True
        # Y la duracion es el largo del bloque: pedirla aparte es pedir dos
        # veces el mismo dato, con la posibilidad de que se contradigan.
        if borrador.duracion_minutos is None:
            cambios["duracion_minutos"] = _duracion_del_bloque(borrador.schedule[0])

    # Una ventana preferida solo tiene sentido si alguien mas elige el
    # horario: si el usuario lo dictara, daria la hora y no un rango.
    elif (
        borrador.is_fixed is None
        and borrador.hora_preferida_inicio is not None
        and borrador.hora_preferida_fin is not None
    ):
        cambios["is_fixed"] = False

    return borrador.model_copy(update=cambios) if cambios else borrador
