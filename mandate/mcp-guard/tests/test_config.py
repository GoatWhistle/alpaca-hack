import pytest

from mandate_guard.config import validate_paper_base_url


def test_accepts_only_canonical_paper_url() -> None:
    assert validate_paper_base_url("https://paper-api.alpaca.markets/") == (
        "https://paper-api.alpaca.markets"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://api.alpaca.markets",
        "http://paper-api.alpaca.markets",
        "https://paper-api.alpaca.markets.evil.example",
        "https://paper-api.alpaca.markets/v2",
        "https://user:pass@paper-api.alpaca.markets",
    ],
)
def test_rejects_live_or_noncanonical_urls(url: str) -> None:
    with pytest.raises(ValueError, match="ALPACA_BASE_URL"):
        validate_paper_base_url(url)
