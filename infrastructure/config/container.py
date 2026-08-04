from dependency_injector import containers, providers
from dependency_injector.wiring import Provide, inject

from domain.services.llm_parser_service import LLMParserService
from domain.services.schedule_service import PenaltyWeights, ScheduleOptimizer
from domain.services.reschedule_service import RescheduleService
from domain.services.suggest_service import SuggestService
from infrastructure.adapters.outbound.llm.openai_compatible_adapter import (
    OpenAICompatibleAdapter,
)
from infrastructure.adapters.outbound.llm.openai_tools_adapter import (
    OpenAIToolsAdapter,
)
from infrastructure.adapters.outbound.llm.conversational_failover_adapter import (
    ConversationalFailoverAdapter,
)
from infrastructure.adapters.outbound.llm.circuit_breaker_adapter import (
    CircuitBreakerAdapter,
)
from infrastructure.adapters.outbound.llm.failover_adapter import (
    FailoverAdapter,
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
            "infrastructure.adapters.inbound.api.v1.assistant_router",
        ],
    )

    # ── Config ──
    settings = providers.Singleton(get_settings)

    # ── LLM Providers ──
    groq_adapter = providers.Singleton(
        OpenAICompatibleAdapter,
        api_key=providers.Callable(lambda s: s.GROQ_API_KEY, settings),
        base_url="https://api.groq.com/openai/v1",
        default_model="llama-3.3-70b-versatile",
    )

    cerebras_adapter = providers.Singleton(
        OpenAICompatibleAdapter,
        api_key=providers.Callable(lambda s: s.CEREBRAS_API_KEY, settings),
        base_url="https://api.cerebras.ai/v1",
        default_model="gpt-oss-120b",
    )

    mistral_adapter = providers.Singleton(
        OpenAICompatibleAdapter,
        api_key=providers.Callable(lambda s: s.MISTRAL_API_KEY, settings),
        base_url="https://api.mistral.ai/v1",
        default_model="mistral-small-latest",
    )

    # ── Circuit Breakers (one per provider) ──
    groq_circuit_breaker = providers.Singleton(
        CircuitBreakerAdapter,
        inner=groq_adapter,
    )
    cerebras_circuit_breaker = providers.Singleton(
        CircuitBreakerAdapter,
        inner=cerebras_adapter,
    )
    mistral_circuit_breaker = providers.Singleton(
        CircuitBreakerAdapter,
        inner=mistral_adapter,
    )

    # ── Failover (tries Groq → Cerebras → Mistral) ──
    llm_adapter = providers.Singleton(
        FailoverAdapter,
        providers.List(
            groq_circuit_breaker,
            cerebras_circuit_breaker,
            mistral_circuit_breaker,
        ),
    )

    # ── Conversacional (tool calling) ──
    # Cadena aparte de la de un disparo: son puertos distintos y los modelos
    # con mejor tool calling no son necesariamente los mejores extrayendo.
    groq_tools_adapter = providers.Singleton(
        OpenAIToolsAdapter,
        api_key=providers.Callable(lambda s: s.GROQ_API_KEY, settings),
        base_url="https://api.groq.com/openai/v1",
        default_model="llama-3.3-70b-versatile",
    )

    cerebras_tools_adapter = providers.Singleton(
        OpenAIToolsAdapter,
        api_key=providers.Callable(lambda s: s.CEREBRAS_API_KEY, settings),
        base_url="https://api.cerebras.ai/v1",
        default_model="gpt-oss-120b",
    )

    mistral_tools_adapter = providers.Singleton(
        OpenAIToolsAdapter,
        api_key=providers.Callable(lambda s: s.MISTRAL_API_KEY, settings),
        base_url="https://api.mistral.ai/v1",
        default_model="mistral-small-latest",
    )

    # Sin circuit breaker todavia: el existente envuelve LLMPort, que tiene
    # otra firma. El orden Groq -> Cerebras -> Mistral esta puesto sin
    # evidencia; la suite de conversaciones doradas es la que deberia
    # decidirlo.
    conversational_adapter = providers.Singleton(
        ConversationalFailoverAdapter,
        providers.List(
            groq_tools_adapter,
            cerebras_tools_adapter,
            mistral_tools_adapter,
        ),
    )

    # ── LLM Service ──
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
