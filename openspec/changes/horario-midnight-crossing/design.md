# Design: horario-midnight-crossing

## Technical Approach

Two-phase delivery: **Phase 1** relaxes schema validation and replaces `fin - inicio` with `abs_duration()` in 4 arithmetic sites. **Phase 2** splits the CP‑SAT day window into two segments for flexible tasks, restricts rest blocks to one segment, and adjusts RB bound/threshold computation per segment. Both phases share `abs_duration()` from `time_utils.py` — no new primitives needed.

## Architecture Decisions

### Decision A: Window Representation in CP‑SAT

| Option | Tradeoff | Decision |
|--------|----------|----------|
| **A1 — Segment split** (two OptionalIntervalVar per task/day) | + Keeps contiguous IntVar domains; non-crossing days unchanged<br>– 2× vars per crossing day; RB iteration becomes segment-aware | **CHOSEN** |
| A2 — Single non‑contiguous domain | – CP‑SAT propagates poorly on disjoint domains; RB‑03/05 still need segment detection | Rejected |
| A3 — Shifted time (`(t − inicio) % 1440`) | – Absolute‑time variables break travel/order constraints that use day‑relative values | Rejected |

**Rationale**: A1 is the only option that keeps non‑crossing days untouched (backward compat) while giving the solver contiguous domains for each segment. The extra BoolVar per segment is cheap (CP‑SAT handles thousands).

### Decision B: Rest Block Placement

| Case | Placement | Rationale |
|------|-----------|-----------|
| `1440 − inicio ≥ 30` (segment 1 fits) | Segment 1: `s ∈ [inicio, 1440−30)` | Default: same as today's behavior for non‑crossing |
| else | Segment 2: `s ∈ [0, fin−30)` | Only when window starts very late (>1410) |

No choice BoolVar — placement is decided at model‑build time. This is safe because at least one segment always fits (validated `abs_duration > 0`, rest = 30 min).

### Decision C: RB Threshold per Segment

For crossing windows, RB‑03 and RB‑05 need segment‑aware arithmetic. Rather than adding `is_after_midnight` BoolVars, the design adds per‑segment entries to `info["vars"][dia]` so each RB iteration can use segment‑specific bounds.

---

## Phase 1 — Schema / Arithmetic Changes

### `_validate_per_day_hours` (schedule_request.py, line 54)

Relax from `0 ≤ inicio < fin ≤ 1440` to:

```python
for i in range(d_tot):
    inicio = ctx.horario_inicio[i]
    fin = ctx.horario_fin[i]
    if not (0 <= inicio <= 1440 and 0 <= fin <= 1440):
        raise ValueError(...)
    if abs_duration(inicio, fin) <= 0:
        raise ValueError(...)
```

Rejects zero‑duration windows. Import `abs_duration` from `domain.services.time_utils`.

### `_validate_task_duration` (line 656)

```python
# Before
max_daily = max(ctx.horario_fin[d] - ctx.horario_inicio[d] for d ...)
# After
max_daily = max(abs_duration(ctx.horario_inicio[d], ctx.horario_fin[d]) for d ...)
```

### `_validate_consistency` (line 760)

```python
# Before
ctx.horario_fin[d] - ctx.horario_inicio[d] - occupied_per_day.get(d, 0)
# After
abs_duration(ctx.horario_inicio[d], ctx.horario_fin[d]) - occupied_per_day.get(d, 0)
```

### Diagnosis fallback (line 817)

```python
# Before
available = (diag.get("horario_fin", 1200) - diag.get("horario_inicio", 480)) * dias_totales
# After
hi = diag.get("horario_inicio", 480)
hf = diag.get("horario_fin", 1200)
available = abs_duration(hi, hf) * dias_totales
```

---

## Phase 2 — CP‑SAT Model Changes

### Window Split: `_add_flexible_task` (line 289)

When `horario_inicio[dia] > horario_fin[dia]`:

```
FOR each crossing day:
    seg1_start = max(inicio, pref_inicio)
    seg1_end   = 1440
    seg2_start = 0
    seg2_end   = min(fin, pref_fin)

    p1 ← BoolVar("seg1")
    s1 ← IntVar(seg1_start, 1440 − dur)
    e1 ← IntVar(seg1_start + dur, 1440)
    iv1 ← OptionalIntervalVar(dia*1440 + s1, dur, dia*1440 + e1, p1)

    p2 ← BoolVar("seg2")
    s2 ← IntVar(0, seg2_end − dur)
    e2 ← IntVar(dur, seg2_end)
    iv2 ← OptionalIntervalVar(dia*1440 + s2, dur, dia*1440 + e2, p2)

    # Exactly one segment active if task on this day
    Add(p == p1 + p2)

    info["vars"][dia] = {
        "p": p, "s": s_main, "e": e_main,  # overall (for RD‑05 sum ≤ 1)
        "seg1": {"p": p1, "s": s1, "e": e1},
        "seg2": {"p": p2, "s": s2, "e": e2},
    }
```

`s_main` and `e_main` reference seg1's vars (arbitrary — `p` already delegates via p1 + p2).

### Rest Blocks: `_add_rest_blocks` (line 222)

```
IF is_crossing(inicio, fin):
    IF 1440 − inicio >= 30:
        seg = 1; s_low=inicio; s_high=1440−30
    ELSE:
        seg = 2; s_low=0; s_high=fin−30
    s ← IntVar(s_low, s_high)
    e ← IntVar(s_low + 30, s_high + 30)  # same segment
ELSE:
    s ← IntVar(inicio, fin−30)
    e ← IntVar(inicio+30, fin)
```

### RB‑02 (line 422) — bound fix only

```python
effective_range = abs_duration(ctx.horario_inicio[dia], ctx.horario_fin[dia])
total = model.NewIntVar(0, effective_range, f"rb02_t_d{dia}")
```

Also widen `excess` bound: `min(600, effective_range - 360)` → `max(600, effective_range - 360)`.

### RB‑03 (line 435) — per‑segment thresholds

```
early_thr = inicio + 60                                    # segment 1 only
late_thr_seg1 = 1440 - 60  (= 1380)                       # last 60 min of seg 1
late_thr_seg2 = max(0, fin - 60)                          # last 60 min of seg 2

# Segment 1: early check
IF "seg1" IN v:
    early ← v["seg1"]["s"] < early_thr

# Segment 1: late check (using seg1 end)
    late1 ← v["seg1"]["e"] > late_thr_seg1

# Segment 2: late check only (early zone doesn't reach seg 2)
IF "seg2" IN v:
    late2 ← v["seg2"]["e"] > late_thr_seg2

# Penalty: w per active late/early variable, gated by segment's own p
```

### RB‑04 (line 458) — bound fix only

```python
day_range = abs_duration(ctx.horario_inicio[dia], ctx.horario_fin[dia])
total = model.NewIntVar(0, day_range, ...)   # same logic
idle = model.NewIntVar(0, day_range, ...)
model.Add(idle == day_range - total)
```

Correct: `idle` measures unused portion of the effective window, which excludes the `[fin, inicio)` gap.

### RB‑05 (line 487) — segment‑aware work_before

```
effective_range = abs_duration(inicio, fin)
work_before ← IntVar(0, effective_range)

IF is_crossing(inicio, fin):
    after_midnight ← BoolVar("rb05_am")
    Add(v["s"] < inicio).OnlyEnforceIf(after_midnight)
    Add(v["s"] >= inicio).OnlyEnforceIf(after_midnight.Not())
    # work_before = v["s"] − inicio + (1440 if after_midnight else 0)
    Add(work_before == v["s"] − inicio + 1440 * after_midnight).OnlyEnforceIf(v["p"])
ELSE:
    Add(work_before == v["s"] − inicio).OnlyEnforceIf(v["p"])

Add(work_before == 0).OnlyEnforceIf(v["p"].Not())
```

Widen `excess` bound same as RB‑02: `max(600, effective_range - 240)`.

### RB‑06 (line 501) — bound fix only

```python
effective_range = abs_duration(ctx.horario_inicio[dia], ctx.horario_fin[dia])
mis = model.NewIntVar(0, effective_range, f"rb06_mis_{tid}_d{dia}")
model.Add(mis >= effective_range - info["dur"] * 3).OnlyEnforceIf(v["p"])
```

### RB‑08 (line 513) — no change needed

RB‑08 sums durations per day (not positions). The 600 bound for `sd`/`sd1` and `diff` may be tight for large windows but is not a crossing‑specific issue. Not modified.

---

## Backward Compatibility

| Scenario | Checks |
|----------|--------|
| Default (480, 1200) | All validation passes `inicio < fin` → `is_crossing` is False → no split → identical model |
| Any same‑day window | Same path — `is_crossing` False → pre‑change code path identical |
| Crossing window | Only when `fin <= inicio` (newly accepted) → new code path |

No data migration needed — existing stored data always has `inicio < fin`.

---

## Files Changed

| File | Action | Phase |
|------|--------|-------|
| `schemas/schedule_request.py` | Modify `_validate_per_day_hours` | 1 |
| `domain/services/schedule_service.py` | Modify `_validate_task_duration`, `_validate_consistency`, `_build_response` (diagnosis), `_add_rest_blocks`, `_add_flexible_task`, RB‑02/03/04/05/06 | 1+2 |
| `tests/test_midnight_crossing.py` | Fix assertions at lines 272–273 (segment‑aware checks) | 1 |
| `tests/test_schedule_optimizer.py` | No changes needed (all use same‑day windows) | — |

No new files needed.

---

## Testing Strategy

| Layer | Phase | What | Approach |
|-------|-------|------|----------|
| Unit (Phase 1) | 1 | Schema accepts crossing, rejects zero‑duration | Parameterized `_validate_per_day_hours` tests with (480,60) → OK, (1440,0) → ValueError, (480,1200) → OK |
| Unit (Phase 1) | 1 | `_validate_task_duration` uses effective window | Task of 600 min with (480,60) → OK |
| Unit (Phase 1) | 1 | `_validate_consistency` positive `available_per_day` | Crossing window, no occupied → all entries = `abs_duration` |
| Unit (Phase 1) | 1 | Diagnosis uses `abs_duration` | Cross window, infeasible → `available` = 1020 × days |
| Unit (Phase 2) | 2 | Rest block bounds | (480,60) → s ∈ [480, 1410), e ∈ [510, 1440) |
| Unit (Phase 2) | 2 | Flex task split | 60‑min task, (480,60): seg1 s ∈ [480, 1380), seg2 s ∈ [0, 0] |
| Integration | 2 | Full schedule with crossing window | (480,60) + 3 tasks → OPTIMA |
| Regression | 1+2 | Default window identical | (480,1200) produces same IntVar bounds and objective |
| Soft constraints | 2 | RB‑03 with `late_thr` = 0 | Only segment‑2 tasks penalised as late |
| Soft constraints | 2 | RB‑05 after‑midnight work_before | Task at s=30 → work_before=990 |
| Edge | 2 | Rest in segment 2 | Window (1400, 120) → rest in seg2 |

---

## Migration

No data migration. Existing stored `ContextoUsuario` entries always have `inicio < fin`. The defaults (480, 1200) produce identical behavior.

---

## Open Questions

- [ ] **RB‑03 late zone for `fin < 60`**: When the crossing window ends less than 60 min past midnight, the "last 60 min" spans both segments (e.g., fin=30 → last 60 min = [1410, 1440) ∪ [0, 30)). Should we penalize BOTH the seg1 tail AND seg2? Current design penalizes only seg2. Frequency of `fin < 60` is expected to be negligible.
- [ ] **RB‑02/05 `excess` bound**: Increasing from 600 to `max(600, effective_range - 360/240)` may change penalty magnitude for non‑crossing days with very long windows. Verify no regression on existing scenarios.
