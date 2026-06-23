"""Integration tests for RB-01 branches in ScheduleOptimizer.

Builds a CP-SAT model and verifies constraints hold for TENDENCIA and CRONICO.
"""

from ortools.sat.python import cp_model

from domain.entities.enums import Dificultad, PatronEnergia
from domain.entities.user_context import ContextoUsuario
from domain.services.schedule_service import PenaltyWeights, ScheduleOptimizer


# ═══════════════════════════════════════════════════════════════
# Helper: run a minimal model with _rb_01 only
# ═══════════════════════════════════════════════════════════════


def _run_rb01(patron: PatronEnergia, tasks: list[dict], nivel_energia: int = 1):
    """Set up a minimal CP-SAT model, call _rb_01, solve, and return solver + state."""
    model = cp_model.CpModel()
    ctx = ContextoUsuario(nivel_energia=nivel_energia)
    state: dict = {"flex": {}, "meta": {"dia_inicio": 0, "dias_totales": 7}}
    terms: list = []

    for idx, task in enumerate(tasks):
        tid = f"t{idx}"
        dur = task.get("dur", 60)
        dificultad = task.get("dificultad", Dificultad.MEDIA)
        vars_dict = {}
        for dia in task.get("days", [0]):
            p = model.NewBoolVar(f"p_{tid}_d{dia}")
            s = model.NewIntVar(0, 1000, f"s_{tid}_d{dia}")
            e = model.NewIntVar(0, 1000, f"e_{tid}_d{dia}")
            vars_dict[dia] = {"p": p, "s": s, "e": e}
        state["flex"][tid] = {
            "nombre": tid,
            "tipo": None,
            "loc": None,
            "dificultad": dificultad,
            "prioridad": 1,
            "dur": dur,
            "vars": vars_dict,
            "all_p": [v["p"] for v in vars_dict.values()],
        }

    optimizer = ScheduleOptimizer(weights=PenaltyWeights(rb_01=10))
    optimizer._patron_override = patron
    optimizer._rb_01(model, ctx, state, terms, patron)

    # Add a dummy objective
    if terms:
        model.Minimize(sum(terms))

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.max_time_in_seconds = 2
    status = solver.Solve(model)

    return solver, status, state, terms


# ═══════════════════════════════════════════════════════════════
# TENDENCIA: max 1 ALTA per day
# ═══════════════════════════════════════════════════════════════


def test_tendencia_max_one_alta_per_day():
    """With TENDENCIA, at most 1 ALTA task can be scheduled per day."""
    tasks = [
        {"dificultad": Dificultad.ALTA, "dur": 30, "days": [0]},
        {"dificultad": Dificultad.ALTA, "dur": 30, "days": [0]},
        {"dificultad": Dificultad.BAJA, "dur": 30, "days": [0]},
    ]
    solver, status, state, terms = _run_rb01(PatronEnergia.TENDENCIA, tasks)

    # Both ALTA tasks on day 0 → the constraint sum(alta_p) <= 1
    # must be enforced. The model should still find a solution since
    # the third task is BAJA and both ALTA can be assigned different days,
    # but if both only allow day 0, the solver should enforce at most 1.
    alta_vars = [
        state["flex"]["t0"]["vars"][0]["p"],
        state["flex"]["t1"]["vars"][0]["p"],
    ]
    sum_alta = solver.Value(alta_vars[0]) + solver.Value(alta_vars[1])
    assert sum_alta <= 1, (
        f"TENDENCIA should allow at most 1 ALTA task per day, got {sum_alta}"
    )


def test_tendencia_multiple_alta_different_days_ok():
    """TENDENCIA allows 1 ALTA per day across different days."""
    tasks = [
        {"dificultad": Dificultad.ALTA, "dur": 30, "days": [0, 1]},
        {"dificultad": Dificultad.ALTA, "dur": 30, "days": [0, 1]},
    ]
    solver, status, state, terms = _run_rb01(PatronEnergia.TENDENCIA, tasks)

    # Each ALTA can be on different days, so both can be assigned
    t0_p0 = solver.Value(state["flex"]["t0"]["vars"][0]["p"])
    t0_p1 = solver.Value(state["flex"]["t1"]["vars"][1]["p"])
    # At least one ALTA per day (they're the only tasks), both should be scheduled
    # but each on a different day
    alta_day0 = 0
    alta_day1 = 0
    if t0_p0:
        alta_day0 += 1
    if solver.Value(state["flex"]["t1"]["vars"][0]["p"]):
        alta_day0 += 1
    if t0_p1:
        alta_day1 += 1
    if solver.Value(state["flex"]["t1"]["vars"][1]["p"]):
        alta_day1 += 1
    assert alta_day0 <= 1
    assert alta_day1 <= 1


# ═══════════════════════════════════════════════════════════════
# CRONICO: ALTA tasks get higher penalty variables
# ═══════════════════════════════════════════════════════════════


def test_cronico_alta_penalty_higher_than_media():
    """Under CRONICO, ALTA tasks get a higher penalty coefficient than MEDIA.

    ALTA uses v['s'] * w * 2 → max 1440 * w * 2 = 28800.
    MEDIA uses info['dur'] * w  → max 1440 * w     = 14400.

    This test verifies:
    - The model is feasible (solver finds a solution)
    - The ALTA penalty variable has a higher upper bound than MEDIA's
    """
    tasks = [
        {"dificultad": Dificultad.ALTA, "dur": 60, "days": [0]},
        {"dificultad": Dificultad.MEDIA, "dur": 60, "days": [0]},
    ]
    solver, status, state, terms = _run_rb01(PatronEnergia.CRONICO, tasks, nivel_energia=2)

    # One penalty variable per (task, day) pair
    assert len(terms) == 2, f"Expected 2 penalty terms (ALTA + MEDIA), got {len(terms)}"

    # terms[0] = ALTA (t0, day 0), terms[1] = MEDIA (t1, day 0)
    # ALTA max = 1440 * w * 2 = 28800, MEDIA max = 1440 * w = 14400
    # domain is a flat [min, max] list in newer OR-Tools protos
    alta_max = terms[0].domain.max()
    media_max = terms[1].domain.max()
    assert alta_max > media_max, (
        f"ALTA penalty max ({alta_max}) should exceed MEDIA max ({media_max})"
    )

    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE), (
        f"CRONICO model should be solvable, got status {status}"
    )


def test_cronico_feasible_with_mixed_tasks():
    """CRONICO model should solve with mixed difficulty tasks."""
    tasks = [
        {"dificultad": Dificultad.ALTA, "dur": 45, "days": [0, 1]},
        {"dificultad": Dificultad.BAJA, "dur": 30, "days": [0, 1]},
        {"dificultad": Dificultad.MEDIA, "dur": 60, "days": [0, 1]},
    ]
    solver, status, state, terms = _run_rb01(PatronEnergia.CRONICO, tasks, nivel_energia=2)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE), (
        f"CRONICO model with mixed tasks should be solvable, got status {status}"
    )
