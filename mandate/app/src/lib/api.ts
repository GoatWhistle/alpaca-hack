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
  kind: "trigger" | "news" | "reasoning" | "tool_call" | "tool_result"
    | "position_watch" | "hypothesis" | "critics" | "plan" | "execution" | "risk_exit" | "session";
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

export interface BrokerTradeOrder {
  id: string | null;
  client_order_id: string | null;
  replaces: string | null;
  replaced_by: string | null;
  symbol: string | null;
  asset_class: string | null;
  side: string | null;
  position_intent: string | null;
  ratio_qty: string | null;
  qty: string | null;
  filled_qty: string | null;
  filled_avg_price: string | null;
  order_class: string | null;
  status: string | null;
  submitted_at: string | null;
  filled_at: string | null;
  legs: BrokerTradeOrder[];
}

const TIMELINE_KINDS = new Set<TraderTimelineEvent["kind"]>([
  "trigger", "news", "reasoning", "tool_call", "tool_result", "hypothesis",
  "position_watch", "critics", "plan", "execution", "risk_exit", "session",
]);
const TIMELINE_STATUSES = new Set<TraderTimelineEvent["status"]>([
  "ok", "parked", "submitted", "degraded",
]);

export function isTraderTimelineEvent(item: unknown, after = -1): item is TraderTimelineEvent {
  return item !== null
    && typeof item === "object"
    && (item as TraderTimelineEvent).schema === "trader.timeline.v1"
    && Number.isInteger((item as TraderTimelineEvent).sequence)
    && (item as TraderTimelineEvent).sequence > after
    && typeof (item as TraderTimelineEvent).at === "string"
    && typeof (item as TraderTimelineEvent).trading_date === "string"
    && TIMELINE_KINDS.has((item as TraderTimelineEvent).kind)
    && TIMELINE_STATUSES.has((item as TraderTimelineEvent).status)
    && ((item as TraderTimelineEvent).session_id === null
      || typeof (item as TraderTimelineEvent).session_id === "string")
    && typeof (item as TraderTimelineEvent).summary === "string"
    && (item as TraderTimelineEvent).summary.length <= 4_000
    && typeof (item as TraderTimelineEvent).details === "object"
    && (item as TraderTimelineEvent).details !== null;
}

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
  tradingDate?: string,
  latest?: number,
): Promise<TraderTimelinePage> {
  const query = new URLSearchParams({ after: String(after), limit: String(limit) });
  if (tradingDate) query.set("trading_date", tradingDate);
  if (latest !== undefined) query.set("latest", String(latest));
  const response = await fetch(`${getApiBase()}/api/trader/timeline?${query}`, {
    headers: { Accept: "application/json" },
    cache: "no-store",
    signal,
  });
  if (!response.ok) throw new Error(await readError(response, `Dashboard API returned ${response.status}`));
  // A stale dashboard build answers unknown API paths with the SPA index.
  if (!(response.headers.get("content-type") ?? "").includes("application/json")) {
    throw new Error("The dashboard API is too old to serve the trader timeline");
  }
  const payload = await response.json() as Partial<TraderTimelinePage>;
  let previousSequence = after;
  const validItems = Array.isArray(payload.items) && payload.items.every((item) => {
    const valid = isTraderTimelineEvent(item, previousSequence);
    if (valid) previousSequence = item.sequence;
    return valid;
  });
  if (payload.schema !== "trader.timeline.page.v1" || !validItems
    || !Number.isInteger(payload.next_after) || Number(payload.next_after) < previousSequence) {
    throw new Error("The dashboard API returned an invalid trader timeline");
  }
  return payload as TraderTimelinePage;
}

export async function getBrokerTradeOrders(signal?: AbortSignal): Promise<BrokerTradeOrder[]> {
  const response = await fetch(`${getApiBase()}/api/trade-history/orders`, {
    headers: { Accept: "application/json" },
    cache: "no-store",
    signal,
  });
  if (!response.ok) throw new Error(await readError(response, `Dashboard API returned ${response.status}`));
  const payload = await response.json() as { schema?: unknown; items?: unknown };
  if (payload.schema !== "trade.orders.v1" || !Array.isArray(payload.items)) {
    throw new Error("The dashboard API returned invalid broker order history");
  }
  return payload.items as BrokerTradeOrder[];
}

export function getTraderStreamUrl(after = 0, tradingDate?: string): string {
  const query = new URLSearchParams({ after: String(after) });
  if (tradingDate) query.set("trading_date", tradingDate);
  return `${getApiBase()}/api/trader/stream?${query}`;
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
