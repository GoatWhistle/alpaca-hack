import { TrueForge } from "@truefoundry/trueforge-sdk";

import { loadWorkspaceEnv } from "./workspaceEnv.js";

loadWorkspaceEnv();

const timeoutSeconds = Math.min(
  60,
  Math.max(5, Number(process.env.MANDATE_MODEL_SMOKE_TIMEOUT_SECONDS ?? 30)),
);
const client = new TrueForge({
  baseUrl: process.env.TRUEFORGE_BASE_URL ?? "http://localhost:8790",
  token: process.env.TRUEFORGE_API_KEY || undefined,
  maxRetries: 0,
});

const agents = [
  process.env.MANDATE_AGENT_NAME ?? "mandate-paper-agent",
  process.env.MANDATE_RISK_CRITIC_AGENT ?? "mandate-risk-critic",
  process.env.MANDATE_MARKET_CRITIC_AGENT ?? "mandate-market-critic",
  process.env.MANDATE_EXECUTION_CRITIC_AGENT ?? "mandate-execution-critic",
];

function eventText(event: { content?: unknown }): string {
  if (typeof event.content === "string") return event.content.trim();
  if (!Array.isArray(event.content)) return "";
  return event.content.flatMap((part) => {
    if (typeof part !== "object" || part === null) return [];
    const item = part as Record<string, unknown>;
    return item.type === "text" && typeof item.text === "string" ? [item.text] : [];
  }).join("\n").trim();
}

async function probe(agent: string): Promise<Record<string, unknown>> {
  const startedAt = performance.now();
  let sessionId: string | undefined;
  try {
    const requestOptions = {
      timeoutInSeconds: timeoutSeconds,
      maxRetries: 0,
      abortSignal: AbortSignal.timeout(timeoutSeconds * 1_000),
    };
    const session = await client.sessions.create({ agent: { name: agent } }, requestOptions);
    sessionId = session.data.id;
    const stream = await client.sessions.createTurnStream(sessionId, {
      input: [{
        type: "user.message",
        content: "Read-only readiness probe. Do not use tools. Reply with exactly READY.",
      }],
    }, requestOptions);
    let text = "";
    let toolCalls = 0;
    for await (const event of stream) {
      if (event.type === "model.message") {
        text = eventText(event) || text;
        toolCalls += event.toolCalls?.length ?? 0;
      } else if (event.type === "tool.approval_required" || event.type === "tool.response") {
        toolCalls += 1;
      } else if (event.type === "turn.done") {
        if (event.state.status === "error") throw new Error(event.state.message);
        if (event.state.status === "cancelled") throw new Error(event.state.reason);
        if (event.state.output) {
          text = eventText(event.state.output) || text;
          toolCalls += event.state.output.toolCalls?.length ?? 0;
        }
      }
    }
    const ready = text.trim().toUpperCase() === "READY" && toolCalls === 0;
    return {
      agent,
      ready,
      latency_ms: Math.round(performance.now() - startedAt),
      response: text.slice(0, 80),
      tool_calls: toolCalls,
    };
  } catch (error) {
    const message = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
    return {
      agent,
      ready: false,
      latency_ms: Math.round(performance.now() - startedAt),
      error: message.split(/\r?\n/u, 1)[0]?.slice(0, 180),
    };
  } finally {
    if (sessionId) {
      try {
        await client.sessions.delete(sessionId, {
          timeoutInSeconds: 10,
          maxRetries: 0,
          abortSignal: AbortSignal.timeout(10_000),
        });
      } catch {
        // A readiness result should not be hidden by best-effort test-session cleanup.
      }
    }
  }
}

const results = await Promise.all(agents.map(probe));
console.log(JSON.stringify({ timeout_seconds: timeoutSeconds, results }, null, 2));
if (results.some((result) => result.ready !== true)) process.exitCode = 1;
