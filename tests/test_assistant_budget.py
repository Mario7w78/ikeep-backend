"""Tests del presupuesto de contexto.

Reemplaza al viejo "quedate con los ultimos N intercambios". Contar turnos no
sirve: un turno puede ser "si" o puede traer una propuesta con la
configuracion por dia entera, y son dos ordenes de magnitud distintos.

Podar es seguro porque el estado no vive en la prosa sino en el borrador. Lo
que no se puede es separar una invocacion de su resultado: la API rechaza una
conversacion donde un tool_call quedo sin responder.
"""

import pytest

from domain.services.assistant.budget import (
    agrupar_turnos,
    estimar_tokens,
    podar_turnos,
)


def usuario(texto="hola"):
    return {"role": "user", "content": texto}


def asistente(texto="ok"):
    return {"role": "assistant", "content": texto}


def con_tools(id_="call-1", nombre="actualizar_borrador"):
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": id_,
                "type": "function",
                "function": {"name": nombre, "arguments": "{}"},
            }
        ],
    }


def resultado(id_="call-1", contenido="{}"):
    return {"role": "tool", "tool_call_id": id_, "content": contenido}


class TestEstimacion:
    def test_un_texto_vacio_cuesta_poco(self):
        assert estimar_tokens([usuario("")]) < 20

    def test_mas_texto_cuesta_mas(self):
        assert estimar_tokens([usuario("a" * 4000)]) > estimar_tokens([usuario("a")])

    def test_cuenta_los_argumentos_de_las_tools(self):
        """Una propuesta con la configuracion por dia pesa, aunque el content
        del turno este vacio."""
        pesado = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "c",
                    "type": "function",
                    "function": {"name": "x", "arguments": "y" * 4000},
                }
            ],
        }

        assert estimar_tokens([pesado]) > estimar_tokens([asistente("ok")])


class TestAgrupacion:
    def test_los_turnos_sueltos_son_grupos_de_uno(self):
        grupos = agrupar_turnos([usuario(), asistente()])

        assert [len(g) for g in grupos] == [1, 1]

    def test_una_invocacion_y_su_resultado_son_un_solo_grupo(self):
        grupos = agrupar_turnos([usuario(), con_tools(), resultado()])

        assert [len(g) for g in grupos] == [1, 2]

    def test_varias_invocaciones_de_un_turno_van_juntas(self):
        turnos = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "a", "type": "function", "function": {"name": "x", "arguments": "{}"}},
                    {"id": "b", "type": "function", "function": {"name": "y", "arguments": "{}"}},
                ],
            },
            resultado("a"),
            resultado("b"),
        ]

        assert [len(g) for g in agrupar_turnos(turnos)] == [3]

    def test_un_resultado_huerfano_no_rompe_la_agrupacion(self):
        """Puede pasar si el cliente reenvia turnos manipulados."""
        grupos = agrupar_turnos([resultado("sin-padre"), usuario()])

        assert [len(g) for g in grupos] == [1, 1]


class TestPoda:
    def test_si_entra_no_se_poda_nada(self):
        turnos = [usuario(), asistente()]

        assert podar_turnos(turnos, presupuesto=10_000) == turnos

    def test_se_van_los_mas_viejos(self):
        turnos = [usuario("viejo"), asistente("viejo"), usuario("nuevo")]

        podados = podar_turnos(turnos, presupuesto=estimar_tokens([usuario("nuevo")]) + 5)

        assert podados[-1]["content"] == "nuevo"
        assert len(podados) < len(turnos)

    def test_nunca_separa_una_invocacion_de_su_resultado(self):
        """La regla dura. Un tool_call sin respuesta invalida la conversacion
        entera para la API."""
        turnos = [
            usuario("a" * 2000),
            con_tools("call-1"),
            resultado("call-1", "b" * 2000),
            usuario("ahora"),
        ]

        podados = podar_turnos(turnos, presupuesto=200)

        pedidos = {c["id"] for t in podados for c in t.get("tool_calls", [])}
        respondidos = {t["tool_call_id"] for t in podados if t.get("role") == "tool"}
        assert pedidos == respondidos

    def test_conserva_lo_ultimo_aunque_no_entre(self):
        """Podar hasta dejar la conversacion vacia seria peor que pasarse:
        el modelo no tendria ni la pregunta que tiene que responder."""
        podados = podar_turnos([usuario("a" * 40_000)], presupuesto=10)

        assert len(podados) == 1

    def test_mantiene_el_orden_original(self):
        turnos = [usuario("1"), asistente("2"), usuario("3")]

        podados = podar_turnos(turnos, presupuesto=10_000)

        assert [t["content"] for t in podados] == ["1", "2", "3"]

    def test_una_conversacion_vacia_no_rompe(self):
        assert podar_turnos([], presupuesto=1000) == []

    def test_el_resultado_entra_en_el_presupuesto(self):
        turnos = [usuario("x" * 400) for _ in range(50)]

        podados = podar_turnos(turnos, presupuesto=500)

        # Con margen para el ultimo grupo, que se conserva siempre.
        assert estimar_tokens(podados) <= 500 + estimar_tokens([turnos[-1]])
