"""Tests del bucle de conversacion.

El modelo se reemplaza por uno guionado: se le dicta que devolver en cada
iteracion. Asi se prueba la orquestacion —que tool se ejecuta, que vuelve al
modelo, cuando termina el turno— sin depender de que un proveedor real se
comporte.
"""

from datetime import datetime, timezone

import pytest

from domain.ports.outbound.conversational_llm_port import (
    InvocacionTool,
    RespuestaConversacional,
)
from domain.services.assistant.context_builder import BloqueAgenda
from domain.services.assistant.conversation import (
    MAX_ITERACIONES,
    FuenteDeDatos,
    ServicioConversacion,
)
from schemas.assistant import BloqueHorario, Borrador

AHORA = datetime(2026, 8, 3, 14, 30, tzinfo=timezone.utc)


class ModeloGuionado:
    """Devuelve las respuestas dictadas, una por iteracion."""

    def __init__(self, *respuestas: RespuestaConversacional):
        self.respuestas = list(respuestas)
        self.llamadas: list[list[dict]] = []

    def conversar(self, mensajes, tools):
        self.llamadas.append(mensajes)
        if not self.respuestas:
            return RespuestaConversacional(texto="sin guion")
        return self.respuestas.pop(0)


class DatosDePrueba(FuenteDeDatos):
    def __init__(self, agenda=None, actividades=None):
        self._agenda = agenda or []
        self._actividades = actividades or []
        self.sugerencias_pedidas = 0

    def agenda(self):
        return self._agenda

    def buscar_actividad(self, texto):
        from domain.services.assistant.conversation import coincidencias

        return coincidencias(self._actividades, texto)

    def sugerir_tarea(self):
        self.sugerencias_pedidas += 1
        return {"sugerencia": "Estudiar Calculo"}


def servicio(modelo, datos=None):
    return ServicioConversacion(modelo=modelo, datos=datos or DatosDePrueba())


def texto(t):
    return RespuestaConversacional(texto=t)


def tool(nombre, argumentos=None, id_="call-1"):
    return RespuestaConversacional(
        invocaciones=[InvocacionTool(id=id_, nombre=nombre, argumentos=argumentos or {})]
    )


class TestRespuestaDeTexto:
    def test_un_texto_sin_tools_es_una_pregunta(self):
        resultado = servicio(ModeloGuionado(texto("Que dias?"))).responder(
            mensaje="clase de calculo", borrador=Borrador(), turnos=[], ahora=AHORA
        )

        assert resultado.tipo == "pregunta"
        assert resultado.mensaje == "Que dias?"

    def test_el_mensaje_del_usuario_llega_al_modelo(self):
        modelo = ModeloGuionado(texto("ok"))

        servicio(modelo).responder(
            mensaje="clase de calculo", borrador=Borrador(), turnos=[], ahora=AHORA
        )

        assert modelo.llamadas[0][-1] == {
            "role": "user",
            "content": "clase de calculo",
        }

    def test_el_contexto_viaja_en_el_system(self):
        modelo = ModeloGuionado(texto("ok"))

        servicio(modelo).responder(
            mensaje="hola", borrador=Borrador(), turnos=[], ahora=AHORA
        )

        system = modelo.llamadas[0][0]
        assert system["role"] == "system"
        assert "huecos_libres_hoy" in system["content"]


class TestBorrador:
    def test_actualizar_borrador_acumula(self):
        modelo = ModeloGuionado(
            tool("actualizar_borrador", {"name": "Calculo"}),
            texto("Que dias la tenes?"),
        )

        resultado = servicio(modelo).responder(
            mensaje="clase de calculo", borrador=Borrador(), turnos=[], ahora=AHORA
        )

        assert resultado.borrador.name == "Calculo"

    def test_conserva_lo_que_ya_sabia(self):
        """El test del 'se olvida', ahora de punta a punta."""
        previo = Borrador(name="Calculo", activity_type="clase")
        modelo = ModeloGuionado(
            tool("actualizar_borrador", {"is_fixed": True}),
            texto("A que hora?"),
        )

        resultado = servicio(modelo).responder(
            mensaje="siempre a la misma hora",
            borrador=previo,
            turnos=[],
            ahora=AHORA,
        )

        assert resultado.borrador.name == "Calculo"
        assert resultado.borrador.is_fixed is True

    def test_el_modelo_recibe_que_falta_todavia(self):
        """El resultado de la tool le dice que sigue faltando, para que
        pregunte lo siguiente sin tener que deducirlo."""
        modelo = ModeloGuionado(
            tool("actualizar_borrador", {"name": "Calculo"}), texto("ok")
        )

        servicio(modelo).responder(
            mensaje="calculo", borrador=Borrador(), turnos=[], ahora=AHORA
        )

        resultados = [m for m in modelo.llamadas[1] if m.get("role") == "tool"]
        assert "activity_type" in resultados[0]["content"]

    def test_un_patch_invalido_no_tumba_el_turno(self):
        """El modelo puede emitir un valor fuera de rango; se descarta el
        parche y la conversacion sigue."""
        modelo = ModeloGuionado(
            tool("actualizar_borrador", {"priority": "urgentisima"}),
            texto("Que dias?"),
        )

        resultado = servicio(modelo).responder(
            mensaje="calculo", borrador=Borrador(), turnos=[], ahora=AHORA
        )

        assert resultado.tipo == "pregunta"
        assert resultado.borrador.priority is None


class TestToolsDeLectura:
    def test_consultar_agenda_devuelve_los_bloques(self):
        datos = DatosDePrueba(
            agenda=[BloqueAgenda("act-1", "Calculo", dia=0, inicio=600, fin=720)]
        )
        modelo = ModeloGuionado(tool("consultar_agenda"), texto("Tenes Calculo"))

        servicio(modelo, datos).responder(
            mensaje="que tengo hoy?", borrador=Borrador(), turnos=[], ahora=AHORA
        )

        resultado = [m for m in modelo.llamadas[1] if m.get("role") == "tool"][0]
        assert "Calculo" in resultado["content"]

    def test_buscar_actividad_ignora_acentos_y_caja(self):
        datos = DatosDePrueba(
            actividades=[{"id": "act-1", "nombre": "Matemática Discreta"}]
        )
        modelo = ModeloGuionado(
            tool("buscar_actividad", {"texto": "matematica"}), texto("La encontre")
        )

        servicio(modelo, datos).responder(
            mensaje="borra matematica", borrador=Borrador(), turnos=[], ahora=AHORA
        )

        resultado = [m for m in modelo.llamadas[1] if m.get("role") == "tool"][0]
        assert "act-1" in resultado["content"]

    def test_sugerir_tarea_consulta_la_fuente(self):
        datos = DatosDePrueba()
        modelo = ModeloGuionado(tool("sugerir_tarea"), texto("Podrias estudiar"))

        servicio(modelo, datos).responder(
            mensaje="que hago?", borrador=Borrador(), turnos=[], ahora=AHORA
        )

        assert datos.sugerencias_pedidas == 1


class TestPropuestas:
    def test_proponer_actividad_termina_el_turno(self):
        borrador = Borrador(
            name="Calculo", activity_type="clase", is_fixed=False, duracion_minutos=60
        )
        modelo = ModeloGuionado(tool("proponer_actividad"))

        resultado = servicio(modelo).responder(
            mensaje="dale", borrador=borrador, turnos=[], ahora=AHORA
        )

        assert resultado.tipo == "propuesta"
        assert resultado.propuesta.tipo == "crear"

    def test_la_propuesta_lleva_el_borrador_completo(self):
        borrador = Borrador(
            name="Calculo", activity_type="clase", is_fixed=False, duracion_minutos=60
        )
        modelo = ModeloGuionado(tool("proponer_actividad"))

        resultado = servicio(modelo).responder(
            mensaje="dale", borrador=borrador, turnos=[], ahora=AHORA
        )

        assert resultado.propuesta.borrador.name == "Calculo"

    def test_no_se_propone_un_borrador_incompleto(self):
        """El modelo puede adelantarse. En vez de proponer algo a medias, se
        vuelve a preguntar."""
        modelo = ModeloGuionado(
            tool("proponer_actividad"), texto("Me falta saber los dias")
        )

        resultado = servicio(modelo).responder(
            mensaje="dale", borrador=Borrador(name="Calculo"), turnos=[], ahora=AHORA
        )

        assert resultado.tipo == "pregunta"

    def test_proponer_eliminacion_lleva_el_id(self):
        modelo = ModeloGuionado(
            tool("proponer_eliminacion", {"activity_id": "act-9"})
        )

        resultado = servicio(modelo).responder(
            mensaje="borrala", borrador=Borrador(), turnos=[], ahora=AHORA
        )

        assert resultado.propuesta.tipo == "eliminar"
        assert resultado.propuesta.activity_id == "act-9"

    def test_proponer_regeneracion_no_necesita_nada(self):
        modelo = ModeloGuionado(tool("proponer_regeneracion"))

        resultado = servicio(modelo).responder(
            mensaje="reorganiza mi semana", borrador=Borrador(), turnos=[], ahora=AHORA
        )

        assert resultado.propuesta.tipo == "regenerar"

    def test_eliminar_sin_id_no_propone(self):
        """Sin id no hay nada que senalar; proponer a ciegas podria borrar
        lo que no era."""
        modelo = ModeloGuionado(tool("proponer_eliminacion"), texto("Cual?"))

        resultado = servicio(modelo).responder(
            mensaje="borrala", borrador=Borrador(), turnos=[], ahora=AHORA
        )

        assert resultado.tipo == "pregunta"


class TestRobustez:
    def test_una_tool_inventada_se_ignora(self):
        modelo = ModeloGuionado(tool("formatear_disco"), texto("Perdon, que decias?"))

        resultado = servicio(modelo).responder(
            mensaje="hola", borrador=Borrador(), turnos=[], ahora=AHORA
        )

        assert resultado.tipo == "pregunta"

    def test_el_bucle_tiene_tope(self):
        """Un modelo que pide tools sin parar no puede colgar la peticion."""
        modelo = ModeloGuionado(
            *[tool("actualizar_borrador", {"name": f"n{i}"}) for i in range(20)]
        )

        resultado = servicio(modelo).responder(
            mensaje="hola", borrador=Borrador(), turnos=[], ahora=AHORA
        )

        assert len(modelo.llamadas) <= MAX_ITERACIONES
        assert resultado.tipo in {"pregunta", "charla"}

    def test_sin_texto_ni_tools_devuelve_algo_igual(self):
        """Un modelo puede responder vacio; el usuario no puede quedarse
        mirando la nada."""
        resultado = servicio(ModeloGuionado(RespuestaConversacional())).responder(
            mensaje="hola", borrador=Borrador(), turnos=[], ahora=AHORA
        )

        assert resultado.mensaje


class TestTurnosVerbatim:
    def test_las_invocaciones_vuelven_tal_cual_al_siguiente_turno(self):
        """El corazon del arreglo: el modelo recibe de vuelta su propio JSON
        estructurado, no una parafrasis en prosa."""
        modelo = ModeloGuionado(
            tool("actualizar_borrador", {"name": "Calculo"}), texto("Que dias?")
        )

        resultado = servicio(modelo).responder(
            mensaje="calculo", borrador=Borrador(), turnos=[], ahora=AHORA
        )

        con_tools = [t for t in resultado.turnos if t.get("tool_calls")]
        assert con_tools
        assert con_tools[0]["tool_calls"][0]["function"]["name"] == "actualizar_borrador"

    def test_los_turnos_previos_se_conservan(self):
        previos = [
            {"role": "user", "content": "hola"},
            {"role": "assistant", "content": "hola!"},
        ]

        resultado = servicio(ModeloGuionado(texto("y?"))).responder(
            mensaje="calculo", borrador=Borrador(), turnos=previos, ahora=AHORA
        )

        assert resultado.turnos[0] == previos[0]
        assert resultado.turnos[1] == previos[1]

    def test_toda_invocacion_queda_emparejada_con_su_resultado(self):
        """Podar un tool_call sin su resultado deja la conversacion invalida
        para la API."""
        modelo = ModeloGuionado(
            tool("actualizar_borrador", {"name": "Calculo"}), texto("ok")
        )

        resultado = servicio(modelo).responder(
            mensaje="calculo", borrador=Borrador(), turnos=[], ahora=AHORA
        )

        pedidos = {
            llamada["id"]
            for t in resultado.turnos
            for llamada in t.get("tool_calls", [])
        }
        respondidos = {
            t["tool_call_id"] for t in resultado.turnos if t.get("role") == "tool"
        }
        assert pedidos == respondidos


class TestSolapamiento:
    """Comparar rangos horarios es aritmetica, justo donde estos modelos se
    equivocan. El servidor lo resuelve y se lo entrega servido."""

    def _agenda(self):
        return [BloqueAgenda("act-1", "Calculo", dia=1, inicio=600, fin=720)]

    def test_avisa_cuando_el_horario_choca(self):
        datos = DatosDePrueba(agenda=self._agenda())
        modelo = ModeloGuionado(
            tool(
                "actualizar_borrador",
                {
                    "name": "Gimnasio",
                    "schedule": [{"day": "Martes", "start_time": 630, "end_time": 700}],
                },
            ),
            texto("Ojo que se superpone con Calculo."),
        )

        servicio(modelo, datos).responder(
            mensaje="gimnasio el martes 10:30", borrador=Borrador(), turnos=[], ahora=AHORA
        )

        resultado = [m for m in modelo.llamadas[1] if m.get("role") == "tool"][0]
        assert "solapa_con" in resultado["content"]
        assert "Calculo" in resultado["content"]

    def test_no_avisa_si_no_choca(self):
        datos = DatosDePrueba(agenda=self._agenda())
        modelo = ModeloGuionado(
            tool(
                "actualizar_borrador",
                {
                    "name": "Gimnasio",
                    "schedule": [{"day": "Martes", "start_time": 900, "end_time": 960}],
                },
            ),
            texto("Listo"),
        )

        servicio(modelo, datos).responder(
            mensaje="gimnasio el martes 15:00", borrador=Borrador(), turnos=[], ahora=AHORA
        )

        resultado = [m for m in modelo.llamadas[1] if m.get("role") == "tool"][0]
        assert "solapa_con" not in resultado["content"]

    def test_otro_dia_no_es_solapamiento(self):
        datos = DatosDePrueba(agenda=self._agenda())
        modelo = ModeloGuionado(
            tool(
                "actualizar_borrador",
                {
                    "name": "Gimnasio",
                    "schedule": [{"day": "Lunes", "start_time": 600, "end_time": 720}],
                },
            ),
            texto("Listo"),
        )

        servicio(modelo, datos).responder(
            mensaje="gimnasio el lunes", borrador=Borrador(), turnos=[], ahora=AHORA
        )

        resultado = [m for m in modelo.llamadas[1] if m.get("role") == "tool"][0]
        assert "solapa_con" not in resultado["content"]

    def test_bloques_pegados_no_se_solapan(self):
        """Terminar a las 12 y empezar a las 12 no es un choque."""
        datos = DatosDePrueba(agenda=self._agenda())
        modelo = ModeloGuionado(
            tool(
                "actualizar_borrador",
                {
                    "name": "Gimnasio",
                    "schedule": [{"day": "Martes", "start_time": 720, "end_time": 780}],
                },
            ),
            texto("Listo"),
        )

        servicio(modelo, datos).responder(
            mensaje="gimnasio martes 12", borrador=Borrador(), turnos=[], ahora=AHORA
        )

        resultado = [m for m in modelo.llamadas[1] if m.get("role") == "tool"][0]
        assert "solapa_con" not in resultado["content"]


class TestPresupuestoDeTiempo:
    """Contar iteraciones no acota la duracion de un turno: cada vuelta puede
    tardar 25s por proveedor y con failover se triplica. Sin tope de tiempo
    real, un turno lento supera el limite del proxy y el usuario recibe un 502
    —sin mensaje y sin forma de recuperarse— en vez de una respuesta."""

    def test_devuelve_algo_util_cuando_se_acaba_el_tiempo(self):
        from unittest.mock import patch

        from domain.services.assistant.conversation import PRESUPUESTO_SEGUNDOS

        modelo = ModeloGuionado(
            *[tool("actualizar_borrador", {"name": f"n{i}"}) for i in range(6)]
        )

        # El reloj salta mas alla del presupuesto despues de la primera vuelta.
        tiempos = iter([0.0, 0.0, PRESUPUESTO_SEGUNDOS + 1] + [PRESUPUESTO_SEGUNDOS + 1] * 20)
        with patch("time.monotonic", lambda: next(tiempos)):
            resultado = servicio(modelo).responder(
                mensaje="hola", borrador=Borrador(), turnos=[], ahora=AHORA
            )

        assert resultado.tipo == "pregunta"
        assert resultado.mensaje
        # No agoto las seis vueltas: corto por tiempo.
        assert len(modelo.llamadas) < 6

    def test_un_turno_rapido_no_se_corta(self):
        from unittest.mock import patch

        modelo = ModeloGuionado(
            tool("actualizar_borrador", {"name": "Calculo"}), texto("Que dias?")
        )

        with patch("time.monotonic", lambda: 0.0):
            resultado = servicio(modelo).responder(
                mensaje="calculo", borrador=Borrador(), turnos=[], ahora=AHORA
            )

        assert resultado.mensaje == "Que dias?"
        assert resultado.borrador.name == "Calculo"

    def test_conserva_el_borrador_al_cortar(self):
        """Quedarse sin tiempo no puede costar lo que ya se entendio."""
        from unittest.mock import patch

        from domain.services.assistant.conversation import PRESUPUESTO_SEGUNDOS

        modelo = ModeloGuionado(
            *[tool("actualizar_borrador", {"name": "Calculo"}) for _ in range(6)]
        )
        tiempos = iter([0.0, 0.0, PRESUPUESTO_SEGUNDOS + 1] + [PRESUPUESTO_SEGUNDOS + 1] * 20)

        with patch("time.monotonic", lambda: next(tiempos)):
            resultado = servicio(modelo).responder(
                mensaje="calculo", borrador=Borrador(), turnos=[], ahora=AHORA
            )

        assert resultado.borrador.name == "Calculo"


class TestNoAfirmarLoQueNoHizo:
    """Nada se guarda hasta que el usuario confirma una propuesta.

    Un turno que termina en texto no persistio nada, asi que decir que algo
    "quedo actualizado" es falso siempre. El usuario cierra el chat creyendo
    que su horario cambio, y no cambio: eso paso en produccion.
    """

    def test_se_le_corrige_y_vuelve_a_intentar(self):
        modelo = ModeloGuionado(
            texto("Listo, la tarea PEPE quedó actualizada."),
            texto("¿Quieres que la aplique con esos datos?"),
        )

        resultado = servicio(modelo).responder(
            mensaje="nada mas", borrador=Borrador(), turnos=[], ahora=AHORA
        )

        assert resultado.mensaje == "¿Quieres que la aplique con esos datos?"

    def test_la_correccion_le_llega_al_modelo(self):
        modelo = ModeloGuionado(
            texto("Ya está creada."),
            texto("¿La creo?"),
        )

        servicio(modelo).responder(
            mensaje="dale", borrador=Borrador(), turnos=[], ahora=AHORA
        )

        correccion = modelo.llamadas[1][-1]
        assert correccion["role"] == "system"
        assert "No has guardado nada" in correccion["content"]

    def test_si_insiste_el_usuario_ve_la_verdad(self):
        modelo = ModeloGuionado(
            texto("Ya la guardé."),
            texto("Sí, ya la guardé, no te preocupes."),
        )

        resultado = servicio(modelo).responder(
            mensaje="seguro?", borrador=Borrador(), turnos=[], ahora=AHORA
        )

        assert "Todavía no guardé nada" in resultado.mensaje
        assert resultado.propuesta is None

    def test_el_futuro_no_cuenta_como_afirmacion(self):
        # Hablar de lo que va a pasar es legitimo; lo que no se puede es dar
        # por hecho algo que no ocurrio.
        modelo = ModeloGuionado(texto("Cuando tenga los dias, la agrego."))

        resultado = servicio(modelo).responder(
            mensaje="dale", borrador=Borrador(), turnos=[], ahora=AHORA
        )

        assert resultado.mensaje == "Cuando tenga los dias, la agrego."


class TestSinMarkdown:
    """El chat muestra texto plano: un asterisco es un asterisco.

    El prompt ya lo prohibe y el modelo igual lo escribe. Pedirlo no alcanza.
    """

    def test_se_quitan_las_marcas_del_mensaje(self):
        modelo = ModeloGuionado(texto("**Nombre:** PEPE\n**Tipo:** tarea"))

        resultado = servicio(modelo).responder(
            mensaje="dame los datos", borrador=Borrador(), turnos=[], ahora=AHORA
        )

        assert resultado.mensaje == "Nombre: PEPE\nTipo: tarea"

    def test_el_turno_guardado_conserva_lo_que_dijo_el_modelo(self):
        # Los turnos vuelven al modelo verbatim. Limpiar ahi tambien seria
        # reescribirle su propia memoria.
        modelo = ModeloGuionado(texto("**PEPE**"))

        resultado = servicio(modelo).responder(
            mensaje="dame los datos", borrador=Borrador(), turnos=[], ahora=AHORA
        )

        assert resultado.turnos[-1]["content"] == "**PEPE**"


class TestNoPedirConfirmacionSinProponer:
    """El unico boton que confirma es el de la tarjeta de propuesta.

    Caso real: el modelo dijo "la creo en cuanto me confirmes" sin llamar a
    proponer_actividad. El usuario escribio "Confirmo" y el turno murio.
    """

    def test_se_le_corrige_para_que_proponga(self):
        # El borrador ya esta completo: lo unico que faltaba era que el modelo
        # llamara a la herramienta en vez de prometer que lo haria.
        completo = Borrador(
            name="Programacion movil",
            activity_type="clase",
            is_fixed=True,
            schedule=[
                BloqueHorario(day="Martes", start_time=1200, end_time=1320),
                BloqueHorario(day="Sabado", start_time=600, end_time=780),
            ],
        )
        modelo = ModeloGuionado(
            texto("La clase de programacion movil, la creo en cuanto me confirmes."),
            tool("proponer_actividad"),
        )

        resultado = servicio(modelo).responder(
            mensaje="martes de 8 a 10", borrador=completo, turnos=[], ahora=AHORA
        )

        assert resultado.tipo == "propuesta"

    def test_la_correccion_le_explica_por_que(self):
        modelo = ModeloGuionado(texto("¿Quieres que la cree?"), texto("¿Que dias?"))

        servicio(modelo).responder(
            mensaje="dale", borrador=Borrador(), turnos=[], ahora=AHORA
        )

        correccion = modelo.llamadas[1][-1]
        assert correccion["role"] == "system"
        assert "no tiene nada que confirmar" in correccion["content"]

    def test_una_pregunta_normal_pasa_sin_tocar(self):
        modelo = ModeloGuionado(texto("¿Cuántos minutos dura?"))

        resultado = servicio(modelo).responder(
            mensaje="hola", borrador=Borrador(), turnos=[], ahora=AHORA
        )

        assert resultado.mensaje == "¿Cuántos minutos dura?"
        assert len(modelo.llamadas) == 1
