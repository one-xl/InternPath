import pytest
from unittest.mock import MagicMock

from ai_analyzer import _call_openai_text
from backend.agents.base import BaseAgent
from backend.main import (
    openai_responses_body,
    openai_responses_url,
    serialize_provider_cache_stats,
    wrap_openai_responses_response,
)


class FakeProviderStatusError(Exception):
    def __init__(self, status_code: int, body: dict):
        super().__init__(f"Error code: {status_code} - {body!r}")
        self.status_code = status_code
        self.body = body


def test_openai_responses_url_normalizes_chat_endpoint():
    assert openai_responses_url("https://api.example.com/v1/chat/completions") == "https://api.example.com/v1/responses"
    assert openai_responses_url("https://api.example.com/v1/chat") == "https://api.example.com/v1/responses"
    assert openai_responses_url("https://api.example.com") == "https://api.example.com/v1/responses"


def test_openai_responses_body_maps_gemini_style_request():
    body = openai_responses_body(
        "gpt-test",
        {
            "contents": [{"role": "user", "parts": [{"text": "Return an object."}]}],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": 256,
                "responseMimeType": "application/json",
            },
        },
    )

    assert body["model"] == "gpt-test"
    assert body["temperature"] == 0
    assert body["max_output_tokens"] == 256
    assert body["input"][0]["role"] == "user"
    assert "JSON format" in body["input"][0]["content"]
    assert body["text"]["format"]["type"] == "json_object"


def test_openai_responses_body_adds_prompt_cache_fields():
    body = openai_responses_body(
        "gpt-test",
        {
            "contents": [{"role": "user", "parts": [{"text": "Return an object."}]}],
            "generationConfig": {"temperature": 0},
        },
        prompt_cache_extra={
            "promptCacheKey": "fixed-cache-key",
            "promptCacheRetention": "24h",
        },
    )

    assert body["prompt_cache_key"] == "fixed-cache-key"
    assert body["prompt_cache_retention"] == "24h"


def test_wrap_openai_responses_response_maps_to_gemini_shape():
    wrapped = wrap_openai_responses_response(
        {
            "output_text": "done",
            "status": "completed",
            "usage": {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5},
        }
    )

    assert wrapped["candidates"][0]["content"]["parts"][0]["text"] == "done"
    assert wrapped["candidates"][0]["finishReason"] == "STOP"
    assert wrapped["usageMetadata"]["promptTokenCount"] == 2
    assert wrapped["usageMetadata"]["candidatesTokenCount"] == 3
    assert wrapped["usageMetadata"]["totalTokenCount"] == 5


def test_call_openai_text_uses_responses_api_when_configured():
    client = MagicMock()
    client._internpath_stream_api_mode = "responses"
    client._internpath_prompt_cache_key = "star-cache-key"
    client._internpath_prompt_cache_retention = "24h"
    client.responses.create.return_value = {
        "output_text": "ok",
        "usage": {"input_tokens": 4, "output_tokens": 6, "total_tokens": 10},
    }

    text, usage = _call_openai_text(
        client,
        "gpt-test",
        [
            {"role": "system", "content": "Return JSON."},
            {"role": "user", "content": "ping"},
        ],
        temperature=0,
        response_format={"type": "json_object"},
        max_tokens=123,
    )

    assert text == "ok"
    assert usage == {"prompt_tokens": 4, "completion_tokens": 6, "total_tokens": 10, "cached_tokens": 0}
    kwargs = client.responses.create.call_args.kwargs
    assert kwargs["model"] == "gpt-test"
    assert kwargs["max_output_tokens"] == 123
    assert kwargs["stream"] is True
    assert kwargs["text"]["format"]["type"] == "json_object"
    assert kwargs["prompt_cache_key"] == "star-cache-key"
    assert kwargs["prompt_cache_retention"] == "24h"
    client.chat.completions.create.assert_not_called()


def test_provider_cache_usage_extracts_responses_cached_tokens():
    stats = BaseAgent._extract_provider_cache_usage({
        "usage": {
            "input_tokens": 100,
            "output_tokens": 20,
            "input_tokens_details": {"cached_tokens": 64},
        }
    })

    assert stats["providerCacheAvailable"] is True
    assert stats["providerCacheHit"] is True
    assert stats["providerCachedTokens"] == 64
    assert stats["providerInputTokens"] == 100


def test_provider_cache_usage_extracts_stream_completed_usage():
    stats = BaseAgent._extract_provider_cache_usage({
        "type": "response.completed",
        "response": {
            "usage": {
                "input_tokens": 100,
                "output_tokens": 20,
                "input_tokens_details": {"cached_tokens": 64},
            }
        },
    })

    assert stats["providerCacheAvailable"] is True
    assert stats["providerCacheHit"] is True
    assert stats["providerCachedTokens"] == 64
    assert stats["providerInputTokens"] == 100


def test_provider_cache_stats_are_separate_from_local_reuse():
    summary = serialize_provider_cache_stats([
        {
            "stage": "plan",
            "agent": "AgentPlanner",
            "modelId": "gpt-test",
            "providerCacheAvailable": True,
            "providerCacheHit": True,
            "providerCachedTokens": 64,
            "providerInputTokens": 100,
            "providerEndpointMode": "responses",
            "providerStream": True,
            "providerPromptCacheDisabledReason": "provider_rejected_prompt_cache_fields",
        },
        {
            "stage": "local_reuse",
            "agent": "LocalReuse",
            "cacheHit": True,
            "providerCacheAvailable": False,
        },
    ])

    assert summary["checks"] == 1
    assert summary["hits"] == 1
    assert summary["cachedTokens"] == 64
    assert summary["items"][0]["endpointMode"] == "responses"
    assert summary["items"][0]["stream"] is True
    assert summary["items"][0]["promptCacheDisabledReason"] == "provider_rejected_prompt_cache_fields"


def test_responses_stream_retries_without_prompt_cache_when_provider_rejects_fields():
    client = MagicMock()
    client.responses.create.side_effect = [
        FakeProviderStatusError(
            403,
            {"error": {"message": "openai_error", "type": "bad_response_status_code"}},
        ),
        [
            {"type": "response.output_text.delta", "delta": "ok"},
            {
                "type": "response.completed",
                "response": {
                    "usage": {
                        "input_tokens": 1200,
                        "output_tokens": 2,
                        "input_tokens_details": {"cached_tokens": 0},
                    }
                },
            },
        ],
    ]

    result = BaseAgent._collect_responses_stream_sync(
        client,
        {
            "model": "gpt-test",
            "input": "ping",
            "prompt_cache_key": "cache-key",
            "prompt_cache_retention": "24h",
        },
        model="gpt-test",
        namespace="agent_planner",
    )

    assert result == "ok"
    assert client.responses.create.call_count == 2
    first_kwargs = client.responses.create.call_args_list[0].kwargs
    second_kwargs = client.responses.create.call_args_list[1].kwargs
    assert first_kwargs["stream"] is True
    assert first_kwargs["prompt_cache_key"] == "cache-key"
    assert first_kwargs["prompt_cache_retention"] == "24h"
    assert second_kwargs["stream"] is True
    assert "prompt_cache_key" not in second_kwargs
    assert "prompt_cache_retention" not in second_kwargs
    client.chat.completions.create.assert_not_called()

    stats = BaseAgent.pop_provider_cache_usage(client)
    assert stats["providerEndpointMode"] == "responses"
    assert stats["providerStream"] is True
    assert stats["providerPromptCacheKey"] == ""
    assert stats["providerPromptCacheRetention"] == ""
    assert stats["providerPromptCacheDisabledReason"] == "provider_rejected_prompt_cache_fields"
    assert stats["providerInputTokens"] == 1200


def test_responses_stream_does_not_retry_without_prompt_cache_fields():
    client = MagicMock()
    client.responses.create.side_effect = FakeProviderStatusError(
        403,
        {"error": {"message": "openai_error", "type": "bad_response_status_code"}},
    )

    with pytest.raises(FakeProviderStatusError):
        BaseAgent._collect_responses_stream_sync(
            client,
            {"model": "gpt-test", "input": "ping"},
            model="gpt-test",
            namespace="agent_planner",
        )

    assert client.responses.create.call_count == 1
    assert client.responses.create.call_args.kwargs["stream"] is True
    client.chat.completions.create.assert_not_called()
