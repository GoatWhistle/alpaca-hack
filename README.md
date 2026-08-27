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

The unprivileged `mandate-research` package is also a loadable TrueForge Skill. Its
`evaluate_trajectory` tool replaces repeated agent-authored arithmetic with one Decimal-based decision
matrix. It computes liquidity and stale-data gates, session movement, ATR14 sizing capped by live mandate
headroom, SPY trend/range regime, and a regime-weighted ensemble over five explainable approaches:

- price momentum;
- mean reversion by rolling z-score;
- price breakout confirmed by relative volume;
- structured Z.AI news impact score (sentiment, confidence, event type, horizon and 48-hour novelty)
  confirmed by price momentum;
- regime-weighted ensemble that favors momentum/breakout in trends and mean reversion in ranges.

Signals receive only the history available at their decision timestamp. The harness reports return,
maximum drawdown, turnover and position changes, with configurable fees plus explicit spread-crossing
slippage on entries, changes and final exit. It also emits a chronological frozen-parameter holdout. This is an
engineering comparison, not a profitability claim.

The same package exposes a separate read-only MCP boundary with five tools:
`probe_news_sources`, `compare_live_signals`, `get_market_monitoring`, `score_news_llm`, and
`evaluate_trajectory`. The scorer batches and caches bounded JSON results from Z.AI and fails closed when
credentials, transport or the structured response are invalid. It has
no trading client or write tool. This gives the
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
npm run apply
npm run eval:sandbox
npm run eval:subagents
npm run eval:approval
npm run eval:research-e2e
MANDATE_E2E_ALLOW=true npm run eval:paper-e2e
```

### Unified operator UI

The TrueForge UI at `http://localhost:8790` is the single operator surface. **Overview** shows live
paper-account equity, positions and pending orders; mandate usage and headroom; service health; wake
conditions; and the durable prepared, submitted, denied, deduplicated and parked decision timeline.
**Agent workspace** keeps the stock TrueForge agent library, chat history, tool-call details, composer and
approval cards. Broker credentials never reach the browser: live overview data is read through the guard's
read-only MCP tools. If the guard is restarting, Overview fails visibly into a degraded mode backed by the
local mandate and journal instead of displaying stale values as live.

Use Node 22 or 24, build the web assets, then start the companion overview API and TrueForge after the
guard is running:

```bash
cd mandate/app
npm install
npm run build

cd ../mcp-guard
python -m pip install -e .
mandate-dashboard

# In another terminal, from the repository root:
PORT=8790 FRONTEND_DIR=/absolute/path/to/harness/mandate/app/dist npx @truefoundry/trueforge@0.1.4
```

Open only `http://localhost:8790` and switch between **Overview** and **Agent workspace**. Port `8030` is
the local, read-only companion API consumed by Overview; it is not a second UI.

### 24/7 autonomy and chat control plane

The autonomy runner stays alive outside chat, subscribes to Alpaca news and IEX/SIP market WebSockets,
keeps REST polling as a configurable fallback, and deduplicates events through a durable cursor. It starts
a read-only TrueForge analysis immediately for new headlines or on the configured cadence. Each cycle is
visible in Chat History and must finish with `ACTION: PARK` or `ACTION: PROPOSE`.
Background turns are mechanically audited after completion and fail if they request an execution,
trajectory-write or approval tool. `PROPOSE` is a notification for the human, never permission to trade.

Start it after TrueForge, guard and research MCP are healthy:

```bash
cd mandate/agent
npm run autonomy
```

The shared trajectory defaults to AAPL/MSFT/NVDA/SPY, realtime streams, a 60-second REST fallback and a
15-minute full analysis. Every market poll adds Alpaca snapshots, spread/staleness/volume gates, SPY
confirmation, observation-only movers/most-actives discovery and corporate-action risks. Optional option
chain confirmation is disabled by default. Discovery never expands the mandate universe. A deterministic
post-model gate converts `PROPOSE` to `PARK` when regular-hours, liquidity or SPY checks fail.
The three strongest movers are exposed as an observation-only research watchlist. SPY's 20-bar regime
changes ensemble weights and halves gross sizing below its 20-period moving average. Strategy multipliers
learn only from completed 60-minute proposal outcomes, are evidence-shrunk and remain bounded.
In normal chat, ask the agent to explain `get_autonomy_state`, pause/resume monitoring, narrow the symbols,
change cadence, risk posture or thesis. Persistent changes go through `update_trajectory`, require approval,
and cannot add a symbol outside the hard mandate. Runtime heartbeat, next analysis and news deliveries are
shown on Overview, where Monitoring settings require a separate review and confirmation click. State lives
in ignored `mandate/logs/trajectory.json`, `autonomy-runtime.json`, `market-monitoring.json`,
`forward-outcomes.json`, `news-cursor.json` and `news-alerts.jsonl` files. Forward returns are measured at
5, 15 and 60 minutes as evaluation evidence, never as a claim of profitability.

For unattended operation across terminal disconnects or machine restarts, run `npm run autonomy` under the
host process manager. The runner is restart-safe and immediately reports `degraded` plus the last error when
news, TrueForge or the model is unavailable; it never silently converts an infrastructure failure into a
proposal.

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

`eval:research-e2e` is intentionally read-only. It requires TrueForge/Z.AI to call `get_mandate` and one
`evaluate_trajectory` for the complete symbol set. The verifier requires five strategy outputs and a
structured LLM score whenever live news is present, and rejects sandbox execution or broker-write calls.
mandate-bounded whole-share quantity for every symbol, rejects sandbox `exec`, redundant low-level
research calls and every execution tool, and requires a bounded `ACTION: PARK` or `ACTION: PROPOSE` conclusion.

`eval:patterns` audits the latest persisted agent sessions without mutating them. The extraction baseline
found 77 sandbox `exec` calls in 25 sessions, dominated by basis-point/spread, return, ratio, drawdown,
exposure and VWAP calculations. This is the regression baseline for the decision-math tool.

`eval:sandbox` proves deterministic Code Mode execution with one persisted `exec` call and no MCP or
approval event. `eval:subagents` requires exactly two `create_sub_agent` delegations, distinct isolated
threads, no approval and no direct or nested execution tool.

`MANDATE_GUARD_HOST` and `MANDATE_GUARD_PORT` control the server bind address. Set the separate
`MANDATE_GUARD_URL` to the HTTP(S) address reachable from TrueForge; it is validated and may not contain
embedded credentials. `MANDATE_RESEARCH_URL` independently configures the read-only research endpoint.

The registered `mandate-paper-agent` uses `zai/glm-5-3-flash`, sandbox execution, dynamic subagents,
generative UI, context compaction and three MCP servers. Alpaca exposes only
calendar, clock and stock-data research tools to the model; all execution flows through `mandate-guard`.
The `mandate-research` Git Skill is enabled by default and can be disabled with
`MANDATE_ENABLE_RESEARCH_SKILL=false`. The read-only research MCP remains enabled independently of the Git Skill.

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
allow, broker-evidence and retry-dedup assertions used by the subsequent regular-session run.

At the 27 August regular-session open, that supervised runner completed through the real paper endpoint.
The first persisted approval produced one AAPL buy-1 limit-$1 order and durable `prepared → submitted`
events. An unchanged retry paused for a second approval and produced only `deduplicated`, with the same
client-order ID and mandate fingerprint. Official Alpaca MCP readback independently matched every order
term and showed status `new`. A separate exact-ID cleanup then paused at `cancel_order`, was approved,
wrote `cancel_order/submitted`, and official readback showed the same order as `canceled`. The sanitized
artifact is [`docs/evidence/paper-e2e-2026-08-27.json`](docs/evidence/paper-e2e-2026-08-27.json).

`eval:cancel-e2e` is a cleanup verifier for an exact broker order ID and mandate client-order ID. It
requires durable submitted provenance before requesting cancellation, validates the persisted TrueForge
call before approval, and can re-audit an existing session without replaying the cancel action.

The current local suite has 91 guard tests, 55 research/Skill/MCP tests and 9 autonomy-runner tests. It covers hot-reloaded human
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
IEX market monitoring, current paper-account mandate headroom and no write call. The live autonomy cycle
observed four passing quality gates, one MSFT corporate action and returned `ACTION: PARK`; its first durable
5-minute forward outcome was then measured without any broker write.

The decision-math E2E session `01m1269wsz849mfa0hac88yqbg` subsequently called only `get_mandate` and
`evaluate_trajectory` for AAPL/MSFT/NVDA/SPY. It returned five-strategy evidence and ready whole-share
sizing, chose `PARK`, made no sandbox-code call and attempted no broker write. The dashboard now exposes a
60-minute per-strategy/news-vs-price outcome scorecard; historical records without captured directions are
excluded rather than guessed.
