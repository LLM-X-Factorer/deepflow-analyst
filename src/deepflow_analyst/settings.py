from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "dev"
    app_port: int = 8000

    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # 默认选 deepseek/deepseek-v3.2 的原因（基于 tests/golden 的 7 条评估对比）：
    # - 地区鲁棒：deepseek 对所有区域开放，不会像 Anthropic 那样触发 403 provider-ToS
    # - 成本最低：$0.25 input / $0.38 output 每 M token
    # - 质量可用：Text-to-SQL 任务首轮评估 4/7（57%）> minimax-m2.7 的 3/7（43%）
    # 若想试其他模型，直接在 .env 里覆盖 DEFAULT_MODEL 即可。
    # W11 的 ModelRouter 会按复杂度自动分流。
    default_model: str = "deepseek/deepseek-v3.2"

    # 0.0 让 SQL 生成和评估稳定、可比较。生产里解读阶段可以调高一点让话术
    # 更自然（W11 的 ModelRouter 会按任务分配不同 temperature）。
    default_temperature: float = 0.0

    database_url: str = "postgresql+psycopg://deepflow:deepflow@localhost:5432/deepflow"


settings = Settings()
