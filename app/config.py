from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: str = "gemini"  # gemini | claude | local
    llm_max_parallel: int = 2     # parallel AI requests (free-tier keys: keep low)
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-flash-latest"   # or gemini-pro-latest for best accuracy
    anthropic_api_key: str | None = None
    claude_model: str = "claude-opus-5-5"
    claude_fast_model: str = "claude-haiku-5-5"
    local_base_url: str = "http://localhost:8001/v1"
    local_model: str = "Qwen/Qwen2.5-VL-32B-Instruct"

    rules_dir: Path = Path("knowledge/rules")
    compiled_rules: Path = Path("knowledge/compiled/rules.json")
    designs_dir: Path = Path("designs")


settings = Settings()
