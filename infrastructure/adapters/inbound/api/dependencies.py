from domain.ports.inbound.reschedule_port import AbstractRescheduleService
from domain.ports.inbound.scheduler_port import AbstractSchedulerService
from domain.services.reschedule_service import RescheduleService
from domain.services.schedule_service import PenaltyWeights, ScheduleOptimizer
from infrastructure.config.settings import get_settings


def get_scheduler_service() -> AbstractSchedulerService:
    settings = get_settings()
    return ScheduleOptimizer(
        timeout_seconds=settings.SCHEDULER_TIMEOUT,
        weights=PenaltyWeights(),
    )


def get_reschedule_service() -> AbstractRescheduleService:
    optimizer = get_scheduler_service()
    return RescheduleService(optimizer=optimizer)
