import { SnapshotSchema, type Snapshot } from "./schema";

export type { Snapshot, Journal, ServiceStatus } from "./schema";

export interface ApprovalDecision {
  sessionId: string;
  toolCallId: string;
  threadId: string;
  approve: boolean;
  reason?: string;
}

export interface TraderTimelineEvent {
  schema: "trader.timeline.v1";
  sequence: number;
  at: string;
  trading_date: string;
  kind: "critics" | "plan" | "execution" | "risk_exit" | "session";
  status: "ok" | "parked" | "submitted" | "degraded";
  session_id: string | null;
  summary: string;
  details: Record<string, unknown>;
}

export interface TraderTimelinePage {
  schema: "trader.timeline.page.v1";
  items: TraderTimelineEvent[];
  next_after: number;
}

const TIMELINE_KINDS = new Set<TraderTimelineEvent["kind"]>([
  "critics", "plan", "execution", "risk_exit", "session",
]);
const TIMELINE_STATUSES = new Set<TraderTimelineEvent["status"]>([
  "ok", "parked", "submitted", "degraded",
]);

function getApiBase(): string {
  if (import.meta.env.VITE_MANDATE_API_URL) {
    return import.meta.env.VITE_MANDATE_API_URL;
  }
  if (import.meta.env.BASE_URL !== "/") {
    return new URL(import.meta.env.BASE_URL, window.location.origin).toString().replace(/\/$/u, "");
  }
  // Both the dashboard server and Vite's development proxy expose /api on the
  // current origin. This also keeps SSH-tunnel deployments port-agnostic.
  return window.location.origin;
}

async function readError(response: Response, fallback: string): Promise<string> {
  const body = await response.json().catch(() => ({})) as Record<string, unknown>;
  return String(body.error ?? fallback);
}

export async function getSnapshot(signal?: AbortSignal): Promise<Snapshot> {
  const response = await fetch(`${getApiBase()}/api/snapshot`, {
    headers: { Accept: "application/json" },
    cache: "no-store",
    signal,
  });
  if (!response.ok) {
    throw new Error(`Dashboard API returned ${response.status}`);
  }
  const parsed = SnapshotSchema.safeParse(await response.json());
  if (!parsed.success) {
    console.error("Snapshot failed validation", parsed.error.issues);
    throw new Error("The dashboard API returned a snapshot this console cannot read");
  }
  return parsed.data;
}

export async function getTraderTimeline(
  after = 0,
  limit = 200,
  signal?: AbortSignal,
): Promise<TraderTimelinePage> {
  const query = new URLSearchParams({ after: String(after), limit: String(limit) });
  const response = await fetch(`${getApiBase()}/api/trader/timeline?${query}`, {
    headers: { Accept: "application/json" },
    cache: "no-store",
    signal,
  });
  if (!response.ok) throw new Error(await readError(response, `Dashboard API returned ${response.status}`));
  const payload = await response.json() as Partial<TraderTimelinePage>;
  const validItems = Array.isArray(payload.items) && payload.items.every((item) => (
    item !== null
    && typeof item === "object"
    && item.schema === "trader.timeline.v1"
    && Number.isInteger(item.sequence)
    && typeof item.at === "string"
    && typeof item.trading_date === "string"
    && TIMELINE_KINDS.has(item.kind)
    && TIMELINE_STATUSES.has(item.status)
    && (item.session_id === null || typeof item.session_id === "string")
    && typeof item.summary === "string"
    && typeof item.details === "object"
    && item.details !== null
  ));
  if (payload.schema !== "trader.timeline.page.v1" || !validItems
    || !Number.isInteger(payload.next_after)) {
    throw new Error("The dashboard API returned an invalid trader timeline");
  }
  return payload as TraderTimelinePage;
}

export async function updateTrajectory(
  payload: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const response = await fetch(`${getApiBase()}/api/trajectory`, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({ ...payload, confirmed: true }),
  });
  const body = await response.json() as Record<string, unknown>;
  if (!response.ok) {
    throw new Error(String(body.error ?? `Dashboard API returned ${response.status}`));
  }
  return body;
}

export async function respondToApproval(payload: ApprovalDecision): Promise<void> {
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
    throw new Error(await readError(response, `Dashboard API returned ${response.status}`));
  }
}
