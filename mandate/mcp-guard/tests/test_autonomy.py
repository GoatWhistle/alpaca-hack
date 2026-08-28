from __future__ import annotations

import json
from pathlib import Path

import pytest

from mandate_guard.autonomy import AutonomyStore


def test_trajectory_persists_valid_bounded_changes(tmp_path: Path) -> None:
    store = AutonomyStore(tmp_path / "trajectory.json", tmp_path / "alerts.jsonl")
    initial = store.read()
    updated = store.update(
        mandate_symbols=["AAPL", "MSFT"],
        updated_by="chat:operator",
        symbols=[" msft "],
        execution_mode="auto_paper",
        analysis_interval_minutes=30,
        risk_posture="defensive",
        thesis="  Wait for two confirming signals.  ",
        monitoring_mode="polling",
        discovery_top=20,
        max_spread_bps=25,
    )

    assert updated.version == initial.version + 1
    assert updated.symbols == ["MSFT"]
    assert updated.execution_mode == "auto_paper"
    assert updated.analysis_interval_minutes == 30
    assert updated.thesis == "Wait for two confirming signals."
    assert updated.monitoring_mode == "polling"
    assert updated.discovery_top == 20
    assert updated.max_spread_bps == 25
    assert store.read() == updated


def test_trajectory_cannot_expand_mandate_universe(tmp_path: Path) -> None:
    store = AutonomyStore(tmp_path / "trajectory.json", tmp_path / "alerts.jsonl")
    with pytest.raises(ValueError, match="cannot expand mandate universe: TSLA"):
        store.update(
            mandate_symbols=["AAPL"],
            updated_by="chat:operator",
            symbols=["AAPL", "TSLA"],
        )


def test_recent_alerts_are_bounded_and_skip_malformed_lines(tmp_path: Path) -> None:
    alerts = tmp_path / "alerts.jsonl"
    alerts.write_text(
        '\n'.join([json.dumps({"id": 1}), "not-json", json.dumps({"id": 2})]) + "\n",
        encoding="utf-8",
    )
    store = AutonomyStore(tmp_path / "trajectory.json", alerts)
    assert store.recent_alerts(limit=3) == [{"id": 1}, {"id": 2}]
