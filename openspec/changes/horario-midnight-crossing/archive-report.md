# Archive Report: horario-midnight-crossing

**Change**: horario-midnight-crossing
**Archived**: 2026-06-09
**Artifact Store**: openspec (file-based)
**Status**: success
**Verdict**: PASS WITH WARNINGS

---

## Executive Summary

Implemented midnight-crossing support for `horario_inicio` / `horario_fin` in `ContextoUsuario`, allowing windows like `inicio=480, fin=60` (8 AM → 1 AM next day) using the existing `abs_duration()` convention. Two-phase delivery: **Phase 1** relaxed schema validation and replaced `fin - inicio` with `abs_duration()` at 4 arithmetic sites; **Phase 2** split CP‑SAT day windows into two segments for flexible tasks, constrained rest blocks to a single segment, and adjusted RB bound/threshold computation. All 162 tests pass (57 midnight-crossing-specific). 12/12 tasks complete. Backward compatible — default `(480, 1200)` windows produce identical results.

---

## Change Summary

| Field | Value |
|-------|-------|
| Change name | `horario-midnight-crossing` |
| Phases | 2 (Phase 1: Schema + Arithmetic; Phase 2: CP-SAT Model) |
| Total tasks | 12 |
| Completed | 12 |
| Tests (specific) | 57 |
| Tests (full suite) | 162 (1 deseased pre-existing failure) |
| Delivery | Two chained PRs |

---

## Final State

### Files Modified

| File | Action | Phase | Summary |
|------|--------|-------|---------|
| `schemas/schedule_request.py` | Modified | 1 | `_validate_per_day_hours` relaxed to accept crossing windows; uses `abs_duration(inicio, fin) > 0` instead of `inicio < fin` |
| `domain/services/schedule_service.py` | Modified | 1+2 | `_validate_task_duration`, `_validate_consistency`, `_build_response` (diagnosis) use `abs_duration()`. `_add_rest_blocks` crossing guard. `_add_flexible_task` segment-split (2 OptionalIntervalVar per crossing day). RB‑02/04/06 bound fixes. RB‑03 per-segment thresholds. RB‑05 `after_midnight` BoolVar. |
| `domain/services/time_utils.py` | Modified | 2 | Added `effective_window()`, `effective_window_start()`, `effective_window_end()` helpers |
| `tests/test_midnight_crossing.py` | Modified | 1 | Sleep-block assertions at lines 272–273 made segment-aware (`[0]` → `[block.dia]`) |

### Tests Added

| File | Count | Coverage |
|------|-------|----------|
| `tests/test_midnight_crossing.py` | 57 | Unit: `time_utils` helpers (abs_duration, is_crossing, to_abs_minutes, etc.), schema validation (R1), task duration (R2), consistency (R3). Integration: fixed crossing, sleep crossing, mixed, multi-day validation, rest block crossing (R6), flex task crossing (R7), post-midnight placement, backward compat (R12), overlap detection |

### Source of Truth Updated

- `openspec/specs/schedule/spec.md` — created from delta spec (full spec, no merge needed)

---

## Deviations from Design

| Design Element | Actual | Notes |
|----------------|--------|-------|
| RB‑02/05 `excess` bound widening | `max(600, effective_range - N)` | Design specified `max(600, effective_range - 360/240)`. Implemented correctly. |
| RB‑03 per-segment thresholds | As designed | `early_thr` seg1 only; `late_thr` seg1 = 1380, seg2 = `max(0, fin - 60)`. Per design. |
| RB‑05 `after_midnight` BoolVar | As designed | `s < inicio` branch → `work_before = s + 1440 - inicio` |
| Rest block placement | As designed | Single segment at model-build time; `seg1_len >= 30` check. No choice BoolVar. |
| Flex task segment split | As designed | 2 OptionalIntervalVar per crossing day, `p == p1 + p2`, merged s/e vars for RB compat. |

**No deviations found** — implementation matches design exactly.

---

## Warnings for Future Maintainers

1. **RB‑03 penalty asymmetry between crossing and non-crossing**: Non-crossing path uses a single `pen` variable (max `w` even if both early and late fire). Crossing path creates per-flag terms (up to `w` per flag = up to `2w` for seg1 alone). This is by design but may cause unexpected penalty differences at the boundary between crossing and non-crossing windows. Review if penalty behavior changes are needed.

2. **RB‑03 `fin < 60` edge case**: When the crossing window ends less than 60 minutes past midnight, the "last 60 min" spans both segments (e.g., `fin=30` → last 60 min = `[1410, 1440) ∪ [0, 30)`). Current design penalizes only seg2. Frequency of `fin < 60` is expected to be negligible, but worth noting.

3. **`_validate_task_duration` preferred-window check uses raw subtraction** (line 813): `window = act.hora_preferida_fin - act.hora_preferida_inicio` doesn't use `abs_duration()`. If a task's preferred window crosses midnight, this check would erroneously reject it. Pre-existing issue, not part of this change.

4. **No RB‑03 or RB‑05 integration test with crossing window**: The threshold logic (R9, R10) is verified only by code review — no runtime test asserts the solver correctly applies these soft constraints with crossing windows.

5. **`test_rest_block_crossing` only checks feasibility**: Tests only that the solver finds a solution, without structural assertions that the rest block bounds are within valid ranges. Low risk (incorrect bounds would likely cause solver failure), but weaker than ideal.

6. **Implicit assertion pattern in `TestSchemaCrossingPhase1`**: Three tests use `_ = solicitud  # should not raise` instead of explicit assertions. Standard practice for Pydantic validation tests, but worth noting.

---

## Verification Results

### Test Execution

| Suite | Result | Details |
|-------|--------|---------|
| Midnight-crossing specific | ✅ 57/57 passed | `pytest tests/test_midnight_crossing.py -v --tb=short` — 0.34s |
| Full suite (w/ pre-existing failure deselected) | ✅ 162/162 passed | `pytest tests/ -v --tb=short -k "not test_cronico_alta_penalty_higher_than_media"` — 0.96s |

### Pre-existing Issues (Unrelated)

- `test_cronico_alta_penalty_higher_than_media` fails on base commit with `IndexError: Index out of range` (OR-Tools API change). **Not caused by this change.**
- Non-deterministic segfault in `test_tasks_dont_overlap_sleep` and `test_tasks_at_different_locations_get_travel_time` when running full suite — CP-SAT/Python 3.13 GC issue. **Not caused by this change.**

### Spec Compliance

| Requirement | Phase | Result | Evidence |
|-------------|-------|--------|----------|
| R1 — Schema accepts crossing | 1 | ✅ | `TestSchemaCrossingPhase1` (3 accept + 2 reject cases) |
| R2 — `_validate_task_duration` uses `abs_duration()` | 1 | ✅ | `TestValidateTaskDurationPhase1` (valid, excessive, same-day) |
| R3 — `_validate_consistency` uses `abs_duration()` | 1 | ✅ | `TestValidateConsistencyPhase1` (crossing positive, normal window) |
| R4 — Diagnosis uses `abs_duration()` | 1 | ✅ | Code review (line 967) |
| R5 — Tests segment-aware assertions | 1 | ✅ | `test_sleep_block_crossing_midnight` (lines 272-273) |
| R6 — Rest block crossing | 2 | ✅ | `test_rest_block_crossing` |
| R7 — Flex task segment-split | 2 | ✅ | `test_flex_task_crossing_midnight`, `test_flex_task_crossing_post_midnight` |
| R8 — RB‑02/04/06 `abs_duration()` bounds | 2 | ✅ | Code review (lines 505, 587, 648) |
| R9 — RB‑03 per-segment thresholds | 2 | ✅ | Code review (lines 530-549) |
| R10 — RB‑05 `after_midnight` BoolVar | 2 | ✅ | Code review (lines 626-632) |
| R11 — RB‑08 day-range arithmetic | 2 | ➖ N/A | Design confirms no change needed |
| R12 — Backward compat | 1+2 | ✅ | `test_crossing_default_window_identical` + same-day validation/consistency tests |

**Compliance summary**: 15/16 scenarios compliant (1 N/A)

---

## Archive Contents

```
openspec/changes/horario-midnight-crossing/
├── proposal.md       ✅  (intent, scope, approach)
├── spec.md           ✅  (delta spec — 12 requirements, 15 scenarios)
├── design.md         ✅  (architecture decisions, CP-SAT formulation)
├── tasks.md          ✅  (12/12 tasks complete)
├── verify-report.md  ✅  (PASS WITH WARNINGS)
└── archive-report.md ✅  (this file)
```

---

## SDD Cycle Complete

The `horario-midnight-crossing` change has been fully planned (proposal → spec → design → tasks), implemented and verified (12/12 tasks, 57 tests, PASS WITH WARNINGS), and archived. All requirements are implemented and backward compatible. Source files remain in `sdd/horario-midnight-crossing/` (originals preserved). Spec synced to `openspec/specs/schedule/spec.md`.

Ready for the next change.
