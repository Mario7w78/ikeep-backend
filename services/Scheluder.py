from ortools.sat.python import cp_model
from schemas.Entities import Actividad, ActividadProgramada

class GestorVariablesHorario:
    def __init__(self, model: cp_model.CpModel, inicio_dia: int, fin_dia: int):
        self.model = model
        self.inicio_dia = inicio_dia
        self.fin_dia = fin_dia
        self.intervalos_por_dia = {dia: [] for dia in range(7)} # Diccionario de los dias de la semana con arrays vacios
        self.estado_tareas = {}

    def registrar_actividad(self, act: Actividad): 
        duracion_total = act.duracion_minutos + act.tiempo_traslado_minutos
        self.estado_tareas[act.id] = {'nombre': act.nombre, 'vars_dia': {}}

        if act.es_fija:
            self._crear_variables_fijas(act, duracion_total)
        else:
            self._crear_variables_flexibles(act, duracion_total)

    def _crear_variables_fijas(self, act: Actividad, duracion: int):
        # Asumimos que la actividad fija tiene 1 solo día permitido en su lista
        dia_fijo = act.dias_permitidos[0]
        inicio_real = act.inicio_minutos - act.tiempo_traslado_minutos
        
        start_var = self.model.NewIntVar(inicio_real, inicio_real, f'start_{act.id}')
        end_var = self.model.NewIntVar(act.fin_minutos, act.fin_minutos, f'end_{act.id}')
        interval_var = self.model.NewIntervalVar(start_var, duracion, end_var, f'int_{act.id}')
        
        self.intervalos_por_dia[dia_fijo].append(interval_var)
        
        # Guardamos que este día siempre está activo (1)
        presence_var = self.model.NewConstant(1)
        self.estado_tareas[act.id]['vars_dia'][dia_fijo] = (presence_var, start_var, end_var)

    def _crear_variables_flexibles(self, act: Actividad, duracion: int):
        presencias_posibles = []
        
        # Creamos una opción por cada día permitido
        for dia in act.dias_permitidos:
            # Variable Booleana: ¿Se agendó esta tarea EN ESTE DÍA específico?
            presence_var = self.model.NewBoolVar(f'pres_{act.id}_d{dia}')
            presencias_posibles.append(presence_var)
            
            start_var = self.model.NewIntVar(self.inicio_dia, self.fin_dia - duracion, f'start_{act.id}_d{dia}')
            end_var = self.model.NewIntVar(self.inicio_dia + duracion, self.fin_dia, f'end_{act.id}_d{dia}')
            
            # EL TRUCO: Intervalo Opcional. Solo existe si presence_var es True
            interval_var = self.model.NewOptionalIntervalVar(
                start_var, duracion, end_var, presence_var, f'int_opt_{act.id}_d{dia}'
            )
            
            self.intervalos_por_dia[dia].append(interval_var)
            self.estado_tareas[act.id]['vars_dia'][dia] = (presence_var, start_var, end_var)

        # RESTRICCIÓN: De todos los días permitidos, SOLO 1 debe ser elegido
        self.model.AddExactlyOne(presencias_posibles)


class GestorRestriccionesHorario:
    """Responsabilidad: Aplicar las reglas de negocio al modelo."""
    def __init__(self, model: cp_model.CpModel):
        self.model = model

    def evitar_solapamientos(self, intervalos_por_dia: dict):
        # Aplicamos la regla de no chocar para CADA DÍA de forma independiente
        for dia, intervalos_del_dia in intervalos_por_dia.items():
            if intervalos_del_dia:
                self.model.AddNoOverlap(intervalos_del_dia)


class PlanificadorSemanal:
    """Responsabilidad: Orquestar el proceso (La fachada principal)."""
    def __init__(self, inicio_dia: int, fin_dia: int):
        self.model = cp_model.CpModel()
        self.creador_vars = GestorVariablesHorario(self.model, inicio_dia, fin_dia)
        self.restricciones = GestorRestriccionesHorario(self.model)

    def resolver(self, actividades: list[Actividad]) -> list[ActividadProgramada]:
        # 1. Crear variables e intervalos
        for act in actividades:
            self.creador_vars.registrar_actividad(act)
            
        # 2. Aplicar restricciones
        self.restricciones.evitar_solapamientos(self.creador_vars.intervalos_por_dia)
        
        # 3. Resolver
        solver = cp_model.CpSolver()
        status = solver.Solve(self.model)
        
        return self._formatear_salida(solver, status)

    def _formatear_salida(self, solver, status) -> list[ActividadProgramada]:
        resultado = []
        if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
            for act_id, info in self.creador_vars.estado_tareas.items():
                for dia, (presence_var, start_var, end_var) in info['vars_dia'].items():
                    # Si el modelo decidió que esta variable booleana es Verdadera (1)
                    if solver.Value(presence_var) == 1:
                        resultado.append(ActividadProgramada(
                            id_actividad=act_id,
                            nombre=info['nombre'],
                            dia=dia,
                            inicio=solver.Value(start_var),
                            fin=solver.Value(end_var)
                        ))
            
            # Ordenamos por día y luego por hora de inicio
            resultado.sort(key=lambda x: (x.dia, x.inicio))
        return resultado


# Función exportable para FastAPI
def generar_horario_semanal(actividades: list[Actividad], inicio_dia: int, fin_dia: int) -> list[ActividadProgramada]:
    planificador = PlanificadorSemanal(inicio_dia, fin_dia)
    return planificador.resolver(actividades)