# MANDATE verification matrix

This file separates implemented behavior from runtime evidence. A passing unit test is not used as proof
of a broker-side effect, and a model statement is not used as proof of a tool call.

| Requirement | Status | Authoritative evidence |
|---|---|---|
| Paper-only broker boundary | Verified | `AlpacaPaperClient` accepts only the exact HTTPS paper host; config and client rejection tests are in `mandate/mcp-guard/tests/test_config.py` and `test_alpaca.py`. |
| TrueForge/Z.AI agent integration | Verified | Agent manifest uses `zai/glm-5-3-flash`, sandbox, dynamic subagents and explicit MCP allowlists. Live persisted research session `01m11kyaz2b3c5rrctmecem5kh` passed `npm run eval:research-e2e`. |
| Deterministic sandbox code | Verified | Session `01m11mzx7n026dagnhx1g5k057` persisted exactly one `exec` call, returned `42` for `7 * 6`, requested no approval and made no broker call. |
| Dynamic subagent delegation | Verified | Session `01m11mp0tm5wgej7jvejrbjj10` persisted exactly two `create_sub_agent` calls and isolated threads for source health and strategy/risk analysis; no approval or write was observed. |
| Deterministic mandate enforcement | Verified | 84 guard tests cover universe, instrument, order type, session, expiry, daily loss, order count, position/gross exposure, pending sells, predecisions and mandate hot reload. |
| Multiple news parsers and sources | Verified | Alpaca JSON, generic Atom/SEC Atom, RSS2 and issuer binding have parser tests. Live MCP evidence saw Alpaca and Apple healthy while preserving SEC HTTP 403 as an isolated upstream failure. |
| News decision compared with explainable baselines | Verified | `compare_live_signals` returned momentum, mean reversion, breakout-with-volume and news-plus-price confirmation over 270 paginated IEX hourly bars and 70 deduplicated news events at `2026-08-27T12:00:00Z`. The agent returned `ACTION: PARK` for a flat news-confirmed signal. |
| Human approval denial boundary | Verified | `npm run eval:approval` observed `tool.approval_required`, sent deny and proved the guard journal was unchanged. |
| Durable audit journal and restart recovery | Verified | JSONL writes are flushed and fsynced; restoration and malformed-journal failure are tested. A live restart recovered a parked action. |
| Live risk metrics | Verified | `get_mandate` returns fresh usage, headroom, wake triggers and predecisions; `get_session_state` returns paper equity, P&L, exposure, positions, pending orders and journal. Live TrueForge research E2E consumed current headroom. |
| Approved paper submission and idempotent retry during regular hours | **Pending** | Closed-market E2E proved fail-closed with no broker write. The supervised runner is waiting for the Alpaca regular session and must still prove `prepared → submitted`, a second explicit approval, `deduplicated`, one client order ID and one mandate fingerprint. |
| Qodo review of implementation head | Verified | The PR #2 Qodo comment points to commit `26b5da8` and reports Bugs 0, Rule violations 0 and Skill insights 0. This matrix was added afterward and contains documentation only. |

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

The final command is intentionally not considered successful open-market evidence when it reports
`deferred: market_closed`.
