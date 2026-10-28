from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = ""
    redis_url: str = "redis://redis:6379/0"
    secret_key: str = ""
    admin_password: str = ""
    frontend_url: str = "http://localhost:3000"
    timezone: str = ""
    scan_retention_days: int = 0
    auto_verify: bool = False
    auto_link_check: bool = False
    microsoft_client_id: str = ""
    microsoft_client_secret: str = ""
    microsoft_tenant: str = "consumers"
    google_client_id: str = ""
    google_client_secret: str = ""
    llm_provider: str = "openai"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "llama3"
    scan_batch_size: int = 50
    dry_run: bool = True

    class Config:
        env_file = ".env"

settings = Settings()
