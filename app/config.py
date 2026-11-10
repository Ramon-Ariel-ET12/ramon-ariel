"""Environment-based configuration.

No credentials are hardcoded: every value comes from the environment with a local
development default that is safe because the database is never published outside the
internal plant network.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore",
                                     populate_by_name=True, case_sensitive=False)

    system_name: str = Field("Academia Novit", alias="SISTEMA_NOMBRE")
    database_url: str = Field("postgresql://pia:pia-local-dev@localhost:5432/pia", alias="DATABASE_URL")

    plant_url: str = Field("http://localhost:8100", alias="PLANT_URL")
    mqtt_host: str = Field("localhost", alias="MQTT_HOST")
    mqtt_port: int = Field(1883, alias="MQTT_PORT")
    link_control_url: str = Field("http://localhost:8081", alias="LINK_CONTROL_URL")
    cloud_sync_url: str = Field("http://localhost:8300", alias="CLOUD_SYNC_URL")

    asr_model: str = Field("small", alias="ASR_MODEL")
    asr_threads: int = Field(4, alias="ASR_THREADS")
    asr_beam_size: int = Field(5, alias="ASR_BEAM_SIZE")
    embedding_model: str = Field("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", alias="EMBEDDING_MODEL")
    llm_enabled: bool = Field(False, alias="LLM_ENABLED")
    llm_model: str = Field("Qwen/Qwen2.5-0.5B-Instruct", alias="LLM_MODEL")

    materials_path: Path = Field(ROOT / "datos" / "materiales.yaml", alias="MATERIALS_PATH")
    plant_snapshot_path: Path = Field(ROOT / "datos" / "planta.yaml", alias="PLANT_SNAPSHOT_PATH")
    media_dir: Path = Field(ROOT / "var" / "media", alias="MEDIA_DIR")
    evaluation_dir: Path = Field(ROOT / "evaluacion", alias="EVALUATION_DIR")

    note_timeout_s: float = Field(180.0, alias="NOTE_TIMEOUT_S")
    max_attempts: int = Field(6, alias="MAX_ATTEMPTS")
    max_note_steps: int = Field(8, alias="MAX_NOTE_STEPS")
    token_budget: int = Field(8000, alias="TOKEN_BUDGET")
    heartbeat_seconds: float = Field(30.0, alias="HEARTBEAT_SECONDS")
    sync_batch_size: int = Field(50, alias="SYNC_BATCH_SIZE")
    sync_poll_seconds: float = Field(5.0, alias="SYNC_POLL_SECONDS")
    link_poll_seconds: float = Field(10.0, alias="LINK_POLL_SECONDS")
    ui_port: int = Field(8200, alias="UI_PORT")
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    # The official correction runs one scenario at a time; this lets the operator force
    # human review for an equipment without inventing detection rules.
    forced_pending: dict[str, list[str]] = Field(default_factory=dict, alias="FORCED_PENDING")

    @property
    def proxy(self) -> str:
        import os

        return os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or ""


def get_settings() -> Settings:
    return Settings()
