import { TrueForge } from "@truefoundry/trueforge-sdk";

const baseUrl = process.env.TRUEFORGE_BASE_URL ?? "http://localhost:8790";
const agentName = process.env.MANDATE_AGENT_NAME ?? "mandate-paper-agent";
const sessionLimit = Math.min(Math.max(Number(process.env.MANDATE_AUDIT_SESSIONS ?? 25), 1), 25);
const client = new TrueForge({ baseUrl, token: process.env.TRUEFORGE_API_KEY || undefined });

const agents = await client.agents.list();
const agent = agents.data.find((item) => item.name === agentName);
if (!agent) throw new Error(`agent not found: ${agentName}`);

const sessions = await client.sessions.list({ limit: sessionLimit, agentId: agent.id });
const directTools = new Map<string, number>();
const nestedTools = new Map<string, number>();
const codeFragments: string[] = [];
let modelMessages = 0;

function increment(target: Map<string, number>, key: string): void {
  target.set(key, (target.get(key) ?? 0) + 1);
}

function extractNestedTool(argumentsText: string): string | undefined {
  try {
    const payload = JSON.parse(argumentsText) as Record<string, unknown>;
    for (const key of ["name", "tool_name", "toolName"]) {
      if (typeof payload[key] === "string") return payload[key];
    }
  } catch {
    // Some Code Mode bridges embed JSON in a string; the regex remains bounded.
  }
  const match = argumentsText.match(/(?:tool_name|toolName|name)[\\"']?\s*[:=]\s*[\\"']([^\\"']+)/u);
  return match?.[1];
}

for (const session of sessions.data) {
  const events = await client.sessions.listEvents(session.id, { limit: 100 });
  for (const item of events.data) {
    const event = item.event;
    if (event.type !== "model.message") continue;
    modelMessages += 1;
    for (const call of event.toolCalls ?? []) {
      increment(directTools, call.function.name);
      if (call.function.name === "call_tool") {
        const nested = extractNestedTool(call.function.arguments);
        if (nested) increment(nestedTools, nested);
      }
      if (call.function.name === "exec") {
        codeFragments.push(call.function.arguments.slice(0, 1_200));
      }
    }
  }
}

const arithmeticTerms = [
  "percent", "percentage", "return", "drawdown", "spread", "basis point", "bps",
  "headroom", "exposure", "ratio", "change", "pnl", "profit", "loss", "vwap",
];
const arithmeticMentions: Record<string, number> = {};
for (const term of arithmeticTerms) {
  const count = codeFragments.filter((fragment) => fragment.toLowerCase().includes(term)).length;
  if (count > 0) arithmeticMentions[term] = count;
}

function ranked(values: Map<string, number>): { name: string; count: number }[] {
  return [...values].map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count);
}

console.log(JSON.stringify({
  agent: agentName,
  sessions: sessions.data.length,
  model_messages: modelMessages,
  direct_tools: ranked(directTools),
  nested_tools: ranked(nestedTools),
  exec_calls: codeFragments.length,
  arithmetic_mentions_in_exec: arithmeticMentions,
  exec_samples: codeFragments.slice(0, 3),
}, null, 2));
