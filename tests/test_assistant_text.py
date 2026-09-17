"""Lo que el asistente dice, verificado en codigo y no pedido en el prompt."""

import pytest

from domain.services.assistant.text import (
    afirma_haber_actuado,
    invita_a_confirmar,
    limpiar_markdown,
    promete_crear,
)


class TestLimpiarMarkdown:
    def test_quita_las_negritas(self):
        assert limpiar_markdown("**Nombre:** PEPE") == "Nombre: PEPE"

    def test_quita_encabezados(self):
        assert limpiar_markdown("## Resumen\nPEPE") == "Resumen\nPEPE"

    def test_las_vinetas_quedan_como_punto(self):
        # Borrarlas sin mas dejaria tres lineas que se leen como una frase
        # cortada.
        assert limpiar_markdown("- uno\n- dos") == "• uno\n• dos"

    def test_deja_el_texto_del_enlace(self):
        assert limpiar_markdown("Mira [tu agenda](https://x.com)") == "Mira tu agenda"

    def test_no_toca_el_texto_plano(self):
        texto = "La tarea PEPE dura 4 horas y no tiene hora fija."
        assert limpiar_markdown(texto) == texto

    def test_un_texto_vacio_no_rompe(self):
        assert limpiar_markdown(None) == ""
        assert limpiar_markdown("") == ""


class TestAfirmaHaberActuado:
    @pytest.mark.parametrize(
        "texto",
        [
            "Listo, la tarea PEPE quedó actualizada con la nueva duración.",
            "Ya está creada.",
            "He guardado los cambios.",
            "Creé la actividad Cálculo.",
            "La eliminé de tu horario.",
            "Se actualizó correctamente.",
            "Modifiqué la duración a 4 horas.",
        ],
    )
    def test_detecta_la_afirmacion(self, texto):
        assert afirma_haber_actuado(texto) is True

    @pytest.mark.parametrize(
        "texto",
        [
            "¿Quieres que la cree con estos datos?",
            "Voy a crearla en cuanto me confirmes.",
            "Si me lo confirmas, la guardo.",
            "La tarea PEPE dura 4 horas y su horario es flexible.",
            "¿Es una tarea con horario fijo?",
            "Nombre: PEPE. Tipo: tarea. Duración: 4 horas.",
        ],
    )
    def test_no_marca_lo_que_todavia_no_paso(self, texto):
        assert afirma_haber_actuado(texto) is False

    def test_un_texto_vacio_no_rompe(self):
        assert afirma_haber_actuado(None) is False


class TestInvitaAConfirmar:
    """La unica forma de confirmar es el boton de la tarjeta.

    Sin propuesta, pedir confirmacion deja al usuario escribiendo "Confirmo"
    contra algo que no escucha. Paso en una conversacion real.
    """

    @pytest.mark.parametrize(
        "texto",
        [
            "La clase de programacion movil, la creo en cuanto me confirmes.",
            "¿Quieres que la cree con estos datos?",
            "Confírmame y la agrego.",
            "¿Te parece bien así?",
        ],
    )
    def test_detecta_la_invitacion(self, texto):
        assert invita_a_confirmar(texto) is True

    @pytest.mark.parametrize(
        "texto",
        [
            "¿Cuánto dura la clase, en minutos?",
            "¿Qué días la tienes?",
            "La clase dura 4 horas y su horario es flexible.",
        ],
    )
    def test_una_pregunta_normal_no_lo_es(self, texto):
        assert invita_a_confirmar(texto) is False

    def test_un_texto_vacio_no_rompe(self):
        assert invita_a_confirmar(None) is False


class TestPrometeCrear:
    """Prometer que algo se va a crear ahora.

    No es una mentira como "la creé", pero si el turno termina ahi sin llamar
    a proponer_actividad, la tarjeta que esa frase le anuncia al usuario no
    existe. Con el borrador completo el servidor la fuerza.
    """

    @pytest.mark.parametrize(
        "texto",
        [
            "Perfecto, te voy a crear la actividad de Calculo.",
            "Voy a añadir tu clase de programacion movil.",
            "Voy a registrar el gimnasio en tu semana.",
            "Crearé la tarea con esos datos.",
            "Te la agregaré apenas confirme el horario.",
            "Dale, te la creo.",
            "¿La creo? Ya tengo todos los datos.",
            "La voy a agendar para el martes.",
        ],
    )
    def test_detecta_la_promesa(self, texto):
        assert promete_crear(texto) is True

    @pytest.mark.parametrize(
        "texto",
        [
            "Cuando tenga los dias, la agrego.",
            "¿Cuánto dura la clase, en minutos?",
            "¿Quieres que la modifique?",
            "Creo que ya tengo todo lo que necesito.",
            "El martes de 8 a 10 y no hay más.",
            "La clase dura 4 horas y su horario es flexible.",
        ],
    )
    def test_no_marca_lo_que_no_es_una_promesa(self, texto):
        assert promete_crear(texto) is False

    def test_un_texto_vacio_no_rompe(self):
        assert promete_crear(None) is False
