"""Unit tests for energy history mappers."""

from schemas.user_context import ContextoUsuario as ContextoDTO
from schemas.user_context import RegistroEnergia as RegistroEnergiaDTO

from domain.entities.user_context import ContextoUsuario as ContextoDomain
from domain.entities.user_context import RegistroEnergia as RegistroEnergiaDomain

from infrastructure.adapters.inbound.api.mappers import (
    contexto_to_domain,
    registro_energia_to_domain,
)


def test_empty_historial_energia_maps_to_empty_list():
    dto = ContextoDTO(historial_energia=[])
    domain = contexto_to_domain(dto)
    assert domain.historial_energia == []


def test_three_entries_round_trip_correctly():
    dto = ContextoDTO(
        nivel_energia=2,
        historial_energia=[
            RegistroEnergiaDTO(
                timestamp="2026-05-30T08:00:00+00:00",
                nivel=3,
                dia_semana=6,
                contexto="Después del café",
            ),
            RegistroEnergiaDTO(
                timestamp="2026-05-29T14:30:00+00:00",
                nivel=2,
                dia_semana=5,
                contexto=None,
            ),
            RegistroEnergiaDTO(
                timestamp="2026-05-28T22:00:00+00:00",
                nivel=1,
                dia_semana=4,
            ),
        ],
    )

    domain = contexto_to_domain(dto)

    assert len(domain.historial_energia) == 3

    # First entry
    e0 = domain.historial_energia[0]
    assert isinstance(e0, RegistroEnergiaDomain)
    assert e0.timestamp == "2026-05-30T08:00:00+00:00"
    assert e0.nivel == 3
    assert e0.dia_semana == 6
    assert e0.contexto == "Después del café"

    # Second entry — contexto=None
    e1 = domain.historial_energia[1]
    assert e1.timestamp == "2026-05-29T14:30:00+00:00"
    assert e1.nivel == 2
    assert e1.dia_semana == 5
    assert e1.contexto is None

    # Third entry — contexto omitted
    e2 = domain.historial_energia[2]
    assert e2.timestamp == "2026-05-28T22:00:00+00:00"
    assert e2.nivel == 1
    assert e2.dia_semana == 4
    assert e2.contexto is None


def test_registro_energia_to_domain_single_entry():
    dto = RegistroEnergiaDTO(
        timestamp="2026-05-31T12:00:00+00:00",
        nivel=3,
        dia_semana=0,
        contexto="Energético",
    )
    domain = registro_energia_to_domain(dto)

    assert isinstance(domain, RegistroEnergiaDomain)
    assert domain.timestamp == "2026-05-31T12:00:00+00:00"
    assert domain.nivel == 3
    assert domain.dia_semana == 0
    assert domain.contexto == "Energético"


def test_contexto_other_fields_preserved():
    """Mapping historial_energia should not affect other ContextoUsuario fields."""
    dto = ContextoDTO(
        nivel_energia=1,
        horario_inicio=420,
        horario_fin=1080,
        historial_energia=[
            RegistroEnergiaDTO(timestamp="2026-05-30T10:00:00+00:00", nivel=2, dia_semana=5),
        ],
    )
    domain = contexto_to_domain(dto)

    assert domain.nivel_energia == 1
    assert domain.horario_inicio == 420
    assert domain.horario_fin == 1080
    assert len(domain.historial_energia) == 1
