from __future__ import annotations

import argparse
import json

from mandate_research.live_sources import probe_live_sources


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe live bounded MANDATE news sources")
    parser.add_argument("--symbol", default="AAPL")
    parser.add_argument("--cik", default="0000320193")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            probe_live_sources(symbol=args.symbol, cik=args.cik, strict=args.strict),
            default=str,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
