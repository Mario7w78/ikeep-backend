# Proposal: horario-midnight-crossing

## Intent

Allow `horario_inicio > horario_fin` to express a crossing-midnight active window (e.g., 8 AM → 1 AM). Currently `inicio < fin` is required, breaking validation, CP-SAT IntVar bounds, and soft-constraint ranges.

## Scope

### In Scope
- Relax schema validation to accept any `[0,1440]` pair where `abs_duration(inicio, fin) > 0`
- Fix arithmetic in validation/diagnosis: replace `fin - inicio` with `abs_duration()`
- Update test assertions broken by crossing windows
- Split CP-SAT day window into `[inicio, 1440)` ∪ `[0, fin)` for flexible tasks and rest blocks
- Fix IntVar bounds in RB-02 through RB-06 using effective window + segment-aware mapping
- Full backward compatibility: default `(480, 1200)` and all same-day windows must behave identically

### Out of Scope
- Sleep blocks (`BloqueSueno`) — already handle crossing
- Activity-level crossing — already handled via `abs_duration()`
- API contract changes — same JSON shape, same defaults

## Approach

Two-phase delivery to isolate CP-SAT risk.

**Phase 1** (mechanical, ~20 lines): relax `_validate_per_day_hours` in `schemas/schedule_request.py`; replace `fin - inicio` with `abs_duration()` at 4 sites in `domain/services/schedule_service.py` (`_validate_task_duration`, `_validate_consistency`, diagnosis); fix 3 assertions in `tests/test_midnight_crossing.py`.

**Phase 2** (CP-SAT, ~60 lines in `domain/services/schedule_service.py`): window split via optional interval vars in `_add_rest_blocks` and `_add_flexible_task`; fix IntVar bounds in RB-02–RB-06 with `abs_duration()` + segment-aware `late_thr` and work-before logic.

## PR Strategy

**Two chained PRs** — Phase 1 first (<50 lines, fast review), then Phase 2. Each independently testable.

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| P2 optional interval vars increase model complexity | Med | Test both crossing and non-crossing |
| RB-03 `late_thr` meaningless with crossing | Low | Compute in absolute: `(fin + 1440 − 60) % 1440` |
| RB-05 `s − inicio` negative post-midnight | Med | Branch: `s + 1440 − inicio` when `s < inicio` |

## Rollback Plan

- Phase 1: revert 3 files independently
- Phase 2: revert `schedule_service.py` only
- Full: `git revert` each chained PR

## Dependencies

None — `abs_duration()` in `time_utils.py` already handles crossing.

## Success Criteria

- [ ] `inicio=480, fin=60` generates valid schedule
- [ ] `inicio=480, fin=1200` produces identical results to today
- [ ] All existing tests pass
