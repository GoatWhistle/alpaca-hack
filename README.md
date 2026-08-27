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
only when the order's client ID is backed by a submitted event in the persistent guard journal. Every
prepared, denied and submitted decision records a SHA-256 fingerprint of the exact validated mandate, so
auditors can distinguish decisions made before and after a human hot-reload. Retries recover their original
broker client ID from durable provenance, so renaming a mandate cannot turn one intent into a second order;
conflicting stored IDs fail closed.

Human predecisions are executable YAML, not model guidance. A directive such as
`daily_loss_pct >= 1 → park_new_orders` is evaluated from the fresh broker snapshot before every order.
The initial grammar deliberately supports only metrics the guard can observe itself and one fail-closed
action; unknown metrics or actions prevent the mandate from loading.

The human-owned YAML is reloaded and strictly validated at the start of every policy operation. This lets
an operator tighten or revoke authority without restarting the guard. A missing, malformed or partially
written file fails closed before broker state is fetched or an order can be submitted; use an atomic file
replacement when editing it in production. The agent has no tool for writing or reloading this file.

The server refuses live, HTTP, look-alike, credential-bearing, port-bearing, and path-bearing base URLs.
Secrets are read from environment variables and must never be committed.

Short selling is a separate, explicit mandate capability and defaults to disabled. The guard considers
already-pending sell orders when evaluating a new sell, so individually valid orders cannot collectively
cross a long position through zero. Buys that reduce an existing short remain possible without expanding
that authority.

## Implemented research paths

News is normalized as untrusted data before it reaches any strategy:

- Alpaca News JSON;
- SEC EDGAR Atom feeds;
- Apple Newsroom Atom and NVIDIA investor-relations RSS feeds with fixed issuer mappings.

The parsers cap input size, require timezone-aware timestamps, remove markup, normalize symbols and
deduplicate revisions. Text such as “ignore previous instructions” remains inert data; it is never used as
an agent instruction. Company-specific feeds receive an explicit symbol binding before scoring, and the
news strategy uses only revisions available at each historical cutoff within a bounded 24-hour window. An
issuer feed is never rebound to another ticker: AAPL can use Apple Newsroom and NVDA can use NVIDIA IR,
while other symbols receive neither feed unless an attributable source is added explicitly.

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

The same package exposes a separate read-only MCP boundary with exactly two tools:
`probe_news_sources` and `compare_live_signals`. It has no trading client or write tool. This gives the
TrueForge agent a server-side path to fixed-host news/data fetches without placing paper credentials in
the turn sandbox; execution authority remains exclusively in `mandate-guard`.

Two read-only live probes are available when Alpaca data credentials are exported:

```bash
cd mandate/research
PYTHONPATH=src python scripts/probe_live_sources.py
PYTHONPATH=src python scripts/compare_live_signals.py --symbol AAPL --fee-bps 1
```

The source probe isolates upstream failures so one unavailable publisher cannot erase evidence from the
others; `--strict` requires every source to succeed. Fetches use verified TLS, fixed HTTPS host allowlists,
one-megabyte response bounds and explicit SEC identification. The comparison runner follows bounded Alpaca
pagination and reports the data cutoff, fees, observations, return, drawdown, turnover and position changes.

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
`streamable-http` mode on port 8010. Install the research package and run its read-only MCP on port 8020,
then register or update the agent:

```bash
cd mandate/research
python -m pip install -e .
MANDATE_RESEARCH_TRANSPORT=streamable-http mandate-research-mcp

cd mandate/agent
npm install
npm run typecheck
MANDATE_ENABLE_RESEARCH_SKILL=true npm run apply
npm run eval:approval
npm run eval:research-e2e
MANDATE_E2E_ALLOW=true npm run eval:paper-e2e
```

`eval:approval` is a fail-safe live conformance probe. It creates a dedicated TrueForge session, asks
the configured model to request `cancel_order` for a nonexistent probe ID, verifies the exact tool pauses
at `tool.approval_required`, sends a denial, and asserts the guard journal remains byte-for-byte unchanged.
It never sends an allow decision. Run it from `mandate/agent` while TrueForge and the guard are available.

`eval:paper-e2e` is the supervised paper execution acceptance runner. Its opt-in environment flag permits
only the exact `AAPL buy 1, limit $1` intent after it validates the persisted TrueForge tool call and every
execution argument. During regular hours it requires and allows the first approval, verifies durable
`prepared`/`submitted` evidence, repeats the same intent through a second approval, and requires
`deduplicated=true` without another submission. Outside regular hours it proves the guard's session breach,
checks that no broker write was attempted, reports `deferred: market_closed`, and exits successfully.

`eval:research-e2e` is intentionally read-only. It requires TrueForge/Z.AI to obtain multi-source news
health, all four point-in-time strategy comparisons and current mandate headroom. The verifier reconciles
streaming events with persisted session events, unwraps Code Mode `call_tool` bridge calls, rejects any
nested or direct execution tool, and requires a bounded `ACTION: PARK` or `ACTION: PROPOSE` conclusion.

`MANDATE_GUARD_HOST` and `MANDATE_GUARD_PORT` control the server bind address. Set the separate
`MANDATE_GUARD_URL` to the HTTP(S) address reachable from TrueForge; it is validated and may not contain
embedded credentials. `MANDATE_RESEARCH_URL` independently configures the read-only research endpoint.

The registered `mandate-paper-agent` uses `zai/glm-5-3-flash`, sandbox execution, dynamic subagents,
generative UI, context compaction and three MCP servers. Alpaca exposes only
calendar, clock and stock-data research tools to the model; all execution flows through `mandate-guard`.
The `mandate-research` Git Skill is enabled with `MANDATE_ENABLE_RESEARCH_SKILL=true`; TrueForge's secure
downloader intentionally supports public Git repositories without ambient credentials, so keep it disabled
while this repository is private.

The example mandate is [`mandate/mandates/example.yaml`](mandate/mandates/example.yaml). An expired or
invalid mandate prevents startup and blocks subsequent policy operations if introduced while running.

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

A live approval conformance probe then requested a fake cancellation through Z.AI and TrueForge. The
harness emitted `tool.approval_required`, accepted an automated denial, completed the resumed turn and left
the guard journal byte-for-byte unchanged. This proves the irreversible tool was stopped before reaching
the execution boundary even while the market was closed.

The supervised paper E2E runner was also executed while the exchange was closed. Z.AI called the real
guard, the deterministic session rule stopped the order before an approval event, the runner observed no
new submission provenance and reported `brokerWriteAttempted: false`. The same runner contains the exact
allow, broker-evidence and retry-dedup assertions for the next regular session.

The current local suite has 84 guard tests and 32 research/Skill/MCP tests. It covers hot-reloaded human
authority, fail-closed malformed edits, concurrent submissions,
pending-order risk reservations, broker-clock fail-closed behavior, stable retry IDs, journal restoration,
live mandate headroom and wake triggers, risk-reducing closes, and rejection of foreign order cancellation.

On 27 August 2026 the live source probe parsed 20 Alpaca JSON events, 20 Apple Newsroom Atom events and
20 NVIDIA investor-relations RSS events with unique content hashes and explicit symbol scope. SEC EDGAR's
Atom endpoint returned HTTP 403 from this environment and is reported as an upstream failure rather than a
successful parse. A live AAPL comparison then consumed 269 paginated IEX hourly bars and 50 Alpaca news
items. With a 24-hour news window and 1 bp transaction cost, momentum returned 6.62% with 5.06% maximum
drawdown while news-plus-price confirmation returned 1.37% with 0.95% maximum drawdown; mean reversion and
breakout-with-volume were negative. These are engineering observations over this sample, not forecasts.

A subsequent live read-only decision E2E ran through TrueForge, Z.AI, `mandate-research` and
`mandate-guard`. Persisted events proved two healthy attributable news sources, all four strategy outputs,
current paper-account mandate headroom and no write call. With a flat news-confirmed signal and the market
closed, the agent returned `ACTION: PARK`; the verifier reported `brokerWriteAttempted: false`.
