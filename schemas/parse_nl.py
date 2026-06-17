"""Pydantic schemas for the natural language activity parsing endpoint.

These DTOs are shaped for the frontend wizard's mental model (day names,
string enums), not the backend Actividad domain entity.
"""

from pydantic import BaseModel, Field


class ParseNLRequest(BaseModel):
    """Request body for POST /api/v1/horarios/parse-nl."""

    text: str = Field(min_length=1, description="Natural language activity description")


class ParsedSchedule(BaseModel):
    """A single schedule slot parsed from natural language."""

    day: str = Field(description="Day name in Spanish, e.g. 'Lunes', 'Martes'")
    start_time: int = Field(ge=0, description="Start time in minutes from midnight")
    end_time: int = Field(ge=0, description="End time in minutes from midnight")


class ParseNLResponse(BaseModel):
    """Response body for a successful natural language parse.

    Fields mirror the frontend wizard's form model rather than the
    backend Actividad entity, so no mapping is needed on the client side.
    """

    name: str | None = None
    activity_type: str | None = Field(
        default=None,
        description="'clase' | 'trabajo' | 'tarea'",
    )
    is_fixed: bool = True
    is_anchor: bool = False
    difficulty: str | None = Field(
        default=None,
        description="'baja' | 'media' | 'alta'",
    )
    priority: str | None = Field(
        default=None,
        description="'baja' | 'media' | 'alta'",
    )
    schedule: list[ParsedSchedule] = []
    duracion_minutos: int | None = Field(
        default=None,
        description="Duration in minutes when the user specifies a duration but NO specific start/end time. "
                    "Ex: 'en 15 min', '10 minutos', 'media hora'. "
                    "When set, schedule entries should have start_time=0, end_time=0.",
        ge=1,
    )
    location: str | None = None
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Model confidence score between 0.0 and 1.0",
    )
    missing_fields: list[str] = []
