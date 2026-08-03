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
