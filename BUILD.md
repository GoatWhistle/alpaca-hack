# MANDATE runtime

MANDATE is an autonomous Alpaca paper-trading system with four runtime components:

1. The official Alpaca MCP server (`alpacahq/alpaca-mcp-server`, streamable HTTP on `127.0.0.1:8100`) is pinned to `ALPACA_TOOLSETS=assets,stock-data`, so the operator receives only public market/reference reads. Private account, position, order, cancel, close, and exercise toolsets are disabled. The trusted runner reads paper account state directly from Alpaca's paper REST API and remains the only order execution path.
2. `mandate/research` collects news and market data, compares strategies and sizes candidates.
3. `mandate/agent` runs continuous monitoring, watches the open book with a bounded position watcher, challenges candidates and sends auto-paper orders directly to Alpaca.
4. `mandate/control-plane` serves the operator dashboard and reads live account state directly from Alpaca.

There is no intermediate execution service. Alpaca is the execution authority. Orders are placed only by the local deterministic executor, which is pinned to the exact HTTPS paper endpoint; the planning model and the operator assistant have no order tools at all.

The competition profile polls lightweight account/market state every 30 seconds and runs expensive discovery, corporate-action and option-chain confirmation every 3 minutes. Minute bars trigger a separate risk-only exit pass. The seed universe expands temporarily with up to six movers that pass freshness, spread, relative-volume and Alpaca tradability checks. Normal cycles can close two weak positions; the 15:50 ET flatten pass is not capped at two. Independently of those deterministic hard exits, the read-only position watcher assesses up to six open underlyings and the main trader must return an explicit HOLD, REDUCE or EXIT for each of them; only REDUCE and EXIT reach the executor, are bounded to six actions per cycle, and fail closed to HOLD whenever the watcher is unavailable. The watcher is advisory by default because stops, targets, flattening and strong ensemble reversals already have a deterministic fast path. Optional `MANDATE_POSITION_FAST_EXIT=true` mode can turn INVALIDATED together with EXIT into an exit-only PARK plan before the planning turn, bounded by `MANDATE_POSITION_FAST_EXIT_MAX`; it is disabled in the production profile. The watcher itself never reaches the broker; every close still goes through the deterministic executor and is clamped against live positions. After refreshing broker state, the agent may enter two ranked opportunities. The first eligible entry uses a 7–21 DTE long option or level-3 debit spread when chain liquidity and account permissions allow it; every fallback is recorded. Orders are polled, repriced within bounded limits, cancelled when still unfilled, and journaled with actual fill state.

The mandate file is authoritative for its scalar limits: 40% per position, 100% gross, a 10% maximum daily loss with new entries parked at 8%, and 200 orders per day. Limits are further bounded by reported buying power. Option premium risk defaults to 6% of equity per trade and 25% total. Options receive grouped close orders for stops, targets, time stops, expiry protection and the intraday flatten. Re-entry cooldown, reversal hysteresis, live position revalidation and tagged stale-order recovery prevent accidental flips and rapid churn. These are paper-only competition settings; operational thresholds are documented in `mandate/.env.example`.

## Local services

```sh
cd mandate/research
PYTHONPATH=src python -m mandate_research.server

cd mandate/control-plane
PYTHONPATH=src python -m mandate_control.dashboard

cd mandate/agent
npm run apply
npm run autonomy
```

Build the web console with `cd mandate/app && npm run build` before starting the dashboard.

Required secrets are `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, and the configured model/provider credentials. Never commit them. `ALPACA_BASE_URL` must remain `https://paper-api.alpaca.markets`.
