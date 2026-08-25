from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path


class Settings(BaseSettings):
    app_name: str = "Synapse-Mesh (Exocortex)"
    app_version: str = "0.1.0-beta"
    mcp_protocol_version: str = "2026-07-28"
    domain: str = "synapsemesh.dev"
    base_url: str = "https://synapsemesh.dev"
    canonical_mcp_url: str = "https://mcp.synapsemesh.dev"
    environment: str = "production"
    log_level: str = "INFO"
    
    # Database
    db_path: str = "data/synapse_mesh.sqlite3"
    
    # Security
    admin_token: str = ""
    ops_password: str = "synapse-ops-2026"
    
    # CORS
    cors_origins: list[str] = ["*"]

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()

# Ensure data directory exists
Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
