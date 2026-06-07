import math
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from domain.entities.enums import Dificultad, EstadoSolucion, PatronEnergia, TipoActividad
from domain.services.energy_classifier import clasificar_patron_energia
from domain.entities.schedule_request import SolicitudHorario
from domain.entities.schedule_response import BloqueTiempo, RespuestaHorario
from domain.ports.inbound.scheduler_port import AbstractSchedulerService
from domain.services.time_utils import (
    MAX_BLOCK_MINUTES,
    MAX_CROSSING_DAYS,
    MAX_SLEEP_MINUTES,
    MINUTES_PER_DAY,
    abs_duration,
    to_abs,
    to_abs_minutes,
)


# ──────────────────────────── Config ────────────────────────────

@dataclass
class PenaltyWeights:
    rb_01: int = 10   # tareas difíciles en días con energía baja
    rb_02: int = 8    # concentración de tareas en un solo día
    rb_03: int = 6    # fuera del horario preferido
    rb_04: int = 4    # tiempos muertos largos
    rb_05: int = 10   # tareas exigentes después de turnos largos
    rb_06: int = 5    # desajuste duración/bloque
    rb_08: int = 3    # diferencias entre días consecutivos
    rb_09: int = 7    # múltiples cambios de ubicación
    rb_10: int = 9    # postergar tareas con fecha límite cercana
    rb_priority: int = 0  # tareas de baja prioridad en días tardíos
    omitido: int = 100000  # F9: penalización por omitir una tarea (× duración). Default alto = solo omite si es realmente inviable


MIN_REST_BLOCK_MINUTES = 30


# ───────────────────── ScheduleOptimizer ─────────────────────

class ScheduleOptimizer(AbstractSchedulerService):

    def __init__(
        self,
        timeout_seconds: int = 5,
        weights: PenaltyWeights | None = None,
    ):
        self.timeout = timeout_seconds
        self.weights = weights or PenaltyWeights()

    # ======================== API pública ========================

    def generar(self, solicitud: SolicitudHorario) -> RespuestaHorario:
        ctx = solicitud.contexto_usuario
        dia_inicio = solicitud.dia_inicio
        dias_totales = solicitud.dias_totales

        # F7: validate horario_inicio/fin list has enough entries for dias_totales
        if isinstance(ctx.horario_inicio, list) and len(ctx.horario_inicio) < dia_inicio + dias_totales:
            raise ValueError(
                f"horario_inicio tiene {len(ctx.horario_inicio)} elementos, "
                f"pero se necesitan al menos {dia_inicio + dias_totales} "
                f"(dia_inicio={dia_inicio} + dias_totales={dias_totales})."
            )
        if isinstance(ctx.horario_fin, list) and len(ctx.horario_fin) < dia_inicio + dias_totales:
            raise ValueError(
                f"horario_fin tiene {len(ctx.horario_fin)} elementos, "
                f"pero se necesitan al menos {dia_inicio + dias_totales} "
                f"(dia_inicio={dia_inicio} + dias_totales={dias_totales})."
            )

        self._validate_fixed_overlaps(solicitud.actividades_fijas)
        self._validate_task_duration(solicitud.tareas_pendientes, ctx, dia_inicio, dias_totales)
        self._validate_consistency(solicitud.actividades_fijas, ctx.bloques_sueno, solicitud.tareas_pendientes, ctx, dia_inicio, dias_totales, omitido_weight=self.weights.omitido)

        model = cp_model.CpModel()

        if ctx.patron_energia_manual is not None:
            patron = ctx.patron_energia_manual
        else:
            patron = clasificar_patron_energia(ctx.historial_energia, ctx.nivel_energia)
        self._patron_override = patron

        travel_lookup = self._build_travel_lookup(solicitud)

        state: dict = {
            "meta": {"dia_inicio": dia_inicio, "dias_totales": dias_totales},
            "intervals": {d: [] for d in range(dia_inicio, dia_inicio + dias_totales)},
            "intervals_abs": [],
            "fixed": {},
            "flex": {},
            "order_vars": {},
            "diagnosis": {
                "num_flex": len(solicitud.tareas_pendientes),
                "total_flex_min": sum(a.duracion_estimada for a in solicitud.tareas_pendientes),
                "num_fixed": len(solicitud.actividades_fijas),
                "num_sleep": len(ctx.bloques_sueno),
                "patron": patron.value,
                "horario_inicio": ctx.horario_inicio[0],
                "horario_fin": ctx.horario_fin[0],
                "has_alta": any(a.dificultad == Dificultad.ALTA for a in solicitud.tareas_pendientes),
            },
        }

        # RD-06: bloques de sueño
        self._add_sleep_blocks(model, ctx.bloques_sueno, state)

        # RD-02 / RD-03: actividades fijas
        for act in solicitud.actividades_fijas:
            self._add_fixed(model, act, state)

        # RB-07 (garantizada): bloque de descanso por día
        self._add_rest_blocks(model, ctx, state)

        # Variables de decisión para tareas flexibles
        for act in solicitud.actividades_optimizables:
            self._add_flexible_task(model, act, ctx, state)

        # RD-01: no solapamiento (flat absolute timeline)
        _add_no_overlap(model, state["intervals_abs"])

        # RD-04: tiempo de traslado entre ubicaciones
        self._add_travel_constraints(model, travel_lookup, state)
        state["travel_lookup"] = travel_lookup

        # Restricciones blandas
        objective_terms: list[int] = []

        if solicitud.actividades_optimizables:
            self._rb_01(model, ctx, state, objective_terms, patron)
            self._rb_02(model, ctx, state, objective_terms)
            self._rb_03(model, ctx, state, objective_terms)
            self._rb_04(model, ctx, state, objective_terms)
            self._rb_05(model, ctx, state, objective_terms)
            self._rb_06(model, ctx, state, objective_terms)
            self._rb_08(model, state, objective_terms)
            self._rb_09(model, state, objective_terms)
            self._rb_10(model, state, objective_terms)
            self._rb_priority(model, state, objective_terms)
            self._rb_omission(model, state, objective_terms)

        if objective_terms:
            model.Minimize(sum(objective_terms))

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self.timeout
        raw_status = solver.Solve(model)

        return self._build_response(solver, raw_status, state)

    # ==================== Variables del modelo ====================

    @staticmethod
    def _build_travel_lookup(solicitud: SolicitudHorario) -> dict:
        lookup: dict[tuple[str, str], int] = {}
        for t in solicitud.tiempos_traslado:
            lookup[(t.origen_id, t.destino_id)] = t.tiempo_estimado_minutos
            lookup[(t.destino_id, t.origen_id)] = t.tiempo_estimado_minutos
        for u1 in solicitud.ubicaciones:
            for u2 in solicitud.ubicaciones:
                if u1.id >= u2.id:
                    continue
                fwd, rev = (u1.id, u2.id), (u2.id, u1.id)
                if fwd not in lookup:
                    km = _rough_km(u1.latitud, u1.longitud, u2.latitud, u2.longitud)
                    mins = max(1, int(km / 0.5))
                    lookup[fwd] = mins
                    lookup[rev] = mins
        return lookup

    @staticmethod
    def _add_sleep_blocks(model, bloques, state):
        dia_inicio = state["meta"]["dia_inicio"]
        dias_totales = state["meta"]["dias_totales"]
        for s in bloques:
            if not (dia_inicio <= s.dia < dia_inicio + dias_totales):
                continue
            abs_start = s.dia * 1440 + s.inicio
            dur = abs_duration(s.inicio, s.fin)
            abs_end = abs_start + dur
            start_var = model.NewConstant(abs_start)
            end_var = model.NewConstant(abs_end)
            iv = model.NewIntervalVar(start_var, dur, end_var, f"sleep_d{s.dia}")
            state["intervals_abs"].append(iv)

    @staticmethod
    def _add_fixed(model, act, state):
        if act.dia is None:
            raise ValueError(
                f"La actividad fija '{act.nombre}' no tiene un día asignado. "
                "Las actividades fijas requieren un día específico."
            )
        dia_inicio = state["meta"]["dia_inicio"]
        dias_totales = state["meta"]["dias_totales"]
        if not (dia_inicio <= act.dia < dia_inicio + dias_totales):
            raise ValueError(
                f"La actividad fija '{act.nombre}' tiene día {act.dia} fuera de la ventana "
                f"[{dia_inicio}, {dia_inicio + dias_totales})"
            )
        dur = abs_duration(act.hora_inicio, act.hora_fin)
        abs_start = to_abs(act.dia, act.hora_inicio)
        abs_end = abs_start + dur
        s_abs = model.NewConstant(abs_start)
        e_abs = model.NewConstant(abs_end)
        iv = model.NewIntervalVar(s_abs, dur, e_abs, f"fix_{act.id}_d{act.dia}")
        state["intervals_abs"].append(iv)
        state["fixed"][act.id] = {
            "s": model.NewConstant(act.hora_inicio),  # day-relative for travel
            "e": model.NewConstant(act.hora_fin),     # day-relative for travel
            "s_abs": s_abs,
            "e_abs": e_abs,
            "loc": act.ubicacion_id,
            "dia": act.dia,
            "nombre": act.nombre,
            "tipo": act.tipo,
        }

    @staticmethod
    def _add_rest_blocks(model, ctx, state):
        dia_inicio = state["meta"]["dia_inicio"]
        dias_totales = state["meta"]["dias_totales"]
        for dia in range(dia_inicio, dia_inicio + dias_totales):
            p = model.NewBoolVar(f"rest_p_d{dia}")
            dur = MIN_REST_BLOCK_MINUTES
            s = model.NewIntVar(ctx.horario_inicio[dia], ctx.horario_fin[dia] - dur, f"rest_s_d{dia}")
            e = model.NewIntVar(ctx.horario_inicio[dia] + dur, ctx.horario_fin[dia], f"rest_e_d{dia}")
            iv = model.NewOptionalIntervalVar(dia * 1440 + s, dur, dia * 1440 + e, p, f"rest_iv_d{dia}")
            state["intervals_abs"].append(iv)
            model.Add(p == 1)

    @staticmethod
    def _add_flexible_task(model, act, ctx, state):
        # Day range with backward compat: if dia is set and the new day-range
        # fields are at their defaults, alias dia → dia_hasta (Phase 1 behavior).
        if act.dia is not None and act.dia_desde == 0 and act.dia_hasta == 6:
            day_start = 0
            day_end = act.dia
        else:
            day_start = act.dia_desde
            day_end = act.dia_hasta

        # Permitted days filter
        permitted = act.dias_permitidos

        # Anchor override
        if act.es_ancla:
            if act.dia is not None:
                days = [act.dia]
            elif act.dia_desde == act.dia_hasta:
                days = [act.dia_desde]
            else:
                raise ValueError("Anchor task must have a specific day")
        else:
            days = list(range(day_start, day_end + 1))
            if permitted is not None:
                days = [d for d in days if d in permitted]
                if not days:
                    raise ValueError("No valid days after filtering by dias_permitidos")

        # F8: intersect with rolling window
        dia_inicio = state.get("meta", {}).get("dia_inicio", 0)
        dias_totales = state.get("meta", {}).get("dias_totales", 7)
        window = set(range(dia_inicio, dia_inicio + dias_totales))
        days = [d for d in days if d in window]
        if not days:
            raise ValueError(
                f"La tarea '{act.nombre}' no tiene días dentro de la ventana de "
                f"programación ({dia_inicio}–{dia_inicio + dias_totales - 1})."
            )

        dur = act.duracion_estimada
        all_p: list = []

        # Ventana de tiempo efectiva: intersección del horario del usuario con la preferencia de la tarea
        eff_start = max(ctx.horario_inicio, act.hora_preferida_inicio) if act.hora_preferida_inicio is not None else ctx.horario_inicio
        eff_end = min(ctx.horario_fin, act.hora_preferida_fin) if act.hora_preferida_fin is not None else ctx.horario_fin

        info = {
            "nombre": act.nombre,
            "tipo": act.tipo,
            "loc": act.ubicacion_id,
            "dificultad": act.dificultad,
            "prioridad": act.prioridad,
            "dur": dur,
            "vars": {},
            "all_p": all_p,
        }
        state["flex"][act.id] = info

        for dia in days:
            p = model.NewBoolVar(f"p_{act.id}_d{dia}")
            s = model.NewIntVar(ctx.horario_inicio[dia], ctx.horario_fin[dia] - dur, f"s_{act.id}_d{dia}")
            e = model.NewIntVar(ctx.horario_inicio[dia] + dur, ctx.horario_fin[dia], f"e_{act.id}_d{dia}")
            iv = model.NewOptionalIntervalVar(dia * 1440 + s, dur, dia * 1440 + e, p, f"iv_{act.id}_d{dia}")
            state["intervals_abs"].append(iv)
            info["vars"][dia] = {"p": p, "s": s, "e": e}
            all_p.append(p)

        # RD-05: como máximo un día (F9: permite omitir tareas si es inviable)
        model.Add(sum(all_p) <= 1)

        # F9: variable de omisión — 1 si la tarea no se programa, 0 si se asigna a algún día
        omit = model.NewBoolVar(f"omit_{act.id}")
        model.Add(sum(all_p) >= 1).OnlyEnforceIf(omit.Not())
        model.Add(sum(all_p) == 0).OnlyEnforceIf(omit)
        info["omit"] = omit

    # ==================== Restricciones duras ====================

    @staticmethod
    def _add_travel_constraints(model, lookup, state):
        dia_inicio = state["meta"]["dia_inicio"]
        dias_totales = state["meta"]["dias_totales"]
        for dia in range(dia_inicio, dia_inicio + dias_totales):
            items: list = []

            for tid, info in state["flex"].items():
                if dia in info["vars"]:
                    v = info["vars"][dia]
                    items.append((tid, info["loc"], v["p"], v["s"], v["e"]))

            for fid, finfo in state["fixed"].items():
                if finfo["dia"] == dia:
                    p_one = model.NewConstant(1)
                    items.append((fid, finfo["loc"], p_one, finfo["s"], finfo["e"]))

            n = len(items)
            if n < 2:
                continue

            for i in range(n):
                for j in range(i + 1, n):
                    idi, loci, pi, si, ei = items[i]
                    idj, locj, pj, sj, ej = items[j]
                    if not loci or not locj or loci == locj:
                        continue
                    travel = lookup.get((loci, locj), 0)
                    if travel == 0:
                        continue

                    before = model.NewBoolVar(f"bef_{idi}_{idj}_d{dia}")
                    state["order_vars"][(idi, idj, dia)] = before

                    model.Add(sj >= ei + travel).OnlyEnforceIf([pi, pj, before])
                    model.Add(si >= ej + travel).OnlyEnforceIf([pi, pj, before.Not()])

    # ==================== Restricciones blandas ====================

    def _rb_01(self, model, ctx, state, terms, patron: PatronEnergia):
        """RB-01: penalizar tareas según patrón de energía.

        TRANSCRIPTORIO: penaliza ALTA que empiezan tarde si energía baja.
        TENDENCIA:      max 1 ALTA/día + mismas penalizaciones.
        CRONICO:        penaliza TODAS las tareas; ALTA con 2x, no-ALTA por duración.
        """
        w = self.weights.rb_01
        if w == 0:
            return

        if patron == PatronEnergia.TENDENCIA:
            # Hard constraint: max 1 ALTA task per day
            for dia in range(state["meta"]["dia_inicio"], state["meta"]["dia_inicio"] + state["meta"]["dias_totales"]):
                alta_ps = [
                    info["vars"][dia]["p"]
                    for tid, info in state["flex"].items()
                    if info["dificultad"] == Dificultad.ALTA and dia in info["vars"]
                ]
                if len(alta_ps) > 1:
                    model.Add(sum(alta_ps) <= 1)

        if patron in (PatronEnergia.TENDENCIA, PatronEnergia.TRANSCRIPTORIO):
            # Current behavior: penalize ALTA tasks starting late if energy low
            if ctx.nivel_energia > 2:
                return
            for tid, info in state["flex"].items():
                if info["dificultad"] != Dificultad.ALTA:
                    continue
                for dia, v in info["vars"].items():
                    pen = model.NewIntVar(0, 1440 * w, f"rb01_{tid}_d{dia}")
                    model.Add(pen == v["s"] * w).OnlyEnforceIf(v["p"])
                    model.Add(pen == 0).OnlyEnforceIf(v["p"].Not())
                    terms.append(pen)

        elif patron == PatronEnergia.CRONICO:
            # Deprioritize ALTA: for ALL tasks add penalty
            # ALTA uses 2x multiplier; non-ALTA is duration-based (favor short tasks)
            for tid, info in state["flex"].items():
                for dia, v in info["vars"].items():
                    if info["dificultad"] == Dificultad.ALTA:
                        pen = model.NewIntVar(0, 1440 * w * 2, f"rb01_{tid}_d{dia}")
                        model.Add(pen == v["s"] * w * 2).OnlyEnforceIf(v["p"])
                    else:
                        pen = model.NewIntVar(0, 1440 * w, f"rb01_{tid}_d{dia}")
                        model.Add(pen == info["dur"] * w).OnlyEnforceIf(v["p"])
                    model.Add(pen == 0).OnlyEnforceIf(v["p"].Not())
                    terms.append(pen)

    def _rb_02(self, model, ctx, state, terms):
        """RB-02: penalizar concentrar muchas horas en un día."""
        w = self.weights.rb_02
        if w == 0:
            return
        for dia in range(state["meta"]["dia_inicio"], state["meta"]["dia_inicio"] + state["meta"]["dias_totales"]):
            contribs: list = []
            for info in state["flex"].values():
                if dia not in info["vars"]:
                    continue
                v = info["vars"][dia]
                part = model.NewIntVar(0, info["dur"], f"rb02c_{dia}")
                model.Add(part == info["dur"]).OnlyEnforceIf(v["p"])
                model.Add(part == 0).OnlyEnforceIf(v["p"].Not())
                contribs.append(part)
            if not contribs:
                continue
            total = model.NewIntVar(0, ctx.horario_fin[dia] - ctx.horario_inicio[dia], f"rb02_t_d{dia}")
            model.Add(total == sum(contribs))
            excess = model.NewIntVar(0, 600, f"rb02_x_d{dia}")
            model.Add(total <= 360 + excess)
            terms.append(excess * w)

    def _rb_03(self, model, ctx, state, terms):
        """RB-03: penalizar fuera del horario preferido (primera/última hora)."""
        w = self.weights.rb_03
        if w == 0:
            return
        for tid, info in state["flex"].items():
            for dia, v in info["vars"].items():
                early_thr = ctx.horario_inicio[dia] + 60
                late_thr = ctx.horario_fin[dia] - 60
                early = model.NewBoolVar(f"rb03_early_{tid}_d{dia}")
                late = model.NewBoolVar(f"rb03_late_{tid}_d{dia}")
                model.Add(v["s"] < early_thr).OnlyEnforceIf(early)
                model.Add(v["s"] >= early_thr).OnlyEnforceIf(early.Not())
                model.Add(v["e"] > late_thr).OnlyEnforceIf(late)
                model.Add(v["e"] <= late_thr).OnlyEnforceIf(late.Not())

                pen = model.NewIntVar(0, w, f"rb03_pen_{tid}_d{dia}")
                model.Add(pen == w).OnlyEnforceIf([v["p"], early])
                model.Add(pen == w).OnlyEnforceIf([v["p"], late])
                model.Add(pen == 0).OnlyEnforceIf(v["p"].Not())
                terms.append(pen)

    def _rb_04(self, model, ctx, state, terms):
        """RB-04: penalizar tiempo muerto total en el día."""
        w = self.weights.rb_04
        if w == 0:
            return
        if getattr(self, "_patron_override", None) == PatronEnergia.CRONICO:
            w = max(1, int(w * 0.5))
        for dia in range(state["meta"]["dia_inicio"], state["meta"]["dia_inicio"] + state["meta"]["dias_totales"]):
            day_range = ctx.horario_fin[dia] - ctx.horario_inicio[dia]
            contribs: list = []
            for info in state["flex"].values():
                if dia not in info["vars"]:
                    continue
                v = info["vars"][dia]
                part = model.NewIntVar(0, info["dur"], f"rb04c_{dia}")
                model.Add(part == info["dur"]).OnlyEnforceIf(v["p"])
                model.Add(part == 0).OnlyEnforceIf(v["p"].Not())
                contribs.append(part)
            if not contribs:
                continue
            total = model.NewIntVar(0, day_range, f"rb04_t_d{dia}")
            model.Add(total == sum(contribs))
            idle = model.NewIntVar(0, day_range, f"rb04_idle_d{dia}")
            model.Add(idle == day_range - total)
            terms.append(idle * w)

    def _rb_05(self, model, ctx, state, terms):
        """RB-05: penalizar tarea difícil después de mucho trabajo continuo."""
        w = self.weights.rb_05
        if w == 0:
            return
        if getattr(self, "_patron_override", None) == PatronEnergia.CRONICO:
            w = w + 5
        for tid, info in state["flex"].items():
            if info["dificultad"] != Dificultad.ALTA:
                continue
            for dia, v in info["vars"].items():
                work_before = model.NewIntVar(0, ctx.horario_fin[dia] - ctx.horario_inicio[dia], f"rb05_wb_{tid}_d{dia}")
                model.Add(work_before == v["s"] - ctx.horario_inicio[dia]).OnlyEnforceIf(v["p"])
                model.Add(work_before == 0).OnlyEnforceIf(v["p"].Not())
                excess = model.NewIntVar(0, 600, f"rb05_ex_{tid}_d{dia}")
                model.Add(work_before <= 240 + excess)
                terms.append(excess * w)

    def _rb_06(self, model, ctx, state, terms):
        """RB-06: penalizar desajuste entre duración y bloque libre."""
        w = self.weights.rb_06
        if w == 0:
            return
        for tid, info in state["flex"].items():
            for dia, v in info["vars"].items():
                mis = model.NewIntVar(0, ctx.horario_fin[dia] - ctx.horario_inicio[dia], f"rb06_mis_{tid}_d{dia}")
                model.Add(mis >= (ctx.horario_fin[dia] - ctx.horario_inicio[dia]) - info["dur"] * 3).OnlyEnforceIf(v["p"])
                model.Add(mis >= 0)
                terms.append(mis * w)

    def _rb_08(self, model, state, terms):
        """RB-08: penalizar diferencia de carga entre días consecutivos."""
        w = self.weights.rb_08
        if w == 0:
            return
        dia_inicio = state["meta"]["dia_inicio"]
        dias_totales = state["meta"]["dias_totales"]
        day_loads: dict[int, list] = {d: [] for d in range(dia_inicio, dia_inicio + dias_totales)}
        for info in state["flex"].values():
            for dia, v in info["vars"].items():
                load = model.NewIntVar(0, info["dur"], f"rb08_l_{dia}")
                model.Add(load == info["dur"]).OnlyEnforceIf(v["p"])
                model.Add(load == 0).OnlyEnforceIf(v["p"].Not())
                day_loads[dia].append(load)
        for d in range(dia_inicio, dia_inicio + dias_totales - 1):
            if not day_loads[d] or not day_loads[d + 1]:
                continue
            sd = model.NewIntVar(0, 600, f"rb08_sd{d}")
            sd1 = model.NewIntVar(0, 600, f"rb08_sd{d+1}")
            model.Add(sd == sum(day_loads[d]))
            model.Add(sd1 == sum(day_loads[d + 1]))
            diff = model.NewIntVar(0, 600, f"rb08_diff{d}")
            model.Add(diff >= sd - sd1)
            model.Add(diff >= sd1 - sd)
            terms.append(diff * w)

    def _rb_09(self, model, state, terms):
        """RB-09: penalizar cambios de ubicación dentro del mismo día."""
        w = self.weights.rb_09
        if w == 0:
            return
        for dia in range(state["meta"]["dia_inicio"], state["meta"]["dia_inicio"] + state["meta"]["dias_totales"]):
            day_tasks = [
                (tid, info)
                for tid, info in state["flex"].items()
                if dia in info["vars"] and info.get("loc")
            ]
            for i in range(len(day_tasks) - 1):
                tid_i, inf_i = day_tasks[i]
                tid_j, inf_j = day_tasks[i + 1]
                if inf_i["loc"] == inf_j["loc"]:
                    continue
                key = (tid_i, tid_j, dia)
                before = state["order_vars"].get(key)
                if before is None:
                    continue
                ch = model.NewBoolVar(f"rb09_ch_{tid_i}_{tid_j}_d{dia}")
                pi = inf_i["vars"][dia]["p"]
                pj = inf_j["vars"][dia]["p"]
                model.Add(ch == 1).OnlyEnforceIf([pi, pj, before])
                model.Add(ch == 0).OnlyEnforceIf(pi.Not())
                model.Add(ch == 0).OnlyEnforceIf(pj.Not())
                terms.append(ch * w)

    def _rb_10(self, model, state, terms):
        """RB-10: penalizar postergar tareas con fecha límite cercana."""
        w = self.weights.rb_10
        if w == 0:
            return
        for info in state["flex"].values():
            for dia, v in info["vars"].items():
                urgency = (state["meta"]["dia_inicio"] + state["meta"]["dias_totales"] - 1) - dia
                pen = model.NewIntVar(0, w * 6, f"rb10_pen")
                model.Add(pen == w * urgency).OnlyEnforceIf(v["p"])
                model.Add(pen == 0).OnlyEnforceIf(v["p"].Not())
                terms.append(pen)

    def _rb_priority(self, model, state, terms):
        """RB-PRIORITY: penalizar tareas de baja prioridad en días tardíos.

        Compara la prioridad de cada tarea flexible con la prioridad máxima
        del conjunto. Aplica una penalidad proporcional a
        (max_priority - task_priority) × day_index, para incentivar que
        las tareas más importantes se asignen a días tempranos.
        """
        w = self.weights.rb_priority
        if w == 0:
            return
        max_priority = max(
            (info["prioridad"] for info in state["flex"].values()),
            default=0,
        )
        if max_priority == 0:
            return
        for tid, info in state["flex"].items():
            diff = max_priority - info["prioridad"]
            if diff <= 0:
                continue
            for dia, v in info["vars"].items():
                pen = model.NewIntVar(0, diff * 6 * w, f"rb_prio_{tid}_d{dia}")
                model.Add(pen == diff * dia * w).OnlyEnforceIf(v["p"])
                model.Add(pen == 0).OnlyEnforceIf(v["p"].Not())
                terms.append(pen)

    def _rb_omission(self, model, state, terms):
        """F9: penalizar la omisión de tareas (asignación parcial).

        Cada tarea flexible tiene una variable 'omit'. Si weight > 0,
        se añade una penalización al objetivo por cada tarea omitida,
        proporcional a su duración, incentivando al solver a programar
        la mayor cantidad posible (y las más largas primero).
        """
        w = self.weights.omitido
        if w == 0:
            return
        for tid, info in state["flex"].items():
            omit = info.get("omit")
            if omit is None:
                continue
            max_pen = w * info["dur"]
            pen = model.NewIntVar(0, max_pen, f"rb_omit_{tid}")
            model.Add(pen == max_pen).OnlyEnforceIf(omit)
            model.Add(pen == 0).OnlyEnforceIf(omit.Not())
            terms.append(pen)

    @staticmethod
    def _validate_fixed_overlaps(actividades_fijas):
        """Validate no overlaps using absolute minutes (cross-midnight safe).

        Raises ValueError if any interval exceeds 2880 minutes (2 days).
        """
        items: list[tuple[str, int, int]] = []
        for act in actividades_fijas:
            if act.dia is None:
                raise ValueError(
                    f"La actividad fija '{act.nombre}' no tiene un día asignado. "
                    "Las actividades fijas requieren un día específico."
                )
            abs_start = to_abs(act.dia, act.hora_inicio)
            dur = abs_duration(act.hora_inicio, act.hora_fin)
            if dur > 2880:
                raise ValueError(
                    f"La actividad fija '{act.nombre}' tiene una duración de {dur} min, "
                    f"superando el máximo permitido de 2880 min (2 días)"
                )
            abs_end = abs_start + dur
            items.append((act.nombre, abs_start, abs_end))
        items.sort(key=lambda x: x[1])  # sort by abs_start
        for i in range(len(items) - 1):
            name_a, _, abs_end_a = items[i]
            name_b, abs_start_b, _ = items[i + 1]
            if abs_start_b < abs_end_a:
                raise ValueError(
                    f"Actividades fijas solapadas: "
                    f"'{name_a}' termina a los {abs_end_a} min absolutos "
                    f"pero '{name_b}' empieza a los {abs_start_b} min absolutos"
                )

    @staticmethod
    def _validate_task_duration(tareas_pendientes, ctx, dia_inicio: int = 0, dias_totales: int = 7):
        max_daily = max(ctx.horario_fin[d] - ctx.horario_inicio[d] for d in range(dia_inicio, dia_inicio + dias_totales))
        for act in tareas_pendientes:
            if act.duracion_estimada > max_daily:
                raise ValueError(
                    f"La actividad '{act.nombre}' dura {act.duracion_estimada} min, "
                    f"pero el horario disponible es de solo {max_daily} min/día"
                )
            # Validar contra la ventana preferida de la tarea
            if act.hora_preferida_inicio is not None and act.hora_preferida_fin is not None:
                window = act.hora_preferida_fin - act.hora_preferida_inicio
                if act.duracion_estimada > window:
                    raise ValueError(
                        f"La actividad '{act.nombre}' dura {act.duracion_estimada} min, "
                        f"pero su ventana preferida ({act.hora_preferida_inicio}–{act.hora_preferida_fin}) "
                        f"tiene solo {window} min de espacio"
                    )

    @staticmethod
    def _validate_consistency(
        actividades_fijas: list,
        bloques_sueno: list,
        tareas_pendientes: list,
        ctx,
        dia_inicio: int = 0,
        dias_totales: int = 7,
        omitido_weight: int = 0,
    ) -> None:
        """Pre-solve validation: check constraints before building CP-SAT model.

        Raises ValueError with a descriptive message if the problem is
        trivially infeasible.
        """
        # ── Sleep block duration ──────────────────────────────────
        for s in bloques_sueno:
            dur = abs_duration(s.inicio, s.fin)
            if dur > MAX_SLEEP_MINUTES:
                raise ValueError(
                    f"El bloque de sueño del día {s.dia} dura {dur} min, "
                    f"superando el máximo de {MAX_SLEEP_MINUTES} min ({MAX_SLEEP_MINUTES // 60}h)"
                )

        # ── Sleep conflicts with fixed activities ─────────────────
        sleep_abs: list[tuple[str, int, int]] = [
            ("sleep", to_abs(s.dia, s.inicio), to_abs(s.dia, s.inicio) + abs_duration(s.inicio, s.fin))
            for s in bloques_sueno
            if dia_inicio <= s.dia < dia_inicio + dias_totales
        ]
        fixed_abs: list[tuple[str, int, int]] = [
            (act.nombre,) + to_abs_minutes(act.dia, act.hora_inicio, act.hora_fin)
            for act in actividades_fijas
        ]

        for s_name, s_start, s_end in sleep_abs:
            for f_name, f_start, f_end in fixed_abs:
                if s_start < f_end and f_start < s_end:
                    raise ValueError(
                        f"La actividad fija '{f_name}' solapa con un bloque de sueño. "
                        f"Ajusta los horarios de sueño o la actividad."
                    )

        # ── Day range validation + active window capacity ─────────
        # Per-task: verify each task has at least one valid day
        for act in tareas_pendientes:
            # Backward compat: same alias logic as _add_flexible_task
            if act.dia is not None and act.dia_desde == 0 and act.dia_hasta == 6:
                day_start = 0
                day_end = act.dia
            else:
                day_start = act.dia_desde
                day_end = act.dia_hasta

            if act.es_ancla:
                if act.dia is not None:
                    effective = [act.dia]
                elif act.dia_desde == act.dia_hasta:
                    effective = [act.dia_desde]
                else:
                    raise ValueError(
                        f"La tarea ancla '{act.nombre}' requiere un día específico."
                    )
            else:
                effective = list(range(day_start, day_end + 1))
                if act.dias_permitidos is not None:
                    effective = [d for d in effective if d in act.dias_permitidos]

            if not effective:
                raise ValueError(
                    f"La tarea '{act.nombre}' no tiene días válidos después de aplicar "
                    f"los filtros de programación."
                )

        total_flex = sum(a.duracion_estimada for a in tareas_pendientes)
        days_available = dias_totales

        # Count occupied time per day (sleep + fixed)
        occupied_per_day: dict[int, int] = {}
        for _, s_start, s_end in sleep_abs:
            d = s_start // MINUTES_PER_DAY
            occupied_per_day[d] = occupied_per_day.get(d, 0) + (s_end - s_start)
        for act in actividades_fijas:
            a_start, a_end = to_abs_minutes(act.dia, act.hora_inicio, act.hora_fin)
            d = a_start // MINUTES_PER_DAY
            occupied_per_day[d] = occupied_per_day.get(d, 0) + (a_end - a_start)

        available_per_day = [
            ctx.horario_fin[d] - ctx.horario_inicio[d] - occupied_per_day.get(d, 0)
            for d in range(dia_inicio, dia_inicio + dias_totales)
        ]

        if total_flex > sum(available_per_day):
            if omitido_weight > 0:
                import logging
                logging.warning(
                    f"Las tareas pendientes requieren {total_flex} min totales, "
                    f"pero solo hay {sum(available_per_day)} min disponibles. "
                    "El solver omitirá tareas si es necesario."
                )
            else:
                raise ValueError(
                    f"Las tareas pendientes requieren {total_flex} min totales, "
                    f"pero solo hay {sum(available_per_day)} min disponibles "
                    f"entre los días activos (considerando sueño y actividades fijas). "
                    f"Reduce las tareas o amplía el horario disponible."
                )

    def _build_response(self, solver, raw_status, state) -> RespuestaHorario:
        _map = {
            cp_model.OPTIMAL: EstadoSolucion.OPTIMA,
            cp_model.FEASIBLE: EstadoSolucion.FACTIBLE,
            cp_model.INFEASIBLE: EstadoSolucion.INFACTIBLE,
            cp_model.UNKNOWN: EstadoSolucion.DESCONOCIDO,
        }
        estado = _map.get(raw_status, EstadoSolucion.DESCONOCIDO)

        # ── Construir bloques de actividades fijas (disponibles incluso si falla) ──
        fixed_blocks: list[BloqueTiempo] = [
            BloqueTiempo(
                id_actividad=fid,
                nombre=finfo["nombre"],
                tipo=finfo["tipo"],
                dia=finfo["dia"],
                hora_inicio=solver.Value(finfo["s"]),
                hora_fin=solver.Value(finfo["e"]),
                ubicacion_id=finfo["loc"],
            )
            for fid, finfo in state["fixed"].items()
        ]

        if estado == EstadoSolucion.INFACTIBLE:
            diag = state.get("diagnosis", {})
            tips: list[str] = []

            if diag.get("num_flex", 0) == 0 and diag.get("num_fixed", 0) > 0:
                tips.append("Las actividades fijas o los bloques de sueño se superponen entre si. "
                            "Revisa los horarios e intenta de nuevo.")
            elif diag.get("num_fixed", 0) + diag.get("num_sleep", 0) > 0:
                tips.append("Las actividades fijas o el sueno pueden estar ocupando todo el tiempo disponible. "
                            "Ajusta sus horarios o reduces.")

            if diag.get("num_flex", 0) > 0:
                dias_totales = state.get("meta", {}).get("dias_totales", 7)
                available = (diag.get("horario_fin", 1200) - diag.get("horario_inicio", 480)) * dias_totales
                if diag.get("total_flex_min", 0) > available:
                    tips.append(f"Las {diag['num_flex']} tareas pendientes requieren {diag['total_flex_min']} min en total, "
                                f"pero el horario activo solo ofrece {available} min por semana. "
                                f"Reduce la cantidad de tareas o amplia el horario disponible.")

            if diag.get("has_alta") and diag.get("patron") == "tendencia":
                tips.append("Con un patron de energia en bajada (TENDENCIA) solo puedes tener 1 tarea "
                            "dificil (ALTA) por dia. Distribuye las tareas ALTA en diferentes dias "
                            "o cambia su nivel de dificultad.")

            mensaje = "No se pudo armar el horario completo. " + " ".join(tips) if tips else \
                      "No se pudo armar el horario con estos datos. Reduce las tareas, amplia el horario activo, " \
                      "o aumenta el tiempo de computo del optimizador."

            return RespuestaHorario(
                estado=estado,
                mensaje=mensaje,
                bloques=fixed_blocks,
                recomendaciones=tips,
                tareas_omitidas=[info.get("nombre", tid) for tid, info in state["flex"].items()],
            )

        if estado == EstadoSolucion.DESCONOCIDO:
            omitted_unknown = []
            for tid, info in state["flex"].items():
                assigned = any(solver.Value(v["p"]) == 1 for v in info["vars"].values())
                if not assigned:
                    omitted_unknown.append(info.get("nombre", tid))
            return RespuestaHorario(
                estado=estado,
                mensaje=f"El optimizador no encontro solucion en {self.timeout} segundos. "
                        "Prueba reduciendo la cantidad de tareas pendientes o aumentando "
                        "el tiempo de computo.",
                bloques=fixed_blocks,
                recomendaciones=["Reduce la cantidad de tareas o aumenta el tiempo de computo."],
                tareas_omitidas=omitted_unknown,
            )

        # ── Construir bloques de tareas flexibles (solo si hay solucion) ──
        flex_blocks: list[BloqueTiempo] = []
        omitted: list[str] = []

        for tid, info in state["flex"].items():
            scheduled = False
            for dia, v in info["vars"].items():
                if solver.Value(v["p"]) == 1:
                    flex_blocks.append(
                        BloqueTiempo(
                            id_actividad=tid,
                            nombre=info["nombre"],
                            tipo=info["tipo"],
                            dia=dia,
                            hora_inicio=solver.Value(v["s"]),
                            hora_fin=solver.Value(v["e"]),
                            ubicacion_id=info["loc"],
                        )
                    )
                    scheduled = True
            if not scheduled:
                omitted.append(info.get("nombre", tid))

        bloques = sorted(fixed_blocks + flex_blocks, key=lambda x: (x.dia, x.hora_inicio))
        bloques = self._insert_travel_blocks(bloques, state.get("travel_lookup", {}))
        return RespuestaHorario(
            estado=estado,
            bloques=bloques,
            tareas_omitidas=omitted,
        )


    @staticmethod
    def _insert_travel_blocks(
        bloques: list[BloqueTiempo],
        travel_lookup: dict,
    ) -> list[BloqueTiempo]:
        result: list[BloqueTiempo] = []
        for b in bloques:
            if result and result[-1].dia == b.dia:
                prev = result[-1]
                if (
                    prev.ubicacion_id
                    and b.ubicacion_id
                    and prev.ubicacion_id != b.ubicacion_id
                ):
                    travel = travel_lookup.get(
                        (prev.ubicacion_id, b.ubicacion_id), 15
                    )
                    gap = b.hora_inicio - prev.hora_fin
                    if gap >= travel:
                        result.append(
                            BloqueTiempo(
                                id_actividad=f"viaje_{prev.id_actividad}_{b.id_actividad}",
                                nombre=f"Viaje a {b.nombre}",
                                tipo=TipoActividad.TRABAJO,
                                dia=b.dia,
                                hora_inicio=prev.hora_fin,
                                hora_fin=prev.hora_fin + travel,
                                ubicacion_id=prev.ubicacion_id,
                            )
                        )
            result.append(b)
        return result


# ─────────────────────── Funciones auxiliares ───────────────────────

def _add_no_overlap(model, intervals_abs: list):
    if len(intervals_abs) > 1:
        model.AddNoOverlap(intervals_abs)


def _rough_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return 6371 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
