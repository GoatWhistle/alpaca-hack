import { z } from "zod";

const UnknownRecord = z.record(z.string(), z.unknown());

const JournalEntry = z.object({
  at: z.string(),
  action: z.string(),
  outcome: z.string(),
  rationale: z.string(),
  details: UnknownRecord.optional().default({}),
});

const SnapshotSchema = z.object({
  generated_at: z.string(),
  source: z.enum(["live", "degraded"]),
  paper_only: z.literal(true),
  agent_url: z.string(),
  services: z.array(
    z.object({ name: z.string(), url: z.string(), ok: z.boolean() }),
  ),
  errors: z.array(z.string()),
  mandate: z.object({
    mandate: UnknownRecord,
    as_of: z.string().nullable().optional(),
    market_is_open: z.boolean().optional().default(false),
    usage: UnknownRecord.optional().default({}),
    headroom: UnknownRecord.optional().default({}),
    wake_triggers: z.array(z.unknown()).optional().default([]),
    active_predecisions: z.array(z.unknown()).optional().default([]),
  }),
  session: z.object({
    as_of: z.string().nullable().optional(),
    account: UnknownRecord.optional().default({}),
    market: UnknownRecord.optional().default({}),
    positions: z.record(z.string(), UnknownRecord).optional().default({}),
    orders_today: z.number().optional().default(0),
    pending_orders: z.array(UnknownRecord).optional().default([]),
    journal: z.array(JournalEntry).optional().default([]),
  }),
  autonomy: z.object({
    trajectory: UnknownRecord.optional().default({}),
    runtime: UnknownRecord.optional().default({}),
    alerts: z.array(UnknownRecord).optional().default([]),
    market: UnknownRecord.optional().default({}),
    outcomes: UnknownRecord.optional().default({}),
  }).optional().default({ trajectory: {}, runtime: {}, alerts: [], market: {}, outcomes: {} }),
  approvals: z.object({
    count: z.number().optional().default(0),
    items: z.array(UnknownRecord).optional().default([]),
    error: z.string().optional(),
  }).optional().default({ count: 0, items: [] }),
});

export type Snapshot = z.infer<typeof SnapshotSchema>;
export type Journal = z.infer<typeof JournalEntry>;

export async function getSnapshot(signal?: AbortSignal): Promise<Snapshot> {
  const apiBase = getApiBase();
  const response = await fetch(`${apiBase}/api/snapshot`, {
    headers: { Accept: "application/json" },
    cache: "no-store",
    signal,
  });
  if (!response.ok) {
    throw new Error(`Dashboard API returned ${response.status}`);
  }
  return SnapshotSchema.parse(await response.json());
}

function getApiBase(): string {
  return import.meta.env.VITE_MANDATE_API_URL
    ?? `${window.location.protocol}//${window.location.hostname}:8030`;
}

export async function updateTrajectory(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
  const response = await fetch(`${getApiBase()}/api/trajectory`, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({ ...payload, confirmed: true }),
  });
  const body = await response.json() as Record<string, unknown>;
  if (!response.ok) throw new Error(String(body.error ?? `Dashboard API returned ${response.status}`));
  return body;
}

export async function respondToApproval(payload: {
  sessionId: string;
  toolCallId: string;
  threadId: string;
  approve: boolean;
  reason?: string;
}): Promise<void> {
  const response = await fetch(`${getApiBase()}/api/approvals/respond`, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: payload.sessionId,
      tool_call_id: payload.toolCallId,
      thread_id: payload.threadId,
      approve: payload.approve,
      reason: payload.reason ?? "",
      confirmed: true,
    }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as Record<string, unknown>;
    throw new Error(String(body.error ?? `Dashboard API returned ${response.status}`));
  }
}
