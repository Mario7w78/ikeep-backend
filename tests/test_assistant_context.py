"""Tests del contexto que recibe el asistente.

Hasta ahora la agenda se le pasaba al modelo como prosa espanola sin ids. Sin
ids no se puede senalar una actividad de forma fiable, y esa es la razon
estructural de que el asistente solo supiera crear: para modificar o eliminar
hay que poder decir cual.
"""

from datetime import datetime, timezone

import pytest

from domain.services.assistant.context_builder import (
    BloqueAgenda,
    construir_contexto,
    huecos_libres,
)
from schemas.assistant import Borrador, BorradorPatch
from domain.services.assistant.draft import aplicar_patch

AHORA = datetime(2026, 8, 3, 14, 30, tzinfo=timezone.utc)  # lunes 14:30


def bloque(nombre="Calculo", dia=0, inicio=600, fin=720, id_actividad="act-1"):
    return BloqueAgenda(
        id_actividad=id_actividad, nombre=nombre, dia=dia, inicio=inicio, fin=fin
    )


class TestHuecosLibres:
    def test_un_dia_sin_nada_es_un_solo_hueco(self):
        assert huecos_libres([], 480, 1320) == [(480, 1320)]

    def test_un_bloque_al_medio_parte_el_dia_en_dos(self):
        assert huecos_libres([(600, 720)], 480, 1320) == [(480, 600), (720, 1320)]

    def test_un_bloque_que_arranca_con_el_dia_no_deja_hueco_antes(self):
        assert huecos_libres([(480, 600)], 480, 1320) == [(600, 1320)]

    def test_un_bloque_que_termina_con_el_dia_no_deja_hueco_despues(self):
        assert huecos_libres([(1200, 1320)], 480, 1320) == [(480, 1200)]

    def test_el_dia_lleno_no_deja_huecos(self):
        assert huecos_libres([(480, 1320)], 480, 1320) == []

    def test_ordena_los_bloques_antes_de_calcular(self):
        """El horario puede venir en cualquier orden."""
        assert huecos_libres([(900, 960), (600, 720)], 480, 1320) == [
            (480, 600),
            (720, 900),
            (960, 1320),
        ]

    def test_los_bloques_solapados_cuentan_como_uno(self):
        """Dos actividades encimadas no dejan un hueco entre ellas."""
        assert huecos_libres([(600, 720), (660, 800)], 480, 1320) == [
            (480, 600),
            (800, 1320),
        ]

    def test_los_bloques_pegados_no_dejan_hueco_de_cero(self):
        assert huecos_libres([(600, 720), (720, 840)], 480, 1320) == [
            (480, 600),
            (840, 1320),
        ]

    def test_ignora_lo_que_cae_fuera_del_dia_util(self):
        assert huecos_libres([(0, 120)], 480, 1320) == [(480, 1320)]

    def test_descarta_huecos_demasiado_cortos_para_servir(self):
        """Un hueco de 10 minutos no es tiempo libre util; ofrecerlo seria
        ruido en el contexto."""
        assert huecos_libres([(480, 600), (610, 1320)], 480, 1320) == []


class TestContexto:
    def test_incluye_el_momento_actual(self):
        contexto = construir_contexto(ahora=AHORA, agenda=[], borrador=Borrador())

        assert contexto["ahora"]["dia"] == "Lunes"
        assert contexto["ahora"]["hora_min"] == 870  # 14:30
        assert contexto["ahora"]["fecha"] == "2026-08-03"

    def test_la_agenda_lleva_los_ids(self):
        """Sin esto no se puede modificar ni eliminar nada."""
        contexto = construir_contexto(
            ahora=AHORA, agenda=[bloque(id_actividad="act-42")], borrador=Borrador()
        )

        assert contexto["agenda"][0]["id"] == "act-42"

    def test_la_agenda_trae_dia_y_horas(self):
        contexto = construir_contexto(
            ahora=AHORA, agenda=[bloque(dia=2, inicio=600, fin=720)], borrador=Borrador()
        )

        item = contexto["agenda"][0]
        assert item["dia"] == "Miercoles"
        assert item["inicio"] == 600
        assert item["fin"] == 720

    def test_los_huecos_son_solo_de_hoy(self):
        """Ocupado el martes, pero hoy es lunes: el lunes sigue libre."""
        contexto = construir_contexto(
            ahora=AHORA,
            agenda=[bloque(dia=1, inicio=600, fin=720)],
            borrador=Borrador(),
            inicio_dia=480,
            fin_dia=1320,
        )

        assert contexto["huecos_libres_hoy"] == [[480, 1320]]

    def test_el_borrador_viaja_en_el_contexto(self):
        """Es la memoria: el modelo tiene que ver lo que ya sabe sin tener
        que releerlo de la prosa de turnos anteriores."""
        borrador = aplicar_patch(Borrador(), BorradorPatch(name="Calculo"))

        contexto = construir_contexto(ahora=AHORA, agenda=[], borrador=borrador)

        assert contexto["borrador"]["name"] == "Calculo"

    def test_expone_lo_que_falta_del_borrador(self):
        contexto = construir_contexto(ahora=AHORA, agenda=[], borrador=Borrador())

        assert "name" in contexto["falta"]

    def test_lleva_lo_que_ya_se_pregunto(self):
        """Rompe el bucle de preguntas repetidas: si el usuario esquivo algo,
        el modelo lo ve y no lo vuelve a pedir."""
        contexto = construir_contexto(
            ahora=AHORA, agenda=[], borrador=Borrador(), ya_pregunte=["difficulty"]
        )

        assert contexto["ya_pregunte"] == ["difficulty"]

    def test_incluye_la_energia_cuando_se_conoce(self):
        contexto = construir_contexto(
            ahora=AHORA, agenda=[], borrador=Borrador(), energia="alta"
        )

        assert contexto["energia"] == "alta"

    def test_omite_la_energia_cuando_no_se_sabe(self):
        """Mandar 'desconocida' invita al modelo a razonar sobre un dato que
        no tiene."""
        contexto = construir_contexto(ahora=AHORA, agenda=[], borrador=Borrador())

        assert "energia" not in contexto

    def test_una_agenda_vacia_no_rompe_nada(self):
        contexto = construir_contexto(ahora=AHORA, agenda=[], borrador=Borrador())

        assert contexto["agenda"] == []
