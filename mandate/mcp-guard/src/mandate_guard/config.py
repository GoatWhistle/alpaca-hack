from __future__ import annotations

from urllib.parse import urlparse


PAPER_HOST = "paper-api.alpaca.markets"


def validate_paper_base_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname != PAPER_HOST:
        raise ValueError(
            "ALPACA_BASE_URL must be exactly the Alpaca paper-trading HTTPS host"
        )
    if parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment:
        raise ValueError("ALPACA_BASE_URL must not contain credentials, a port, query, or fragment")
    if parsed.path not in {"", "/"}:
        raise ValueError("ALPACA_BASE_URL must not contain an API path")
    return f"https://{PAPER_HOST}"
