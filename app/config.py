from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: str = "claude"  # claude | local
    anthropic_api_key: str | None = None
    claude_model: str = "claude-opus-5-5"
    claude_fast_model: str = "claude-haiku-5-5"
    local_base_url: str = "http://localhost:8001/v1"
    local_model: str = "Qwen/Qwen2.5-VL-32B-Instruct"

    rules_dir: Path = Path("knowledge/rules")
    compiled_rules: Path = Path("knowledge/compiled/rules.json")
    designs_dir: Path = Path("designs")


settings = Settings()
