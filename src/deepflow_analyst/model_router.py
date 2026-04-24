"""W11 · Per-role model routing.

A minimal ModelRouter: given an agent role, return the configured model
id, falling back to ``settings.default_model`` when no role-specific
override is set.

Why minimal (no complexity-based routing, no LLM-driven classifier):
- OpenRouter is sensitive to model id; *any* model fanout is an A/B
  decision that must be validated with `deepflow-eval`. Hard-coding a
  heuristic classifier here would bake in assumptions without data.
- Per-role env var overrides are the simplest surface that still
  teaches the multi-agent routing pattern. Learners can wire their own
  complexity classifier in W11+.

Role vocabulary is intentionally small (writer/reviewer/intent/insight)
and matches the 4-role pipeline + intent triage node in graph.py.
"""

from __future__ import annotations

from typing import Literal

from .settings import settings

Role = Literal["writer", "reviewer", "intent", "insight"]

_ROLE_FIELD: dict[Role, str] = {
    "writer": "writer_model",
    "reviewer": "reviewer_model",
    "intent": "intent_model",
    "insight": "insight_model",
}


def resolve_model(role: Role | None) -> str:
    """Return the model id to use for ``role``.

    Falls back to ``settings.default_model`` when ``role`` is ``None`` or
    when the role-specific override is empty. Empty string in an env var
    counts as "unset" so learners can comment out overrides without
    forcing a literal fallback value.
    """
    if role is None:
        return settings.default_model
    field = _ROLE_FIELD.get(role)
    if field is None:
        return settings.default_model
    override: str = getattr(settings, field, "") or ""
    return override or settings.default_model
