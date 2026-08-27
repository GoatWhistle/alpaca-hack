# MANDATE

MANDATE is a paper-trading agent that may act only inside a human-authored, versioned mandate. The model
can propose a trade; deterministic code decides whether the action is authorized. Orders outside the
mandate are denied and parked for a human decision.

> Paper trading only. This project does not place live-money orders and is not investment advice.
> Backtests and paper results do not predict future returns.

## Safety boundary

The agent never receives a raw order-placement tool. Its only execution path is `mandate-guard`:

1. Load and strictly validate the current mandate.
2. Fetch a fresh paper-account snapshot and latest IEX trade.
3. Calculate projected position and gross exposure with `Decimal` arithmetic.
4. Reject every violated rule; violations cannot be overridden by the model or an approval click.
5. Fetch state and run the checks again immediately before submission.
6. Submit only to the exact host `https://paper-api.alpaca.markets` and append an audit event.

TrueForge requires human approval only for the three irreversible guard tools: submit, cancel and close.
Approval does not bypass the mandate. Direct Alpaca execution tools are excluded with an explicit
research-tool allowlist. Stable intent IDs make submission retries idempotent, and cancellation is allowed
only when the order's client ID is backed by a submitted event in the persistent guard journal.

Human predecisions are executable YAML, not model guidance. A directive such as
`daily_loss_pct >= 1 → park_new_orders` is evaluated from the fresh broker snapshot before every order.
The initial grammar deliberately supports only metrics the guard can observe itself and one fail-closed
action; unknown metrics or actions prevent the mandate from loading.

The server refuses live, HTTP, look-alike, credential-bearing, port-bearing, and path-bearing base URLs.
Secrets are read from environment variables and must never be committed.

## Implemented research paths

News is normalized as untrusted data before it reaches any strategy:

- Alpaca News JSON;
- SEC EDGAR Atom feeds;
- generic company investor-relations RSS feeds.

The parsers cap input size, require timezone-aware timestamps, remove markup, normalize symbols and
deduplicate revisions. Text such as “ignore previous instructions” remains inert data; it is never used as
an agent instruction.

The unprivileged `mandate-research` package is also a loadable TrueForge Skill. It contains the common
evaluation harness and compares four
explainable approaches:

- price momentum;
- mean reversion by rolling z-score;
- price breakout confirmed by relative volume;
- lexicon news score confirmed by price momentum.

Signals receive only the history available at their decision timestamp. The harness reports return,
maximum drawdown, turnover and position changes, with configurable transaction costs. This is an
engineering comparison, not a profitability claim.

## Local verification

Python 3.11 or newer is required.

```bash
cd mandate/mcp-guard
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
python -m pytest
```

To run the guard, copy `mandate/.env.example` to an ignored `.env`, add **paper-account** credentials,
export the values in your shell, install the package, then run:

```bash
cd mandate
python -m pip install -e mcp-guard
mandate-guard
```

For TrueForge, run the official Alpaca MCP in paper mode on port 8000 and the guard in
`streamable-http` mode on port 8010. Then register or update the agent:

```bash
cd mandate/agent
npm install
npm run typecheck
npm run apply
```

`MANDATE_GUARD_HOST` and `MANDATE_GUARD_PORT` control the server bind address. Set the separate
`MANDATE_GUARD_URL` to the HTTP(S) address reachable from TrueForge; it is validated and may not contain
embedded credentials.

The registered `mandate-paper-agent` uses `zai/glm-5-3-flash`, sandbox execution, dynamic subagents,
generative UI, context compaction and two MCP servers. Alpaca exposes only
calendar, clock and stock-data research tools to the model; all execution flows through `mandate-guard`.
The `mandate-research` Git Skill is enabled with `MANDATE_ENABLE_RESEARCH_SKILL=true`; TrueForge's secure
downloader intentionally supports public Git repositories without ambient credentials, so keep it disabled
while this repository is private.

The example mandate is [`mandate/mandates/example.yaml`](mandate/mandates/example.yaml). An expired or
invalid mandate prevents startup.

## Qodo Code Review Evidence

Qodo Code Review was installed for `GoatWhistle/harness-hack` before product code was added. Every
milestone is developed on a branch, reviewed in a pull request and merged by a human. High-severity
findings must be fixed or explicitly rejected with a written reason.

The running evidence table and project-specific review rules live in
[`docs/QODO_REVIEW_LOG.md`](docs/QODO_REVIEW_LOG.md). PRs use the repository template to require test,
paper-endpoint and secret checks.

## Verified integration

On 27 August 2026 an end-to-end read-only run completed through TrueForge, Z.AI, both MCP servers and the
real Alpaca paper API. The agent read a live `$100,000` paper account, cross-checked the Alpaca and guard
market clocks, obtained an AAPL IEX quote, and asked the guard to evaluate TSLA. The guard denied it for two
independent reasons: TSLA was outside the mandate universe and the exchange was closed. No write tool was
called, and the agent's Alpaca tool discovery contained no order-placement tool.

A separate restart test parked a hypothetical out-of-mandate action, stopped the guard process, created a
fresh guard process and a new TrueForge session, then recovered the exact rationale and intended action from
the fsynced JSONL journal. No broker write tool was involved.

The current local suite has 76 guard tests and 20 research/Skill tests. It covers concurrent submissions,
pending-order risk reservations, broker-clock fail-closed behavior, stable retry IDs, journal restoration,
live mandate headroom and wake triggers, risk-reducing closes, and rejection of foreign order cancellation.
