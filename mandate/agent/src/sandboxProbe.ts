import { TrueForge } from "@truefoundry/trueforge-sdk";

const client = new TrueForge({
  baseUrl: process.env.TRUEFORGE_BASE_URL ?? "http://localhost:8790",
});
const session = await client.sessions.create({
  agent: { name: process.env.MANDATE_AGENT_NAME ?? "mandate-paper-agent" },
});
const stream = await client.sessions.createTurnStream(session.data.id, {
  input: [
    {
      type: "user.message",
      content:
        "AUTONOMY CYCLE conformance probe. Use only exec to calculate 7 * 6 with deterministic " +
        "code, then report the result and end with ACTION: PARK. Do not call MCP, broker, approval, " +
        "trajectory-write, or any other tool.",
    },
  ],
});

let approvalObserved = false;
for await (const event of stream) {
  if (event.type === "tool.approval_required") approvalObserved = true;
}
if (approvalObserved) throw new Error("sandbox-only probe unexpectedly requested approval");

const events = await client.sessions.listEvents(session.data.id, { limit: 100 });
const calls = events.data.flatMap((item) =>
  item.event.type === "model.message" ? (item.event.toolCalls ?? []) : [],
);
if (calls.length !== 1 || calls[0]?.function.name !== "exec") {
  throw new Error(`expected exactly one exec call, got ${calls.map((call) => call.function.name)}`);
}
const response = events.data.find(
  (item) => item.event.type === "tool.response" && item.event.toolCallId === calls[0]?.id,
);
if (response?.event.type !== "tool.response" || !response.event.content.includes("42")) {
  throw new Error("sandbox response did not contain deterministic result 42");
}

console.log(
  JSON.stringify(
    {
      passed: true,
      sessionId: session.data.id,
      tool: "exec",
      result: 42,
      approvalObserved,
      brokerWriteAttempted: false,
    },
    null,
    2,
  ),
);
