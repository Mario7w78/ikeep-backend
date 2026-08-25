"""Cifrado del refresh_token de Google en reposo.

El refresh token es la llave del calendario de alguien para siempre: en la
base no puede estar en claro, y el que cifra no es el mismo que guarda. La
clave vive en una variable de entorno (GOOGLE_TOKEN_FERNET_KEY) y no se
deriva de otro secreto, porque rotarla no deberia pedir cambiar nada mas.

Rotacion: mientras se cambia la clave, la vieja queda en
GOOGLE_TOKEN_FERNET_KEY_PREV. Al leer un token cifrado con ella se descifra,
se re-cifra con la nueva y el llamador lo vuelve a guardar; cuando ya no
quede nada cifrado con la clave previa, se quita la variable y listo.
"""

from cryptography.fernet import Fernet, InvalidToken

from infrastructure.config.settings import get_settings


class ClaveFernetAusente(RuntimeError):
    """No hay clave configurada: guardar o leer tokens es imposible.

    Es un error de despliegue y viaja como tal — no como un fallo raro de
    red que invite a reintentar.
    """


def _fernet_de(clave: str) -> Fernet:
    try:
        return Fernet(clave.encode())
    except (ValueError, TypeError) as exc:
        raise ClaveFernetAusente(
            f"La clave Fernet '{clave[:8]}...' no es valida ({exc}). "
            "Genera una con cryptography.Fernet.generate_key()."
        ) from exc


def _vigente() -> Fernet:
    settings = get_settings()
    if not settings.GOOGLE_TOKEN_FERNET_KEY:
        raise ClaveFernetAusente(
            "Falta GOOGLE_TOKEN_FERNET_KEY: sin ella no se pueden cifrar "
            "los refresh tokens de Google."
        )
    return _fernet_de(settings.GOOGLE_TOKEN_FERNET_KEY)


def _claves_en_orden() -> list[Fernet]:
    """La vigente primero, la previa despues: se cifra con la primera."""
    claves = [_vigente()]
    previa = get_settings().GOOGLE_TOKEN_FERNET_KEY_PREV
    if previa:
        claves.append(_fernet_de(previa))
    return claves


def cifrar(texto: str) -> str:
    # Solo la vigente: la previa existe para LEER lo viejo, no para escribir
    # mas cosas con una clave que ya se esta reemplazando.
    return _vigente().encrypt(texto.encode()).decode()


def descifrar(token_cifrado: str) -> str:
    """Descifra probando cada clave, de la vigente hacia atras."""
    for fernet in _claves_en_orden():
        try:
            return fernet.decrypt(token_cifrado.encode()).decode()
        except InvalidToken:
            continue
    raise ClaveFernetAusente(
        "El token guardado no se descifra con ninguna clave conocida: "
        "probablemente se rotaron las claves perdiendo la anterior. El "
        "usuario tendra que conectar Google de nuevo."
    )


def fue_con_clave_anterior(token_cifrado: str) -> bool:
    """True si este token todavia esta cifrado con la clave previa.

    Quien lee un token lo consulta para re-cifrarlo con la clave vigente
    antes de volverlo a guardar: asi la rotacion termina sola.
    """
    settings = get_settings()
    try:
        _vigente().decrypt(token_cifrado.encode())
        return False  # La clave vigente alcanza: no hace falta nada.
    except InvalidToken:
        pass

    if not settings.GOOGLE_TOKEN_FERNET_KEY_PREV:
        raise ClaveFernetAusente(
            "El token guardado no se descifra con ninguna clave conocida."
        )
    try:
        _fernet_de(settings.GOOGLE_TOKEN_FERNET_KEY_PREV).decrypt(
            token_cifrado.encode()
        )
        return True
    except InvalidToken:
        raise ClaveFernetAusente(
            "El token guardado no se descifra con ninguna clave conocida."
        )
