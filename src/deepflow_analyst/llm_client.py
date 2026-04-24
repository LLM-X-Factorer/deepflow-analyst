"""OpenRouter client wrapper with optional Langfuse tracing.

When ``LANGFUSE_PUBLIC_KEY`` and ``LANGFUSE_SECRET_KEY`` are set, the
``langfuse.openai`` drop-in AsyncOpenAI is used: it is wire-compatible
with the standard OpenAI SDK but each ``chat.completions.create`` call
is auto-traced to Langfuse. When the keys are missing, we import the
plain ``openai.AsyncOpenAI`` so no tracing-side dependency runs in the
hot path — tests and local dev behave identically to v0.4.

``chat`` accepts an optional ``role`` kwarg. It is threaded into the
Langfuse generation name so the Langfuse UI shows Writer / Reviewer /
Insight / Intent calls as distinct generations. When Langfuse is off,
``role`` is purely informational and passed nowhere downstream.
"""

from typing import Any

from .model_router import Role, resolve_model
from .settings import settings


def _langfuse_enabled() -> bool:
    return bool(settings.langfuse_public_key and settings.langfuse_secret_key)


def _build_client() -> Any:
    if _langfuse_enabled():
        # Not a typed public re-export in langfuse==4.x; runtime-only import.
        from langfuse.openai import AsyncOpenAI as LFAsyncOpenAI  # type: ignore[attr-defined]

        return LFAsyncOpenAI(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
        )
    from openai import AsyncOpenAI

    return AsyncOpenAI(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
    )


def get_client() -> Any:
    if not settings.openrouter_api_key:
        raise RuntimeError("OPENROUTER_API_KEY not set. Copy .env.example to .env and fill it in.")
    return _build_client()


async def chat(
    messages: list[dict[str, str]],
    model: str | None = None,
    temperature: float | None = None,
    role: Role | None = None,
) -> str:
    client = get_client()
    resolved_model = model or resolve_model(role)
    resolved_temp = temperature if temperature is not None else settings.default_temperature

    extra: dict[str, Any] = {}
    if role and _langfuse_enabled():
        # Langfuse's OpenAI wrapper picks up `name` to label the generation.
        # Plain openai rejects unknown kwargs, so only pass when enabled.
        extra["name"] = f"llm:{role}"

    resp = await client.chat.completions.create(
        model=resolved_model,
        messages=messages,
        temperature=resolved_temp,
        **extra,
    )
    return resp.choices[0].message.content or ""
