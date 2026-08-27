import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

import { TrueForge } from "@truefoundry/trueforge-sdk";

type Approval = {
  threadId: string;
  toolCallId: string;
  sourceEventId: string;
};

type PhaseResult = {
  approval?: Approval;
  toolResponses: string[];
};

const baseUrl = process.env.TRUEFORGE_BASE_URL ?? "http://localhost:8790";
const agentName = process.env.MANDATE_AGENT_NAME ?? "mandate-paper-agent";
const journalPath = resolve(
  process.env.MANDATE_JOURNAL_PATH ?? "../logs/session.jsonl",
);
const intentId = process.env.MANDATE_E2E_INTENT_ID ?? "e2e-aapl-20260827-v1";
const allow = process.env.MANDATE_E2E_ALLOW === "true";
const expectedOrder = {
  symbol: "AAPL",
  side: "buy",
  qty: "1",
  order_type: "limit",
  limit_price: "1",
  instrument: "equity",
  intent_id: intentId,
};

async function journalEntries(): Promise<Record<string, unknown>[]> {
  let content: string;
  try {
    content = await readFile(journalPath, "utf8");
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT") {
      return [];
    }
    throw error;
  }
  return content
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line) as Record<string, unknown>);
}

function submitRecords(entries: Record<string, unknown>[]): Record<string, unknown>[] {
  return entries.filter((entry) => {
    if (entry.action !== "submit_order") return false;
    const details = entry.details;
    return (
      typeof details === "object" &&
      details !== null &&
      "intent_id" in details &&
      details.intent_id === intentId
    );
  });
}

function detail(entry: Record<string, unknown>, key: string): string | undefined {
  const details = entry.details;
  if (typeof details !== "object" || details === null || !(key in details)) return undefined;
  const value = details[key as keyof typeof details];
  return typeof value === "string" ? value : undefined;
}

async function runPhase(
  client: TrueForge,
  sessionId: string,
  content: string,
): Promise<PhaseResult> {
  const stream = await client.sessions.createTurnStream(sessionId, {
    input: [{ type: "user.message", content }],
  });
  const result: PhaseResult = { toolResponses: [] };
  for await (const event of stream) {
    if (event.type === "tool.response") {
      result.toolResponses.push(event.content);
    }
    if (event.type === "tool.approval_required") {
      if (result.approval !== undefined || event.toolCalls.length !== 1) {
        throw new Error("expected exactly one pending tool approval");
      }
      const toolCall = event.toolCalls[0];
      if (toolCall === undefined) throw new Error("approval event has no tool call");
      result.approval = {
        threadId: event.threadId,
        toolCallId: toolCall.id,
        sourceEventId: toolCall.sourceEventId,
      };
    }
  }
  return result;
}

async function persistedToolCall(
  client: TrueForge,
  sessionId: string,
  approval: Approval,
) {
  const events = await client.sessions.listEvents(sessionId, { limit: 100 });
  const source = events.data.find(
    (item) =>
      item.event.type === "model.message" && item.event.id === approval.sourceEventId,
  );
  if (source?.event.type !== "model.message") {
    throw new Error("approval source model.message was not persisted");
  }
  const call = source.event.toolCalls?.find((item) => item.id === approval.toolCallId);
  if (call === undefined) throw new Error("approved tool call was not found in source event");
  return call;
}

function verifySubmitCall(call: Awaited<ReturnType<typeof persistedToolCall>>): void {
  if (call.function.name !== "submit_order_under_mandate") {
    throw new Error(`refusing approval for unexpected tool ${call.function.name}`);
  }
  const args = JSON.parse(call.function.arguments) as Record<string, unknown>;
  for (const [key, expected] of Object.entries(expectedOrder)) {
    const actual = args[key] ?? (key === "instrument" ? "equity" : undefined);
    if (String(actual) !== expected) {
      throw new Error(`refusing approval: ${key} expected ${expected}, got ${String(actual)}`);
    }
  }
  if (typeof args.rationale !== "string" || args.rationale.trim() === "") {
    throw new Error("refusing approval without a non-empty rationale");
  }
}

async function approve(
  client: TrueForge,
  sessionId: string,
  approval: Approval,
): Promise<string[]> {
  if (!allow) {
    throw new Error("approval requested; rerun with MANDATE_E2E_ALLOW=true after human authorization");
  }
  const stream = await client.sessions.createTurnStream(sessionId, {
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
  for await (const event of stream) {
    if (event.type === "tool.response") responses.push(event.content);
    if (event.type === "tool.approval_required") {
      throw new Error("unexpected second approval request during one execution phase");
    }
  }
  return responses;
}

function closedMarketWasObserved(responses: string[]): boolean {
  return responses.some(
    (content) => content.includes('"rule":"session"') || content.includes('"rule": "session"'),
  );
}

const before = submitRecords(await journalEntries());
const client = new TrueForge({ baseUrl });
const session = await client.sessions.create({ agent: { name: agentName } });
const instruction =
  `Run the supervised paper E2E for intent ${intentId}. First call check_order for ` +
  "AAPL buy 1 share, limit order at $1, equity. If any breach exists, stop without calling park or " +
  "any write tool and report the breach. If allowed, call submit_order_under_mandate with exactly " +
  `those terms and intent_id ${intentId}. Use a concise non-empty E2E rationale. Do not resize, ` +
  "change price, symbol, side, type, or intent ID.";
const execution = await runPhase(client, session.data.id, instruction);

if (execution.approval === undefined) {
  const after = submitRecords(await journalEntries());
  if (!closedMarketWasObserved(execution.toolResponses) || after.length !== before.length) {
    throw new Error("no approval pause and no proven fail-closed market-session breach");
  }
  console.log(
    JSON.stringify(
      {
        passed: true,
        completed: false,
        deferred: "market_closed",
        sessionId: session.data.id,
        brokerWriteAttempted: false,
      },
      null,
      2,
    ),
  );
  process.exit(0);
}

const call = await persistedToolCall(client, session.data.id, execution.approval);
verifySubmitCall(call);
const responses = await approve(client, session.data.id, execution.approval);
const after = submitRecords(await journalEntries());
const newRecords = after.slice(before.length);
const outcomes = newRecords.map((entry) => String(entry.outcome));
if (!outcomes.includes("prepared") || !outcomes.includes("submitted")) {
  throw new Error(`broker submission lacks durable prepared/submitted evidence: ${outcomes.join(",")}`);
}
const clientOrderIds = new Set(newRecords.map((entry) => detail(entry, "client_order_id")));
const mandateFingerprints = new Set(
  newRecords.map((entry) => detail(entry, "mandate_fingerprint")),
);
if (clientOrderIds.size !== 1 || clientOrderIds.has(undefined)) {
  throw new Error("prepared/submitted records do not share one durable client order ID");
}
const mandateFingerprint = [...mandateFingerprints][0];
if (
  mandateFingerprints.size !== 1 ||
  mandateFingerprint === undefined ||
  !/^[a-f0-9]{64}$/.test(mandateFingerprint)
) {
  throw new Error("prepared/submitted records lack one valid mandate fingerprint");
}
if (!responses.some((content) => content.includes('"submitted":true') || content.includes('"submitted": true'))) {
  throw new Error("approved tool response did not report a paper submission");
}

const retryInstruction =
  `Retry the already approved intent ${intentId} to verify idempotency. Call check_order, then call ` +
  "submit_order_under_mandate with exactly AAPL buy 1 share, limit order at $1, equity, the same " +
  `intent_id ${intentId}, and a non-empty retry rationale. Do not change any execution term.`;
const retry = await runPhase(client, session.data.id, retryInstruction);
if (retry.approval === undefined) {
  throw new Error("idempotency retry did not pause for its own explicit approval");
}
const retryCall = await persistedToolCall(client, session.data.id, retry.approval);
verifySubmitCall(retryCall);
const retryResponses = await approve(client, session.data.id, retry.approval);
const finalRecords = submitRecords(await journalEntries());
const retryOutcomes = finalRecords.slice(after.length).map((entry) => String(entry.outcome));
if (retryOutcomes.includes("submitted") || !retryOutcomes.includes("deduplicated")) {
  throw new Error(`retry was not cleanly deduplicated: ${retryOutcomes.join(",")}`);
}
const clientOrderId = [...clientOrderIds][0];
if (
  finalRecords.slice(after.length).some(
    (entry) =>
      detail(entry, "client_order_id") !== clientOrderId ||
      detail(entry, "mandate_fingerprint") !== mandateFingerprint,
  )
) {
  throw new Error("deduplicated retry lost its original mandate or client-order provenance");
}
if (
  !retryResponses.some(
    (content) =>
      (content.includes('"submitted":true') || content.includes('"submitted": true')) &&
      (content.includes('"deduplicated":true') || content.includes('"deduplicated": true')),
  )
) {
  throw new Error("retry tool response did not report deduplicated=true");
}

console.log(
  JSON.stringify(
    {
      passed: true,
      completed: true,
      sessionId: session.data.id,
      intentId,
      tool: call.function.name,
      approval: "allowed",
      clientOrderId,
      mandateFingerprint,
      journalOutcomes: outcomes,
      retryApproval: "allowed",
      retryJournalOutcomes: retryOutcomes,
      deduplicated: true,
    },
    null,
    2,
  ),
);
