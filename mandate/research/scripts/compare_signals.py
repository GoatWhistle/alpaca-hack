from __future__ import annotations

import argparse
import json
from pathlib import Path

from mandate_research.comparison import analyze


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare explainable MANDATE signals")
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("input must be a JSON object")
    print(json.dumps(analyze(payload), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
