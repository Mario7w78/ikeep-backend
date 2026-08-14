"""Las reglas que hacen que el dato de completado valga algo.

No se puede verificar que alguien estudio. Ningun metodo lo consigue: el
tiempo de pantalla mide que el telefono estuvo quieto, la ubicacion no dice
que abrio el libro, y una sesion obligatoria deja fuera justo a quien estudia
con el telefono guardado.

La pregunta que ordena el diseno es otra: a quien le estaria mintiendo? No hay
ranking ni premio; el unico destinatario del dato es la propia persona. Asi
que el objetivo no es verificar, es que decir la verdad salga barato y mentir
no sirva de nada. Estas reglas son las que sostienen eso.
"""

from datetime import date, timedelta

import pytest

from domain.services.rewards.completion import (
    EstadoCompletado,
    MotivoRechazo,
    OrigenCompletado,
    estado_de_la_ocurrencia,
    validar_marcado,
)

HOY = date(2026, 8, 14)


class TestNoSePuedeMarcarElFuturo:
    """La unica trampa que vale la pena cerrar, y se cierra sola."""

    def test_hoy_si(self):
        assert validar_marcado(HOY, hoy=HOY) is None

    def test_manana_no(self):
        assert validar_marcado(HOY + timedelta(days=1), hoy=HOY) is MotivoRechazo.FUTURO

    def test_ayer_si(self):
        assert validar_marcado(HOY - timedelta(days=1), hoy=HOY) is None


class TestVentanaDeGracia:
    """Marcar una semana entera hacia atras es ficcion.

    Y la ficcion envenena el dato: la correlacion entre energia y cumplimiento
    es lo unico que esta app puede hacer y ninguna app de habitos puede. Si se
    rellena con suposiciones, deja de valer.
    """

    def test_anteayer_todavia_entra(self):
        assert validar_marcado(HOY - timedelta(days=2), hoy=HOY) is None

    def test_hace_tres_dias_ya_no(self):
        assert (
            validar_marcado(HOY - timedelta(days=3), hoy=HOY)
            is MotivoRechazo.FUERA_DE_PLAZO
        )

    def test_lo_viejo_queda_sin_resolver_para_siempre(self):
        # No es un castigo: es que "no se" tambien es un dato, y uno honesto.
        assert (
            validar_marcado(HOY - timedelta(days=30), hoy=HOY)
            is MotivoRechazo.FUERA_DE_PLAZO
        )


class TestElEstadoQueFaltaba:
    """`sin_resolver` es el mas importante de los seis.

    Hoy no existe: una actividad sin marcar se parece a una no hecha, y no son
    lo mismo. "No se" y "no" los leen distinto la racha, el crecimiento y la
    correlacion — confundirlos arruina los tres.
    """

    def test_un_bloque_que_no_empezo_esta_pendiente(self):
        estado = estado_de_la_ocurrencia(
            fecha=HOY, hoy=HOY, termino=False, fila=None, cancelada=False
        )

        assert estado is EstadoCompletado.PENDIENTE

    def test_termino_y_nadie_dijo_nada_es_sin_resolver(self):
        estado = estado_de_la_ocurrencia(
            fecha=HOY, hoy=HOY, termino=True, fila=None, cancelada=False
        )

        assert estado is EstadoCompletado.SIN_RESOLVER

    def test_sin_resolver_no_es_lo_mismo_que_no_hecha(self):
        sin_resolver = estado_de_la_ocurrencia(
            fecha=HOY, hoy=HOY, termino=True, fila=None, cancelada=False
        )
        no_hecha = estado_de_la_ocurrencia(
            fecha=HOY,
            hoy=HOY,
            termino=True,
            fila={"estado": "no_hecha"},
            cancelada=False,
        )

        assert sin_resolver is not no_hecha

    def test_lo_que_el_usuario_dijo_manda_sobre_el_reloj(self):
        # Marcar algo antes de que termine el bloque es legitimo: se puede
        # haber adelantado.
        estado = estado_de_la_ocurrencia(
            fecha=HOY, hoy=HOY, termino=False, fila={"estado": "hecha"}, cancelada=False
        )

        assert estado is EstadoCompletado.HECHA

    def test_un_dia_que_no_correspondia_esta_cancelado(self):
        # Viene de la excepcion del calendario, no de una decision del usuario
        # sobre si lo hizo.
        estado = estado_de_la_ocurrencia(
            fecha=HOY, hoy=HOY, termino=True, fila=None, cancelada=True
        )

        assert estado is EstadoCompletado.CANCELADA

    def test_un_dia_pasado_sin_fila_queda_sin_resolver(self):
        estado = estado_de_la_ocurrencia(
            fecha=HOY - timedelta(days=5),
            hoy=HOY,
            termino=True,
            fila=None,
            cancelada=False,
        )

        assert estado is EstadoCompletado.SIN_RESOLVER


class TestElOrigenSeGuarda:
    """Con el tiempo permite saber si lo hecho por sesion se cumple distinto.

    Y esa si es una respuesta util, a diferencia de un numero que solo sube.
    """

    def test_los_tres_caminos_existen(self):
        assert {o.value for o in OrigenCompletado} == {"sesion", "manual", "cierre"}

    def test_ningun_origen_es_automatico(self):
        # Nunca marcar como hecha sola. Si el dato se rellena con
        # suposiciones, la correlacion deja de valer.
        assert "automatico" not in {o.value for o in OrigenCompletado}


class TestElDiaDelUsuario:
    """El servidor no puede saber que dia es para quien pide.

    Usar su propia medianoche es el error que ya tuvo GET /energia/hoy: en
    Lima, lo reportado a las 20:00 del lunes quedaba contado como martes.
    """

    def test_aplica_el_desfase_que_manda_el_cliente(self):
        from datetime import datetime, timezone

        from domain.services.rewards.completion import hoy_del_usuario

        # Medianoche y media UTC del 15. En Lima (-300) todavia es el 14.
        instante = datetime(2026, 8, 15, 0, 30, tzinfo=timezone.utc)

        assert hoy_del_usuario(-300, ahora=instante) == date(2026, 8, 14)
        assert hoy_del_usuario(0, ahora=instante) == date(2026, 8, 15)

    def test_tambien_hacia_adelante(self):
        from datetime import datetime, timezone

        from domain.services.rewards.completion import hoy_del_usuario

        # 23:30 UTC del 14. En Tokio (+540) ya es el 15.
        instante = datetime(2026, 8, 14, 23, 30, tzinfo=timezone.utc)

        assert hoy_del_usuario(540, ahora=instante) == date(2026, 8, 15)


class TestLoHechoPorArea:
    """Lo que ninguna racha puede decir.

    Se pueden llevar treinta dias seguidos estudiando y tres semanas sin
    moverse ni ver a nadie, y la racha felicita igual. Los petalos son el
    unico lugar donde ese desequilibrio se ve.
    """

    #: 2026-06-01: dentro de la ventana si `desde` es enero.
    DENTRO = "2026-06-01"
    #: Anterior a cualquier `desde` que usen estos tests.
    FUERA = "2020-01-01"

    def _repo_devolviendo(self, filas):
        from unittest.mock import Mock, patch

        from infrastructure.adapters.outbound.supabase.completion_repository import (
            SupabaseCompletadosRepository,
        )

        tabla = Mock()
        tabla.select.return_value = tabla
        tabla.gte.return_value = tabla
        tabla.eq.return_value = tabla
        tabla.execute.return_value = Mock(data=filas)
        cliente = Mock()
        cliente.table.return_value = tabla

        parche = patch(
            "infrastructure.adapters.outbound.supabase.completion_repository."
            "client_for_user",
            return_value=cliente,
        )
        return SupabaseCompletadosRepository(), parche

    def test_agrupa_por_area(self):
        repo, parche = self._repo_devolviendo([
            {"fecha": self.DENTRO, "activities": {"area": "estudio"}},
            {"fecha": self.DENTRO, "activities": {"area": "estudio"}},
            {"fecha": self.DENTRO, "activities": {"area": "cuerpo"}},
        ])

        with parche:
            conteos = repo.conteos_por_area("token", date(2026, 1, 1))

        assert conteos.recientes == {"estudio": 2, "cuerpo": 1}

    def test_el_petalo_nunca_encoge_aunque_lo_viejo_salga_de_la_ventana(self):
        # Ver un petalo achicarse porque dejaste de correr es exactamente el
        # reproche que este diseno evita. El TAMANO acumula desde siempre; lo
        # que cambia es la FORMA de la flor.
        repo, parche = self._repo_devolviendo([
            {"fecha": self.FUERA, "activities": {"area": "cuerpo"}},
            {"fecha": self.FUERA, "activities": {"area": "cuerpo"}},
            {"fecha": self.DENTRO, "activities": {"area": "estudio"}},
        ])

        with parche:
            conteos = repo.conteos_por_area("token", date(2026, 1, 1))

        assert conteos.historico == {"cuerpo": 2, "estudio": 1}
        assert conteos.recientes == {"estudio": 1}

    def test_lo_reciente_cuenta_en_las_dos_escalas(self):
        repo, parche = self._repo_devolviendo([
            {"fecha": self.DENTRO, "activities": {"area": "yo"}},
        ])

        with parche:
            conteos = repo.conteos_por_area("token", date(2026, 1, 1))

        assert conteos.historico == conteos.recientes == {"yo": 1}

    def test_tolera_que_postgrest_devuelva_lista(self):
        # Segun la version, la relacion embebida llega como objeto o como
        # lista de uno. Las dos formas dicen lo mismo.
        repo, parche = self._repo_devolviendo([
            {"fecha": self.DENTRO, "activities": [{"area": "vinculos"}]},
        ])

        with parche:
            conteos = repo.conteos_por_area("token", date(2026, 1, 1))

        assert conteos.recientes == {"vinculos": 1}

    def test_una_fila_sin_area_no_se_pierde(self):
        # Perderla haria que el total de los petalos no cuadre con el
        # historial, y esa clase de discrepancia no se detecta mirando.
        repo, parche = self._repo_devolviendo([
            {"fecha": self.DENTRO, "activities": None},
        ])

        with parche:
            conteos = repo.conteos_por_area("token", date(2026, 1, 1))

        assert conteos.recientes == {"estudio": 1}
