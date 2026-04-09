from ortools.sat.python import cp_model
from schemas.Entities import Actividad, ActividadProgramada
from dataclasses import dataclass, field
from enum import Enum


class EstadoSolucion(Enum):
    OPTIMA = "OPTIMA"
    FACTIBLE = "FACTIBLE"
    INFACTIBLE = "INFACTIBLE"
    DESCONOCIDO = "DESCONOCIDO"


@dataclass
class ResultadoHorario:
    estado: EstadoSolucion
    actividades: list[ActividadProgramada] = field(default_factory=list)
    mensaje: str = ""


class GestorVariablesHorario:
    def __init__(self, model: cp_model.CpModel, inicio_dia: int, fin_dia: int):
        self.model = model
        self.inicio_dia = inicio_dia
        self.fin_dia = fin_dia
        self.intervalos_por_dia: dict[int, list] = {dia: [] for dia in range(7)}
        self.estado_tareas: dict[str, dict] = {}
        self._vars_inicio_flexibles: list = []  # Para la función objetivo

    def registrar_actividad(self, act: Actividad) -> None:
        if not act.dias_permitidos:
            raise ValueError(f"Actividad '{act.nombre}' (id={act.id}) no tiene días permitidos.")

        duracion_total = act.duracion_minutos + act.tiempo_traslado_minutos

        if duracion_total > (self.fin_dia - self.inicio_dia):
            raise ValueError(
                f"Actividad '{act.nombre}': duración ({duracion_total} min) "
                f"supera la ventana del día ({self.fin_dia - self.inicio_dia} min)."
            )

        self.estado_tareas[act.id] = {"nombre": act.nombre, "vars_dia": {}}

        if act.es_fija:
            self._crear_variables_fijas(act, duracion_total)
        else:
            self._crear_variables_flexibles(act, duracion_total)

    def _crear_variables_fijas(self, act: Actividad, duracion: int) -> None:
        inicio_bloque = (act.inicio_minutos or 0) - (act.tiempo_traslado_minutos or 0)
        print(f"[FIJA] {act.nombre} | inicio_bloque={inicio_bloque} duracion={duracion} "
          f"fin_esperado={inicio_bloque + duracion} | fin_dia={self.fin_dia}")
    
        if inicio_bloque < self.inicio_dia:
            raise ValueError(
                f"Actividad fija '{act.nombre}': el bloque empieza en {inicio_bloque} "
                f"pero el día comienza en {self.inicio_dia}."
            )
        if inicio_bloque + duracion > self.fin_dia:
            raise ValueError(
                f"Actividad fija '{act.nombre}': el bloque termina en {inicio_bloque + duracion} "
                f"pero el día termina en {self.fin_dia}."
            )
    
        for dia in act.dias_permitidos:
            start_var = self.model.NewConstant(inicio_bloque)
            end_var = self.model.NewConstant(inicio_bloque + duracion)
            
            interval_var = self.model.NewIntervalVar(
                start_var, duracion, end_var, f"int_{act.id}_d{dia}"
            )

            self.intervalos_por_dia[dia].append(interval_var)

            presence_var = self.model.NewConstant(1)
            self.estado_tareas[act.id]["vars_dia"][dia] = (presence_var, start_var, end_var)

    def _crear_variables_flexibles(self, act: Actividad, duracion: int) -> None:

        for dia in act.dias_permitidos:
            presence_var = self.model.NewConstant(1)  # ✅ siempre presente, como fija

            start_var = self.model.NewIntVar(
                self.inicio_dia,
                self.fin_dia - duracion,
                f"start_{act.id}_d{dia}",
            )
            end_var = self.model.NewIntVar(
                self.inicio_dia + duracion,
                self.fin_dia,
                f"end_{act.id}_d{dia}",
            )

            interval_var = self.model.NewIntervalVar(  # ✅ ya no es Optional
            start_var, duracion, end_var, f"int_{act.id}_d{dia}"
            )

            self.intervalos_por_dia[dia].append(interval_var)
            self.estado_tareas[act.id]["vars_dia"][dia] = (presence_var, start_var, end_var)

            self._vars_inicio_flexibles.append(start_var)  # ✅ directo, sin ponderar


def _aplicar_no_solapamiento(model: cp_model.CpModel, intervalos_por_dia: dict) -> None:
    for intervalos in intervalos_por_dia.values():
        if len(intervalos) > 1:
            model.AddNoOverlap(intervalos)


class PlanificadorSemanal:
    def __init__(self, inicio_dia: int, fin_dia: int):
        self.model = cp_model.CpModel()
        self.inicio_dia = inicio_dia
        self.fin_dia = fin_dia
        self.gestor = GestorVariablesHorario(self.model, inicio_dia, fin_dia)

    def resolver(self, actividades: list[Actividad]) -> ResultadoHorario:
        # 1. Registrar actividades (crea variables e intervalos)
        for act in actividades:
            self.gestor.registrar_actividad(act)

        # 2. Restricción: sin solapamientos
        _aplicar_no_solapamiento(self.model, self.gestor.intervalos_por_dia)

        # 3. Función objetivo: minimizar la suma de inicios → actividades lo más temprano posible
        if self.gestor._vars_inicio_flexibles:
            self.model.Minimize(sum(self.gestor._vars_inicio_flexibles))

        # 4. Resolver
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 10.0  # Límite de tiempo por seguridad
        raw_status = solver.Solve(self.model)

        return self._construir_resultado(solver, raw_status)

    def _construir_resultado(self, solver: cp_model.CpSolver, raw_status: int) -> ResultadoHorario:
        _mapa_estado = {
            cp_model.OPTIMAL:    EstadoSolucion.OPTIMA,
            cp_model.FEASIBLE:   EstadoSolucion.FACTIBLE,
            cp_model.INFEASIBLE: EstadoSolucion.INFACTIBLE,
            cp_model.UNKNOWN:    EstadoSolucion.DESCONOCIDO,
        }
        estado = _mapa_estado.get(raw_status, EstadoSolucion.DESCONOCIDO)

        if estado in (EstadoSolucion.INFACTIBLE, EstadoSolucion.DESCONOCIDO):
            return ResultadoHorario(
                estado=estado,
                mensaje="No se encontró una solución válida para las actividades dadas.",
            )

        actividades_programadas = []
        for act_id, info in self.gestor.estado_tareas.items():
            for dia, (presence_var, start_var, end_var) in info["vars_dia"].items():
                if solver.Value(presence_var) == 1:
                    actividades_programadas.append(
                        ActividadProgramada(
                            id_actividad=act_id,
                            nombre=info["nombre"],
                            dia=dia,
                            inicio=solver.Value(start_var),
                            fin=solver.Value(end_var),
                        )
                    )

        actividades_programadas.sort(key=lambda x: (x.dia, x.inicio))
        return ResultadoHorario(estado=estado, actividades=actividades_programadas)


def generar_horario_semanal(
    actividades: list[Actividad], inicio_dia: int, fin_dia: int
) -> ResultadoHorario:
    planificador = PlanificadorSemanal(inicio_dia, fin_dia)
    return planificador.resolver(actividades)