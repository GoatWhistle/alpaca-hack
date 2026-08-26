Task:
You need to build an agent that takes real action (rather than just providing responses) using the TrueForge harness (open source, from TrueFoundry). Key features include connecting real tools via MCP, executing generated code in a sandbox, pausing for human approval before irreversible actions, delegating to sub-agents, and maintaining session resilience against connection drops.

Getting Started
Quick start:
`npx @truefoundry/trueforge` (no cloning required).
Production mode:
`git clone git@github.com:truefoundry/trueforge.git && cd trueforge && docker compose up`.
Next steps: 
connect a model (your choice—OpenAI, Anthropic, Gemini, DeepSeek, or a compatible endpoint) and MCP servers (tools).
Documentation: 
trueforge.dev. Install Qodo (free, open-source)—qodo.ai.

Key Capabilities (8 points)
Integration with any MCP tools (40+ built-in + web search), secure sandboxed code execution, human-in-the-loop approval for sensitive actions, sub-agents, session persistence, model-agnostic operation, skill loading, and scalability (local SQLite → Postgres/Redis in production).

Useful links:
TrueForge: github.com/truefoundry/trueforge
Docs: trueforge.dev
Qodo: qodo.ai
