import { SnapshotSchema, type Snapshot } from "./schema";

export type { Snapshot, Journal, ServiceStatus } from "./schema";

export interface ApprovalDecision {
  sessionId: string;
  toolCallId: string;
  threadId: string;
  approve: boolean;
  reason?: string;
}

function getApiBase(): string {
  if (import.meta.env.VITE_MANDATE_API_URL) {
    return import.meta.env.VITE_MANDATE_API_URL;
  }
  const hostname = window.location.hostname;
  if (hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1") {
    return `${window.location.protocol}//127.0.0.1:8030`;
  }
  // Production serves the UI and proxies /api from the same origin. This
  // avoids exposing the companion dashboard port or causing mixed-content
  // failures when the operator console is behind HTTPS.
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

export async function setDemoMode(enabled: boolean): Promise<void> {
  const response = await fetch(`${getApiBase()}/api/demo`, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({ enabled, confirmed: true }),
  });
  if (!response.ok) {
    throw new Error(await readError(response, `Dashboard API returned ${response.status}`));
  }
}
