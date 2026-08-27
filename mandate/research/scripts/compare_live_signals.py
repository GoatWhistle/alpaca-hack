from __future__ import annotations

import argparse
import json

from mandate_research.live_comparison import compare_live_signals


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare MANDATE signals on live Alpaca data")
    parser.add_argument("--symbol", default="AAPL")
    parser.add_argument("--fee-bps", default="1")
    args = parser.parse_args()
    print(
        json.dumps(
            compare_live_signals(symbol=args.symbol, fee_bps=args.fee_bps),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
