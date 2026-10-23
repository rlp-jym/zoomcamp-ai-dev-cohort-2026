"""Tests for LLM template fallback."""


def test_template_fallback_string():
    from backend.services.llm_client import _template_fallback

    out = _template_fallback("hello world")
    assert out.startswith("[LLM unavailable - template fallback]")
    assert "hello world" in out
