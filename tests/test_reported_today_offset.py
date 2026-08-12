"""La medianoche del usuario, no la del servidor.

Alguien en Lima que reporta su energia a las 20:00 del lunes quedaba
registrado el martes: a las 19:00 locales el servidor UTC ya cree que cambio
el dia.
"""

from datetime import datetime, timezone
from unittest.mock import Mock, patch

from infrastructure.adapters.outbound.supabase.schedule_repository import (
    SupabaseEnergiaRepository,
)

LIMA = -300  # UTC-5


def consultar(ahora_utc: datetime, desfase: int) -> str:
    """Devuelve el `gte` con el que se consulto la tabla."""
    cadena = Mock()
    cadena.select.return_value = cadena
    cadena.gte.return_value = cadena
    cadena.limit.return_value = cadena
    cadena.execute.return_value = Mock(data=[])
    cliente = Mock()
    cliente.table.return_value = cadena

    with patch(
        "infrastructure.adapters.outbound.supabase.schedule_repository.client_for_user",
        return_value=cliente,
    ), patch(
        "infrastructure.adapters.outbound.supabase.schedule_repository._ahora",
        return_value=ahora_utc,
    ):
        SupabaseEnergiaRepository().reported_today("token", desfase)

    return cadena.gte.call_args[0][1]


class TestMedianocheDelUsuario:
    def test_las_20_del_lunes_en_lima_siguen_siendo_lunes(self):
        # 2026-08-11 01:00 UTC = 2026-08-10 20:00 en Lima.
        desde = consultar(datetime(2026, 8, 11, 1, 0, tzinfo=timezone.utc), LIMA)

        # La medianoche del 10 en Lima son las 05:00 UTC del 10.
        assert desde.startswith("2026-08-10T05:00")

    def test_sin_desfase_es_la_medianoche_utc(self):
        desde = consultar(datetime(2026, 8, 11, 1, 0, tzinfo=timezone.utc), 0)

        assert desde.startswith("2026-08-11T00:00")

    def test_un_huso_adelantado_tambien(self):
        # Tokio, UTC+9. Las 08:00 UTC son las 17:00 del mismo dia alli.
        desde = consultar(datetime(2026, 8, 11, 8, 0, tzinfo=timezone.utc), 540)

        # Medianoche del 11 en Tokio = 15:00 UTC del 10.
        assert desde.startswith("2026-08-10T15:00")

    def test_justo_despues_de_la_medianoche_local(self):
        # 2026-08-11 05:30 UTC = 00:30 del 11 en Lima: dia recien empezado.
        desde = consultar(datetime(2026, 8, 11, 5, 30, tzinfo=timezone.utc), LIMA)

        assert desde.startswith("2026-08-11T05:00")

    def test_justo_antes_de_la_medianoche_local(self):
        # 2026-08-11 04:30 UTC = 23:30 del 10 en Lima: todavia es el 10.
        desde = consultar(datetime(2026, 8, 11, 4, 30, tzinfo=timezone.utc), LIMA)

        assert desde.startswith("2026-08-10T05:00")
