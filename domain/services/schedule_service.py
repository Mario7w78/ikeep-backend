import math
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from domain.entities.enums import Dificultad, EstadoSolucion, TipoActividad
from domain.entities.schedule_request import SolicitudHorario
from domain.entities.schedule_response import BloqueTiempo, RespuestaHorario
from domain.ports.inbound.scheduler_port import AbstractSchedulerService


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
        self._validate_fixed_overlaps(solicitud.actividades_fijas)
        self._validate_task_duration(solicitud.tareas_pendientes, solicitud.contexto_usuario)

        model = cp_model.CpModel()
        ctx = solicitud.contexto_usuario

        travel_lookup = self._build_travel_lookup(solicitud)

        state: dict = {
            "intervals": {d: [] for d in range(7)},
            "fixed": {},
            "flex": {},
            "order_vars": {},
        }

        # RD-06: bloques de sueño
        self._add_sleep_blocks(model, ctx.bloques_sueno, state)

        # RD-02 / RD-03: actividades fijas
        for act in solicitud.actividades_fijas:
            self._add_fixed(model, act, state)

        # RB-07 (garantizada): bloque de descanso por día
        self._add_rest_blocks(model, ctx, state)

        # Variables de decisión para tareas flexibles
        for act in solicitud.tareas_pendientes:
            self._add_flexible_task(model, act, ctx, state)

        # RD-01: no solapamiento
        _add_no_overlap(model, state["intervals"])

        # RD-04: tiempo de traslado entre ubicaciones
        self._add_travel_constraints(model, travel_lookup, state)
        state["travel_lookup"] = travel_lookup

        # Restricciones blandas
        objective_terms: list[int] = []

        if solicitud.tareas_pendientes:
            self._rb_01(model, ctx, state, objective_terms)
            self._rb_02(model, ctx, state, objective_terms)
            self._rb_03(model, ctx, state, objective_terms)
            self._rb_04(model, ctx, state, objective_terms)
            self._rb_05(model, ctx, state, objective_terms)
            self._rb_06(model, ctx, state, objective_terms)
            self._rb_08(model, state, objective_terms)
            self._rb_09(model, state, objective_terms)
            self._rb_10(model, state, objective_terms)

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
        for s in bloques:
            if s.dia not in range(7):
                continue
            start = model.NewConstant(s.inicio)
            dur = s.fin - s.inicio
            end = model.NewConstant(s.fin)
            iv = model.NewIntervalVar(start, dur, end, f"sleep_d{s.dia}")
            state["intervals"][s.dia].append(iv)

    @staticmethod
    def _add_fixed(model, act, state):
        dur = act.hora_fin - act.hora_inicio
        s = model.NewConstant(act.hora_inicio)
        e = model.NewConstant(act.hora_fin)
        iv = model.NewIntervalVar(s, dur, e, f"fix_{act.id}_d{act.dia}")
        state["intervals"][act.dia].append(iv)
        state["fixed"][act.id] = {
            "s": s,
            "e": e,
            "loc": act.ubicacion_id,
            "dia": act.dia,
            "nombre": act.nombre,
            "tipo": act.tipo,
        }

    @staticmethod
    def _add_rest_blocks(model, ctx, state):
        for dia in range(7):
            p = model.NewBoolVar(f"rest_p_d{dia}")
            dur = MIN_REST_BLOCK_MINUTES
            s = model.NewIntVar(ctx.horario_inicio, ctx.horario_fin - dur, f"rest_s_d{dia}")
            e = model.NewIntVar(ctx.horario_inicio + dur, ctx.horario_fin, f"rest_e_d{dia}")
            iv = model.NewOptionalIntervalVar(s, dur, e, p, f"rest_iv_d{dia}")
            state["intervals"][dia].append(iv)
            model.Add(p == 1)

    @staticmethod
    def _add_flexible_task(model, act, ctx, state):
        deadline = min(act.dia, 6)
        days = list(range(deadline + 1))
        dur = act.duracion_estimada
        all_p: list = []

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
            s = model.NewIntVar(ctx.horario_inicio, ctx.horario_fin - dur, f"s_{act.id}_d{dia}")
            e = model.NewIntVar(ctx.horario_inicio + dur, ctx.horario_fin, f"e_{act.id}_d{dia}")
            iv = model.NewOptionalIntervalVar(s, dur, e, p, f"iv_{act.id}_d{dia}")
            state["intervals"][dia].append(iv)
            info["vars"][dia] = {"p": p, "s": s, "e": e}
            all_p.append(p)

        # RD-05: exactamente un día
        model.Add(sum(all_p) == 1)

    # ==================== Restricciones duras ====================

    @staticmethod
    def _add_travel_constraints(model, lookup, state):
        for dia in range(7):
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

    def _rb_01(self, model, ctx, state, terms):
        """RB-01: penalizar tareas difíciles empezando tarde si energía baja."""
        w = self.weights.rb_01
        if ctx.nivel_energia >= 5 or w == 0:
            return
        for tid, info in state["flex"].items():
            if info["dificultad"] != Dificultad.ALTA:
                continue
            for dia, v in info["vars"].items():
                pen = model.NewIntVar(0, 1440 * w, f"rb01_{tid}_d{dia}")
                model.Add(pen == v["s"] * w).OnlyEnforceIf(v["p"])
                model.Add(pen == 0).OnlyEnforceIf(v["p"].Not())
                terms.append(pen)

    def _rb_02(self, model, ctx, state, terms):
        """RB-02: penalizar concentrar muchas horas en un día."""
        w = self.weights.rb_02
        if w == 0:
            return
        for dia in range(7):
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
            total = model.NewIntVar(0, ctx.horario_fin - ctx.horario_inicio, f"rb02_t_d{dia}")
            model.Add(total == sum(contribs))
            excess = model.NewIntVar(0, 600, f"rb02_x_d{dia}")
            model.Add(total <= 360 + excess)
            terms.append(excess * w)

    def _rb_03(self, model, ctx, state, terms):
        """RB-03: penalizar fuera del horario preferido (primera/última hora)."""
        w = self.weights.rb_03
        if w == 0:
            return
        early_thr = ctx.horario_inicio + 60
        late_thr = ctx.horario_fin - 60
        for tid, info in state["flex"].items():
            for dia, v in info["vars"].items():
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
        day_range = ctx.horario_fin - ctx.horario_inicio
        for dia in range(7):
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
        for tid, info in state["flex"].items():
            if info["dificultad"] != Dificultad.ALTA:
                continue
            for dia, v in info["vars"].items():
                work_before = model.NewIntVar(0, ctx.horario_fin - ctx.horario_inicio, f"rb05_wb_{tid}_d{dia}")
                model.Add(work_before == v["s"] - ctx.horario_inicio).OnlyEnforceIf(v["p"])
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
                mis = model.NewIntVar(0, ctx.horario_fin - ctx.horario_inicio, f"rb06_mis_{tid}_d{dia}")
                model.Add(mis >= (ctx.horario_fin - ctx.horario_inicio) - info["dur"] * 3).OnlyEnforceIf(v["p"])
                model.Add(mis >= 0)
                terms.append(mis * w)

    def _rb_08(self, model, state, terms):
        """RB-08: penalizar diferencia de carga entre días consecutivos."""
        w = self.weights.rb_08
        if w == 0:
            return
        day_loads: dict[int, list] = {d: [] for d in range(7)}
        for info in state["flex"].values():
            for dia, v in info["vars"].items():
                load = model.NewIntVar(0, info["dur"], f"rb08_l_{dia}")
                model.Add(load == info["dur"]).OnlyEnforceIf(v["p"])
                model.Add(load == 0).OnlyEnforceIf(v["p"].Not())
                day_loads[dia].append(load)
        for d in range(6):
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
        for dia in range(7):
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
                urgency = 6 - dia
                pen = model.NewIntVar(0, w * 6, f"rb10_pen")
                model.Add(pen == w * urgency).OnlyEnforceIf(v["p"])
                model.Add(pen == 0).OnlyEnforceIf(v["p"].Not())
                terms.append(pen)

    @staticmethod
    def _validate_fixed_overlaps(actividades_fijas):
        per_day: dict[int, list] = {}
        for act in actividades_fijas:
            per_day.setdefault(act.dia, []).append(act)
        for dia, acts in per_day.items():
            sorted_acts = sorted(acts, key=lambda a: a.hora_inicio)
            for i in range(len(sorted_acts) - 1):
                a, b = sorted_acts[i], sorted_acts[i + 1]
                if b.hora_inicio < a.hora_fin:
                    raise ValueError(
                        f"Actividades fijas solapadas el día {dia}: "
                        f"'{a.nombre}' termina a las {a.hora_fin} min "
                        f"pero '{b.nombre}' empieza a las {b.hora_inicio} min"
                    )

    @staticmethod
    def _validate_task_duration(tareas_pendientes, ctx):
        max_daily = ctx.horario_fin - ctx.horario_inicio
        for act in tareas_pendientes:
            if act.duracion_estimada > max_daily:
                raise ValueError(
                    f"La tarea '{act.nombre}' dura {act.duracion_estimada} min, "
                    f"pero el horario disponible es de solo {max_daily} min/día"
                )

    def _build_response(self, solver, raw_status, state) -> RespuestaHorario:
        _map = {
            cp_model.OPTIMAL: EstadoSolucion.OPTIMA,
            cp_model.FEASIBLE: EstadoSolucion.FACTIBLE,
            cp_model.INFEASIBLE: EstadoSolucion.INFACTIBLE,
            cp_model.UNKNOWN: EstadoSolucion.DESCONOCIDO,
        }
        estado = _map.get(raw_status, EstadoSolucion.DESCONOCIDO)

        if estado == EstadoSolucion.INFACTIBLE:
            return RespuestaHorario(
                estado=estado,
                mensaje="No se encontró una solución con las restricciones actuales. "
                        "Verifica que las actividades fijas no solapen los bloques de sueño, "
                        "que haya tiempo disponible para cada tarea, "
                        "y que el horario activo tenga suficiente capacidad.",
            )

        if estado == EstadoSolucion.DESCONOCIDO:
            return RespuestaHorario(
                estado=estado,
                mensaje=f"El optimizador no encontró solución en {self.timeout}s. "
                        "Reduce la cantidad de tareas o aumenta el tiempo límite.",
            )

        bloques: list[BloqueTiempo] = []

        for tid, info in state["flex"].items():
            for dia, v in info["vars"].items():
                if solver.Value(v["p"]) == 1:
                    bloques.append(
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

        for fid, finfo in state["fixed"].items():
            bloques.append(
                BloqueTiempo(
                    id_actividad=fid,
                    nombre=finfo["nombre"],
                    tipo=finfo["tipo"],
                    dia=finfo["dia"],
                    hora_inicio=solver.Value(finfo["s"]),
                    hora_fin=solver.Value(finfo["e"]),
                    ubicacion_id=finfo["loc"],
                )
            )

        bloques.sort(key=lambda x: (x.dia, x.hora_inicio))
        bloques = self._insert_travel_blocks(bloques, state.get("travel_lookup", {}))
        return RespuestaHorario(estado=estado, bloques=bloques)


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

def _add_no_overlap(model, intervals_per_day: dict):
    for intervals in intervals_per_day.values():
        if len(intervals) > 1:
            model.AddNoOverlap(intervals)


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
