# FACTS.md — verified technical facts we will build against

Everything here was read from source or official docs during the research phase. Keep it accurate; delete
anything that turns out wrong rather than leaving it.

## TrueForge

Open-source agent harness by TrueFoundry, MIT, launched 19 Aug 2026. It is a **replacement for Claude Code**,
not a plugin — same category, and their own benchmark compares against "Claude managed agents".

Run: `npx @truefoundry/trueforge` (no account, no clone, SQLite, server + chat UI on one port) or
`docker compose up` / Helm with Postgres + Redis.

Three surfaces: bundled chat UI · HTTP API + `@truefoundry/trueforge-sdk` · embeddable
`@truefoundry/trueforge-ui`. Everything the UI does, the API does.

### Capabilities that matter to us
- **Sandbox as a tool** — a sandbox is provisioned only when code must run, not for the whole session.
  Secrets stay in the harness.
- **Code Mode** — the agent writes one Python script in the sandbox; its MCP calls are **bridged back to the
  harness, which injects the stored credentials**. Tokens never enter the sandbox.
- **Subagents** — `create_sub_agent`, parallel, isolated context, same tools as the root, only the final
  result returns. No nesting. Subagents cannot talk to the user.
- **Skills** — a **directory in a git repo rooted at `SKILL.md`** (YAML frontmatter + instructions +
  scripts), mounted into the sandbox at `/opt/tfy/skills/{name}`, loaded in full only when the agent decides
  it is relevant (progressive disclosure). CRUD via `/api-reference/skills/*`.
  NOTE: the claim "TrueForge has no skills" that circulated in our notes is **wrong**.
- **Generative UI (OpenUI)** — the agent can emit a declarative UI into chat: `Form`, `FormControl`, `Input`,
  `Select`, `Modal`, `Table` (column-oriented, components in cells, row action buttons), 11 chart types,
  reactive `$binding`, builtins `@Count @Sum @Avg @Sort @Filter @Each @Round`, and
  `Action([@Set, @Reset, @Run, @ToAssistant, @OpenUrl])`. Rendered by `@openuidev/react-lang`.
  Buttons act by round-tripping a message back into the agent loop via `@ToAssistant`.
- **Sessions** survive reconnects and restarts. Rich API: turns, session/turn events, subscribe to a running
  turn, cancel a turn, **download a file from the turn sandbox**.
- **Model-agnostic** — OpenAI, Anthropic, Gemini, DeepSeek, any compatible endpoint, switchable in the UI.

### The approval gate, exactly
`packages/trueforge-core/src/core/mcp/toolSelectors.ts`:
```
DEFAULT_REQUIRE_APPROVAL_FOR_TOOLS = ['@write', '@destructive']
isReadOnly    = annotations?.readOnlyHint === true
isWrite       = annotations?.readOnlyHint === false && annotations.destructiveHint !== true
isDestructive = annotations?.destructiveHint === true
```
Doc comment above `toolRequiresApproval`, verbatim:
> "Unannotated tools are exempt unless named in `require_approval_for_tools` or covered by `@all`."

**Consequence: a tool with no MCP annotations executes with no approval under the shipped default.**
The MCP spec itself says annotations are hints and clients must treat them as untrusted.
Rule for us: annotate every write tool in our own MCP server **and** name the dangerous ones literally in
`require_approval_for_tools`. Belt and braces.

### UI SDK
`@truefoundry/trueforge-ui` is a component library, not a finished chat: atoms, containers, hooks, theming,
layouts, streaming events. It already ships `ToolApprovalBar.tsx` and `ToolApprovalContainer.tsx`.
Build the console by composing these with a custom theme plus our own domain containers — cheaper than
writing a frontend from scratch, and it counts as sponsor-tool usage.

## Alpaca

Hackathon: **28 Aug – 4 Sep 2026**, deadline **4 Sep 15:00 UTC**, $6,000, fully online.
**Paper trading only** — simulated funds, real market data, no card. Submissions must be original and MIT.
lablab's rulebook requires the **core AI functionality to be built inside the event window** — read
https://lablab.ai/hackathon-rules before reusing anything written before 28 Aug.

Official MCP server: **`alpacahq/alpaca-mcp-server`**, v2.3.0, MIT. 60+ tools generated from Alpaca's OpenAPI
specs with FastMCP, plus hand-written order overrides. Defaults to paper trading.

### Annotation coverage — checked in source
`src/alpaca_mcp_server/overrides.py` contains exactly **three** annotated blocks:
```
"title": "Place Stock Order",  "readOnlyHint": False, "destructiveHint": True, "idempotentHint": False
"title": "Place Crypto Order", "readOnlyHint": False, "destructiveHint": True, "idempotentHint": False
"title": "Place Option Order", "readOnlyHint": False, "destructiveHint": True, "idempotentHint": False
```
`market_data_overrides.py` annotates data tools `readOnlyHint: True`.
**The 60+ OpenAPI-generated tools carry no annotations at all.**

Combined with TrueForge's default policy: order placement is gated out of the box, but every write operation
that lives in the generated tail runs **ungated**. TODO before the demo: enumerate that tail and record which
write operations it contains (cancel order, replace order, close position, close all positions).

Upstream opportunity: a PR to `alpacahq/alpaca-mcp-server` adding annotations to the generated write tools.
Real open-source contribution, and it doubles as Qodo review evidence.

## TrueForge hackathon — submission requirements
- Agent running on TrueForge where a judge can see: a real tool being reached, code running in the sandbox,
  and a stop before an irreversible action.
- Public repo with a README that starts on someone else's machine.
- A `## Qodo Code Review Evidence` section linking at least one **merged** PR reviewed by Qodo, describing
  what was found and what was fixed or deliberately rejected. No direct pushes to main. Every High finding
  fixed or rejected with a written reason in the thread.
- ~3-minute demo video that **must contain the approval moment**.
- Own accounts and data only; keys and personal data out of the repo and the video.
- Deadline 30 Aug 2026, 20:00 London. Six equally weighted criteria: impact, originality, technical
  excellence, sponsor tools, control and safety, presentation.
