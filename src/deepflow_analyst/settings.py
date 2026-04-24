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

    # Z · stability sampling. sample_size > 1 开启「self-consistency」：Writer
    # 以 sample_temperature 采样 K 次 → 各自 Reviewer+Execute → 按结果集多数
    # 投票。目的是吸收 OpenRouter 上游路由的 ±5pp 噪声，让 EVAL_THRESHOLD 能
    # 抬高到基线附近。sample_size=1 完全等价原单次路径（零开销）。
    sample_size: int = 1
    sample_temperature: float = 0.5

    # X · few-shot RAG. rag_enabled=True 时 Writer 从本地 BM25 example bank 里
    # 检索 top-K 相似的 (question, sql) 对，注入 system prompt 作为 precedent，
    # 让 LLM 在 hard 结构性 pattern 上（self-join / DISTINCT ON / 多表 join
    # chain）有可模仿的参考答案。bank 独立于 golden dataset，严禁重叠。
    rag_enabled: bool = True
    rag_top_k: int = 3

    # W11 · Langfuse tracing（可选）。三个 key 都配齐才启用；任何一个缺就
    # graceful no-op（保持 v0.4 行为，不影响 eval / CI）。LANGFUSE_HOST 默认
    # 是 Langfuse Cloud；自建 instance 在 .env 里覆写。
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # W11 · ModelRouter（per-role model overrides）。任何一个空字符串代表
    # fallback 到 `default_model`。教学意图：同一套 LangGraph pipeline，通过
    # env var 做 A/B（例如 Writer 用 deepseek、Insight 换 kimi-k2）。
    writer_model: str = ""
    reviewer_model: str = ""
    intent_model: str = ""
    insight_model: str = ""

    database_url: str = "postgresql+psycopg://deepflow:deepflow@localhost:5432/deepflow"


settings = Settings()
