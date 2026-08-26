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
4. Reject every violated rule, or surface an explicitly annotated destructive tool for human approval.
5. Fetch state and run the checks again immediately before submission.
6. Submit only to the exact host `https://paper-api.alpaca.markets` and append an audit event.

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

The unprivileged `mandate-research` package contains the common evaluation harness and compares four
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

To run the MCP server, copy `mandate/.env.example` to an ignored `.env`, add **paper-account** credentials,
export the values in your shell, then run:

```bash
cd mandate
mandate-guard
```

The example mandate is [`mandate/mandates/example.yaml`](mandate/mandates/example.yaml). An expired or
invalid mandate prevents startup.

## Qodo Code Review Evidence

Qodo Code Review was installed for `GoatWhistle/harness-hack` before product code was added. Every
milestone is developed on a branch, reviewed in a pull request and merged by a human. High-severity
findings must be fixed or explicitly rejected with a written reason.

The running evidence table and project-specific review rules live in
[`docs/QODO_REVIEW_LOG.md`](docs/QODO_REVIEW_LOG.md). PRs use the repository template to require test,
paper-endpoint and secret checks.

## Current status

M1 is in progress: the privileged `mandate-guard` package contains only mandate enforcement, the paper
broker client and MCP boundary. Normalized news input, explainable signals and evaluation live in the
separate unprivileged `mandate-research` package. Both are covered by tests. TrueForge agent configuration
and the end-to-end approval flow are the next milestone.
