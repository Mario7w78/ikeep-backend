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

    return borrador.model_copy(update=cambios, deep=True)
