"""Tests del borrador de actividad y su reducer.

Aca vive el arreglo del "se olvida". Hasta ahora el historial que volvia al
modelo era solo el texto legible de cada turno: cuando extraia una entidad
estructurada, ese JSON no volvia nunca, y el modelo tenia que re-deducirla de
una prosa que no la contenia.

El borrador invierte eso: es memoria explicita. El modelo emite parches
parciales y el servidor los acumula de forma determinista. Los turnos de
conversacion pasan a ser solo conversacion.
"""

import pytest

from domain.services.assistant.draft import aplicar_patch
from schemas.assistant import BloqueHorario, Borrador, BorradorPatch


class TestAcumulacion:
    def test_un_patch_sobre_un_borrador_vacio_lo_llena(self):
        resultado = aplicar_patch(Borrador(), BorradorPatch(name="Calculo"))

        assert resultado.name == "Calculo"

    def test_lo_que_el_patch_no_menciona_sobrevive(self):
        """El test del "se olvida".

        El usuario dice "clase de calculo" y despues "los martes". El segundo
        turno no repite el nombre, y hasta ahora se perdia.
        """
        borrador = aplicar_patch(
            Borrador(), BorradorPatch(name="Calculo", activity_type="clase")
        )

        resultado = aplicar_patch(
            borrador,
            BorradorPatch(schedule=[BloqueHorario(day="Martes", start_time=600, end_time=720)]),
        )

        assert resultado.name == "Calculo"
        assert resultado.activity_type == "clase"
        assert len(resultado.schedule) == 1

    def test_un_campo_repetido_se_reemplaza(self):
        """Correccion tardia: "mejor que sea de 11, no de 10"."""
        borrador = aplicar_patch(Borrador(), BorradorPatch(name="Calculo"))

        resultado = aplicar_patch(borrador, BorradorPatch(name="Algebra"))

        assert resultado.name == "Algebra"

    def test_acumula_a_lo_largo_de_varios_turnos(self):
        borrador = Borrador()
        for patch in [
            BorradorPatch(name="Calculo"),
            BorradorPatch(activity_type="clase"),
            BorradorPatch(is_fixed=True),
            BorradorPatch(difficulty="alta"),
        ]:
            borrador = aplicar_patch(borrador, patch)

        assert borrador.name == "Calculo"
        assert borrador.activity_type == "clase"
        assert borrador.is_fixed is True
        assert borrador.difficulty == "alta"

    def test_el_borrador_original_no_se_muta(self):
        """Cada turno produce un borrador nuevo: si se mutara, un fallo a
        mitad de turno dejaria el estado a medio aplicar."""
        original = aplicar_patch(Borrador(), BorradorPatch(name="Calculo"))

        aplicar_patch(original, BorradorPatch(name="Algebra"))

        assert original.name == "Calculo"


class TestBorrado:
    def test_un_null_explicito_limpia_el_campo(self):
        """"No, no tiene fecha limite" tiene que poder deshacer."""
        borrador = aplicar_patch(Borrador(), BorradorPatch(deadline="2026-09-01"))

        resultado = aplicar_patch(borrador, BorradorPatch(deadline=None))

        assert resultado.deadline is None

    def test_un_campo_ausente_no_limpia_nada(self):
        """Distinto de arriba: no mencionarlo no es lo mismo que negarlo."""
        borrador = aplicar_patch(Borrador(), BorradorPatch(deadline="2026-09-01"))

        resultado = aplicar_patch(borrador, BorradorPatch(name="Calculo"))

        assert resultado.deadline == "2026-09-01"


class TestHorarios:
    def test_el_horario_se_reemplaza_entero_no_se_mezcla(self):
        """Nunca mezclar por indice.

        Es el origen de los bugs de "cambie el lunes y se duplico el
        miercoles": un merge posicional aplica el bloque nuevo sobre el
        primero de la lista vieja, que no tiene por que ser el mismo dia.
        """
        borrador = aplicar_patch(
            Borrador(),
            BorradorPatch(
                schedule=[
                    BloqueHorario(day="Lunes", start_time=600, end_time=720),
                    BloqueHorario(day="Miercoles", start_time=600, end_time=720),
                ]
            ),
        )

        resultado = aplicar_patch(
            borrador,
            BorradorPatch(schedule=[BloqueHorario(day="Lunes", start_time=660, end_time=780)]),
        )

        assert len(resultado.schedule) == 1
        assert resultado.schedule[0].day == "Lunes"
        assert resultado.schedule[0].start_time == 660

    def test_no_mandar_horario_conserva_el_que_habia(self):
        borrador = aplicar_patch(
            Borrador(),
            BorradorPatch(schedule=[BloqueHorario(day="Lunes", start_time=600, end_time=720)]),
        )

        resultado = aplicar_patch(borrador, BorradorPatch(name="Calculo"))

        assert len(resultado.schedule) == 1

    def test_una_lista_vacia_explicita_borra_los_horarios(self):
        borrador = aplicar_patch(
            Borrador(),
            BorradorPatch(schedule=[BloqueHorario(day="Lunes", start_time=600, end_time=720)]),
        )

        resultado = aplicar_patch(borrador, BorradorPatch(schedule=[]))

        assert resultado.schedule == []


class TestValidacionDeHoras:
    @pytest.mark.parametrize("minuto", [0, 720, 1439])
    def test_acepta_minutos_validos_del_dia(self, minuto):
        assert BloqueHorario(day="Lunes", start_time=minuto, end_time=minuto).start_time == minuto

    @pytest.mark.parametrize("minuto", [-1, 1440, 9999])
    def test_rechaza_minutos_fuera_del_dia(self, minuto):
        """Reemplaza a las lineas de prompt que rogaban "nunca confundas 1 pm
        con 1 am": un rango invalido se rechaza en el schema, no se pide."""
        with pytest.raises(ValueError):
            BloqueHorario(day="Lunes", start_time=minuto, end_time=600)


class TestCamposFaltantes:
    def test_un_borrador_vacio_pide_lo_que_no_depende_de_nada(self):
        """Todavia no pide horario ni duracion.

        Cual de los dos hace falta depende de si la actividad es fija, y eso
        aun no se sabe. Pedir los dos llevaria al modelo a preguntar por algo
        que despues resulta irrelevante.
        """
        faltantes = Borrador().campos_faltantes

        assert faltantes == ["name", "activity_type", "is_fixed"]

    def test_lo_que_ya_se_sabe_deja_de_faltar(self):
        """Los slots vacios del borrador SON la lista de faltantes.

        Por eso desaparece missing_fields del contrato: era una segunda
        fuente de verdad sobre lo mismo, que podia contradecir al borrador.
        """
        borrador = aplicar_patch(Borrador(), BorradorPatch(name="Calculo"))

        assert "name" not in borrador.campos_faltantes

    def test_una_actividad_fija_completa_no_deja_faltantes(self):
        borrador = aplicar_patch(
            Borrador(),
            BorradorPatch(
                name="Calculo",
                activity_type="clase",
                is_fixed=True,
                schedule=[BloqueHorario(day="Martes", start_time=600, end_time=720)],
            ),
        )

        assert borrador.campos_faltantes == []

    def test_una_flexible_necesita_duracion_en_vez_de_horario(self):
        """Una actividad sin hora fija no puede pedir bloques: justamente lo
        que se delega al solver es cuando ponerla."""
        borrador = aplicar_patch(
            Borrador(),
            BorradorPatch(name="Estudiar", activity_type="tarea", is_fixed=False),
        )

        assert "duracion_minutos" in borrador.campos_faltantes
        assert "schedule" not in borrador.campos_faltantes

    def test_una_flexible_con_duracion_esta_completa(self):
        borrador = aplicar_patch(
            Borrador(),
            BorradorPatch(
                name="Estudiar",
                activity_type="tarea",
                is_fixed=False,
                duracion_minutos=90,
            ),
        )

        assert borrador.campos_faltantes == []


class TestListoParaProponer:
    def test_no_esta_listo_si_falta_algo(self):
        assert aplicar_patch(Borrador(), BorradorPatch(name="Calculo")).esta_completo is False

    def test_esta_listo_cuando_no_falta_nada(self):
        borrador = aplicar_patch(
            Borrador(),
            BorradorPatch(
                name="Calculo",
                activity_type="clase",
                is_fixed=True,
                schedule=[BloqueHorario(day="Martes", start_time=600, end_time=720)],
            ),
        )

        assert borrador.esta_completo is True
