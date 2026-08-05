"""Corre las conversaciones doradas contra un modelo guionado.

Verifica la orquestacion en escenarios reales, sin red: que el bucle acumule,
ejecute tools y proponga como corresponde en cada caso.

Lo que NO verifica es que un modelo real sepa producir ese guion. Eso lo mide
scripts/eval_assistant.py contra el proveedor de verdad, y es un riesgo
distinto: aca falla el codigo, alla falla el modelo.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from domain.ports.outbound.conversational_llm_port import (
    InvocacionTool,
    RespuestaConversacional,
)
from domain.services.assistant.context_builder import BloqueAgenda
from domain.services.assistant.conversation import (
    FuenteDeDatos,
    ServicioConversacion,
    coincidencias,
)
from schemas.assistant import Borrador

GOLDEN = Path(__file__).parent / "golden"
AHORA = datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)  # lunes 09:00


def cargar_casos():
    return sorted(GOLDEN.glob("*.yaml"))


class ModeloDelGuion:
    """Devuelve lo que el fixture dicta, una respuesta por vuelta."""

    def __init__(self, guion: list[dict]):
        self.guion = list(guion or [])
        self.tools_invocadas: list[str] = []

    def conversar(self, mensajes, tools):
        if not self.guion:
            return RespuestaConversacional(texto="(fin del guion)")

        paso = self.guion.pop(0)
        invocaciones = [
            InvocacionTool(
                id=f"call-{i}",
                nombre=t["nombre"],
                argumentos=t.get("argumentos", {}),
            )
            for i, t in enumerate(paso.get("tools", []))
        ]
        self.tools_invocadas.extend(i.nombre for i in invocaciones)
        return RespuestaConversacional(
            texto=paso.get("texto"), invocaciones=invocaciones
        )


class DatosDelCaso(FuenteDeDatos):
    def __init__(self, caso: dict):
        self._agenda = [
            BloqueAgenda(
                id_actividad=b["id"],
                nombre=b["nombre"],
                dia=b["dia"],
                inicio=b["inicio"],
                fin=b["fin"],
            )
            for b in caso.get("agenda", [])
        ]
        self._actividades = caso.get("actividades", [])

    def agenda(self):
        return self._agenda

    def buscar_actividad(self, texto):
        return coincidencias(self._actividades, texto)

    def sugerir_tarea(self):
        return {"candidatas": self._actividades}


@pytest.mark.parametrize("ruta", cargar_casos(), ids=lambda p: p.stem)
def test_conversacion_dorada(ruta):
    caso = yaml.safe_load(ruta.read_text())
    datos = DatosDelCaso(caso)

    borrador = Borrador()
    turnos: list[dict] = []

    for indice, paso in enumerate(caso["turnos"], start=1):
        modelo = ModeloDelGuion(paso.get("guion", []))
        servicio = ServicioConversacion(modelo=modelo, datos=datos)

        previo = borrador
        resultado = servicio.responder(
            mensaje=paso["usuario"],
            borrador=borrador,
            turnos=turnos,
            ahora=AHORA,
        )
        borrador, turnos = resultado.borrador, resultado.turnos

        _verificar(
            espera=paso.get("espera", {}),
            resultado=resultado,
            previo=previo,
            modelo=modelo,
            donde=f"{ruta.stem}, turno {indice}",
        )


def _verificar(*, espera, resultado, previo, modelo, donde):
    if "tipo" in espera:
        assert resultado.tipo == espera["tipo"], f"{donde}: tipo de respuesta"

    if "propuesta" in espera:
        assert resultado.propuesta is not None, f"{donde}: se esperaba una propuesta"
        assert resultado.propuesta.tipo == espera["propuesta"], f"{donde}: tipo"

    if "activity_id" in espera:
        assert resultado.propuesta.activity_id == espera["activity_id"], donde

    # El borrador es el contrato, no el texto de las preguntas: asertar frases
    # exactas se rompe con cada ajuste del prompt y no protege nada.
    for campo, valor in (espera.get("draft") or {}).items():
        actual = getattr(resultado.borrador, campo)
        assert actual == valor, f"{donde}: draft.{campo} = {actual!r}, esperaba {valor!r}"

    for campo in espera.get("draft_conserva", []):
        anterior = getattr(previo, campo)
        actual = getattr(resultado.borrador, campo)
        assert actual == anterior, (
            f"{donde}: se perdio draft.{campo} "
            f"({anterior!r} -> {actual!r}). Esto es el 'se olvida'."
        )

    if espera.get("draft_vacio"):
        assert resultado.borrador == Borrador(), f"{donde}: el borrador no debia tocarse"

    if "schedule_dias" in espera:
        dias = [b.day for b in resultado.borrador.schedule]
        assert dias == espera["schedule_dias"], f"{donde}: dias del horario"

    if "tools" in espera:
        for esperada in espera["tools"]:
            assert esperada in modelo.tools_invocadas, f"{donde}: falto {esperada}"
        if espera["tools"] == []:
            assert modelo.tools_invocadas == [], f"{donde}: no debia invocar tools"


def test_hay_al_menos_doce_casos():
    """El plan fija doce escenarios minimos; menos deja huecos conocidos."""
    assert len(cargar_casos()) >= 12
