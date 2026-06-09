# Exploration: horario-midnight-crossing

## Current State

`horario_inicio` and `horario_fin` in `ContextoUsuario` define a user's active daily window in minutes (0–1440). Currently **required**: `inicio < fin` (same-day only). The convention for midnight-crossing *activities* and *sleep blocks* already exists in `time_utils.py` via `abs_duration()` (where `fin <= inicio` signals crossing), but this convention is **not** applied to the user's active window.

## Affected Areas — Complete Usage Map

### 1. Domain Entity — `domain/entities/user_context.py`

| Line(s) | Field | What it does | Breaks? | How to update |
|---------|-------|-------------|---------|---------------|
| 24–25 | `horario_inicio: int \| list[int] = 480` | Default value | No | Same default, no change needed |
| 24–25 | `horario_fin: int \| list[int] = 1200` | Default value | No | Same default, no change needed |
| 38–41 | `__post_init__` | Normalizes `int → list[int] * 7` | No | Works as-is; values are just forwarded |

### 2. Schema (Pydantic) — `schemas/user_context.py`

| Line(s) | What it does | Breaks? | How to update |
|---------|-------------|---------|---------------|
| 21–22 | Field declarations with defaults | No | Keep as-is |
| 27–42 | `_validate_horario_list` — validates 0 ≤ each value ≤ 1440 | **No** (range check is fine) | Keep as-is; range [0, 1440] is still valid for crossing |

### 3. Schema Validation — `schemas/schedule_request.py` ⚠️ **KEY BREAKAGE**

| Line(s) | What it does | Breaks? | How to update |
|---------|-------------|---------|---------------|
| 37–38 | Expand `int → list` per `dias_totales` | No | Keep as-is |
| 39–40 | Same for `horario_fin` | No | Keep as-is |
| 43–52 | Validate list length matches `dias_totales` | No | Keep as-is |
| **54–63** | **`_validate_per_day_hours`**: `0 <= inicio < fin <= 1440` | **YES** — `fin=60, inicio=480` would fail `inicio < fin` | **Relax validation**: allow `fin <= inicio` when midnight-crossing is intended. New check: `(0 <= inicio <= 1440)` and `(0 <= fin <= 1440)` and `(inicio != fin or inicio == 0)` — basically allow any combination where `abs_duration(inicio, fin) > 0`. The duration will be computed via `abs_duration()` downstream. |

### 4. Mapper — `infrastructure/adapters/inbound/api/mappers.py`

| Line(s) | What it does | Breaks? | How to update |
|---------|-------------|---------|---------------|
| 76 | `horario_inicio=dto.horario_inicio` | No | Pass-through; DTO already validated |
| 77 | `horario_fin=dto.horario_fin` | No | Pass-through |

### 5. Diagnostics — `domain/services/schedule_service.py` (generar → state["diagnosis"])

| Line(s) | What it does | Breaks? | How to update |
|---------|-------------|---------|---------------|
| 102 | `"horario_inicio": ctx.horario_inicio[0]` — stores first day's start in diagnosis | **YES** — assumes single value for all days | Keep as-is (diagnosis) or change to list; minor impact |
| 103 | `"horario_fin": ctx.horario_fin[0]` — same | **YES** — assumes single value | Same as above |

### 6. Validation — `domain/services/schedule_service.py` (generar)

| Line(s) | What it does | Breaks? | How to update |
|---------|-------------|---------|---------------|
| 61–73 | **Length check**: `len(horario_inicio) >= dia_inicio + dias_totales` | No | Still works |

### 7. Validation — `domain/services/schedule_service.py` (_validate_task_duration)

| Line(s) | What it does | Breaks? | How to update |
|---------|-------------|---------|---------------|
| **656** | `max_daily = max(horario_fin[d] - horario_inicio[d] ...)` | **YES** — `horario_fin[d] - horario_inicio[d]` produces negative for crossing | Replace with: `max_daily = max(abs_duration(horario_inicio[d], horario_fin[d]) ...)` |

### 8. Validation — `domain/services/schedule_service.py` (_validate_consistency)

| Line(s) | What it does | Breaks? | How to update |
|---------|-------------|---------|---------------|
| **761** | `horario_fin[d] - horario_inicio[d] - occupied` | **YES** — negative for crossing | Replace with `abs_duration(horario_inicio[d], horario_fin[d]) - occupied_per_day.get(d, 0)` |

### 9. Hard Constraints — Rest Blocks (`_add_rest_blocks`)

| Line(s) | What it does | Breaks? | How to update |
|---------|-------------|---------|---------------|
| **228** | `IntVar(start, horario_inicio[dia], horario_fin[dia] - dur)` — start bound | **YES** — `horario_fin[dia] - dur` is negative if `fin=60, dur=30` (60-30 = 30, which is *less* than `horario_inicio[dia]=480` → empty domain) | This is the **hardest part**. The current model assumes a contiguous same-day window. For crossing windows, need to split the window into two segments: [inicio, 1440) and [0, fin). For rest blocks specifically: if crossing, either pick one segment or convert to absolute-time modeling. |
| **229** | `IntVar(end, horario_inicio[dia] + dur, horario_fin[dia])` — end bound | **YES** — same issue: `horario_inicio[dia] + dur` > `horario_fin[dia]` when `fin=60` | Same as above — window split needed |

### 10. Hard Constraints — Flexible Tasks (`_add_flexible_task`)

| Line(s) | What it does | Breaks? | How to update |
|---------|-------------|---------|---------------|
| **291-292** | `day_start = horario_inicio[dia]`, `day_end = horario_fin[dia]` | **YES** — `day_start=480, day_end=60` produces empty domain for IntVars | Window-split logic: if crossing, the effective window is `[inicio, 1440)` ∪ `[0, fin)`. For IntVar bounds: cap `day_end` at 1440, and handle the two-segment domain. **Alternative**: model these as absolute intervals instead of day-relative vars. |
| **294–296** | Intersect with `hora_preferida_inicio/fin` | **YES** — `max(480, pref_inicio)` and `min(60, pref_fin)` could produce `max > min` | Apply intersection *per segment* |
| **299–301** | `IntVar(s, day_start, day_end - dur)` etc. | **YES** — `day_end - dur` may be < `day_start` | Window-split or absolute-time approach |

### 11. Soft Constraints — RB-02 (work concentration)

| Line(s) | What it does | Breaks? | How to update |
|---------|-------------|---------|---------------|
| **422** | `total = IntVar(0, horario_fin[dia] - horario_inicio[dia])` | **YES** — negative bound | Replace bound with `abs_duration(inicio, fin)` |
| **435** | `early_thr = horario_inicio[dia] + 60` | No | Still works if `inicio=480` → 540 |
| **436** | `late_thr = horario_fin[dia] - 60` | **YES** — `60 - 60 = 0`, meaning threshold = 0 | For crossing windows, late threshold should be `effective_end() - 60` where `effective_end()` = `fin + 1440`. Or use modulo arithmetic. |

### 12. Soft Constraints — RB-03 (preferred hours)

| Line(s) | What it does | Breaks? | How to update |
|---------|-------------|---------|---------------|
| **435-436** | `early_thr = inicio + 60`, `late_thr = fin - 60` | **YES** — `late_thr = 0` for crossing, which is meaningless | Compute late_thr differently for crossing windows: `late_thr = (fin + 1440) - 60 mod 1440` |

### 13. Soft Constraints — RB-04 (dead time)

| Line(s) | What it does | Breaks? | How to update |
|---------|-------------|---------|---------------|
| **458** | `day_range = horario_fin[dia] - horario_inicio[dia]` | **YES** — negative | Replace with `abs_duration(inicio, fin)` |
| **470-473** | `total`, `idle` IntVars bounded by `day_range` | **YES** — negative domain | Fixed by above fix |

### 14. Soft Constraints — RB-05 (hard task after long work)

| Line(s) | What it does | Breaks? | How to update |
|---------|-------------|---------|---------------|
| **487** | `work_before = IntVar(0, horario_fin[dia] - horario_inicio[dia])` | **YES** — negative bound | Replace bound with `abs_duration(inicio, fin)` |
| **488** | `work_before == v["s"] - horario_inicio[dia]` | **YES** — if task starts at, say, 120 (next day, past midnight), `120 - 480 = -360` | Variable `v["s"]` is day-relative in [0,1440). For crossing windows, a task that starts at 120 is actually 120 minutes *into* the window (since midnight crossing means the window continues next day). The "time before this task" should be computed as: if `v["s"] >= inicio`, then `v["s"] - inicio`; else `v["s"] + 1440 - inicio`. This needs careful modeling. |

### 15. Soft Constraints — RB-06 (duration-block mismatch)

| Line(s) | What it does | Breaks? | How to update |
|---------|-------------|---------|---------------|
| **501** | `mis = IntVar(0, horario_fin[dia] - horario_inicio[dia])` | **YES** — negative bound | Replace with `abs_duration(inicio, fin)` |
| **502** | `mis >= (horario_fin[dia] - horario_inicio[dia]) - dur*3` | **YES** — negative base | Replace inner subtraction with `abs_duration(inicio, fin) - dur*3` |

### 16. Diagnosis fallback (INFEASIBLE response)

| Line(s) | What it does | Breaks? | How to update |
|---------|-------------|---------|---------------|
| **817** | `available = (horario_fin - horario_inicio) * dias_totales` | **YES** — if crossing, e.g., `(60 - 480) = -420` → negative available time | Replace with `abs_duration(horario_inicio[0], horario_fin[0]) * dias_totales` |

### 17. Reschedule Service — `domain/services/reschedule_service.py`

| Line(s) | What it does | Breaks? | How to update |
|---------|-------------|---------|---------------|
| 65–66 | Forward `horario_inicio`, `horario_fin` to new `ContextoUsuario` | No | Straight pass-through; will be validated downstream |

### 18. Test Files

| File | Lines | What it does | Breaks? | Notes |
|------|-------|-------------|---------|-------|
| `tests/test_schedule_optimizer.py` | 54–62, 160, 385, 407, 423, 529, 551 | Uses `_make_ctx(horario_inicio=480, horario_fin=1200)` (same-day) | No | No change needed |
| `tests/test_dynamic_scheduling.py` | 169–1100 | Uses same-day windows in all tests | No | No change needed for existing tests |
| `tests/test_api_endpoints.py` | 54, 90, 129, 152, 193, 231 | Uses `horario_inicio=480`, `horario_fin=1200` in JSON payloads | No | No change needed |
| `tests/test_energy_mapper.py` | 92–102 | Tests mapper preserves values | No | No change needed |
| `tests/test_reschedule_service.py` | 56–57 | Uses 480/1200 | No | No change needed |
| `tests/test_midnight_crossing.py` | 236, 272–273, 294, 513–560 | Tests *activity and sleep* midnight crossing, **NOT** user window crossing | **No but misleading** | Lines 272-273 assert `block.hora_inicio >= ctx.horario_inicio[0]` and `block.hora_fin <= ctx.horario_fin[0]` — these assume same-day ctx window even when testing crossing activities |

## Approaches

### Approach A: Per-Day Window Split (recommended)

In CP-SAT, when `horario_inicio[d] > horario_fin[d]`, split each day's window into two segments:
- Segment 1: `[horario_inicio[d], 1440)`  
- Segment 2: `[0, horario_fin[d]]`

Each task/rest gets a choice of which segment it falls into (via optional interval vars). The `day_range` is `abs_duration(horario_inicio[d], horario_fin[d])`.

- **Pros**: Works within the existing per-day CP-SAT model structure; keeps day-relative variables
- **Cons**: Significant refactor of `_add_rest_blocks` and `_add_flexible_task`; each task needs an extra BoolVar per day to pick segment; RB-03/RB-05 need complex rework for "early/late" boundaries
- **Effort**: High

### Approach B: Absolute-Time Modeling

Convert all day-relative variables to absolute-minute variables (relative to week start). The day window becomes: from `to_abs(d, horario_inicio[d])` to `to_abs(d, horario_inicio[d]) + abs_duration(horario_inicio[d], horario_fin[d])`.

- **Pros**: Naturally handles crossing (abs_duration already works); no window splitting; RB constraints become simpler
- **Cons**: Massive refactor — every per-day IntVar, every constraint, every RB needs rewriting; touches nearly the entire `schedule_service.py`
- **Effort**: Very High

### Approach C: Normalize to Same-Day at Schema Level

At the schema/domain level, convert a crossing window `(inicio=480, fin=60)` into a non-crossing same-day window: set `horario_inicio=480, horario_fin=480 + abs_duration(480, 60) = 1500`, cap at 1440, and adjust `dia` for tasks that fall past midnight.

- **Pros**: Minimal internal changes (all existing CP-SAT code works unchanged)
- **Cons**: Changes the semantics — external API receives a different representation; breaks the "minutes in 0–1440" contract; complex to manage when tasks may span the midnight boundary within the user window
- **Effort**: Medium

### Approach D: Schema-Level Crossing Acceptance + Per-Day Refinement

**This is the pragmatic middle ground.** Changes:
1. **Schema validation** (`schemas/schedule_request.py`): relax `inicio < fin` to accept any valid `[0,1440]` pair where `abs_duration(inicio, fin) > 0`
2. **Validation methods** (`_validate_task_duration`, `_validate_consistency`): replace `fin - inicio` with `abs_duration(inicio, fin)`
3. **Diagnosis**: same replacement
4. **CP-SAT model**: For each day with `inicio > fin`:
   - `day_range` = `abs_duration(inicio, fin)`
   - Rest blocks: restrict to the first segment `[inicio, 1440)` (rest is same-day only)
   - Flexible tasks: split domain into two segments using optional interval vars with a `is_after_midnight` BoolVar
   - RB-03 (early/late): thresholds computed as `inicio + 60` and `(fin + 1440) - 60` in absolute terms, then mapped back
   - RB-05 (work before): compute as: if task in segment 1 → `s - inicio`; if segment 2 → `(1440 - inicio) + s`

- **Pros**: Backward compatible; validation and arithmetic fixes are straightforward; CP-SAT changes are localized to the window-split functions
- **Cons**: RB-03 thresholds need careful mapping; RB-05 work-before needs conditional logic per segment
- **Effort**: Medium-High

## Recommendation

**Approach D** is the most practical. The critical path is:

1. **Relax schema validation** (low effort, no risk)
2. **Fix arithmetic in validation + diagnosis** — replace `fin - inicio` with `abs_duration(inicio, fin)` (medium effort, well-understood pattern)
3. **CP-SAT model changes** — window split for flexible tasks + rest blocks + RB rework (high effort, needs careful CP-SAT modeling)

Steps 1 and 2 can be done independently and verified first. Step 3 is the real engineering challenge.

## Risks

- **Risk 1**: CP-SAT IntVar domains must be contiguous or use `model.NewIntVarFromDomain()` with a `Domain` object. The window split (approach D) requires non-contiguous domains or optional interval vars per segment. This may increase model complexity significantly.
- **Risk 2**: RB-03 (`early_thr`/`late_thr`) loses its intuitive meaning with crossing windows — "first hour" and "last hour" span both segments. Need to decide: penalize tasks in the last 60 min of the *effective* end (1440+fin-60 in absolute terms)?
- **Risk 3**: RB-05's `v["s"] - horario_inicio` assumes `v["s"] >= inicio`. For tasks in the after-midnight segment, `s` is small (e.g., 30) and `inicio` is large (480), producing negative. Needs to compute: `s + 1440 - inicio` for segment-2 tasks.
- **Risk 4**: Test file `tests/test_midnight_crossing.py` lines 272-273 assert `hora_inicio >= horario_inicio[0]` and `hora_fin <= horario_fin[0]` — these will fail if the ctx window itself crosses midnight and the task is scheduled in the post-midnight segment.

## Ready for Proposal

**Yes** — the impact map above is sufficient for proposal and spec writing. The orchestrator should proceed to the proposal phase with this analysis.
