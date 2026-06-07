## Spec: dynamic-scheduling (Phase 1)

---

### Feature 1: Manual Energy Pattern Override

#### Requirements

1.1 MUST add `patron_energia_manual: PatronEnergia | None = None` to `ContextoUsuario` in the domain entity (`domain/entities/user_context.py`).

1.2 MUST add the same field to `ContextoUsuario` in the Pydantic schema (`schemas/user_context.py`).

1.3 MUST update `contexto_to_domain()` in `infrastructure/adapters/inbound/api/mappers.py` to pass `patron_energia_manual` from DTO to domain entity.

1.4 In `ScheduleOptimizer.generar()` (`domain/services/schedule_service.py`), MUST check `ctx.patron_energia_manual` BEFORE calling `clasificar_patron_energia()`. If the manual field is not `None`, SHALL use it directly and skip classification. If `None`, SHALL fall back to the existing classifier call.

1.5 The `_patron_override` mechanism at line 63 SHALL assign whichever value is resolved (manual or classified), keeping all downstream `_rb_*` consumers unchanged.

#### Scenarios

| ID | Scenario | Input | Expected |
|----|----------|-------|----------|
| E1.1 | Manual override active — classifier would disagree | `patron_energia_manual=CRONICO`, history says TRANSCRIPTORIO, level=3 | `self._patron_override = CRONICO`; `clasificar_patron_energia()` NOT called |
| E1.2 | No override — default behavior | `patron_energia_manual=None`, any history/level | Classifier runs; `_patron_override` gets its return value |
| E1.3 | Pydantic rejects invalid enum value | `"patron_energia_manual": "invalido"` | 422 validation error |
| E1.4 | Override + CRONICO path | `patron_energia_manual=CRONICO`, weight > 0 | RB-01, RB-04, RB-05 execute their CRONICO branches |
| E1.5 | Override + TENDENCIA path | `patron_energia_manual=TENDENCIA`, low energy | RB-01 hard‑constraint max 1 ALTA/day activates |

#### Validation

- Field MUST be typed `PatronEnergia | None` (union).
- Default MUST be `None` — all existing callers remain unchanged.
- Pydantic MUST reject any value not in `{TRANSCRIPTORIO, TENDENCIA, CRONICO}`.
- Domain entity is a dataclass — no runtime validation needed beyond the type hint.

#### Behavioral Spec

| Aspect | Before | After |
|--------|--------|-------|
| Pattern resolution | Always calls `clasificar_patron_energia(history, level)` | Checks `ctx.patron_energia_manual` first; skips classifier if set |
| Frontend control | None — pattern inferred server-side | Frontend can send `patron_energia_manual` to bypass the classifier |
| `_patron_override` consumer | RB-01, RB-04, RB-05 read `_patron_override` | Unchanged — they read the same field regardless of source |

---

### Feature 2: Real Priority Weighting

#### Requirements

2.1 MUST add `rb_priority: int = 0` to the `PenaltyWeights` dataclass in `domain/services/schedule_service.py`.

2.2 MUST add a new method `_rb_priority()` to `ScheduleOptimizer` that penalizes assigning tasks to unfavorable slots based on their `prioridad` value.

2.3 MUST call `_rb_priority()` from `generar()` in the same `objective_terms` block as the other `_rb_*` methods (after line 118, only when `solicitud.tareas_pendientes` is non-empty).

2.4 The penalty SHALL be higher when a **low-priority** task occupies a **favorable** slot (early day, good time alignment). Equivalently, **high-priority** tasks SHALL have preferential access to better slots. The exact CP-SAT formulation (per-day penalty, per-time-slot penalty, or a combined expression) is delegated to the design phase.

2.5 Default weight `0` MUST make the method a no-op — no effect on the objective and no solver overhead beyond a guard check.

#### Scenarios

| ID | Scenario | Input | Expected |
|----|----------|-------|----------|
| P2.1 | Mixed priority with positive weight | 2 tasks: P1 prioridad=5, P2 prioridad=0; rb_priority=5 | P1 gets earlier day or better time slot than P2; solution avoids penalty |
| P2.2 | Zero weight (default) | rb_priority=0 | No terms added to objective; priority has zero influence |
| P2.3 | All tasks same priority | 3 tasks, all prioridad=3; rb_priority=5 | Priority does not differentiate; other RB constraints dominate |
| P2.4 | Single task any priority | 1 task prioridad=0; rb_priority=10 | Constraint applies but no relative comparison exists — behavior matches single-task case |

#### Validation

- `rb_priority` MUST accept any non-negative integer.
- Default `0` MUST produce identical solver behavior to the current codebase.
- No new input fields — priority is already on `Actividad` (existing validation applies).

#### Behavioral Spec

| Aspect | Before | After |
|--------|--------|-------|
| `Actividad.prioridad` usage | Stored in state dict but never read by any penalty | Read by `_rb_priority()` to weight slot favorability |
| Objective terms | RB-01 through RB-10 | RB-01 through RB-10 + RB-PRIORITY |
| Solver behavior | Priority-neutral — all tasks treated equally regardless of priority | Higher-priority tasks gravitate to better slots when weight > 0 |
| Backward compat | — | Weight = 0 → identical results |

---

### Feature 3: Optional Day Assignment

#### Requirements

3.1 MUST change `Actividad.dia` from `int` to `int | None = None` in both the domain entity (`domain/entities/activity.py`) and the Pydantic schema (`schemas/activity.py`).

3.2 In `_add_flexible_task()` (`schedule_service.py` line 194): if `act.dia is None`, SHALL set `days = range(7)` (solver may assign any day 0–6). If `act.dia` is set, SHALL use existing behavior (`deadline = min(act.dia, 6)`, `days = range(deadline + 1)`).

3.3 In `_add_fixed()` (`schedule_service.py` line 163): MUST validate that `act.dia is not None` and raise `ValueError` if a fixed activity lacks a day.

3.4 In `_validate_consistency()` (`schedule_service.py` line 516): MUST handle `dia=None` in `tareas_pendientes`. Tasks with `dia=None` SHALL be excluded from the `max(dia)` computation. If any task has `dia=None`, capacity SHALL be evaluated across all 7 days instead of the sub-range determined by deadlines.

3.5 In `reschedule_service.py` (`_to_actividad()`): no code change needed — `bloque.dia` is always an `int` from an existing scheduled block. The new `int | None` type accepts `int` transparently.

3.6 In `actividad_to_domain()` mapper: no code change needed — `dia=dto.dia` maps `int | None` to `int | None` directly.

#### Scenarios

| ID | Scenario | Input | Expected |
|----|----------|-------|----------|
| D3.1 | Flexible task without day | `dia=None`, no deadline | Solver may assign to any day 0–6; `_add_flexible_task` uses `range(7)` |
| D3.2 | Flexible task with explicit day | `dia=3` | Existing behavior: deadline = min(3, 6) = 3, days 0–3 |
| D3.3 | Fixed activity without day | `tipo=CLASE`, `dia=None` | `_add_fixed` raises `ValueError` |
| D3.4 | Mixed: some tasks with `dia`, some without | 2 tasks: T1 `dia=2`, T2 `dia=None` | T1 constrained to days 0–2; T2 free for days 0–6; capacity validated across 7 days |
| D3.5 | All flexible tasks without `dia` | 3 tasks, all `dia=None` | All can span any day; capacity uses full 7-day window |
| D3.6 | Pydantic schema accepts `null` | `"dia": null` in JSON body | Parses as `None`; no validation error |
| D3.7 | Pydantic schema rejects missing `dia` | Omit `dia` from JSON | Parses as default `None` (optional field) — NOT an error |
| D3.8 | Reschedule — existing schedule always has `dia` | `bloque.dia=2` | `Actividad(dia=2)` works with `int \| None = None` |

#### Validation

- `Actividad.dia` domain entity: `int | None = None`
- `Actividad` Pydantic schema: `int | None = None`
- `_add_fixed()`: MUST raise `ValueError` if `dia is None` — fixed activities MUST have a day.
- Schema: no additional Pydantic validator needed; the type union handles it.
- Capacity validation in `_validate_consistency`: MUST NOT crash on `None` values; must compute `days_available` correctly.
- Backward compatible: all existing callers pass `int` → behavior identical.

#### Behavioral Spec

| Aspect | Before | After |
|--------|--------|-------|
| `Actividad.dia` type | `int` (required) | `int \| None = None` |
| Flexible task without day | Not possible — `dia` required | Solver chooses freely across 0–6 |
| Fixed activity without day | Not possible | Raises `ValueError` with descriptive message |
| Capacity validation | `days_available = max(dia)+1` | `None` tasks excluded from max; if any `None` → 7 days |
| Frontend contract | `dia` always required | `dia` optional (default `null`) |
| Reschedule path | Always passes `int` to `Actividad(dia=...)` | Unchanged — `int` still accepted |
