# MANDATE — the trading desk as a living agent graph

Most AI trading demos stop at a generated signal.

MANDATE starts where the signal becomes dangerous.

We built a stateful trading desk for Alpaca paper markets where the main trader is not a chatbot making isolated calls. It is the center of a continuously evolving graph:

`market + news → research → hypotheses → main trader → critics → deterministic policy → execution`

Open positions feed back into the graph through position watchers. Their current price, age, thesis status, and exit risk become fresh evidence for the next decision. Off-hours, the system keeps building and revising the next-open plan. During market hours, it revalidates that plan against fresh quotes before every action.

The important architectural choice is the boundary between probabilistic reasoning and deterministic action.

Agents can:

- discover and rank market hypotheses;
- challenge each other with market, risk, and execution reviews;
- explain what evidence changed the current thesis;
- propose a strictly typed trade plan.

Agents cannot submit orders.

Only the deterministic execution layer can reach Alpaca, and only after schema validation, evidence checks, liquidity and exposure checks, order idempotency, position limits, stop/target rules, and session protection pass. Invalid output, stale data, or an unavailable critic resolves to `PARK` or `HOLD` — never to an inferred trade.

That graph is also the product interface. The trader room streams the main agent’s active hypothesis, summarized worker results, tool outcomes, challenges, and execution state as one conversation. The operations view exposes dependencies, health, open positions, exit policies, and a FIFO trade ledger with realized and unrealized P&L.

This makes the system inspectable at the level that matters: not just “what did the model say?”, but:

1. What evidence entered the system?
2. Which hypothesis survived?
3. What did the main trader decide to test?
4. Which critic or deterministic rule changed the plan?
5. What reached the broker — and why?

The result is less like an autocomplete box and more like a small, observable organization of specialized agents with a hard execution boundary.

Built with Alpaca, Codex, Claude Code, Python, TypeScript, React, FastAPI, MCP, and Z.ai.

Paper trading only. No investment advice.

Live console: https://alpaca.miposts.com  
Source: https://github.com/GoatWhistle/alpaca-hack

#AI #AgenticAI #MultiAgentSystems #QuantitativeFinance #OptionsTrading #Alpaca #Codex #MCP #Fintech #TradingSystems

---

## Suggested image order

1. `mandate-hero.png` — opening image / hero.
2. `agent-graph.png` — graph architecture and dependency flow.
3. `trader-room.png` — conversation-driven trader interface.

All images are original generated visuals and intentionally contain no performance claims or broker screenshots.

## Suggested first comment

The core idea: use models for hypothesis formation and explanation, then make the path to the broker explicit, typed, auditable, and deterministic. The graph is not decoration — it is the system’s memory and control surface.
