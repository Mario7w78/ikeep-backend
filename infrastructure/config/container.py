from dependency_injector import containers, providers
from dependency_injector.wiring import Provide, inject

from domain.services.llm_parser_service import LLMParserService
from domain.services.schedule_service import PenaltyWeights, ScheduleOptimizer
from domain.services.reschedule_service import RescheduleService
from domain.services.suggest_service import SuggestService
from infrastructure.adapters.outbound.llm.gemini_llm_adapter import (
    GeminiLLMAdapter,
)
from infrastructure.config.settings import Settings, get_settings


class ApplicationContainer(containers.DeclarativeContainer):
    """Central DI container for the application.

    Wiring module configures which packages receive injected dependencies.
    """

    wiring_config = containers.WiringConfiguration(
        modules=[
            "infrastructure.adapters.inbound.api.v1.schedule_router",
            "infrastructure.adapters.inbound.api.v1.reschedule_router",
            "infrastructure.adapters.inbound.api.v1.suggest_router",
        ],
    )

    # ── Config ──
    settings = providers.Singleton(get_settings)

    # ── LLM ──
    llm_adapter = providers.Singleton(
        GeminiLLMAdapter,
        settings=settings,
    )

    llm_parser_service = providers.Factory(
        LLMParserService,
        llm_port=llm_adapter,
    )

    # ── Services ──
    penalty_weights = providers.Singleton(PenaltyWeights)

    scheduler_service = providers.Factory(
        ScheduleOptimizer,
        timeout_seconds=providers.Callable(
            lambda s: s.SCHEDULER_TIMEOUT,
            settings,
        ),
        weights=penalty_weights,
    )

    reschedule_service = providers.Factory(
        RescheduleService,
        optimizer=scheduler_service,
    )

    suggest_service = providers.Singleton(SuggestService)
