"""El cifrado del refresh_token: ida y vuelta, rotacion, claves ausentes."""

import pytest
from cryptography.fernet import Fernet

from infrastructure.adapters.outbound.google.token_cipher import (
    ClaveFernetAusente,
    cifrar,
    descifrar,
    fue_con_clave_anterior,
)
from infrastructure.config import settings as settings_module


VIGENTE = Fernet.generate_key().decode()
ANTERIOR = Fernet.generate_key().decode()
SECRETO = "1//refresh-token-de-google"


@pytest.fixture
def claves(monkeypatch):
    """Instala las claves dadas como configuracion vigente del test."""

    def _instalar(vigente: str, previa: str = ""):
        monkeypatch.setattr(
            settings_module,
            "_settings",
            settings_module.Settings(
                VERIFY_SCHEMA_ON_STARTUP=False,
                GOOGLE_TOKEN_FERNET_KEY=vigente,
                GOOGLE_TOKEN_FERNET_KEY_PREV=previa,
            ),
        )

    return _instalar


class TestIdaYVuelta:
    def test_lo_cifrado_se_descifra_igual(self, claves):
        claves(VIGENTE)

        assert descifrar(cifrar(SECRETO)) == SECRETO

    def test_dos_pasadas_no_dejan_el_mismo_texto(self, claves):
        claves(VIGENTE)

        # Fernet lleva IV propio: el mismo secreto no cifra igual dos veces,
        # asi que dos tokens iguales no se delatan mirando la tabla.
        assert cifrar(SECRETO) != cifrar(SECRETO)


class TestRotacion:
    def test_se_lee_lo_cifrado_con_la_clave_anterior(self, claves):
        viejo = Fernet(ANTERIOR.encode()).encrypt(SECRETO.encode()).decode()
        claves(VIGENTE, ANTERIOR)

        assert descifrar(viejo) == SECRETO

    def test_la_clave_anterior_se_reconoce_como_tal(self, claves):
        viejo = Fernet(ANTERIOR.encode()).encrypt(SECRETO.encode()).decode()
        claves(VIGENTE, ANTERIOR)

        assert fue_con_clave_anterior(viejo) is True

    def test_una_clave_malformada_en_previa_no_rompe_la_lectura(self, claves):
        # La previa solo sirve para leer; si esta rota, lo cifrado con la
        # vigente sigue alcanzando.
        claves(VIGENTE, "previa-malformada")

        assert fue_con_clave_anterior(cifrar(SECRETO)) is False

    def test_lo_cifrado_con_la_vigente_no_pide_recifrado(self, claves):
        claves(VIGENTE)

        assert fue_con_clave_anterior(cifrar(SECRETO)) is False

    def test_sin_previa_un_token_ilegible_es_error_y_no_recifrado(self, claves):
        # Sin clave previa no hay segunda oportunidad de leer: eso es un
        # problema de configuracion, no un caso de rotacion.
        claves(VIGENTE)

        with pytest.raises(ClaveFernetAusente):
            fue_con_clave_anterior("no-es-un-token")

    def test_un_token_de_nadie_se_rechaza(self, claves):
        claves(VIGENTE, ANTERIOR)

        with pytest.raises(ClaveFernetAusente):
            descifrar("basura-que-no-cifro-nadie")


class TestClaveAusente:
    def test_sin_clave_no_se_cifra(self, claves):
        claves("")

        with pytest.raises(ClaveFernetAusente):
            cifrar(SECRETO)

    def test_sin_clave_no_se_descifra(self, claves):
        claves("")

        with pytest.raises(ClaveFernetAusente):
            descifrar("lo-que-sea")

    def test_una_clave_malformada_es_error_de_configuracion(self, claves):
        # "clave-malformada" es texto, no bytes base64 de una clave Fernet.
        claves("clave-malformada")

        with pytest.raises(ClaveFernetAusente):
            cifrar(SECRETO)
