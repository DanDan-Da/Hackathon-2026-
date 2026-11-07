from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: str = "gemini"  # gemini | claude | local
    llm_max_parallel: int = 2     # parallel AI requests (free-tier keys: keep low)
    llm_max_rpm: int = 0          # AI requests per minute (0 = unlimited). Free-tier Gemini: 4
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.8-flash"   # free tier: 20 requests/day per model; -latest aliases do not work
    anthropic_api_key: str | None = None
    claude_model: str = "claude-opus-5-5"
    claude_fast_model: str = "claude-haiku-5-5"
    local_base_url: str = "http://localhost:8001/v1"
    local_model: str = "Qwen/Qwen2.5-VL-32B-Instruct"

    rules_dir: Path = Path("knowledge/rules")
    compiled_rules: Path = Path("knowledge/compiled/rules.json")
    designs_dir: Path = Path("designs")
    index_dir: Path = Path("knowledge/index")   # on-disk Qdrant (local mode)
    embedding_model: str = "BAAI/bge-m3"


settings = Settings()
