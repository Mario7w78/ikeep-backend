"""Tests for parse_nl Pydantic schemas.

Tests validation behavior of ParseNLRequest, ParsedSchedule, and ParseNLResponse.
"""

import pytest
from pydantic import ValidationError


class TestParseNLRequest:
    def test_valid_request(self):
        from schemas.parse_nl import ParseNLRequest

        req = ParseNLRequest(text="Entreno de futbol los lunes")
        assert req.text == "Entreno de futbol los lunes"

    def test_empty_text_raises(self):
        from schemas.parse_nl import ParseNLRequest

        with pytest.raises(ValidationError, match="text"):
            ParseNLRequest(text="")

    def test_missing_text_raises(self):
        from schemas.parse_nl import ParseNLRequest

        with pytest.raises(ValidationError):
            ParseNLRequest()  # type: ignore[call-arg]


class TestParsedSchedule:
    def test_valid_schedule(self):
        from schemas.parse_nl import ParsedSchedule

        sched = ParsedSchedule(day="Lunes", start_time=480, end_time=540)
        assert sched.day == "lunes"
        assert sched.start_time == 480
        assert sched.end_time == 540

    def test_start_time_must_be_non_negative(self):
        from schemas.parse_nl import ParsedSchedule

        with pytest.raises(ValidationError):
            ParsedSchedule(day="Lunes", start_time=-1, end_time=540)

    def test_end_time_must_be_non_negative(self):
        from schemas.parse_nl import ParsedSchedule

        with pytest.raises(ValidationError):
            ParsedSchedule(day="Lunes", start_time=0, end_time=-1)


class TestParseNLResponse:
    def test_valid_full_response(self):
        from schemas.parse_nl import ParseNLResponse, ParsedSchedule

        resp = ParseNLResponse(
            name="Entreno de futbol",
            activity_type="tarea",
            is_fixed=True,
            is_anchor=False,
            difficulty="media",
            priority="alta",
            schedule=[ParsedSchedule(day="Lunes", start_time=480, end_time=540)],
            location="Polideportivo",
            confidence=0.95,
            missing_fields=[],
        )
        assert resp.name == "Entreno de futbol"
        assert resp.confidence == 0.95
        assert len(resp.schedule) == 1

    def test_empty_schedule_defaults(self):
        from schemas.parse_nl import ParseNLResponse

        resp = ParseNLResponse()
        assert resp.name is None
        assert resp.schedule == []
        assert resp.missing_fields == []
        assert resp.confidence == 0.0

    def test_confidence_range_validation(self):
        from schemas.parse_nl import ParseNLResponse

        with pytest.raises(ValidationError):
            ParseNLResponse(confidence=1.5)

        with pytest.raises(ValidationError):
            ParseNLResponse(confidence=-0.1)

    def test_boundary_confidence_values_accepted(self):
        from schemas.parse_nl import ParseNLResponse

        resp0 = ParseNLResponse(confidence=0.0)
        assert resp0.confidence == 0.0

        resp1 = ParseNLResponse(confidence=1.0)
        assert resp1.confidence == 1.0

    def test_activity_type_validation(self):
        from schemas.parse_nl import ParseNLResponse

        for valid_type in ["clase", "trabajo", "tarea", None]:
            resp = ParseNLResponse(activity_type=valid_type)
            assert resp.activity_type == valid_type

    def test_difficulty_validation(self):
        from schemas.parse_nl import ParseNLResponse

        for valid in ["baja", "media", "alta", None]:
            resp = ParseNLResponse(difficulty=valid)
            assert resp.difficulty == valid

    def test_priority_validation(self):
        from schemas.parse_nl import ParseNLResponse

        for valid in ["baja", "media", "alta", None]:
            resp = ParseNLResponse(priority=valid)
            assert resp.priority == valid

    def test_missing_fields_listed(self):
        from schemas.parse_nl import ParseNLResponse

        resp = ParseNLResponse(
            name="Estudio",
            missing_fields=["schedule", "location"],
        )
        assert "schedule" in resp.missing_fields
        assert "location" in resp.missing_fields
