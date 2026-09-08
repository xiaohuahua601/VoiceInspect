from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "VoiceInspect"
    app_env: str = "development"
    host: str = "127.0.0.1"
    port: int = 8000
    database_url: str = "sqlite:///./data/db/voiceinspect.db"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_llm_model: str = "qwen2.5:7b-instruct-q4_K_M"
    ollama_embed_model: str = "quentinz/bge-large-zh-v1.5:latest"
    ollama_vision_model: str | None = None
    ollama_timeout_seconds: float = 90.0
    ollama_num_threads: int = 4
    ollama_num_ctx: int = 2048
    ollama_llm_num_predict: int = 512
    ollama_vision_num_predict: int = 256
    vision_image_max_size: int = 1024
    vision_anomaly_second_pass: bool = False
    stt_model_size: str = "small"
    stt_device: str = "cpu"
    stt_compute_type: str = "int8"
    stt_model_path: str | None = None
    max_audio_seconds: int = 120
    max_image_pixels: int = 20000000
    confirmation_ttl_seconds: int = 600
    piper_executable: str = "piper"
    piper_voice: str = ""
    upload_dir: Path = Path("./data/uploads")
    knowledge_dir: Path = Path("./data/knowledge")
    log_dir: Path = Path("./data/logs")
    max_upload_bytes: int = 10 * 1024 * 1024
    access_token_minutes: int = 720
    access_token_secret: str = "voiceinspect-development-secret-change-me"
    cors_allowed_origins: str = "http://127.0.0.1:5173,http://localhost:5173"
    login_max_attempts: int = 5
    login_lockout_seconds: int = 60
    max_active_sessions_per_user: int = 5
    auto_create_schema: bool = True
    seed_demo_data_enabled: bool = True
    demo_operator_username: str = "operator"
    demo_operator_password: str = "change-me"
    demo_admin_username: str = "admin"
    demo_admin_password: str = "change-me-admin"
    demo_supervisor_username: str = "supervisor"
    demo_supervisor_password: str = "change-me-supervisor"
    demo_knowledge_admin_username: str = 'knowledge-admin'
    demo_knowledge_admin_password: str = 'change-me-knowledge'

    model_config = SettingsConfigDict(env_file=".env", env_prefix="", case_sensitive=False, extra="ignore")

    def ensure_directories(self) -> None:
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        Path("./data/db").mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
