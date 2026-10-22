"""Tests for Groq LLM fallback."""


def test_groq_fallback_on_exception(monkeypatch):
    from backend.config import settings
    from backend.services import llm_client

    settings.groq_api_key = "dummy-key"
    llm_client._disabled_until = 0.0

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr("httpx.post", boom)

    result = llm_client.call_llm("system", "user prompt")
    assert result.startswith("[LLM unavailable - template fallback]")