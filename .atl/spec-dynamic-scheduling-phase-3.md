## Spec: dynamic-scheduling-phase-3

### F8: Rolling Week (Foundation)

#### Fields
- `SolicitudHorario.dia_inicio: int = 0` — first day of the rolling window
- `SolicitudHorario.dias_totales: int = 7` — number of days in the window
- Validation: `0 <= dia_inicio`, `1 <= dias_totales <= 14`
- Validation: `dia_inicio + dias_totales <= 7` (within the 7-day week, external timeline stays at 7 fixed days)

#### Scenarios

##### SC-08-01: Rolling week backward compatible default
- **Given**: solicitud with `dia_inicio=0`, `dias_totales=7` (defaults)
- **When**: `generar()` runs
- **Then**: behavior, ranges, and constraints are identical to current hardcoded 7-day week

##### SC-08-02: Mid-week rolling window
- **Given**: solicitud with `dia_inicio=2`, `dias_totales=3`
- **When**: `generar()` runs
- **Then**: tasks are only scheduled on days 2, 3, 4; rest blocks created only for those days

##### SC-08-03: Single-day window
- **Given**: solicitud with `dia_inicio=5`, `dias_totales=1`
- **When**: `generar()` runs
- **Then**: all flexible tasks forced to day 5

##### SC-08-04: Sleep blocks outside window excluded
- **Given**: solicitud with `dia_inicio=3, dias_totales=2`; sleep blocks on days 0, 3, 4
- **When**: _add_sleep_blocks runs
- **Then**: sleep block on day 0 excluded (not in range 3-4); day 3 and 4 included

##### SC-08-05: RB-08 limited to window days
- **Given**: solicitud with `dia_inicio=1, dias_totales=3`
- **When**: _rb_08 runs
- **Then**: consecutive day comparisons only between (1,2) and (2,3); day 0 and 4-6 ignored

##### SC-08-06: RB-10 urgency reindexed
- **Given**: solicitud with `dia_inicio=3, dias_totales=3` (last day = 5)
- **When**: _rb_10 runs
- **Then**: urgency on day 5 = 0 (least urgent), day 3 = 2 (most urgent)

##### SC-08-07: Dia validation error — negative dia_inicio
- **Given**: solicitud with `dia_inicio=-1`
- **When**: Pydantic validation runs
- **Then**: ValueError raised: dia_inicio must be >= 0

##### SC-08-08: Dia validation error — dias_totales out of range
- **Given**: solicitud with `dias_totales=0` or `dias_totales=15`
- **When**: Pydantic validation runs
- **Then**: ValueError raised: dias_totales must be in [1, 14]

##### SC-08-09: Consistency validation uses rolling window
- **Given**: solicitud with `dia_inicio=2, dias_totales=3`, fixed activity on day 1 consuming 600 min
- **When**: _validate_consistency runs
- **Then**: day 1's occupied time excluded from capacity calculation; only days 2, 3, 4 available time counted

### F7: Per-Day Active Hours (on top of F8)

#### Fields
- `ContextoUsuario.horario_inicio: int | list[int] = 480` — schema accepts both; domain always stores `list[int]`
- `ContextoUsuario.horario_fin: int | list[int] = 1200` — same pattern
- List length MUST equal `SolicitudHorario.dias_totales`
- Backward compat: when single `int` received, validator converts to `[int] * dias_totales`

#### Scenarios

##### SC-07-01: Uniform hours backward compatible
- **Given**: ctx with `horario_inicio=480, horario_fin=1200` (single ints)
- **When**: schedule request validated
- **Then**: converted to `[480]*7` and `[1200]*7`; behavior identical to current

##### SC-07-02: Per-day varied hours
- **Given**: ctx with `horario_inicio=[480,480,600,480,480,600,600]`, `horario_fin=[1080,1080,1200,1080,1080,960,960]`
- **When**: constraints built
- **Then**: Mon/Tue/Thu/Fri = 8:00-18:00, Wed = 10:00-20:00, Sat/Sun = 10:00-16:00

##### SC-07-03: Rest blocks respect per-day bounds
- **Given**: ctx with per-day hours as in SC-07-02
- **When**: _add_rest_blocks runs for each day
- **Then**: rest block IntVar bounds use `horario_inicio[dia]` and `horario_fin[dia]` for that day

##### SC-07-04: Flexible task bounds per day
- **Given**: ctx with per-day hours, task on day with 10:00-16:00 window
- **When**: _add_flexible_task runs
- **Then**: `s` and `e` IntVars bounded by `horario_inicio[dia]` and `horario_fin[dia]`

##### SC-07-05: RB-03 uses per-day early/late thresholds
- **Given**: ctx with day 0: 8:00-18:00, day 1: 10:00-16:00
- **When**: _rb_03 evaluates early/late penalty
- **Then**: day 0 threshold = 9:00 / 17:00; day 1 threshold = 11:00 / 15:00

##### SC-07-06: RB-05 work_before uses per-day horario_inicio
- **Given**: ctx with varied start hours
- **When**: _rb_05 computes `work_before = v["s"] - ctx.horario_inicio[dia]`
- **Then**: excess calculation per day's actual start time

##### SC-07-07: List length mismatch raises validation error
- **Given**: ctx with `horario_inicio=[480,480]` (2 items) and request with `dias_totales=7`
- **When**: Pydantic validation runs
- **Then**: ValueError: horario_inicio length (2) must match dias_totales (7)

##### SC-07-08: Invalid hour range raises error
- **Given**: ctx with day 2 having `horario_inicio[2]=1080, horario_fin[2]=600`
- **When**: validation runs
- **Then**: ValueError: hora_inicio must be < hora_fin for all days

### F9: Partial Assignment (additive)

#### Fields
- `PenaltyWeights.omitido: int = 50` — penalty multiplier per minute of omitted task
- `RespuestaHorario.tareas_omitidas: list[str] = []` — IDs of tasks the solver could not assign
- RD-05 softened: `model.Add(sum(all_p) <= 1)` instead of `== 1`
- Penalty per omitted task: `omitido_weight * duracion_estimada` added to objective

#### Scenarios

##### SC-09-01: All tasks fit — full assignment
- **Given**: total flexible task duration < capacity, `omitido=50`
- **When**: solver runs
- **Then**: `sum(all_p) == 1` for each task; `tareas_omitidas` empty; penalty = 0

##### SC-09-02: Tasks exceed capacity — partial assignment
- **Given**: total flexible task duration >> capacity, `omitido=50`
- **When**: solver runs
- **Then**: some tasks have `sum(all_p) == 0`; their IDs appear in `tareas_omitidas`; objective includes skip penalties

##### SC-09-03: Omitted tasks in response
- **Given**: partial assignment as in SC-09-02
- **When**: _build_response runs
- **Then**: `RespuestaHorario.tareas_omitidas` contains IDs of unassigned tasks; bloques only include assigned tasks

##### SC-09-04: Capacity check advisory with F9 active
- **Given**: total flex > capacity, `omitido=50` (> 0)
- **When**: _validate_consistency runs
- **Then**: warning logged but ValueError NOT raised; solver proceeds

##### SC-09-05: Capacity check blocking with F9 inactive
- **Given**: total flex > capacity, `omitido=0`
- **When**: _validate_consistency runs
- **Then**: raises ValueError (current behavior preserved)

##### SC-09-06: No flexible tasks — no penalty added
- **Given**: empty `tareas_pendientes`, `omitido=50`
- **When**: solver runs
- **Then**: no omitido penalty variables created; objective only from existing RB terms
