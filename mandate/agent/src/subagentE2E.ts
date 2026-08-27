import { TrueForge } from "@truefoundry/trueforge-sdk";

const baseUrl = process.env.TRUEFORGE_BASE_URL ?? "http://localhost:8790";
const agentName = process.env.MANDATE_AGENT_NAME ?? "mandate-paper-agent";
const forbidden = ["submit_order_under_mandate", "cancel_order", "close_position", "park"];

const client = new TrueForge({ baseUrl });
const session = await client.sessions.create({ agent: { name: agentName } });
const stream = await client.sessions.createTurnStream(session.data.id, {
  input: [
    {
      type: "user.message",
      content:
        "Run a read-only dynamic-subagent conformance probe. Delegate exactly two independent " +
        "tasks with create_sub_agent: (1) verify AAPL news-source health using only " +
        "probe_news_sources; (2) compare AAPL live signals and current mandate headroom using only " +
        "compare_live_signals and get_mandate. Run them in parallel if supported, then synthesize " +
        "their final answers. Do not call check_order, park, submit, cancel, close, or request approval.",
    },
  ],
});

let approvalObserved = false;
for await (const event of stream) {
  if (event.type === "tool.approval_required") approvalObserved = true;
}
if (approvalObserved) throw new Error("read-only subagent probe requested approval");

const events = await client.sessions.listEvents(session.data.id, { limit: 100 });
const toolNames = new Set<string>();
const threadIds = new Set<string>();
let createSubAgentCalls = 0;
for (const item of events.data) {
  const event = item.event;
  if ("threadId" in event && typeof event.threadId === "string") {
    threadIds.add(event.threadId);
  }
  if (event.type !== "model.message") continue;
  for (const call of event.toolCalls ?? []) {
    toolNames.add(call.function.name);
    const serialized = `${call.function.name}\n${call.function.arguments}`;
    if (serialized.includes("create_sub_agent")) createSubAgentCalls += 1;
    for (const name of forbidden) {
      if (
        call.function.name === name ||
        (call.function.name === "call_tool" && call.function.arguments.includes(name))
      ) {
        throw new Error(`forbidden tool appeared in subagent probe: ${name}`);
      }
    }
  }
}
if (createSubAgentCalls !== 2) {
  throw new Error(`expected exactly two create_sub_agent calls, got ${createSubAgentCalls}`);
}
if (threadIds.size < 3) {
  throw new Error(`expected root plus two isolated threads, got ${threadIds.size}`);
}

console.log(
  JSON.stringify(
    {
      passed: true,
      sessionId: session.data.id,
      createSubAgentCalls,
      isolatedThreads: threadIds.size - 1,
      toolNames: [...toolNames].sort(),
      approvalObserved,
      brokerWriteAttempted: false,
    },
    null,
    2,
  ),
);
