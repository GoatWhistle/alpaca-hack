from __future__ import annotations

from datetime import datetime, timezone

from mandate_research.llm_news import score_news_batch_llm
from mandate_research.news import NewsEvent


def _event() -> NewsEvent:
    return NewsEvent(
        "alpaca", "1", datetime(2026, 8, 27, tzinfo=timezone.utc),
        "Company beats estimates but cuts full-year guidance",
        "Management cited weaker demand.", ("AAPL",),
    )


def test_llm_scorer_validates_bounded_structured_output(monkeypatch) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "test-token")

    def post(url, headers, payload):
        assert url == "https://api.z.ai/api/coding/paas/v4/chat/completions"
        assert headers["Authorization"] == "Bearer test-token"
        assert "untrusted" in payload["messages"][0]["content"]
        return {"choices": [{"message": {"content": '{"items":[{"id":0,"score":-0.7,"confidence":0.9,"event_type":"guidance","horizon":"multiday","novelty_48h":0.8,"reason":"Guidance cut dominates the earnings beat"}]}'}}]}

    result = score_news_batch_llm([_event()], symbol="AAPL", poster=post)[0]
    assert result["available"] is True
    assert result["score"] == "-0.7"
    assert result["confidence"] == "0.9"


def test_llm_scorer_fails_closed_without_credentials(monkeypatch) -> None:
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    result = score_news_batch_llm([
        NewsEvent("alpaca", "missing-key", datetime(2026, 8, 27, tzinfo=timezone.utc), "Headline")
    ], symbol="AAPL")[0]
    assert result["available"] is False
    assert result["score"] == "0"


def test_llm_scorer_fails_closed_on_invalid_model_range(monkeypatch) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "test-token")

    def post(url, headers, payload):
        return {
            "choices": [{
                "message": {
                    "content": (
                        '{"items":[{"id":0,"score":1.2,"confidence":0.9,'
                        '"event_type":"guidance","horizon":"multiday",'
                        '"novelty_48h":0.8,"reason":"Out of range"}]}'
                    )
                }
            }]
        }

    event = NewsEvent(
        "alpaca", "invalid-range", datetime(2026, 8, 27, tzinfo=timezone.utc),
        "Invalid range fixture", symbols=("AAPL",),
    )
    result = score_news_batch_llm([event], symbol="AAPL", poster=post)[0]
    assert result["available"] is False
    assert result["score"] == "0"


def test_llm_scorer_rejects_non_official_endpoint(monkeypatch) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "test-token")
    monkeypatch.setenv("ZAI_BASE_URL", "https://example.com/v4")
    event = NewsEvent(
        "alpaca", "bad-endpoint", datetime(2026, 8, 27, tzinfo=timezone.utc),
        "Endpoint validation fixture", symbols=("AAPL",),
    )
    result = score_news_batch_llm([event], symbol="AAPL", poster=lambda *_: {})[0]
    assert result["available"] is False
    assert "ValueError" in result["reason"]


def test_llm_scorer_bounds_batch_size() -> None:
    events = [
        NewsEvent(
            "alpaca", f"batch-{index}", datetime(2026, 8, 27, tzinfo=timezone.utc),
            f"Batch fixture {index}", symbols=("AAPL",),
        )
        for index in range(21)
    ]
    try:
        score_news_batch_llm(events, symbol="AAPL")
    except ValueError as exc:
        assert "at most 20" in str(exc)
    else:
        raise AssertionError("oversized LLM batch was accepted")
