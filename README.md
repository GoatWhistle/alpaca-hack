# Alpaca Autonomous Trading Agent

## Project conditions

Build an autonomous paper-trading agent for the Alpaca hackathon.

The agent is evaluated on:

- total account equity at the end of the scoring window;
- trading performance and P&L;
- autonomy of the trading workflow;
- creativity of market research and opportunity discovery;
- robustness of continuous operation;
- clarity of live decisions and explanations.

## Official account

- Use a newly created Alpaca paper account.
- Initial balance: `$100,000`.
- Do not use the development or testing account for official measurement.
- Official account equity, rather than cash balance, is the primary P&L metric.

## Timeline

- Hackathon window: August 28, 2026 at 9:30 a.m. ET through September 4, 2026 at 9:30 a.m. ET.
- Official P&L window: August 31, 2026 at 9:30 a.m. ET through September 4, 2026 at 9:30 a.m. ET.
- Final portfolio equity is measured at EOD September 3, 2026.

## Trading objective

Maximize total paper-account equity during the official scoring window.

The agent should:

- trade actively throughout the session;
- take both long and short opportunities;
- make several meaningful decisions per day when the market provides opportunities;
- avoid passive buy-and-hold behavior;
- rotate capital when a stronger opportunity appears;
- close, cover or reverse positions whose setup has weakened;
- use available buying power efficiently;
- concentrate capital in stronger setups instead of distributing it across negligible positions;
- continue monitoring even when no fresh company news exists.

## Opportunity universe

The initial universe includes:

`AAPL` `MSFT` `NVDA` `GOOGL` `AMZN` `META` `AMD` `AVGO` `ORCL` `IBM` `PLTR` `CRM` `ANET` `TSM` `ASML` `ARM` `BABA` `BIDU` `SPY`

The agent should also discover and research:

- newly listed IPOs;
- fast-growing public technology companies;
- AI model providers and infrastructure companies;
- semiconductor and networking companies;
- cloud platforms;
- unusual gainers and losers;
- high-relative-volume stocks;
- stocks reacting to earnings, guidance, regulation, partnerships or corporate actions;
- liquid symbols outside the initial list when they present a stronger opportunity.

## Research conditions

The agent may use:

- real-time and historical Alpaca market data;
- trades, quotes, snapshots and bars;
- market movers and most-active lists;
- corporate actions;
- company and macro news;
- official company, regulator and platform sources;
- relative strength against SPY;
- volume and liquidity changes;
- ATR, RSI, MACD, VWAP and momentum;
- breakouts and mean reversion;
- market regime classification;
- structured LLM scoring of catalysts;
- measured forward outcomes from earlier decisions;
- IPO listing date, offer price, liquidity and post-listing behavior.

News is not mandatory for a trade. Price-only and macro-price opportunities are valid.

## Position behavior

- Position size should respond to opportunity strength, volatility and available buying power.
- Existing positions must be reconsidered on every cycle.
- Weak positions should not remain open only because no stop has fired.
- Profitable positions may be reduced or closed when momentum fades.
- Losing positions may be closed, covered or reversed when the thesis changes.
- Short positions are part of the normal opportunity set.
- Intraday opportunities should produce intraday actions.
- Overnight exposure should exist only when the expected continuation is stronger than available intraday alternatives.

## Autonomous behavior

- Monitor continuously without waiting for chat messages.
- React to both scheduled cycles and fresh market events.
- Produce one ranked portfolio decision at a time, with up to two entries and two risk-reducing exits per cycle.
- Explain every trade, exit, reversal and refusal with a concise market-based reason.
- Avoid generic inactivity explanations.
- Avoid repeating research already supplied by the current evaluation.
- Avoid prolonged debate when a tradable opportunity is already identified.
- Continue searching after a candidate fails.
- Prefer liquid defined-risk option expressions for the first eligible setup, with equity fallback when permissions or chain quality fail.

## Required interface information

The dashboard should show:

- current account equity and P&L;
- open positions and current returns;
- pending and completed orders;
- the current pipeline stage;
- the latest market or news event;
- the selected candidate;
- the latest model reason;
- recent trade and exit history;
- per-strategy forward performance;
- the dedicated IPO research stream.

## Technical resources

- [Alpaca Trading API](https://docs.alpaca.markets/us/docs/trading-api)
- [Alpaca Market Data API](https://docs.alpaca.markets/us/docs/getting-started-with-alpaca-market-data)
- [Alpaca MCP Server](https://github.com/alpacahq/alpaca-mcp-server)
- [Alpaca Skills](https://github.com/alpacahq/alpaca-skills)
- [Alpaca JavaScript SDK](https://github.com/alpacahq/alpaca-trade-api-js)

## Submission

- Repository containing the complete agent project.
- Working autonomous paper-trading deployment.
- New official `$100,000` Alpaca paper account.
- Recorded demonstration of continuous monitoring, opportunity selection, trading, position rotation and P&L changes.
- Final account equity available for judging at the end of the official window.
