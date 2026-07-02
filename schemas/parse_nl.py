"""Pydantic schemas for the natural language activity parsing endpoint.

These DTOs are shaped for the frontend wizard's mental model (day names,
string enums), not the backend Actividad domain entity.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ParseNLRequest(BaseModel):
    """Request body for POST /api/v1/horarios/parse-nl."""

    text: str = Field(min_length=1, description="Natural language activity description")


class ParsedSchedule(BaseModel):
    """A single schedule slot parsed from natural language."""

    day: str = Field(description="Day name in Spanish, e.g. 'Lunes', 'Martes'")
    start_time: int = Field(ge=0, description="Start time in minutes from midnight")
    end_time: int = Field(ge=0, description="End time in minutes from midnight")

    @field_validator("day")
    @classmethod
    def normalize_day(cls, v: str) -> str:
        return v.lower() if v else v


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
    hora_preferida_inicio: int | None = Field(
        default=None,
        description="Preferred window start in minutes from midnight. "
                    "Use when the user says 'desde las X' or 'entre las X y las Y' "
                    "WITH a separate duration. NOT for fixed time slots.",
        ge=0,
    )
    hora_preferida_fin: int | None = Field(
        default=None,
        description="Preferred window end in minutes from midnight. "
                    "Use together with hora_preferida_inicio when the user specifies "
                    "a range the activity can be placed in, not a fixed slot.",
        ge=0,
    )
    location: str | None = None
    travel_to: int | None = Field(default=None, description="Tiempo de traslado de ida en minutos", ge=0)
    travel_from: int | None = Field(default=None, description="Tiempo de traslado de vuelta en minutos", ge=0)
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Model confidence score between 0.0 and 1.0",
    )
    missing_fields: list[str] = []


class ConversationMessage(BaseModel):
    """A single message in the conversation history."""

    role: Literal["user", "assistant"]
    content: str
    type: Literal["question", "result", "chat"] | None = None


class ParseNLConversationRequest(BaseModel):
    """Request body for POST /api/v1/horarios/parse-nl-conversation."""

    text: str = Field(min_length=1, description="Natural language activity description")
    history: list[ConversationMessage] = []
    agenda_context: str | None = Field(default=None, description="Contexto de las actividades existentes del usuario en la agenda")
    current_day: str | None = Field(default=None, description="Día actual de la semana en español, ej: 'Lunes'")



class QuestionResponse(BaseModel):
    """Response when the LLM needs more information."""

    type: Literal["question"] = "question"
    ai_message: str
    missing_fields: list[str] = []


class ChatResponse(BaseModel):
    """Response when the user is chatting or asking off-topic questions."""

    type: Literal["chat"] = "chat"
    ai_message: str


class ResultResponse(ParseNLResponse):
    """Response when the LLM has enough information to produce structured data."""

    type: Literal["result"] = "result"


ParseNLConversationResponse = QuestionResponse | ChatResponse | ResultResponse
