"""Groq LLM client with template fallback.

Primary path: call Groq's chat-completions API using ``GROQ_API_KEY``.
Fallback: if the key is missing or the API call fails, return a
deterministic template string so the pipeline can continue without
interruption.
"""

import logging

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "llama-3.3-70b-versatile"


def _template_fallback(prompt: str) -> str:
    """Return a deterministic template string when LLM is unavailable."""
    return (
        "[LLM unavailable — template fallback] "
        f"Agent task received: {prompt[:200]}"
    )


def call_llm(
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
    temperature: float = 0.2,
) -> str:
    """Call Groq LLM with a system and user prompt.

    Args:
        system_prompt: System-level instruction (e.g. a SKILL.md).
        user_prompt: The task-specific context / question.
        model: Override the default model name.
        temperature: Sampling temperature.

    Returns:
        The LLM's response text, or a template fallback string if the
        API key is missing or the request fails.
    """
    if not settings.groq_api_key:
        logger.warning("GROQ_API_KEY not set — using template fallback.")
        return _template_fallback(user_prompt)

    model = model or _DEFAULT_MODEL
    try:
        resp = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.groq_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": temperature,
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as exc:
        logger.warning("Groq API call failed (%s) — using template fallback.", exc)
        return _template_fallback(user_prompt)
