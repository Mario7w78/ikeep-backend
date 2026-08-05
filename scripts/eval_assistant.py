#!/usr/bin/env python
"""Corre las conversaciones doradas contra un proveedor real.

Los tests de CI usan un modelo guionado y verifican la orquestacion. Esto
verifica lo otro: que un modelo de verdad, con este prompt y estas tools, sepa
producir ese guion. Es el unico que mide el riesgo de quedarse en
Groq/Cerebras, cuyo tool calling multi-turno es irregular.

Fuera de CI a proposito: gasta cuota y no es determinista.

Uso:
    venv/bin/python scripts/eval_assistant.py                # todos, N=3
    venv/bin/python scripts/eval_assistant.py --proveedor cerebras
    venv/bin/python scripts/eval_assistant.py --repeticiones 5 --caso 01
"""

import argparse
import logging
import sys
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

GOLDEN = Path(__file__).resolve().parent.parent / "tests" / "golden"
AHORA = datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)

# Umbral de aprobacion: por debajo de esto un proveedor no sirve para ir
# primero en la cadena de failover.
UMBRAL = 0.90

PROVEEDORES = {
    "groq": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile", "GROQ_API_KEY"),
    "cerebras": ("https://api.cerebras.ai/v1", "gpt-oss-120b", "CEREBRAS_API_KEY"),
    "mistral": ("https://api.mistral.ai/v1", "mistral-small-latest", "MISTRAL_API_KEY"),
}


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
    return OpenAIToolsAdapter(api_key=api_key, base_url=base_url, default_model=modelo)


def correr_caso(caso, modelo):
    """Devuelve (aprobado, motivo)."""
    datos = DatosDelCaso(caso)
    borrador, turnos = Borrador(), []

    for indice, paso in enumerate(caso["turnos"], start=1):
        servicio = ServicioConversacion(modelo=modelo, datos=datos)
        previo = borrador
        try:
            resultado = servicio.responder(
                mensaje=paso["usuario"],
                borrador=borrador,
                turnos=turnos,
                ahora=AHORA,
            )
        except Exception as exc:
            return False, f"turno {indice}: excepcion {exc}"

        borrador, turnos = resultado.borrador, resultado.turnos
        espera = paso.get("espera", {})

        if "tipo" in espera and resultado.tipo != espera["tipo"]:
            return False, f"turno {indice}: tipo {resultado.tipo} != {espera['tipo']}"

        if "propuesta" in espera:
            if not resultado.propuesta:
                return False, f"turno {indice}: no propuso nada"
            if resultado.propuesta.tipo != espera["propuesta"]:
                return False, (
                    f"turno {indice}: propuso {resultado.propuesta.tipo}"
                    f" != {espera['propuesta']}"
                )

        for campo, valor in (espera.get("draft") or {}).items():
            actual = getattr(borrador, campo)
            if actual != valor:
                return False, f"turno {indice}: draft.{campo}={actual!r} != {valor!r}"

        for campo in espera.get("draft_conserva", []):
            if getattr(borrador, campo) != getattr(previo, campo):
                return False, f"turno {indice}: se perdio draft.{campo}"

    return True, "ok"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--proveedor", default="groq", choices=sorted(PROVEEDORES))
    parser.add_argument("--repeticiones", type=int, default=3)
    parser.add_argument("--caso", default=None, help="Prefijo del archivo, ej. 01")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    casos = sorted(GOLDEN.glob("*.yaml"))
    if args.caso:
        casos = [c for c in casos if c.stem.startswith(args.caso)]
    if not casos:
        raise SystemExit("No hay casos que correr.")

    modelo = construir_modelo(args.proveedor)
    resultados = defaultdict(list)

    print(f"\nProveedor: {args.proveedor}  |  N={args.repeticiones}\n")

    for ruta in casos:
        caso = yaml.safe_load(ruta.read_text())
        for _ in range(args.repeticiones):
            aprobado, motivo = correr_caso(caso, modelo)
            resultados[ruta.stem].append((aprobado, motivo))

        aprobados = sum(1 for a, _ in resultados[ruta.stem] if a)
        total = len(resultados[ruta.stem])
        marca = "PASA" if aprobados == total else "FALLA" if aprobados == 0 else "MIXTO"
        print(f"  [{marca:5}] {ruta.stem}  {aprobados}/{total}")
        for aprobado, motivo in resultados[ruta.stem]:
            if not aprobado:
                print(f"           - {motivo}")

    total = sum(len(v) for v in resultados.values())
    aprobados = sum(1 for v in resultados.values() for a, _ in v if a)
    tasa = aprobados / total if total else 0

    print(f"\n  Total: {aprobados}/{total} ({tasa:.0%})")
    print(f"  Umbral para ir primero en el failover: {UMBRAL:.0%}")
    print("  VEREDICTO:", "sirve" if tasa >= UMBRAL else "no alcanza", "\n")

    return 0 if tasa >= UMBRAL else 1


if __name__ == "__main__":
    raise SystemExit(main())
