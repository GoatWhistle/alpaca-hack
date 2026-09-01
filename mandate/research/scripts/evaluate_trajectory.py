from __future__ import annotations

import argparse
import json

from mandate_research.decision_math import evaluate_trajectory


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one deterministic trajectory evaluation")
    parser.add_argument("--symbols", required=True)
    parser.add_argument("--max-spread-bps", default="35")
    parser.add_argument("--min-relative-volume", default="0.25")
    parser.add_argument("--equity", required=True)
    parser.add_argument("--position-headroom-pct", required=True)
    parser.add_argument("--gross-headroom-pct", required=True)
    parser.add_argument("--adaptive-weights-json", default="{}")
    parser.add_argument("--priority-symbols", default="")
    parser.add_argument("--research-limit", type=int, default=5)
    parser.add_argument("--risk-budget-pct", default="1.0")
    parser.add_argument("--atr-multiplier", default="1.0")
    args = parser.parse_args()
    result = evaluate_trajectory(
        symbols=[value.strip().upper() for value in args.symbols.split(",") if value.strip()],
        fee_bps="1",
        max_spread_bps=args.max_spread_bps,
        min_relative_volume=args.min_relative_volume,
        regular_hours_only=True,
        equity=args.equity,
        position_headroom_pct=args.position_headroom_pct,
        gross_headroom_pct=args.gross_headroom_pct,
        adaptive_weights_json=args.adaptive_weights_json,
        risk_budget_pct=args.risk_budget_pct,
        atr_multiplier=args.atr_multiplier,
        priority_symbols_csv=args.priority_symbols,
        research_limit=args.research_limit,
        compact_output=True,
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
