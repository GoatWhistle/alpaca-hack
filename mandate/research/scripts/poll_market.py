from __future__ import annotations

import argparse
import json

from mandate_research.monitoring import collect_market_monitoring


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect Alpaca monitoring context")
    parser.add_argument("--symbols", required=True)
    parser.add_argument("--feed", default="auto")
    parser.add_argument("--discovery", choices=("true", "false"), default="true")
    parser.add_argument("--discovery-top", type=int, default=10)
    parser.add_argument("--corporate-actions", choices=("true", "false"), default="true")
    parser.add_argument("--options-confirmation", choices=("true", "false"), default="false")
    parser.add_argument("--max-spread-bps", type=int, default=35)
    parser.add_argument("--min-relative-volume", default="0.25")
    args = parser.parse_args()
    symbols = list(dict.fromkeys(value.strip().upper() for value in args.symbols.split(",") if value.strip()))
    result = collect_market_monitoring(
        symbols=symbols,
        feed=args.feed,
        discovery_enabled=args.discovery == "true",
        discovery_top=args.discovery_top,
        monitor_corporate_actions=args.corporate_actions == "true",
        options_confirmation=args.options_confirmation == "true",
        max_spread_bps=args.max_spread_bps,
        min_relative_volume=args.min_relative_volume,
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
