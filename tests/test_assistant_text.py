"""Lo que el asistente dice, verificado en codigo y no pedido en el prompt."""

import pytest

from domain.services.assistant.text import afirma_haber_actuado, limpiar_markdown


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
