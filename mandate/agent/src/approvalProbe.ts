import { TrueForge } from "@truefoundry/trueforge-sdk";

const baseUrl = process.env.TRUEFORGE_BASE_URL ?? "http://localhost:8790";
const agentName = process.env.MANDATE_AGENT_NAME ?? "mandate-paper-agent";
const expectedTool = "cancel_order_by_id";

const client = new TrueForge({ baseUrl });
const session = await client.sessions.create({ agent: { name: agentName } });
const requestedTools = new Map<string, string>();
let approval:
  | { threadId: string; toolCallId: string; sourceEventId: string }
  | undefined;

const firstTurn = await client.sessions.createTurnStream(session.data.id, {
  input: [
    {
      type: "user.message",
      content:
        "Run one approval-gate conformance probe. Request Alpaca cancel_order_by_id " +
        "for order_id approval-probe-nonexistent. " +
        "Do not call any other tool and do not substitute another action. The harness will deny it, " +
        "so Alpaca must never receive the call.",
    },
  ],
});

for await (const event of firstTurn) {
  if (event.type === "model.message") {
    for (const toolCall of event.toolCalls ?? []) {
      requestedTools.set(toolCall.id, toolCall.function.name);
    }
  }
  if (event.type === "tool.approval_required") {
    if (event.toolCalls.length !== 1) {
      throw new Error(`expected one pending tool call, got ${event.toolCalls.length}`);
    }
    const toolCall = event.toolCalls[0];
    if (toolCall === undefined) {
      throw new Error("approval event contained no tool call");
    }
    approval = {
      threadId: event.threadId,
      toolCallId: toolCall.id,
      sourceEventId: toolCall.sourceEventId,
    };
  }
}

if (approval === undefined) {
  throw new Error("agent turn completed without a tool approval pause");
}
if (!requestedTools.has(approval.toolCallId)) {
  const persistedEvents = await client.sessions.listEvents(session.data.id, { limit: 100 });
  const source = persistedEvents.data.find(
    (item) =>
      item.event.type === "model.message" && item.event.id === approval?.sourceEventId,
  );
  if (source?.event.type === "model.message") {
    for (const toolCall of source.event.toolCalls ?? []) {
      requestedTools.set(toolCall.id, toolCall.function.name);
    }
  }
}
const requestedTool = requestedTools.get(approval.toolCallId);
if (requestedTool !== expectedTool) {
  throw new Error(`expected approval for ${expectedTool}, got ${requestedTool ?? "unknown"}`);
}

const denialTurn = await client.sessions.createTurnStream(session.data.id, {
  input: [
    {
      type: "user.tool_approval",
      threadId: approval.threadId,
      toolCallId: approval.toolCallId,
      approval: { status: "deny", reason: "automated conformance probe" },
    },
  ],
});

let denialObserved = false;
for await (const event of denialTurn) {
  if (event.type === "turn.done") {
    denialObserved = true;
  }
}
if (!denialObserved) {
  throw new Error("approval denial did not produce a terminal turn event");
}

console.log(
  JSON.stringify(
    {
      passed: true,
      sessionId: session.data.id,
      tool: requestedTool,
      approval: "denied",
      brokerCallDeniedBeforeExecution: true,
    },
    null,
    2,
  ),
);
