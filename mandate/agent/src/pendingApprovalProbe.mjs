// E2E probe: raise a real approval and LEAVE it pending, then exit.
// Prints {sessionId, threadId, toolCallId} as JSON for the dashboard test.
import { TrueForge } from "@truefoundry/trueforge-sdk";

const baseUrl = process.env.TRUEFORGE_BASE_URL ?? "http://localhost:8790";
const agentName = process.env.MANDATE_AGENT_NAME ?? "mandate-paper-agent";
const client = new TrueForge({ baseUrl });
const session = await client.sessions.create({ agent: { name: agentName } });
const sessionId = session.data.id;
const stream = await client.sessions.createTurnStream(sessionId, {
  input: [
    {
      type: "user.message",
      content:
        "Run one approval-gate conformance probe. Request mandate-guard cancel_order " +
        "for order_id approval-probe-nonexistent with rationale 'approval wiring probe'. " +
        "Do not call any other tool and do not substitute another action. The harness will deny it.",
    },
  ],
});
let approval;
for await (const event of stream) {
  if (event.type === "tool.approval_required") {
    const toolCall = event.toolCalls?.[0];
    if (!toolCall) throw new Error("approval event contained no tool call");
    approval = { threadId: event.threadId, toolCallId: toolCall.id };
    break;
  }
}
if (!approval) {
  console.error("no approval was raised");
  process.exit(1);
}
console.log(JSON.stringify({ sessionId, ...approval }));
process.exit(0);
