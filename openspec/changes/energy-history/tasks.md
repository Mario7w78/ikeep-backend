# Tasks: Energy History

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~170–200 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | single-pr |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Foundation types + classifier + schedule integration + mappers | Single PR | All changes fit well under 400 lines |

---

## Phase 1: Foundation — Types & Schemas

- [x] 1.1 Add `PatronEnergia` enum (`TRANSCRIPTORIO, TENDENCIA, CRONICO`) to `domain/entities/enums.py`
- [x] 1.2 Add `RegistroEnergia` dataclass to `domain/entities/user_context.py` + `historial_energia: list[RegistroEnergia]` field to `ContextoUsuario`
- [x] 1.3 Add `RegistroEnergia` Pydantic model to `schemas/user_context.py` + `historial_energia: list[RegistroEnergia] = []` field to `ContextoUsuario` schema

## Phase 2: Core Logic — Classifier & Scheduler

- [x] 2.1 Create `domain/services/energy_classifier.py` with pure function `clasificar_patron_energia(history, current_level) -> PatronEnergia`: empty history → TRANSCRIPTORIO; <20% low → TRANSCRIPTORIO; 20–60% → TENDENCIA; >60% → CRONICO (last 14 days, low = nivel < 5)
- [x] 2.2 In `domain/services/schedule_service.py`: import `PatronEnergia`/`clasificar_patron_energia`; call classifier in `generar()` before building model; pass `patron` to `_rb_01`
- [x] 2.3 Update `_rb_01` signature to accept `patron`: TRANSCRIPTORIO = current behavior; TENDENCIA = max 1 ALTA/day hard constraint; CRONICO = deprioritize ALTA (2x penalty), favor short tasks (duration-based), adjust weights for rb_04/rb_05 to maximize rest

## Phase 3: Integration — Mappers

- [x] 3.1 Add `registro_energia_to_domain(dto) -> RegistroEnergia` mapper in `infrastructure/adapters/inbound/api/mappers.py`
- [x] 3.2 Update `contexto_to_domain()` to map `historial_energia` list from DTO to domain

## Phase 4: Testing

- [x] 4.1 Unit tests for `clasificar_patron_energia()` — empty history, all three thresholds, edge cases (exactly 20%, exactly 60%)
- [x] 4.2 Integration tests for `generar()` with TENDENCIA and CRONICO branches — verify ALTA task constraints and weight adjustments
- [x] 4.3 Unit tests for mapper — verify `historial_energia` round-trips correctly from DTO to domain
