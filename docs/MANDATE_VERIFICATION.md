# MANDATE verification matrix

This file separates implemented behavior from runtime evidence. A passing unit test is not used as proof
of a broker-side effect, and a model statement is not used as proof of a tool call.

| Requirement | Status | Authoritative evidence |
|---|---|---|
| Paper-only broker boundary | Verified | `AlpacaPaperClient` accepts only the exact HTTPS paper host; config and client rejection tests are in `mandate/mcp-guard/tests/test_config.py` and `test_alpaca.py`. |
| TrueForge/Z.AI agent integration | Verified | Agent manifest uses `zai/glm-5-3-flash`, sandbox, dynamic subagents and explicit MCP allowlists. Live persisted session `01m128da83tm700q7kxa15s6pw` called only the required mandate/trajectory tools (plus read-only MCP discovery); no sandbox code or write tool was observed. |
| Deterministic sandbox code | Verified | Session `01m11mzx7n026dagnhx1g5k057` persisted exactly one `exec` call, returned `42` for `7 * 6`, requested no approval and made no broker call. |
| Dynamic subagent delegation | Verified | Session `01m11mp0tm5wgej7jvejrbjj10` persisted exactly two `create_sub_agent` calls and isolated threads for source health and strategy/risk analysis; no approval or write was observed. |
| Deterministic mandate enforcement | Verified | 91 guard tests cover universe, instrument, order type, session, expiry, daily loss, order count, position/gross exposure, pending sells, predecisions and mandate hot reload. |
| Multiple news parsers and sources | Verified | Alpaca JSON, generic Atom/SEC Atom, RSS2 and issuer binding have parser tests. Live MCP evidence saw Alpaca and Apple healthy while preserving SEC HTTP 403 as an isolated upstream failure. |
| News decision compared with explainable baselines | Verified | Word-list scoring was removed. Bounded Z.AI structured output supplies signed impact, confidence, event type, horizon and novelty; invalid or unavailable scores contribute zero. The live mixed headline “EPS beat but full-year guidance cut” scored `-0.6` with `0.85` confidence, and the four-symbol E2E required at least one successful LLM score whenever news existed. |
| Human approval denial boundary | Verified | `npm run eval:approval` observed `tool.approval_required`, sent deny and proved the guard journal was unchanged. |
| Durable audit journal and restart recovery | Verified | JSONL writes are flushed and fsynced; restoration and malformed-journal failure are tested. A live restart recovered a parked action. |
| Live risk metrics | Verified | `get_mandate` returns fresh usage, headroom, wake triggers and predecisions; `get_session_state` returns paper equity, P&L, exposure, positions, pending orders and journal. Live TrueForge research E2E consumed current headroom. |
| Approved paper submission and idempotent retry during regular hours | Verified | At broker open on 27 August, session `01m11pkjzj18q6zyqd4yb39pms` proved `prepared → submitted`, a second explicit approval, `deduplicated`, one client order ID and one mandate fingerprint. Official Alpaca MCP readback matched AAPL buy 1 limit $1 and showed one order. |
| Provenance-safe paper cleanup | Verified | Session `01m11ptfz4zemy4h63s5ge800z` paused on exact `cancel_order`, received approval, wrote `cancel_order/submitted`, and official Alpaca MCP readback changed the same broker order from `new` to `canceled`. |
| Realtime market/news monitoring | Verified | Alpaca news and IEX WebSockets reported connected; REST snapshots, clock, movers, most actives and corporate actions were healthy. Four mandate symbols passed the live quality snapshot and discovery remained observation-only. |
| Forward outcome measurement | Verified | The autonomy cycle persisted baseline prices and a 5-minute return for all four symbols in `forward-outcomes.json`; 15/60-minute horizons settle on later polls without broker writes. |
| Deterministic decision intelligence | Verified | `evaluate_trajectory` returns Decimal liquidity/session gates, strength-scaled ATR14 whole-share sizing capped by mandate headroom, SPY 20-bar regime/risk-off gross scaling, a five-strategy adaptive ensemble and fee-plus-2-bps-slippage chronological holdout evidence. Train-only selection cannot see modified holdout prices. Research suite: 56 passing tests. |
| Outcome feedback loop | Verified | The runner aggregates only completed 60-minute outcomes from proposals with captured strategy directions into per-strategy and news-vs-price mean signed return/accuracy plus an evidence-shrunk bounded multiplier; the compact scorecard is supplied to the next prompt and rendered in the dashboard. PARK-only history is deliberately excluded from adaptive weights. |
| Monitoring control plane | Verified | Browser E2E verified realtime status, quality/discovery telemetry and the separate Review → Confirm gate. Backend tests reject unconfirmed writes and symbols outside the mandate universe. |
| Qodo review of implementation head | Verified | PR #2 Qodo deep review points to implementation commit `0a47785` and reports Bugs 0, Rule violations 0 and Skill insights 0. |

## Repeatable commands

```bash
cd mandate/mcp-guard && python -m pytest -q
cd mandate/research && python -m pytest -q
cd mandate/agent && npm run typecheck
cd mandate/agent && npm run eval:sandbox
cd mandate/agent && npm run eval:subagents
cd mandate/agent && npm run eval:approval
cd mandate/agent && npm run eval:research-e2e
cd mandate/agent && MANDATE_E2E_ALLOW=true npm run eval:paper-e2e
```

The paper command is intentionally not considered successful open-market evidence when it reports
`deferred: market_closed`. The captured open-market evidence is stored in
`docs/evidence/paper-e2e-2026-08-27.json`; it contains no credentials.
