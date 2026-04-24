import pytest

from deepflow_analyst import model_router
from deepflow_analyst import settings as _settings
from deepflow_analyst.llm_client import _langfuse_enabled


def test_resolve_model_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_settings.settings, "default_model", "default/model")
    monkeypatch.setattr(_settings.settings, "writer_model", "")
    monkeypatch.setattr(_settings.settings, "reviewer_model", "")
    monkeypatch.setattr(_settings.settings, "intent_model", "")
    monkeypatch.setattr(_settings.settings, "insight_model", "")

    assert model_router.resolve_model(None) == "default/model"
    assert model_router.resolve_model("writer") == "default/model"
    assert model_router.resolve_model("reviewer") == "default/model"
    assert model_router.resolve_model("intent") == "default/model"
    assert model_router.resolve_model("insight") == "default/model"


def test_resolve_model_honors_per_role_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_settings.settings, "default_model", "default/model")
    monkeypatch.setattr(_settings.settings, "writer_model", "w/model")
    monkeypatch.setattr(_settings.settings, "insight_model", "i/model")
    monkeypatch.setattr(_settings.settings, "reviewer_model", "")
    monkeypatch.setattr(_settings.settings, "intent_model", "")

    assert model_router.resolve_model("writer") == "w/model"
    assert model_router.resolve_model("insight") == "i/model"
    # Unset ones still fall through to default.
    assert model_router.resolve_model("reviewer") == "default/model"
    assert model_router.resolve_model("intent") == "default/model"


def test_langfuse_disabled_when_keys_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_settings.settings, "langfuse_public_key", "")
    monkeypatch.setattr(_settings.settings, "langfuse_secret_key", "")
    assert _langfuse_enabled() is False


def test_langfuse_enabled_needs_both_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_settings.settings, "langfuse_public_key", "pk-xxx")
    monkeypatch.setattr(_settings.settings, "langfuse_secret_key", "")
    assert _langfuse_enabled() is False  # public only is not enough

    monkeypatch.setattr(_settings.settings, "langfuse_public_key", "pk-xxx")
    monkeypatch.setattr(_settings.settings, "langfuse_secret_key", "sk-xxx")
    assert _langfuse_enabled() is True
