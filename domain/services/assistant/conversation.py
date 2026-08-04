"""El bucle de conversacion del asistente.

Un turno del usuario puede necesitar varias vueltas con el modelo: extraer lo
que dijo, consultar la agenda, y recien entonces responder. El bucle termina
cuando el modelo devuelve texto sin tools, o cuando propone algo.

Toda la logica determinista vive aca y no en el prompt. El modelo extrae y
decide; combinar, validar y ejecutar es trabajo de este servicio. Esa
separacion es lo que permite que un modelo irregular falle sin llevarse la
conversacion por delante.
"""

import json
import logging
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import ValidationError

from domain.ports.outbound.conversational_llm_port import (
    ConversationalLLMPort,
    InvocacionTool,
)
from domain.services.assistant.context_builder import BloqueAgenda, construir_contexto
from domain.services.assistant.draft import aplicar_patch
from domain.services.assistant.system_prompt import SYSTEM_PROMPT
from domain.services.assistant.tools import (
    TOOLS_DE_LECTURA,
    TOOLS_DE_PROPUESTA,
    definiciones_openai,
    es_tool_conocida,
)
from schemas.assistant import Borrador, BorradorPatch

logger = logging.getLogger(__name__)

# Tope de vueltas por turno. Un modelo que pide tools sin parar no puede
# colgar la peticion; a partir de aca se le exige que responda con texto.
MAX_ITERACIONES = 6

_PROPUESTAS = {
    "proponer_actividad": "crear",
    "proponer_modificacion": "modificar",
    "proponer_eliminacion": "eliminar",
    "proponer_regeneracion": "regenerar",
}

# Estas necesitan senalar una actividad concreta. Sin id no hay nada que
# senalar, y proponer a ciegas podria borrar o cambiar lo que no era.
_PROPUESTAS_QUE_EXIGEN_ID = {"proponer_modificacion", "proponer_eliminacion"}

_RESPUESTA_VACIA = "Perdon, no te entendi. Me lo repetis?"


class FuenteDeDatos(ABC):
    """Lo que el asistente puede leer del usuario.

    Se ejecuta en el servidor, en el mismo proceso: con el backend duenio de
    los datos, una tool de lectura ya no necesita ida y vuelta al cliente.
    """

    @abstractmethod
    def agenda(self) -> list[BloqueAgenda]: ...

    @abstractmethod
    def buscar_actividad(self, texto: str) -> list[dict[str, Any]]: ...

    @abstractmethod
    def sugerir_tarea(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class Propuesta:
    tipo: Literal["crear", "modificar", "eliminar", "regenerar"]
    borrador: Borrador | None = None
    activity_id: str | None = None


@dataclass(frozen=True)
class ResultadoConversacion:
    tipo: Literal["pregunta", "charla", "propuesta"]
    mensaje: str | None
    borrador: Borrador
    turnos: list[dict[str, Any]]
    propuesta: Propuesta | None = None


def _sin_acentos(texto: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFD", texto.lower())
        if unicodedata.category(c) != "Mn"
    )


def coincidencias(
    actividades: list[dict[str, Any]], texto: str
) -> list[dict[str, Any]]:
    """Busca por nombre aproximado, ignorando acentos y mayusculas.

    Reemplaza el match por substring exacto que hacia el cliente, donde
    "matematica" no encontraba "Matemática".
    """
    buscado = _sin_acentos(texto.strip())
    if not buscado:
        return []
    return [
        a for a in actividades if buscado in _sin_acentos(str(a.get("nombre", "")))
    ]


class ServicioConversacion:
    def __init__(self, modelo: ConversationalLLMPort, datos: FuenteDeDatos):
        self._modelo = modelo
        self._datos = datos

    def responder(
        self,
        *,
        mensaje: str,
        borrador: Borrador,
        turnos: list[dict[str, Any]],
        ahora: datetime,
        ya_pregunte: list[str] | None = None,
        energia: str | None = None,
    ) -> ResultadoConversacion:
        agenda = self._datos.agenda()
        contexto = construir_contexto(
            ahora=ahora,
            agenda=agenda,
            borrador=borrador,
            ya_pregunte=ya_pregunte,
            energia=energia,
        )

        # Los turnos previos viajan verbatim: las invocaciones y sus
        # resultados vuelven al modelo tal como los emitio, no parafraseados.
        # Que reciba de vuelta su propio JSON estructurado es lo que evita que
        # tenga que re-deducirlo de la prosa.
        turnos_nuevos = list(turnos) + [{"role": "user", "content": mensaje}]
        tools = definiciones_openai()

        for _ in range(MAX_ITERACIONES):
            mensajes = [
                {
                    "role": "system",
                    "content": (
                        f"{SYSTEM_PROMPT}\n\n"
                        f"# Contexto\n{json.dumps(contexto, ensure_ascii=False)}"
                    ),
                }
            ] + turnos_nuevos

            respuesta = self._modelo.conversar(mensajes, tools)

            if not respuesta.pide_tools:
                return ResultadoConversacion(
                    tipo="pregunta",
                    mensaje=respuesta.texto or _RESPUESTA_VACIA,
                    borrador=borrador,
                    turnos=turnos_nuevos
                    + [{"role": "assistant", "content": respuesta.texto or ""}],
                    propuesta=None,
                )

            turnos_nuevos.append(_turno_del_asistente(respuesta))

            propuesta = self._propuesta_de(respuesta.invocaciones, borrador)
            if propuesta:
                return ResultadoConversacion(
                    tipo="propuesta",
                    mensaje=respuesta.texto,
                    borrador=borrador,
                    turnos=turnos_nuevos,
                    propuesta=propuesta,
                )

            # Cada invocacion necesita su resultado, incluso las que se
            # rechazan: un tool_call sin respuesta deja la conversacion
            # invalida para la API en el turno siguiente.
            for invocacion in respuesta.invocaciones:
                borrador, resultado = self._ejecutar(invocacion, borrador)
                turnos_nuevos.append(
                    {
                        "role": "tool",
                        "tool_call_id": invocacion.id,
                        "content": json.dumps(resultado, ensure_ascii=False),
                    }
                )

            # El borrador cambio, asi que el contexto tambien.
            contexto = construir_contexto(
                ahora=ahora,
                agenda=agenda,
                borrador=borrador,
                ya_pregunte=ya_pregunte,
                energia=energia,
            )

        logger.warning("Se agoto el tope de iteraciones del asistente.")
        return ResultadoConversacion(
            tipo="pregunta",
            mensaje=_RESPUESTA_VACIA,
            borrador=borrador,
            turnos=turnos_nuevos,
            propuesta=None,
        )

    def _propuesta_de(
        self, invocaciones: list[InvocacionTool], borrador: Borrador
    ) -> Propuesta | None:
        for invocacion in invocaciones:
            if invocacion.nombre not in TOOLS_DE_PROPUESTA:
                continue

            activity_id = invocacion.argumentos.get("activity_id")
            if invocacion.nombre in _PROPUESTAS_QUE_EXIGEN_ID and not activity_id:
                logger.info("Propuesta sin activity_id, se ignora: %s", invocacion.nombre)
                continue

            # Proponer un borrador a medias produce una tarjeta de
            # confirmacion con huecos. Se prefiere volver a preguntar.
            necesita_borrador = invocacion.nombre in {
                "proponer_actividad",
                "proponer_modificacion",
            }
            if necesita_borrador and not borrador.esta_completo:
                logger.info(
                    "Propuesta con borrador incompleto, falta: %s",
                    borrador.campos_faltantes,
                )
                continue

            return Propuesta(
                tipo=_PROPUESTAS[invocacion.nombre],
                borrador=borrador if necesita_borrador else None,
                activity_id=activity_id,
            )
        return None

    def _ejecutar(
        self, invocacion: InvocacionTool, borrador: Borrador
    ) -> tuple[Borrador, dict[str, Any]]:
        if not es_tool_conocida(invocacion.nombre):
            logger.warning("Tool desconocida: %s", invocacion.nombre)
            return borrador, {"error": "Esa herramienta no existe."}

        if invocacion.nombre == "actualizar_borrador":
            return self._actualizar_borrador(invocacion, borrador)

        if invocacion.nombre in TOOLS_DE_LECTURA:
            return borrador, self._leer(invocacion)

        return borrador, {"ok": True}

    def _actualizar_borrador(
        self, invocacion: InvocacionTool, borrador: Borrador
    ) -> tuple[Borrador, dict[str, Any]]:
        try:
            patch = BorradorPatch(**invocacion.argumentos)
        except ValidationError as exc:
            # El modelo emitio algo fuera de contrato. Se descarta el parche y
            # se le dice por que: puede corregirlo en la vuelta siguiente.
            logger.info("Patch invalido: %s", exc)
            return borrador, {
                "error": "Algunos campos no son validos.",
                "detalle": exc.errors()[0].get("msg") if exc.errors() else None,
            }

        actualizado = aplicar_patch(borrador, patch)
        # El resultado le devuelve que sigue faltando, para que pregunte lo
        # siguiente sin tener que deducirlo del contexto.
        return actualizado, {
            "ok": True,
            "falta": actualizado.campos_faltantes,
            "completo": actualizado.esta_completo,
        }

    def _leer(self, invocacion: InvocacionTool) -> dict[str, Any]:
        try:
            if invocacion.nombre == "consultar_agenda":
                return {
                    "agenda": [
                        {
                            "id": b.id_actividad,
                            "nombre": b.nombre,
                            "dia": b.dia,
                            "inicio": b.inicio,
                            "fin": b.fin,
                        }
                        for b in self._datos.agenda()
                    ]
                }

            if invocacion.nombre == "buscar_actividad":
                encontradas = self._datos.buscar_actividad(
                    str(invocacion.argumentos.get("texto", ""))
                )
                return {"resultados": encontradas, "cantidad": len(encontradas)}

            return self._datos.sugerir_tarea()
        except Exception as exc:
            # Un fallo leyendo datos no deberia cortar la conversacion: el
            # modelo puede decirle al usuario que no pudo consultarlo.
            logger.warning("Fallo la tool %s: %s", invocacion.nombre, exc)
            return {"error": "No se pudo consultar ese dato ahora."}


def _turno_del_asistente(respuesta) -> dict[str, Any]:
    """El turno del modelo en el formato que la API espera de vuelta."""
    return {
        "role": "assistant",
        "content": respuesta.texto or "",
        "tool_calls": [
            {
                "id": i.id,
                "type": "function",
                "function": {
                    "name": i.nombre,
                    "arguments": json.dumps(i.argumentos, ensure_ascii=False),
                },
            }
            for i in respuesta.invocaciones
        ],
    }
