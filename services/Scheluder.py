from ortools.sat.python import cp_model
from schemas.Entities import Actividad, ActividadProgramada

def generar_horario_optimizado(actividades: list[Actividad], inicio_dia: int, fin_dia: int) -> list[ActividadProgramada]:
    model = cp_model.CpModel()
    
    tareas = {}
    intervalos = []
    
    # 1. Crear variables e intervalos para cada actividad
    for act in actividades:
        duracion_total = act.duracion_minutos + act.tiempo_traslado_minutos
        
        if act.es_fija:
            # El bloque real debe empezar antes para incluir el traslado
            inicio_real = act.inicio_minutos - act.tiempo_traslado_minutos
            
            # Restricción dura: La actividad fija tiene un horario inamovible
            start_var = model.NewIntVar(inicio_real, inicio_real, f'start_{act.id}')
            end_var = model.NewIntVar(act.fin_minutos, act.fin_minutos, f'end_{act.id}')
        else:
            # Las actividades flexibles pueden ocurrir en cualquier momento del día
            start_var = model.NewIntVar(inicio_dia, fin_dia - duracion_total, f'start_{act.id}')
            end_var = model.NewIntVar(inicio_dia + duracion_total, fin_dia, f'end_{act.id}')
            
        interval_var = model.NewIntervalVar(start_var, duracion_total, end_var, f'interval_{act.id}')
        
        tareas[act.id] = {
            'start': start_var,
            'end': end_var,
            'nombre': act.nombre
        }
        intervalos.append(interval_var)
        
    # 2. Restricción Dura: No solapamientos
    model.AddNoOverlap(intervalos)
    
    # 3. Resolver el modelo
    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    
    resultado = []
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        for act_id, vars in tareas.items():
            resultado.append(ActividadProgramada(
                id_actividad=act_id,
                nombre=vars['nombre'],
                inicio=solver.Value(vars['start']),
                fin=solver.Value(vars['end'])
            ))
        # Ordenar cronológicamente
        resultado.sort(key=lambda x: x.inicio)
        
    return resultado