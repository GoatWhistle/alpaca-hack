import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

import { TrueForge } from "@truefoundry/trueforge-sdk";

const baseUrl = process.env.TRUEFORGE_BASE_URL ?? "http://localhost:8790";
const agentName = process.env.MANDATE_AGENT_NAME ?? "mandate-paper-agent";
const journalPath = resolve(process.env.MANDATE_JOURNAL_PATH ?? "../logs/session.jsonl");
const orderId = process.env.MANDATE_E2E_CANCEL_ORDER_ID ?? "";
const clientOrderId = process.env.MANDATE_E2E_CANCEL_CLIENT_ORDER_ID ?? "";
const auditSessionId = process.env.MANDATE_E2E_CANCEL_SESSION_ID;
if (process.env.MANDATE_E2E_ALLOW !== "true") {
  throw new Error("cancellation requires MANDATE_E2E_ALLOW=true after human authorization");
}
if (!/^[a-f0-9-]{36}$/u.test(orderId) || !clientOrderId.startsWith("mandate-")) {
  throw new Error("exact broker order ID and mandate client order ID are required");
}

const entries = (await readFile(journalPath, "utf8"))
  .split("\n")
  .filter(Boolean)
  .map((line) => JSON.parse(line) as Record<string, unknown>);
const hasProvenance = entries.some((entry) => {
  const details = entry.details;
  return (
    entry.action === "submit_order" &&
    entry.outcome === "submitted" &&
    typeof details === "object" &&
    details !== null &&
    "client_order_id" in details &&
    details.client_order_id === clientOrderId
  );
});
if (!hasProvenance) throw new Error("refusing cleanup without durable submitted provenance");
const before = entries.length;

const client = new TrueForge({ baseUrl });
if (auditSessionId !== undefined) {
  const persisted = await client.sessions.listEvents(auditSessionId, { limit: 100 });
  const cancelCall = persisted.data
    .flatMap((item) =>
      item.event.type === "model.message" ? (item.event.toolCalls ?? []) : [],
    )
    .find((item) => item.function.name === "cancel_order");
  if (cancelCall === undefined) throw new Error("audited session has no cancel_order call");
  const auditedArgs = JSON.parse(cancelCall.function.arguments) as Record<string, unknown>;
  if (auditedArgs.order_id !== orderId) throw new Error("audited cancel changed the order ID");
  const approvalWasRequired = persisted.data.some(
    (item) =>
      item.event.type === "tool.approval_required" &&
      item.event.toolCalls.some((call) => call.id === cancelCall.id),
  );
  const response = persisted.data.find(
    (item) =>
      item.event.type === "tool.response" && item.event.toolCallId === cancelCall.id,
  );
  const responseContent = response?.event.type === "tool.response" ? response.event.content : "";
  const journalProvesCancel = entries.some((entry) => {
    const details = entry.details;
    return (
      entry.action === "cancel_order" &&
      entry.outcome === "submitted" &&
      typeof details === "object" &&
      details !== null &&
      "order_id" in details &&
      details.order_id === orderId
    );
  });
  if (
    !approvalWasRequired ||
    !journalProvesCancel ||
    (!responseContent.includes('"cancelled":true') &&
      !responseContent.includes('"cancelled": true'))
  ) {
    throw new Error("audited cancellation lacks approval, response, or journal evidence");
  }
  console.log(
    JSON.stringify(
      {
        passed: true,
        sessionId: auditSessionId,
        orderId,
        clientOrderId,
        approval: "allowed",
        journalOutcome: "submitted",
        auditedWithoutReplay: true,
      },
      null,
      2,
    ),
  );
  process.exit(0);
}
const session = await client.sessions.create({ agent: { name: agentName } });
const first = await client.sessions.createTurnStream(session.data.id, {
  input: [
    {
      type: "user.message",
      content:
        `Cancel the exact paper order ${orderId} through mandate-guard cancel_order with ` +
        "rationale 'supervised E2E cleanup'. Do not call any other tool or change the order ID.",
    },
  ],
});
let approval:
  | { threadId: string; toolCallId: string; sourceEventId: string }
  | undefined;
for await (const event of first) {
  if (event.type === "tool.approval_required") {
    if (approval !== undefined || event.toolCalls.length !== 1) {
      throw new Error("expected exactly one cancel approval");
    }
    const call = event.toolCalls[0];
    if (call === undefined) throw new Error("cancel approval had no tool call");
    approval = {
      threadId: event.threadId,
      toolCallId: call.id,
      sourceEventId: call.sourceEventId,
    };
  }
}
if (approval === undefined) throw new Error("cancel did not pause for approval");

const persisted = await client.sessions.listEvents(session.data.id, { limit: 100 });
const source = persisted.data.find(
  (item) =>
    item.event.type === "model.message" && item.event.id === approval?.sourceEventId,
);
if (source?.event.type !== "model.message") throw new Error("cancel source was not persisted");
const call = source.event.toolCalls?.find((item) => item.id === approval?.toolCallId);
if (call?.function.name !== "cancel_order") {
  throw new Error(`refusing approval for unexpected tool ${call?.function.name ?? "unknown"}`);
}
const args = JSON.parse(call.function.arguments) as Record<string, unknown>;
if (args.order_id !== orderId || typeof args.rationale !== "string" || !args.rationale.trim()) {
  throw new Error("refusing approval for changed cancel arguments");
}

const resumed = await client.sessions.createTurnStream(session.data.id, {
  input: [
    {
      type: "user.tool_approval",
      threadId: approval.threadId,
      toolCallId: approval.toolCallId,
      approval: { status: "allow" },
    },
  ],
});
const responses: string[] = [];
for await (const event of resumed) {
  if (event.type === "tool.response") responses.push(event.content);
  if (event.type === "tool.approval_required") {
    throw new Error("unexpected second approval during one cancel");
  }
}
const after = (await readFile(journalPath, "utf8"))
  .split("\n")
  .filter(Boolean)
  .map((line) => JSON.parse(line) as Record<string, unknown>);
const cleanupEntries = after.slice(before);
const journalProvesCancel = cleanupEntries.some((entry) => {
  const details = entry.details;
  return (
    entry.action === "cancel_order" &&
    entry.outcome === "submitted" &&
    typeof details === "object" &&
    details !== null &&
    "order_id" in details &&
    details.order_id === orderId
  );
});
const responseProvesCancel = responses.some(
  (content) => content.includes('"cancelled":true') || content.includes('"cancelled": true'),
);
if (!journalProvesCancel || !responseProvesCancel) {
  throw new Error("approved cancellation lacks tool-response or journal evidence");
}

console.log(
  JSON.stringify(
    {
      passed: true,
      sessionId: session.data.id,
      orderId,
      clientOrderId,
      approval: "allowed",
      journalOutcome: "submitted",
    },
    null,
    2,
  ),
);
