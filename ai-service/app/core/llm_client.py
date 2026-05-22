"""OpenAI-compatible chat client for optional evidence-grounded generation."""

from __future__ import annotations

import httpx

from app.core.config import Settings


class LLMConfigurationError(RuntimeError):
    """Raised when LLM settings are missing or still placeholders."""


class LLMRequestError(RuntimeError):
    """Raised when the provider request fails or returns an unexpected payload."""


def _chat_completions_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/chat/completions"


def build_evidence_messages(question: str, citations: list[dict]) -> list[dict]:
    evidence = "\n\n".join(
        f"[{item['index']}] Source: {item['original_filename']} / chunk {item['chunk_index']}\n"
        f"{item['text_preview']}"
        for item in citations
    )
    return [
        {
            "role": "system",
            "content": (
                "你是一个严谨的检索增强问答助手。只能依据给定证据回答。"
                "关键结论必须带引用编号，例如 [1]。如果证据不足，明确说明无法回答。"
            ),
        },
        {
            "role": "user",
            "content": f"问题：{question}\n\n证据：\n{evidence}",
        },
    ]


def generate_evidence_answer(question: str, citations: list[dict]) -> str:
    """Call an OpenAI-compatible chat endpoint when configured."""
    if Settings.LLM_API_KEY.strip() in {
        "",
        "your_api_key_here",
        "your_deepseek_or_openai_api_key_here",
    }:
        raise LLMConfigurationError("LLM_API_KEY is not configured")

    payload = {
        "model": Settings.LLM_MODEL,
        "messages": build_evidence_messages(question, citations),
        "temperature": 0.2,
    }
    headers = {
        "Authorization": f"Bearer {Settings.LLM_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=Settings.LLM_TIMEOUT) as client:
            response = client.post(
                _chat_completions_url(Settings.LLM_BASE_URL),
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        raise LLMRequestError(f"LLM API request failed: {exc}") from exc
    except ValueError as exc:
        raise LLMRequestError("LLM API returned invalid JSON") from exc

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMRequestError("LLM API response missing choices[0].message.content") from exc
    if not isinstance(content, str) or not content.strip():
        raise LLMRequestError("LLM API returned an empty answer")
    return content.strip()

