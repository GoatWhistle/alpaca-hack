# MANDATE runtime

MANDATE is an autonomous Alpaca paper-trading system with four runtime components:

1. The official Alpaca MCP server on port `8000` exposes account, market-data and trading tools.
2. `mandate/research` collects news and market data, compares strategies and sizes candidates.
3. `mandate/agent` runs continuous monitoring, challenges candidates and sends auto-paper orders directly to Alpaca.
4. `mandate/control-plane` serves the operator dashboard and reads live account state directly from Alpaca.

There is no intermediate execution service. Alpaca is the execution authority. Manual mode uses TrueForge tool approval for Alpaca write tools; auto-paper mode uses the local direct executor. Both paths are restricted to the exact HTTPS paper endpoint.

The competition profile polls news every 30 seconds and evaluates the market every 3 minutes. The seed universe expands temporarily with up to six movers that pass freshness, spread, relative-volume and Alpaca tradability checks. Each cycle can close two weak positions and, after refreshing broker state, enter two ranked opportunities. The first eligible entry uses a 7–21 DTE long option or level-3 debit spread when chain liquidity and account permissions allow it; equity is the fallback. Orders are polled, repriced within bounded limits, cancelled when still unfilled, and journaled with actual fill state.

Default exposure ceilings are 40% per equity position and 200% gross, further bounded by reported buying power. Option premium risk defaults to 6% of equity per trade and 25% total. These are paper-only competition settings and are configurable through `mandate/.env.example`.

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
