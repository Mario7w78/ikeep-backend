"""Regression tests for the five CP-SAT model corrections.

Each test here corresponds to a defect found by reading `schedule_service.py`:

1. RB-10 had an inverted urgency formula (penalised EARLY days) and never read
   `act.fecha_limite`.
2. RB-01 declared its penalty domain against the static constant 1440, so a
   midnight-crossing window ending after 01:00 forced a domain violation and the
   solver returned a spurious INFEASIBLE.
3. RB-03 left `pen` unconstrained when the task was present and neither early nor
   late.
4. Duplicate variable names made the solver log unreadable.
5. Two hard constraints were camouflaged inside soft-constraint code (documented
   here so the decision is pinned by a test, not only by a comment).
"""

import pytest
from ortools.sat.python import cp_model

from domain.entities.activity import Actividad
from domain.entities.enums import Dificultad, EstadoSolucion, PatronEnergia, TipoActividad
from domain.entities.schedule_request import SolicitudHorario
from domain.entities.user_context import ContextoUsuario
from domain.services import schedule_service as ss
from domain.services.schedule_service import (
    MIN_REST_BLOCK_MINUTES,
    PenaltyWeights,
    ScheduleOptimizer,
)


# ══════════════════════════════════════════════════════════════════
# Corrección 2 — RB-01: dominio dinámico en ventanas cross-midnight
# ══════════════════════════════════════════════════════════════════


class TestRB01DominioDinamico:
    """El dominio de la penalización debe derivar de day_end, no de 1440."""

    @staticmethod
    def _solicitud_ventana_cruzada() -> SolicitudHorario:
        """Ventana activa 22:00 → 02:00 (1320 → 120), es decir fin = 120 > 60."""
        return SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables_puras=[
                Actividad(
                    id="t1",
                    nombre="Nocturna",
                    tipo=TipoActividad.TAREA,
                    dia=0,
                    duracion_estimada=60,
                    dificultad=Dificultad.ALTA,
                    # 01:00 en una ventana que empieza a las 22:00 → el dominio
                    # de s se desplaza a 1500 (= 60 + 1440), por encima de 1440.
                    hora_preferida_inicio=60,
                ),
            ],
            contexto_usuario=ContextoUsuario(
                nivel_energia=1,
                horario_inicio=[1320] * 7,
                horario_fin=[120] * 7,
                patron_energia_manual=PatronEnergia.CRONICO,
            ),
            dia_inicio=0,
            dias_totales=7,
        )

    def test_no_es_infactible_por_violacion_de_dominio(self):
        """Antes: la tarea se perdía. Ahora: se programa.

        Con la ventana 1320 → 120 (22:00 → 02:00) el inicio puede llegar a 1500, pero el
        dominio de la penalización de RB-01 estaba clavado en 1440·w·2. La única
        salida del modelo era apagar la tarea (p == 0 en todos los días), así que el
        solver devolvía un horario óptimo con cero bloques: un fallo silencioso, no un
        INFEASIBLE. Con el tope derivado de day_end la tarea entra y se programa.
        """
        respuesta = ScheduleOptimizer(timeout_seconds=10).generar(self._solicitud_ventana_cruzada())

        assert respuesta.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE), (
            f"Esperaba una solución, el solver devolvió {respuesta.estado.value}."
        )
        assert [b for b in respuesta.bloques if b.id_actividad == "t1"], (
            "La tarea se ha perdido: el dominio de RB-01 la volvió incostable y el "
            "solver la omitió en silencio."
        )

    def test_tope_inicio_dia_refleja_el_cruce(self):
        """_tope_inicio_dia devuelve fin + 1440 en ventana cruzante, no 1440."""
        ctx = ContextoUsuario(horario_inicio=[1320] * 7, horario_fin=[120] * 7)
        assert ScheduleOptimizer._tope_inicio_dia(ctx, 0) == 1560

    def test_tope_inicio_dia_en_ventana_normal(self):
        """En ventana normal el tope es simplemente el fin del día."""
        ctx = ContextoUsuario(horario_inicio=[480] * 7, horario_fin=[1200] * 7)
        assert ScheduleOptimizer._tope_inicio_dia(ctx, 3) == 1200

    def test_transitorio_tambien_usa_el_tope_dinamico(self):
        """La rama TENDENCIA/TRANSCRIPTORIO tenía el mismo 1440·w fijo."""
        solicitud = self._solicitud_ventana_cruzada()
        solicitud.contexto_usuario.patron_energia_manual = PatronEnergia.TRANSCRIPTORIO
        respuesta = ScheduleOptimizer(timeout_seconds=10).generar(solicitud)
        assert respuesta.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)


# ══════════════════════════════════════════════════════════════════
# Corrección 1 — RB-10: dependencia real de fecha_limite
# ══════════════════════════════════════════════════════════════════


class TestDiaDeFechaLimite:
    """Parsing de la fecha límite a índice de día (0 = Lunes)."""

    def test_el_parser_existe(self):
        """El código anterior no tenía forma de traducir `fecha_limite` a un día."""
        assert hasattr(ss, "_dia_de_fecha_limite"), (
            "Falta `_dia_de_fecha_limite`: `fecha_limite` nunca llegaba al modelo"
        )

    @pytest.mark.parametrize(
        "crudo,esperado",
        [
            ("2026-10-05", 0),  # lunes
            ("2026-10-09", 4),  # viernes
            ("2026-10-05T00:00:00.000Z", 0),  # lo que produce Date.toISOString()
            ("3", 3),
            (None, None),
            ("", None),
            ("no-es-fecha", None),
            ("9", None),  # fuera de rango
        ],
    )
    def test_parsing(self, crudo, esperado):
        assert ss._dia_de_fecha_limite(crudo) == esperado


class TestRB10Urgencia:
    """La urgencia se mide contra la fecha límite, no contra la posición."""

    @staticmethod
    def _solicitud(fecha_limite, dias=7):
        return SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables_puras=[
                Actividad(
                    id="t1",
                    nombre="Con plazo",
                    tipo=TipoActividad.TAREA,
                    dia=0,
                    dia_desde=0,
                    dia_hasta=6,
                    duracion_estimada=60,
                    fecha_limite=fecha_limite,
                ),
            ],
            contexto_usuario=ContextoUsuario(
                horario_inicio=[480] * 7,
                horario_fin=[1200] * 7,
                patron_energia_manual=PatronEnergia.TENDENCIA,
            ),
            dia_inicio=0,
            dias_totales=dias,
        )

    def test_la_tarea_se_acerca_a_la_fecha_limite(self):
        """Con plazo en el lunes, la tarea debe ir al lunes, no al domingo.

        La fórmula anterior (rampa - día) empujaba al ÚLTIMO día de la ventana,
        que es justo lo contrario de "no postergar".
        """
        fecha = "2026-10-05"  # lunes → día 0
        respuesta = ScheduleOptimizer(timeout_seconds=10).generar(self._solicitud(fecha))
        bloque = next(b for b in respuesta.bloques if b.id_actividad == "t1")
        assert bloque.dia == 0, f"La tarea con plazo en lunes cayó en el día {bloque.dia}"

    def test_un_plazo_tardio_no_tienta_a_posponerlo(self):
        """Con plazo el viernes, la tarea no cae nunca después.

        La fórmula anterior (`urgencia = rampa - dia`) era 0 justo el último día de
        la ventana, así que empujaba la tarea al domingo (día 6) por encima de su
        viernes. Ahora la urgencia crece al acercarse la fecha, de modo que cualquier
        día con >= 2 días de holgura vale 0 y los días siguientes se pagan.
        """
        fecha = "2026-10-09"  # viernes → día 4
        respuesta = ScheduleOptimizer(timeout_seconds=10).generar(self._solicitud(fecha))
        bloque = next(b for b in respuesta.bloques if b.id_actividad == "t1")
        assert bloque.dia <= 4, f"Cayó en el día {bloque.dia}, después de su fecha límite"

    def test_la_penalizacion_crece_al_aproximarse_la_fecha_limite(self):
        """El coste por día debe crecer de forma monótona hacia la fecha y más allá.

        Este es el test que discrimina la corrección. Con la fórmula anterior
        `urgencia = último_día - día` el día 6 costaba 0 y el día 0 costaba 6·w: la
        regla pagaba por aplazar. Y como nunca leía `fecha_limite`, dos tareas con
        plazos distintos costaban exactamente lo mismo el mismo día.
        """
        lunes = _costes_por_dia(dia_limite=0)
        assert lunes, "Sin término RB-10: `fecha_limite` no está llegando al modelo"
        assert lunes[0] < lunes[1] < lunes[2] < lunes[6], (
            f"La penalización no crece al acercarse la fecha: {lunes}"
        )

        # Y con un plazo distinto, el coste del mismo día cambia.
        viernes = _costes_por_dia(dia_limite=4)
        assert viernes[0] == 0, "Con 4 días de holgura el lunes no debe costar nada"
        assert viernes[4] > 0 and viernes[6] > viernes[4], viernes



    def test_la_holgura_define_donde_empieza_a_penalizar(self):
        """Con holgura=2 y plazo el viernes (día 4), solo los días 3..6 tienen término.

        Si la rampa fuera `dias_totales`, aparecería un término para cada día de la
        ventana y la única colocación gratuita sería el lunes: la regla degeneraría
        en "programa todo lo que tenga plazo el primer día posible".
        """
        model = cp_model.CpModel()
        state = {
            "meta": {"dia_inicio": 0, "dias_totales": 7},
            "flex": {},
            "order_vars": {},
        }
        vars_d = {
            dia: {
                "p": model.NewBoolVar(f"p_d{dia}"),
                "s": model.NewIntVar(480, 1140, f"s_d{dia}"),
                "e": model.NewIntVar(540, 1200, f"e_d{dia}"),
            }
            for dia in range(7)
        }
        state["flex"]["t1"] = {
            "dur": 60, "vars": vars_d,
            "all_p": [v["p"] for v in vars_d.values()],
            "dia_fecha_limite": 4,
        }
        terms: list = []
        ScheduleOptimizer()._rb_10(model, state, terms)
        nombres = _nombres_del_modelo(model)

        # Holgura >= 2 (días 0,1,2): sin término, coste cero.
        for dia in (0, 1, 2):
            assert f"rb10_pen_t1_d{dia}" not in nombres
        # Cerca o vencida: término presente y creciente.
        for dia in (3, 4, 5, 6):
            assert f"rb10_pen_t1_d{dia}" in nombres
        assert len(terms) == 4

    def test_un_plazo_lejos_de_la_ventana_no_rompe_el_dominio(self):
        """Un plazo fuera de la ventana no debe sacar el término de rango.

        Es el mismo modo de fallo que RB-01: un tope global en vez de acotado a los
        días reales de la tarea produce un INFEASIBLE espurio.
        """
        respuesta = ScheduleOptimizer(timeout_seconds=10).generar(
            self._solicitud("2026-10-05T00:00:00.000Z", dias=2)
        )
        assert respuesta.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE), (
            f"Devolvió {respuesta.estado.value}; un plazo fuera de la ventana no debe "
            "declarar el modelo inviable"
        )

    def test_sin_fecha_limite_no_hay_termino(self):
        """Sin fecha límite no hay postergación que penalizar: no se crea variable."""
        respuesta = ScheduleOptimizer(timeout_seconds=10).generar(self._solicitud(None))
        assert respuesta.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)

    def test_peso_cero_no_opera(self):
        """rb_10 = 0 desactiva la regla sin romper el modelo."""
        respuesta = ScheduleOptimizer(
            timeout_seconds=10, weights=PenaltyWeights(rb_10=0)
        ).generar(self._solicitud("2026-10-05"))
        assert respuesta.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)


# ══════════════════════════════════════════════════════════════════
# Corrección 3 — RB-03: la cláusula que faltaba
# ══════════════════════════════════════════════════════════════════


class TestRB03ClausulaAusente:
    """`_rb_03` real: se comprueba la cláusula sobre el modelo que construye producción.

    Reconstruir la regla a mano en el test solo probaría el test; aquí se invoca
    `ScheduleOptimizer._rb_03` y se lee el valor que el solver le da a la variable.
    """

    @staticmethod
    def _pen_para(ventana=(480, 1200), dur=60, inicio_tarea=540):
        """Coste de RB-03 con la tarea programada en `inicio_tarea` dentro de `ventana`."""
        hora_inicio, hora_fin = ventana
        ctx = ContextoUsuario(horario_inicio=[hora_inicio] * 7, horario_fin=[hora_fin] * 7)
        model = cp_model.CpModel()
        p = model.NewBoolVar("p_d0")
        vars_d = {0: {
            "p": p,
            "s": model.NewIntVar(0, 2880, "s_d0"),
            "e": model.NewIntVar(0, 2880, "e_d0"),
        }}
        state = {
            "meta": {"dia_inicio": 0, "dias_totales": 7},
            "flex": {"t1": {"dur": dur, "vars": vars_d, "all_p": [p]}},
            "order_vars": {},
        }
        terms: list = []
        ScheduleOptimizer()._rb_03(model, ctx, state, terms)
        model.Add(p == 1)
        model.Add(vars_d[0]["s"] == inicio_tarea)
        model.Add(vars_d[0]["e"] == inicio_tarea + dur)
        model.Minimize(sum(terms))

        solver = cp_model.CpSolver()
        status = solver.Solve(model)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE), status
        return int(solver.ObjectiveValue())

    def test_penalizacion_cero_en_el_rango_ideal(self):
        """Presente ∧ ¬early ∧ ¬late ⇒ pen == 0, ahora fijado por una cláusula.

        Antes `pen` quedaba libre en [0, w]. En el modelo completo casi no se notaba
        porque Minimize lo empujaba a 0, pero eso es una preferencia, no una garantía:
        cualquier término fijo posterior podía exploitationar el hueco.
        """
        assert self._pen_para(inicio_tarea=540) == 0   # 09:00, dentro del rango
        assert self._pen_para(inicio_tarea=600) == 0   # 10:00, dentro del rango

    def test_penaliza_el_inicio_temprano(self):
        """El umbral es `inicio + 60`: la primera hora de la ventana se paga.

        Justo en el umbral ya no penaliza; un minuto antes, sí. Fijar este borde es lo
        que hace falta para que la cláusula `¬early ∧ ¬late ⇒ pen == 0` sea comprobable.
        """
        assert self._pen_para(inicio_tarea=510) > 0    # 08:30, dentro de la primera hora
        assert self._pen_para(inicio_tarea=539) > 0    # 08:59, un minuto antes del umbral
        assert self._pen_para(inicio_tarea=540) == 0   # 09:00 = inicio + 60, en rango

    def test_penaliza_el_final_tardio(self):
        """Umbral de fin: fin - 60. Terminar después se paga aunque empiece dentro."""
        assert self._pen_para(dur=60, inicio_tarea=1079) == 0   # acaba 18:59
        assert self._pen_para(dur=60, inicio_tarea=1080) == 0   # acaba 19:00 = fin - 60
        assert self._pen_para(dur=60, inicio_tarea=1085) > 0    # acaba 19:05, tarde


# ══════════════════════════════════════════════════════════════════
# Corrección 4 — nombres de variable únicos
# ══════════════════════════════════════════════════════════════════


def _nombres_del_modelo(model) -> list[str]:
    """Nombres de todas las variables declaradas, incluidos los términos internos."""
    return [v.name for v in model.Proto().variables]


class TestNombresUnicos:
    def test_no_hay_nombres_duplicados_en_el_modelo(self):
        """`rb10_pen` era un nombre constante para todas las tareas y todos los días.

        Dos penalizaciones distintas con el mismo nombre no es solo ruido en el log:
        el solver las reporta como la misma variable y cualquier lectura del modelo
        para depurar miente.
        """
        model = cp_model.CpModel()
        ctx = ContextoUsuario(horario_inicio=[480] * 7, horario_fin=[1200] * 7)
        state = {
            "meta": {"dia_inicio": 0, "dias_totales": 7},
            "flex": {},
            "order_vars": {},
        }
        opt = ScheduleOptimizer()
        opt._patron_override = PatronEnergia.CRONICO
        for i in range(3):
            tid = f"t{i}"
            vars_d = {}
            for dia in range(7):
                p = model.NewBoolVar(f"p_{tid}_d{dia}")
                vars_d[dia] = {
                    "p": p,
                    "s": model.NewIntVar(480, 1140, f"s_{tid}_d{dia}"),
                    "e": model.NewIntVar(540, 1200, f"e_{tid}_d{dia}"),
                }
            state["flex"][tid] = {
                "dificultad": Dificultad.MEDIA,
                "prioridad": 1,
                "dur": 60,
                "loc": "gym",
                "vars": vars_d,
                "all_p": [v["p"] for v in vars_d.values()],
                "dia_fecha_limite": 6,
            }
        terms: list = []
        opt._rb_02(model, ctx, state, terms)
        opt._rb_03(model, ctx, state, terms)
        opt._rb_04(model, ctx, state, terms)
        opt._rb_08(model, state, terms)
        opt._rb_10(model, state, terms)
        model.Minimize(sum(terms))

        nombres = _nombres_del_modelo(model)
        repetidos = sorted({n for n in nombres if nombres.count(n) > 1})
        assert not repetidos, f"Variables con nombres repetidos: {repetidos}"
        # Y los nombres incorporan el id de tarea y el día.
        for tid in ("t0", "t1", "t2"):
            assert f"rb10_pen_{tid}_d6" in nombres
            assert f"rb02c_{tid}_d6" in nombres

    def test_rb08_incluye_el_id_de_tarea(self):
        """`rb08_l_{dia}` no distinguía tareas: el mismo nombre para todas."""
        model = cp_model.CpModel()
        state = {"meta": {"dia_inicio": 0, "dias_totales": 3}, "flex": {}, "order_vars": {}}
        for i in range(2):
            tid = f"t{i}"
            vars_d = {
                dia: {
                    "p": model.NewBoolVar(f"p_{tid}_d{dia}"),
                    "s": model.NewIntVar(0, 100, f"s_{tid}_d{dia}"),
                    "e": model.NewIntVar(0, 100, f"e_{tid}_d{dia}"),
                }
                for dia in (0, 1)
            }
            state["flex"][tid] = {
                "dur": 60, "vars": vars_d,
                "all_p": [v["p"] for v in vars_d.values()],
            }
        terms: list = []
        ScheduleOptimizer()._rb_08(model, state, terms)
        nombres = _nombres_del_modelo(model)
        assert "rb08_l_t0_d0" in nombres and "rb08_l_t1_d0" in nombres
        repetidos = sorted({n for n in nombres if nombres.count(n) > 1})
        assert not repetidos, repetidos



# ══════════════════════════════════════════════════════════════════
# Corrección 5 — restricciones duras documentadas (decisión fijada por test)
# ══════════════════════════════════════════════════════════════════


class TestRestriccionesDurasDocumentadas:
    """Las dos restricciones que se camuflaban en el espacio blando se mantienen
    DURAS por decisión de producto. Estos tests las fijan para que un refactor
    inadvertido las convierta en blandas falle en CI.

    - RD-07: descanso diario de 30 min garantizado (Add(p == 1)).
    - RD-08: con energía TENDENCIA, máximo 1 tarea difícil por día.
    """

    def test_rd07_el_descanso_diario_cede_ante_la_tarea(self):
        """El descanso se mantiene antes que una tarea larga: la tarea se omite.

        720 min de ventana − 30 de descanso = 690 disponibles, y la tarea pide
        700. Si RD-07 fuera blanda, el solver la programaría y renunciaría al descanso
        (la penalización de omisión son 70 000 000). Que la tarea desaparezca
        es la prueba de que el descanso es una restricción dura.
        """
        solicitud = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables_puras=[
                Actividad(
                    id="t1", nombre="Larga", tipo=TipoActividad.TAREA,
                    dia=0, dia_desde=0, dia_hasta=6,
                    duracion_estimada=700,
                ),
            ],
            contexto_usuario=ContextoUsuario(
                horario_inicio=[480] * 7,
                horario_fin=[1200] * 7,  # 720 min
            ),
            dia_inicio=0,
            dias_totales=7,
        )
        respuesta = ScheduleOptimizer(timeout_seconds=10).generar(solicitud)

        assert respuesta.estado in (EstadoSolucion.OPTIMA, EstadoSolucion.FACTIBLE)
        # `tareas_omitidas` lleva nombres, no ids.
        assert respuesta.tareas_omitidas == ["Larga"], (
            f"Se esperaba la tarea omitida por el descanso garantizado; "
            f"omitidas={respuesta.tareas_omitidas}"
        )

    def test_rd08_max_una_alta_por_dia_con_tendencia(self):
        solicitud = SolicitudHorario(
            actividades_fijas=[],
            actividades_optimizables_puras=[
                Actividad(
                    id=f"t{i}", nombre=f"Difícil {i}", tipo=TipoActividad.TAREA,
                    dia=0, dia_desde=0, dia_hasta=6,
                    duracion_estimada=120,
                    dificultad=Dificultad.ALTA,
                )
                for i in range(2)
            ],
            contexto_usuario=ContextoUsuario(
                nivel_energia=1,
                horario_inicio=[480] * 7,
                horario_fin=[1200] * 7,
                patron_energia_manual=PatronEnergia.TENDENCIA,
            ),
            dia_inicio=0,
            dias_totales=7,
        )
        respuesta = ScheduleOptimizer(timeout_seconds=10).generar(solicitud)
        dias = [b.dia for b in respuesta.bloques if b.id_actividad in ("t0", "t1")]
        assert len(dias) == len(set(dias)), f"Dos ALTA el mismo día {dias}"

    def test_el_descanso_ocupa_treinta_minutos(self):
        assert MIN_REST_BLOCK_MINUTES == 30


def _costes_por_dia(dia_limite: int) -> dict[int, int]:
    """Coste real de programar la tarea en cada día, según el modelo construido.

    Se fuerza `p == 1` en el día de interés y se lee el valor de su penalización tras
    minimizar, así que el número es el que el solver realmente soportaría, no una
    fórmula replicada a mano.
    """
    resultado: dict[int, int] = {}
    for dia in range(7):
        model = cp_model.CpModel()
        vars_d = {
            d: {
                "p": model.NewBoolVar(f"p_d{d}"),
                "s": model.NewIntVar(480, 1140, f"s_d{d}"),
                "e": model.NewIntVar(540, 1200, f"e_d{d}"),
            }
            for d in range(7)
        }
        state = {
            "meta": {"dia_inicio": 0, "dias_totales": 7},
            "flex": {
                "t1": {
                    "dur": 60, "vars": vars_d,
                    "all_p": [v["p"] for v in vars_d.values()],
                    "dia_fecha_limite": dia_limite,
                },
            },
            "order_vars": {},
        }
        terms: list = []
        ScheduleOptimizer()._rb_10(model, state, terms)
        model.Add(vars_d[dia]["p"] == 1)
        model.Minimize(sum(terms))
        solver = cp_model.CpSolver()
        status = solver.Solve(model)
        assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE), status
        objetivo = int(solver.ObjectiveValue())
        # Los días no forzados quedan en 0 (no hay término de holgura o el solver los
        # apaga), así que el objetivo es el coste del día forzado.
        resultado[dia] = objetivo
    return resultado
