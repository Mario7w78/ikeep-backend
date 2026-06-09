# Delta spec: horario-midnight-crossing

## Purpose

Allow `horario_inicio` / `horario_fin` in `ContextoUsuario` to express midnight-crossing windows
(e.g., `inicio=480`, `fin=60` meaning 8 AM → 1 AM next day), using the existing
`abs_duration()` convention where `fin <= inicio` signals crossing.

Two-phase delivery: **Phase 1** (schema + arithmetic fixes), **Phase 2** (CP‑SAT window split).

## Requirements

| ID | Domain | Requirement | Phase |
|----|--------|-------------|-------|
| R1 | Validación Schema | `_validate_per_day_hours` MUST accept any pair where `0 ≤ inicio ≤ 1440`, `0 ≤ fin ≤ 1440`, and `abs_duration(inicio, fin) > 0` | 1 |
| R2 | Validación Service | `_validate_task_duration` MUST use `abs_duration()` for `max_daily` | 1 |
| R3 | Consistencia | `_validate_consistency` MUST use `abs_duration()` for `available_per_day` | 1 |
| R4 | Diagnóstico | `_build_response` (line 817) MUST use `abs_duration()` for `available` | 1 |
| R5 | Tests | `test_midnight_crossing.py` assertions hardcoding `horario_inicio[0]` / `horario_fin[0]` MUST use segment-aware checks | 1 |
| R6 | Descanso | `_add_rest_blocks` MUST constrain rest interval to `[inicio, 1440)` when window crosses | 2 |
| R7 | Tareas flexibles | `_add_flexible_task` MUST split crossing window into `[inicio, 1440)` ∪ `[0, fin]` with per-segment optional interval vars | 2 |
| R8 | RB‑02/04/06 | IntVar upper bounds MUST use `abs_duration(inicio, fin)` instead of `fin - inicio` | 2 |
| R9 | RB‑03 | `late_thr` MUST compute as `effective_end - 60` for crossing windows | 2 |
| R10 | RB‑05 | `work_before` MUST use `s + 1440 - inicio` when `s < inicio` | 2 |
| R11 | RB‑08 | Day‑range arithmetic MUST use `abs_duration()` | 2 |
| R12 | Retrocompat | All existing `(480, 1200)` windows MUST produce identical results | 1+2 |

## Scenarios

### R1 — Schema accepts crossing window
- GIVEN `horario_inicio=480, horario_fin=60`
- WHEN `SolicitudHorario` validates
- THEN no `ValueError` is raised

### R1 — Same‑day window still works
- GIVEN `horario_inicio=480, horario_fin=1200`
- WHEN `SolicitudHorario` validates
- THEN no `ValueError` is raised

### R1 — Zero‑duration window rejected
- GIVEN `horario_inicio=1440, horario_fin=0`
- WHEN `SolicitudHorario` validates
- THEN `ValueError` is raised

### R2 — Task duration respects effective window
- GIVEN `horario_inicio=480, horario_fin=60` (1020 min effective) and task of 600 min
- WHEN `_validate_task_duration` runs
- THEN no error (600 < 1020)

### R3 — Available per day not negative
- GIVEN `horario_inicio=480, horario_fin=60` over 7 days, no occupied time
- WHEN `_validate_consistency` computes `available_per_day`
- THEN each entry is 1020, not negative

### R4 — Diagnosis shows positive available hours
- GIVEN crossing window and infeasible problem
- WHEN `_build_response` computes `available`
- THEN `available = abs_duration(480, 60) × dias_totales = 1020 × 7`

### R5 — Sleep‑block test assertion passes
- GIVEN `test_sleep_block_crossing_midnight` with a crossing ctx window
- WHEN assertion `hora_inicio >= ctx.horario_inicio[0]` runs
- THEN it accounts for the segment the task landed in (first‑segment tasks keep the assertion; second‑segment tasks compare against 0)

### R6 — Rest block bounds valid crossing
- GIVEN `horario_inicio=480, horario_fin=60`
- WHEN `_add_rest_blocks` creates IntVars
- THEN `s` domain is `[480, 1440 − dur]`, `e` domain is `[480 + dur, 1440]`

### R7 — Flex task in pre‑midnight segment
- GIVEN 60 min flex task, window `(480, 60)`
- WHEN placed pre‑midnight
- THEN `s ∈ [480, 1380)`, `e = s + 60`

### R7 — Flex task post‑midnight
- GIVEN 60 min flex task, window `(480, 60)`
- WHEN placed after midnight
- THEN `s ∈ [0, 0]` (only `s=0` fits a 60‑min block in `[0, 60]`), `e = 60`

### R8 — RB‑02 total bound valid
- GIVEN `horario_inicio=480, horario_fin=60`
- WHEN RB‑02 creates `total` IntVar
- THEN upper bound is 1020 (not negative)

### R9 — RB‑03 late threshold crossing
- GIVEN `horario_inicio=480, horario_fin=60`
- WHEN RB‑03 computes `late_thr`
- THEN `late_thr = (60 + 1440 − 60) % 1440 = 0` (last 60 min before 01:00)

### R10 — RB‑05 work‑before post‑midnight
- GIVEN `s = 30`, `inicio = 480`, window crosses
- WHEN RB‑05 computes `work_before`
- THEN `work_before = 30 + 1440 − 480 = 990`

### R12 — Default window identical
- GIVEN `horario_inicio=480, horario_fin=1200`
- WHEN any optimization runs
- THEN every IntVar bound and objective value matches pre‑change output

## Coverage

- **Happy paths**: R1, R2, R3, R4, R12 — cross‑window acceptance and arithmetic fixes
- **Edge cases**: R1 (zero‑duration), R6 (rest bounds crossing), R7 (both segments), R9 (late threshold crossing), R10 (work‑before crossing)
- **Error states**: R1 (zero‑duration rejection), R4 (diagnosis)
