#!/usr/bin/env python
"""Corre las conversaciones doradas contra un proveedor real.

Los tests de CI usan un modelo guionado y verifican la orquestacion. Esto
verifica lo otro: que un modelo de verdad, con este prompt y estas tools, sepa
producir ese guion. Es lo unico que mide el riesgo de quedarnos en
Groq/Cerebras, cuyo tool calling multi-turno es irregular.

Los planes gratuitos tienen limites por minuto bastante bajos —Groq da 12.000
tokens/min y una conversacion gasta ~3.500—, asi que el script va despacio a
proposito y espera cuando lo cortan. Una corrida completa lleva varios
minutos; correrla rapido solo produce 429 en cascada, que no miden nada.

Uso:
    venv/bin/python scripts/eval_assistant.py --proveedor groq
    venv/bin/python scripts/eval_assistant.py --caso 01 --repeticiones 1
    venv/bin/python scripts/eval_assistant.py --pausa 30
"""

import argparse
import logging
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml  # noqa: E402

from domain.services.assistant.context_builder import BloqueAgenda  # noqa: E402
from domain.services.assistant.conversation import (  # noqa: E402
    FuenteDeDatos,
    ServicioConversacion,
    coincidencias,
)
from infrastructure.adapters.outbound.llm.openai_tools_adapter import (  # noqa: E402
    OpenAIToolsAdapter,
)
from infrastructure.config.settings import get_settings  # noqa: E402
from schemas.assistant import Borrador  # noqa: E402
from tests.golden_asserts import verificar_conservados, verificar_draft  # noqa: E402

GOLDEN = Path(__file__).resolve().parent.parent / "tests" / "golden"
AHORA = datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)

UMBRAL = 0.90

# Segundos de espera entre conversaciones. 20s deja ~3 por minuto, que es lo
# que tolera el plan gratuito de Groq con conversaciones de ~3.500 tokens.
PAUSA_POR_DEFECTO = 20
MAX_ESPERAS = 4

PROVEEDORES = {
    "groq": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile", "GROQ_API_KEY"),
    "cerebras": ("https://api.cerebras.ai/v1", "gpt-oss-120b", "CEREBRAS_API_KEY"),
    "mistral": ("https://api.mistral.ai/v1", "mistral-small-latest", "MISTRAL_API_KEY"),
}

_SENALES_DE_LIMITE = ("429", "rate_limit", "too_many_requests", "quota", "queue")


def es_limite_de_tasa(error: str) -> bool:
    return any(s in error.lower() for s in _SENALES_DE_LIMITE)


def segundos_sugeridos(error: str) -> float:
    """Los proveedores dicen cuanto esperar; conviene hacerles caso."""
    match = re.search(r"try again in ([\d.]+)\s*s", error, re.IGNORECASE)
    if match:
        return float(match.group(1)) + 1
    match = re.search(r"try again in (\d+)\s*ms", error, re.IGNORECASE)
    if match:
        return float(match.group(1)) / 1000 + 1
    return 15.0


class ModeloConEspera:
    """Envuelve al adaptador y espera cuando el proveedor corta por cuota.

    Solo en esta herramienta. En produccion un 429 debe pasar al siguiente
    proveedor de inmediato, que es lo que hace el failover: hacer esperar a un
    usuario porque se acabo la cuota seria peor que responderle con otro
    modelo.
    """

    def __init__(self, interno):
        self._interno = interno
        self.esperas = 0

    def conversar(self, mensajes, tools):
        ultimo = None
        for intento in range(MAX_ESPERAS):
            try:
                return self._interno.conversar(mensajes, tools)
            except Exception as exc:
                ultimo = exc
                if not es_limite_de_tasa(str(exc)):
                    raise
                espera = segundos_sugeridos(str(exc)) * (intento + 1)
                self.esperas += 1
                print(f"      (limite de tasa, esperando {espera:.0f}s)", flush=True)
                time.sleep(espera)
        raise ultimo


class DatosDelCaso(FuenteDeDatos):
    def __init__(self, caso):
        self._agenda = [
            BloqueAgenda(b["id"], b["nombre"], b["dia"], b["inicio"], b["fin"])
            for b in caso.get("agenda", [])
        ]
        self._actividades = caso.get("actividades", [])

    def agenda(self):
        return self._agenda

    def buscar_actividad(self, texto):
        return coincidencias(self._actividades, texto)

    def sugerir_tarea(self):
        return {"candidatas": self._actividades}


def construir_modelo(nombre):
    base_url, modelo, clave = PROVEEDORES[nombre]
    api_key = getattr(get_settings(), clave, "")
    if not api_key:
        raise SystemExit(f"Falta {clave} en el .env")
    return ModeloConEspera(
        OpenAIToolsAdapter(api_key=api_key, base_url=base_url, default_model=modelo)
    )


def _resumen(borrador) -> str:
    """Lo que el modelo entendio, para poder diagnosticar un fallo."""
    return ", ".join(
        f"{k}={v!r}"
        for k, v in borrador.model_dump(exclude_none=True).items()
        if v not in ([], {}, False)
    ) or "(vacio)"


def correr_caso(caso, modelo, detalle=False):
    """Devuelve (estado, motivo) con estado en {ok, falla, sin_medir}.

    `sin_medir` separa "el proveedor no me dejo preguntar" de "el modelo
    contesto mal". Contarlos juntos haria que un problema de cuota parezca un
    problema de calidad.
    """
    datos = DatosDelCaso(caso)
    borrador, turnos = Borrador(), []

    for indice, paso in enumerate(caso["turnos"], start=1):
        servicio = ServicioConversacion(modelo=modelo, datos=datos)
        previo = borrador
        donde = f"turno {indice}"

        try:
            resultado = servicio.responder(
                mensaje=paso["usuario"],
                borrador=borrador,
                turnos=turnos,
                ahora=AHORA,
            )
        except Exception as exc:
            if es_limite_de_tasa(str(exc)):
                return "sin_medir", f"{donde}: cuota agotada"
            return "falla", f"{donde}: excepcion {exc}"

        borrador, turnos = resultado.borrador, resultado.turnos
        espera = paso.get("espera", {})

        if detalle:
            print(f"      [{donde}] {resultado.tipo}: {_resumen(borrador)}")

        if "tipo" in espera and resultado.tipo != espera["tipo"]:
            return "falla", (
                f"{donde}: respondio {resultado.tipo}, esperaba {espera['tipo']}"
                f" | draft: {_resumen(borrador)}"
            )

        if "propuesta" in espera:
            if not resultado.propuesta:
                return "falla", f"{donde}: no propuso nada"
            if resultado.propuesta.tipo != espera["propuesta"]:
                return "falla", (
                    f"{donde}: propuso {resultado.propuesta.tipo},"
                    f" esperaba {espera['propuesta']}"
                )

        problema = verificar_draft(borrador, espera.get("draft"), donde)
        if problema:
            return "falla", problema

        problema = verificar_conservados(
            borrador, previo, espera.get("draft_conserva"), donde
        )
        if problema:
            return "falla", problema

    return "ok", "ok"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--proveedor", default="groq", choices=sorted(PROVEEDORES))
    parser.add_argument("--repeticiones", type=int, default=3)
    parser.add_argument("--caso", default=None, help="Prefijo del archivo, ej. 01")
    parser.add_argument(
        "--detalle",
        action="store_true",
        help="Muestra el borrador turno a turno.",
    )
    parser.add_argument(
        "--pausa",
        type=float,
        default=PAUSA_POR_DEFECTO,
        help="Segundos entre conversaciones, para no agotar la cuota.",
    )
    args = parser.parse_args()

    # Los warnings del adaptador ensucian el reporte y no agregan nada: los
    # fallos ya se resumen abajo.
    logging.basicConfig(level=logging.ERROR, format="%(levelname)s %(message)s")

    casos = sorted(GOLDEN.glob("*.yaml"))
    if args.caso:
        casos = [c for c in casos if c.stem.startswith(args.caso)]
    if not casos:
        raise SystemExit("No hay casos que correr.")

    modelo = construir_modelo(args.proveedor)
    resultados = defaultdict(list)
    corridas = len(casos) * args.repeticiones

    print(f"\nProveedor: {args.proveedor}  |  N={args.repeticiones}")
    print(f"{corridas} conversaciones, ~{args.pausa:.0f}s entre cada una.")
    print(f"Estimado: {corridas * args.pausa / 60:.0f} min.\n")

    primera = True
    for ruta in casos:
        caso = yaml.safe_load(ruta.read_text())
        for _ in range(args.repeticiones):
            if not primera:
                time.sleep(args.pausa)
            primera = False
            resultados[ruta.stem].append(correr_caso(caso, modelo, args.detalle))

        estados = [e for e, _ in resultados[ruta.stem]]
        ok = estados.count("ok")
        sin_medir = estados.count("sin_medir")
        medidos = len(estados) - sin_medir

        if sin_medir == len(estados):
            marca = "?"
        elif ok == medidos:
            marca = "PASA"
        elif ok == 0:
            marca = "FALLA"
        else:
            marca = "MIXTO"

        sufijo = f" ({sin_medir} sin medir)" if sin_medir else ""
        print(f"  [{marca:5}] {ruta.stem}  {ok}/{medidos or 0}{sufijo}", flush=True)
        for estado, motivo in resultados[ruta.stem]:
            if estado == "falla":
                print(f"           - {motivo}")

    todos = [r for v in resultados.values() for r in v]
    ok = sum(1 for e, _ in todos if e == "ok")
    sin_medir = sum(1 for e, _ in todos if e == "sin_medir")
    medidos = len(todos) - sin_medir
    tasa = ok / medidos if medidos else 0

    print(f"\n  Medidas: {ok}/{medidos} ({tasa:.0%})")
    if sin_medir:
        print(f"  Sin medir por cuota: {sin_medir}. Subi --pausa y volve a correr.")
    if modelo.esperas:
        print(f"  Esperas por limite de tasa: {modelo.esperas}")

    if medidos < len(todos) / 2:
        print("  VEREDICTO: muestra insuficiente para concluir nada.\n")
        return 2

    print(f"  Umbral para ir primero en el failover: {UMBRAL:.0%}")
    print("  VEREDICTO:", "sirve" if tasa >= UMBRAL else "no alcanza", "\n")
    return 0 if tasa >= UMBRAL else 1


if __name__ == "__main__":
    raise SystemExit(main())
