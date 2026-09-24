from functools import lru_cache
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "agro-asistente"
    app_env: str = "development"
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "postgres"
    postgres_password: str = ""
    postgres_database: str = "agro_asistente"

    jwt_secret: str = "change-me-in-local-env-do-not-use-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 120

    knowledge_dir: str = "../knowledge"

    chroma_persist_dir: str = "./chroma_data"
    chroma_collection: str = "agro_knowledge_pmv1"

    rag_top_k: int = 3
    rag_min_similarity: float = 0.12
    chunk_size: int = 500

    embedding_provider: str = "local"
    embedding_dimension: int = 128
    embedding_api_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = ""

    generation_provider: str = "ollama"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:1.5b"
    ollama_timeout_seconds: int = 90

    senamhi_wis2_base_url: str = "https://wis.senamhi.gob.pe/oapi"
    senamhi_wis2_collection: str = "urn:wmo:md:pe-senamhi:synop-hourly"
    senamhi_wis2_timeout_seconds: int = 20

    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def postgres_url(self) -> str:
        user = quote_plus((self.postgres_user or "").strip())
        password = quote_plus(self.postgres_password) if self.postgres_password else ""
        host = (self.postgres_host or "localhost").strip()
        database = (self.postgres_database or "").strip()

        if password:
            auth = f"{user}:{password}"
        else:
            auth = user

        return (
            f"postgresql+psycopg://{auth}@{host}:{self.postgres_port}/"
            f"{database}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
