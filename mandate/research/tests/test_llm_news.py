from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from mandate_research import llm_news
from mandate_research.llm_news import gate_news_batch_llm
from mandate_research.news import NewsEvent
from mandate_research.news_graph import NewsGraphStore


def _event(external_id: str = "1") -> NewsEvent:
    return NewsEvent(
        "alpaca",
        external_id,
        datetime(2026, 8, 27, tzinfo=timezone.utc),
        "Company beats estimates but cuts full-year guidance",
        "Management cited weaker demand.",
        ("AAPL",),
    )


@pytest.fixture(autouse=True)
def clear_gate_cache() -> None:
    llm_news._CACHE.clear()


def _response_for(payload: dict, *, decision: str = "PASS", reason: str = "Concrete guidance update") -> dict:
    request = json.loads(payload["messages"][1]["content"])["items"][0]
    return {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "items": [{
                        "schema": "news.gate.response.v1",
                        "request_id": request["request_id"],
                        "reason": reason,
                        "decision": decision,
                    }]
                })
            }
        }]
    }


def test_gate_uses_narrow_versioned_request_and_response(monkeypatch) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "test-token")

    def post(url, headers, payload):
        assert url == "https://api.z.ai/api/coding/paas/v4/chat/completions"
        assert headers["Authorization"] == "Bearer test-token"
        assert "untrusted" in payload["messages"][0]["content"]
        request = json.loads(payload["messages"][1]["content"])["items"][0]
        assert list(request) == [
            "schema", "request_id", "story_id", "target_symbols", "published_at",
            "source_count", "headline", "summary",
        ]
        assert request["schema"] == "news.gate.request.v1"
        assert request["target_symbols"] == ["AAPL"]
        return _response_for(payload)

    result = gate_news_batch_llm([_event()], symbol="AAPL", poster=post)[0]
    assert list(result) == ["schema", "request_id", "reason", "decision"]
    assert result["schema"] == "news.gate.response.v1"
    assert result["decision"] == "PASS"


def test_missing_credentials_is_error_not_skip_and_recovers(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    store = NewsGraphStore(tmp_path / "news.db")

    result = gate_news_batch_llm([_event("missing-key")], symbol="AAPL", store=store)[0]

    assert result["schema"] == "news.gate.error.v1"
    assert result["error_type"] == "ConfigurationError"
    assert result["retryable"] is False
    assert "decision" not in result
    assert store.gate_attempts(result["request_id"]) == []
    replay = gate_news_batch_llm([_event("missing-key")], symbol="AAPL", store=store)[0]
    assert replay == result
    assert store.gate_attempts(result["request_id"]) == []

    monkeypatch.setenv("ZAI_API_KEY", "restored-token")
    recovered = gate_news_batch_llm(
        [_event("missing-key")], symbol="AAPL", store=store,
        poster=lambda _url, _headers, payload: _response_for(payload),
    )[0]
    assert recovered["decision"] == "PASS"
    assert store.gate_attempts(result["request_id"])[0]["state"] == "COMPLETED"


def test_invalid_model_shape_is_retryable_error(monkeypatch) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "test-token")

    def post(_url, _headers, payload):
        response = _response_for(payload)
        decoded = json.loads(response["choices"][0]["message"]["content"])
        decoded["items"][0]["score"] = 0.9
        response["choices"][0]["message"]["content"] = json.dumps(decoded)
        return response

    result = gate_news_batch_llm([_event("invalid-shape")], symbol="AAPL", poster=post)[0]
    assert result["schema"] == "news.gate.error.v1"
    assert result["retryable"] is True
    assert "decision" not in result


def test_retry_is_a_second_persisted_attempt(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "test-token")
    store = NewsGraphStore(tmp_path / "news.db")
    calls = 0

    def post(_url, _headers, payload):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("temporary timeout")
        return _response_for(payload, decision="SKIP", reason="Generic commentary")

    first = gate_news_batch_llm([_event("retry")], symbol="AAPL", poster=post, store=store)[0]
    second = gate_news_batch_llm([_event("retry")], symbol="AAPL", poster=post, store=store)[0]

    assert first["schema"] == "news.gate.error.v1"
    assert second["decision"] == "SKIP"
    assert store.gate_attempts(first["request_id"]) == [
        {
            "attempt_no": 1, "state": "ERROR", "reason": "TimeoutError: gate unavailable",
            "decision": None, "error_type": "TimeoutError", "retryable": 1,
        },
        {
            "attempt_no": 2, "state": "COMPLETED", "reason": "Generic commentary",
            "decision": "SKIP", "error_type": None, "retryable": 0,
        },
    ]
    assert calls == 2


def test_gate_rejects_non_official_endpoint(monkeypatch) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "test-token")
    monkeypatch.setenv("ZAI_BASE_URL", "https://example.com/v4")
    result = gate_news_batch_llm([_event("bad-endpoint")], symbol="AAPL", poster=lambda *_: {})[0]
    assert result["schema"] == "news.gate.error.v1"
    assert result["error_type"] == "ValueError"
    assert "decision" not in result


def test_gate_bounds_batch_size() -> None:
    events = [_event(f"batch-{index}") for index in range(llm_news.MAX_ITEMS + 1)]
    with pytest.raises(ValueError, match=f"at most {llm_news.MAX_ITEMS}"):
        gate_news_batch_llm(events, symbol="AAPL")
