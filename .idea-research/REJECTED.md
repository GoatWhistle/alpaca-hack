# REJECTED.md — do not re-litigate

Kept only so nobody spends an afternoon rediscovering a dead end.

## Killed because the world already has it
- **Reversibility compiler** (rewrite irreversible calls into reversible ones + timed commit) — SagaLLM,
  IBM "undo-and-retry", the whole 2026 rollback blogosphere.
- **Behavioural MCP tool auditor** (run the tools, classify by observation) — mcp-scan, MCP-Scanner,
  Snyk agent-scan, MCPXKIT, MCPTox. Crowded field.
- **Disagreement-based escalation** (ask the human only where independent models disagree) — published
  routing taxonomies; "inter-agent agreement is the strongest predictor of accuracy".
- **Declarative reconciliation agent** (declare invariants, agent keeps them true) — kagent,
  "Context Kubernetes". The Kubernetes transplant is already made.
- **Pre/postconditions on tool calls** — ToolGate (Hoare-style contracts, ACL Findings 2026), AgentLTL.
- **Compiling spoken instructions into runtime enforcement** — arXiv 2606.13174, arXiv 2606.26649, and
  Langflow Policies ships it.
- **Gating the agent's claims with provenance** — ProvenanceGuard (2606.18037); the published protocol even
  uses the same phrase "load-bearing claim".

## Killed on fit, not merit
- **Handshake / pull request for the real world** — genuinely new and still unclaimed, but it needs two
  harnesses on screen and does not answer the story the sponsor tells about itself. Park it; it is a real
  product idea outside this hackathon.
- **Release manager / second pilot** (release gate + post-deploy watch, deploying our own hackathon repo) —
  mechanically excellent and zero infra tax, but it is a merge of the two most-copied cards on the
  organizers' own list, and the incident has to be staged.
- **Backup restore prover** — best answer to the video's opening lie, but weaker UI structure and higher
  infra tax than what we picked.
- **Personal finance / statement parser** — best sandbox story and best mass-market impact, but weak
  irreversibility and no natural reason for a long session. Two of the five main-track points lost.
- **Incident responder** — marked "hero project" by the organizers. Judges will see it fifteen times.

## Lessons that survived
- The mechanism space for agent safety is picked clean by 2026 academia. Do not hunt for a new safety
  mechanism; pick a domain where the mechanism is native.
- One narrow job finished beats a platform with three half-features. The demo is three minutes.
- Anything that needs a fake world built around it (fake prod, seeded cloud junk, a ticket system) is a pure
  deduction: those days score nothing in any criterion.
- Never seed a fake history or fake timestamps. A judge who asks "is that real?" and gets "no" is lost.
