from __future__ import annotations

import os
import re
from pathlib import Path


ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def load_workspace_env() -> None:
    """Load the optional repository .env.local without overriding exported values."""
    path = Path(__file__).resolve().parents[4] / ".env.local"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if not ENV_KEY.fullmatch(key):
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)
