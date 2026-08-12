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
        # El fin se corre un minuto: un bloque de duracion cero se rechaza
        # aparte, y usar el mismo valor para los dos medía otra cosa.
        fin = minuto + 1 if minuto < 1439 else minuto - 1
        bloque = BloqueHorario(day="Lunes", start_time=minuto, end_time=fin)

        assert bloque.start_time == minuto

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


class TestBloqueSinDuracion:
    """Un modelo real uso 00:00-00:00 como marcador cuando el usuario dijo el
    dia pero no la hora. Aceptarlo hacia que el borrador pareciera completo y
    se propusiera una actividad sin horario."""

    def test_rechaza_un_bloque_de_duracion_cero(self):
        with pytest.raises(ValueError, match="misma hora"):
            BloqueHorario(day="Martes", start_time=0, end_time=0)

    def test_rechaza_duracion_cero_a_cualquier_hora(self):
        with pytest.raises(ValueError):
            BloqueHorario(day="Martes", start_time=600, end_time=600)

    def test_acepta_un_bloque_que_cruza_medianoche(self):
        """23:00 a 01:00 es valido: no se compara start < end."""
        bloque = BloqueHorario(day="Martes", start_time=1380, end_time=60)

        assert bloque.start_time == 1380
        assert bloque.end_time == 60


class TestInferencia:
    """Un modelo real emitio un horario concreto pero nunca marco is_fixed, y
    el borrador quedaba incompleto para siempre: el asistente preguntaba algo
    cuya respuesta ya tenia delante."""

    def test_un_horario_concreto_implica_actividad_fija(self):
        borrador = aplicar_patch(
            Borrador(),
            BorradorPatch(schedule=[BloqueHorario(day="Martes", start_time=600, end_time=720)]),
        )

        assert borrador.is_fixed is True

    def test_un_horario_concreto_si_pisa_un_flexible_anterior(self):
        """Este test decia lo contrario, y esa regla rompio una conversacion real.

        Un borrador flexible CON bloques concretos es incoherente: lo flexible
        se expresa con ventana preferida y duracion. Cuando el usuario dice
        "va a variar" y despues da las horas exactas, no se contradice —
        precisa—, y la frase especifica es la que manda.
        """
        borrador = aplicar_patch(Borrador(), BorradorPatch(is_fixed=False))

        resultado = aplicar_patch(
            borrador,
            BorradorPatch(schedule=[BloqueHorario(day="Martes", start_time=600, end_time=720)]),
        )

        assert resultado.is_fixed is True

    def test_sin_horario_no_infiere_nada(self):
        borrador = aplicar_patch(Borrador(), BorradorPatch(name="Calculo"))

        assert borrador.is_fixed is None

    def test_con_horario_el_borrador_puede_completarse(self):
        borrador = aplicar_patch(
            Borrador(),
            BorradorPatch(
                name="Calculo",
                activity_type="clase",
                schedule=[BloqueHorario(day="Martes", start_time=600, end_time=720)],
            ),
        )

        assert borrador.esta_completo is True


class TestInferenciaDeDuracion:
    """Salio de las conversaciones doradas: el modelo ponia el horario pero
    no la duracion, y el borrador quedaba incompleto teniendo el dato."""

    def test_la_duracion_sale_del_largo_del_bloque(self):
        borrador = aplicar_patch(
            Borrador(),
            BorradorPatch(schedule=[BloqueHorario(day="Lunes", start_time=840, end_time=960)]),
        )

        assert borrador.duracion_minutos == 120

    def test_contempla_el_cruce_de_medianoche(self):
        """23:00 a 01:00 son dos horas, no menos veintidos."""
        borrador = aplicar_patch(
            Borrador(),
            BorradorPatch(schedule=[BloqueHorario(day="Lunes", start_time=1380, end_time=60)]),
        )

        assert borrador.duracion_minutos == 120

    def test_no_pisa_una_duracion_declarada(self):
        borrador = aplicar_patch(
            Borrador(),
            BorradorPatch(
                duracion_minutos=90,
                schedule=[BloqueHorario(day="Lunes", start_time=840, end_time=960)],
            ),
        )

        assert borrador.duracion_minutos == 90


class TestInferenciaDeFlexible:
    """Una ventana preferida solo tiene sentido si el solver elige el horario:
    si el usuario lo dictara, daria la hora y no un rango."""

    def test_una_ventana_preferida_implica_flexible(self):
        borrador = aplicar_patch(
            Borrador(),
            BorradorPatch(hora_preferida_inicio=840, hora_preferida_fin=1200),
        )

        assert borrador.is_fixed is False

    def test_no_infiere_con_media_ventana(self):
        borrador = aplicar_patch(Borrador(), BorradorPatch(hora_preferida_inicio=840))

        assert borrador.is_fixed is None

    def test_un_horario_concreto_gana_sobre_la_ventana(self):
        """Si hay bloques, es fija aunque tambien haya ventana preferida."""
        borrador = aplicar_patch(
            Borrador(),
            BorradorPatch(
                hora_preferida_inicio=840,
                hora_preferida_fin=1200,
                schedule=[BloqueHorario(day="Lunes", start_time=900, end_time=960)],
            ),
        )

        assert borrador.is_fixed is True

    def test_no_pisa_una_decision_explicita(self):
        borrador = aplicar_patch(Borrador(), BorradorPatch(is_fixed=True))

        resultado = aplicar_patch(
            borrador, BorradorPatch(hora_preferida_inicio=840, hora_preferida_fin=1200)
        )

        assert resultado.is_fixed is True


class TestUnHorarioConcretoMandaSobreLoVago:
    """Dar dia y hora concretos ES la definicion de actividad fija.

    Caso real: "va a variar, son martes y sabados" y despues "el martes es de
    8 a 10 de la noche y el sabado de 10 a 1". El usuario no se contradice:
    precisa. El borrador se quedaba con `is_fixed=False` de la primera frase y
    proponia una actividad flexible de un solo dia, perdiendo el sabado.
    """

    def _con_horario(self, is_fixed):
        return aplicar_patch(
            Borrador(name="Programacion movil", is_fixed=is_fixed),
            BorradorPatch(
                schedule=[
                    BloqueHorario(day="Martes", start_time=1200, end_time=1320),
                    BloqueHorario(day="Sabado", start_time=600, end_time=780),
                ]
            ),
        )

    def test_un_horario_concreto_vuelve_fija_la_actividad(self):
        assert self._con_horario(is_fixed=False).is_fixed is True

    def test_tambien_cuando_no_se_habia_dicho_nada(self):
        assert self._con_horario(is_fixed=None).is_fixed is True

    def test_no_se_pierde_ningun_dia(self):
        borrador = self._con_horario(is_fixed=False)

        assert [b.day for b in borrador.schedule] == ["Martes", "Sabado"]

    def test_sin_horario_lo_que_dijo_el_usuario_se_respeta(self):
        borrador = aplicar_patch(
            Borrador(name="Estudiar", is_fixed=False),
            BorradorPatch(duracion_minutos=120),
        )

        assert borrador.is_fixed is False
