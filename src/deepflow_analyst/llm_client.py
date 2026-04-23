from openai import AsyncOpenAI

from .settings import settings


def get_client() -> AsyncOpenAI:
    if not settings.openrouter_api_key:
        raise RuntimeError("OPENROUTER_API_KEY not set. Copy .env.example to .env and fill it in.")
    return AsyncOpenAI(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
    )


async def chat(messages: list[dict[str, str]], model: str | None = None) -> str:
    client = get_client()
    resp = await client.chat.completions.create(
        model=model or settings.default_model,
        messages=messages,  # type: ignore[arg-type]
    )
    return resp.choices[0].message.content or ""
