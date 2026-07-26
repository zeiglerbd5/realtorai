"""Model routing policy: structured work -> standard tier, review -> Opus tier."""

from realtorai.config.settings import get_settings
from realtorai.inference.model_router import LLMTask, model_for


def test_standard_tier_tasks(offline_env):
    settings = get_settings()
    for task in (LLMTask.EXTRACT, LLMTask.FORM_FILL, LLMTask.CLASSIFY, LLMTask.DRAFT):
        assert model_for(task) == settings.claude_model_standard


def test_review_tier_tasks(offline_env):
    settings = get_settings()
    for task in (LLMTask.VERIFY, LLMTask.DEED_REVIEW):
        assert model_for(task) == settings.claude_model_review


def test_models_configurable_via_env(offline_env, monkeypatch):
    monkeypatch.setenv("CLAUDE_MODEL_REVIEW", "claude-opus-4-8")
    monkeypatch.setenv("CLAUDE_MODEL_STANDARD", "claude-sonnet-5")
    get_settings.cache_clear()
    assert model_for(LLMTask.DEED_REVIEW) == "claude-opus-4-8"
    assert model_for(LLMTask.EXTRACT) == "claude-sonnet-5"


def test_engine_unavailable_without_key(offline_env):
    from realtorai.inference.claude_engine import ClaudeEngine

    assert ClaudeEngine().available is False
