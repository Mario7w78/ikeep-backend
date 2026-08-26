from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./ikeep.db"
    ROUTES_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    CEREBRAS_API_KEY: str = ""
    MISTRAL_API_KEY: str = ""
    SCHEDULER_TIMEOUT: int = 5

    LOG_LEVEL: str = "INFO"
    # Comma-separated list of allowed origins, or "*" for any.
    CORS_ORIGINS: str = "*"
    # Requests per minute per IP on the /parse-nl* endpoints. 0 disables.
    RATE_LIMIT_PER_MINUTE: int = 20

    # Supabase. The backend reaches the database through PostgREST rather than
    # a direct Postgres connection: the container sleeps on the free tier, and
    # a connection pool does not survive that cycle cleanly. Going through the
    # REST API also keeps row-level security in force, since every query runs
    # with the caller's own JWT instead of a privileged service role.
    SUPABASE_URL: str = ""
    # The client-safe key ("publishable" in newer projects, "anon" in older
    # ones). It grants nothing on its own — RLS is what scopes the data.
    SUPABASE_ANON_KEY: str = ""
    # Only used by projects that still sign with the legacy HS256 shared
    # secret. Newer ones sign asymmetrically and are verified through JWKS,
    # which needs no secret at all.
    SUPABASE_JWT_SECRET: str = ""
    # Clave de servicio: saltea RLS. SOLO para escrituras que llegan sin
    # credenciales de usuario —hoy, una sola: el upsert de google_tokens en
    # el callback OAuth del navegador—. Si suma un segundo uso, revisar si
    # conviene un endpoint con el JWT del usuario.
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    # Checking the schema costs one request per table against the live
    # project. Wanted in production, unwanted in tests, which must not depend
    # on the network.
    VERIFY_SCHEMA_ON_STARTUP: bool = True

    # Google Calendar (lectura sola, calendario primario). Vacias = la
    # integracion esta apagada: los endpoints devuelven un error de
    # configuracion distinguible en vez de fallar a media llamada.
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    # Clave Fernet para el refresh_token en reposo, formato
    # `cryptography.Fernet.generate_key()`. Sin ella no se guardan conexiones.
    GOOGLE_TOKEN_FERNET_KEY: str = ""
    # La clave ANTERIOR, solo para leer tokens cifrados con ella mientras
    # dura una rotacion. Al leer con la clave vieja se re-cifra con la nueva,
    # asi que puede quitarse cuando ya quede nadie cifrado con ella.
    GOOGLE_TOKEN_FERNET_KEY_PREV: str = ""
    # Firma el `state` del OAuth (HS256). El callback llega desde el
    # navegador sin JWT de Supabase, asi que el estado tiene que valerse solo.
    GOOGLE_STATE_SECRET: str = ""
    # La URL exacta que Google debe llamar de vuelta. Vacia = se deriva del
    # request (suficiente en local); en produccion conviene fijarla porque
    # el proxy no siempre deja pasar el esquema real.
    GOOGLE_REDIRECT_URI: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    class Config:
        env_file = ".env"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
