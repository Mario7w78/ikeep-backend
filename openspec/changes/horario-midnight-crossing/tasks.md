# Tasks: horario-midnight-crossing

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~204 |
| 400-line budget risk | Low |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 (Phase 1: ~13 lines) → PR 2 (Phase 2: ~191 lines) |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Lines | Notes |
|------|------|-----------|-------|-------|
| 1 | Schema + arithmetic fixes | PR 1 | ~13 | All Phase 1 tasks; base = main |
| 2 | CP-SAT model changes | PR 2 | ~191 | All Phase 2 tasks; base = main or PR 1 branch |

## Phase 1: Schema & Arithmetic Fixes

- [x] **1.1** — `schemas/schedule_request.py:58`: relax validator to accept `fin <= inicio`. Use `abs_duration(inicio, fin) > 0`. Update error message.
- [x] **1.2** — `domain/services/schedule_service.py:656`: `_validate_task_duration`: replace `fin - inicio` with `abs_duration()` for `max_daily`.
- [x] **1.3** — `domain/services/schedule_service.py:761`: `_validate_consistency`: replace `fin - inicio` with `abs_duration()` for `available_per_day`.
- [x] **1.4** — `domain/services/schedule_service.py:817`: `_build_response` diagnosis: replace raw subtraction with `abs_duration(hi, hf)`.
- [x] **1.5** — `tests/test_midnight_crossing.py:272-273`: make sleep-block assertions segment-aware (non-breaking for non-crossing ctx).

## Phase 2: CP-SAT Model Changes

- [x] **2.1** — `domain/services/time_utils.py`: add `effective_window(inicio, fin)` helpers (effective_window_end, effective_window_start).
- [x] **2.2** — `_add_rest_blocks`: when crossing, constrain rest to `[inicio, 1440)` (seg1) if fits, else `[0, fin)` (seg2). Single segment, no choice bool.
- [x] **2.3** — `_add_flexible_task`: when crossing, create 2 OptionalIntervalVar per day (seg1: `[inicio, 1440)`, seg2: `[0, fin]`) with `Add(p == p1 + p2)`. Store seg1/seg2 in `info["vars"][dia]`. Merged s/e vars for RB compat.
- [x] **2.4** — `_rb_03`: per-segment `early_thr`/`late_thr`. Seg1: `inicio+60` / `1440-60`. Seg2: late only `fin-60`. Gate penalty by segment's own `p` bool.
- [x] **2.5** — `_rb_05`: when crossing and `s < inicio`, compute `work_before = s + 1440 - inicio`. Use BoolVar `after_midnight` to branch.
- [x] **2.6** — `_rb_02`, `_rb_04`, `_rb_06`: replace `fin - inicio` with `abs_duration()` for IntVar upper bounds. Widen `excess` to `max(600, effective_range - N)`.
- [x] **2.7** — `_build_response`: response already uses `solver.Value(v["s"])` and `solver.Value(v["e"])` — merged s/e are day-relative (0-1440) and correct for both segments.

### Dependencies

- Phase 2 → Phase 1 (schema must accept crossing before CP-SAT model can exercise it)
- 2.1 → 2.2, 2.3, 2.6 (helper needed)
- 2.4, 2.5 → 2.3 (RB iteration depends on flex vars having seg1/seg2)
- 2.2 ↔ 2.3 (independent)
- 2.7 → 2.3 (verification)
