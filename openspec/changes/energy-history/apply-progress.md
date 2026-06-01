# Apply Progress: Energy History

**Change**: energy-history
**Mode**: Standard (no strict TDD)
**Delivery Strategy**: single-pr

## Completed Tasks

### Phase 1: Foundation — Types & Schemas
- [x] 1.1 Add `PatronEnergia` enum (`TRANSCRIPTORIO, TENDENCIA, CRONICO`) to `domain/entities/enums.py`
- [x] 1.2 Add `RegistroEnergia` dataclass to `domain/entities/user_context.py` + `historial_energia: list[RegistroEnergia]` field to `ContextoUsuario`
- [x] 1.3 Add `RegistroEnergia` Pydantic model to `schemas/user_context.py` + `historial_energia: list[RegistroEnergia] = []` field to `ContextoUsuario` schema

### Phase 2: Core Logic — Classifier & Scheduler
- [x] 2.1 Create `domain/services/energy_classifier.py` with pure function `clasificar_patron_energia(history, current_level) -> PatronEnergia`
- [x] 2.2 In `domain/services/schedule_service.py`: import `PatronEnergia`/`clasificar_patron_energia`; call classifier in `generar()`; pass `patron` to `_rb_01`
- [x] 2.3 Update `_rb_01` with branching: TRANSCRIPTORIO = current behavior; TENDENCIA = max 1 ALTA/day hard constraint; CRONICO = deprioritize ALTA (2x), favor short tasks, adjust weights for rb_04/rb_05

### Phase 3: Integration — Mappers
- [x] 3.1 Add `registro_energia_to_domain(dto) -> RegistroEnergia` mapper in `infrastructure/adapters/inbound/api/mappers.py`
- [x] 3.2 Update `contexto_to_domain()` to map `historial_energia` list from DTO to domain

### Phase 4: Testing
- [x] 4.1 Unit tests for `clasificar_patron_energia()` — 9 test cases covering empty, thresholds, 14-day window
- [x] 4.2 Integration tests for RB-01 branches — TENDENCIA constraint verification, CRONICO penalty checking
- [x] 4.3 Unit tests for mapper — empty/3-entry round-trip, single entry, other fields preserved

## Files Changed

| File | Action | What Was Done |
|------|--------|---------------|
| `domain/entities/enums.py` | Modified | Added `PatronEnergia` enum (3 values) |
| `domain/entities/user_context.py` | Modified | Added `RegistroEnergia` dataclass + `historial_energia` field |
| `schemas/user_context.py` | Modified | Added `RegistroEnergia` Pydantic model + `historial_energia` field |
| `domain/services/energy_classifier.py` | Created | Pure classifier function with 14-day window logic |
| `domain/services/schedule_service.py` | Modified | Imported classifier, called in `generar()`, rewrote `_rb_01` with 3 branches, adjusted `_rb_04`/`_rb_05` weights for CRONICO |
| `infrastructure/adapters/inbound/api/mappers.py` | Modified | Added `registro_energia_to_domain` mapper + updated `contexto_to_domain` |
| `tests/__init__.py` | Created | Package init |
| `tests/test_energy_classifier.py` | Created | 9 unit tests for classifier |
| `tests/test_energy_scheduler.py` | Created | 4 integration tests for RB-01 branches |
| `tests/test_energy_mapper.py` | Created | 5 unit tests for mapper |

## Git Diff Statistics (modified files only)
- 5 files modified: +91 insertions, -21 deletions
- 5 new files created: ~320 lines (classifier + tests)

## Deviations from Design
None — implementation matches the task specifications.

## Issues Found
None.

## Code Architecture Notes

- **Backward compatibility**: `historial_energia` defaults to empty list in all layers (dataclass, Pydantic, mapper). Existing callers that don't provide the field continue working.
- **Hexagonal boundary**: `domain/` has zero imports from `schemas/` or `infrastructure/`. The energy classifier imports only from `domain.entities.*`.
- **Patron override**: `self._patron_override` is set in `generar()` and read by `_rb_04`/`_rb_05` using `getattr` to avoid altering the public API of those methods.
- **Classifier design**: Uses `datetime.fromisoformat` for ISO 8601 parsing and `datetime.now(timezone.utc)` for the 14-day cutoff. Pure function with no side effects.

## Remaining Tasks
None — all 11 tasks complete.

## Status
11/11 tasks complete. Ready for verify.
