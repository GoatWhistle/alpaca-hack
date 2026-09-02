/**
 * Minimal MCP streamable-HTTP client for the official Alpaca MCP server.
 *
 * The runner uses it for read-only broker state (account, positions). Every
 * response is validated by the caller and any failure falls back to the
 * direct paper REST read, so trading logic never depends on this transport.
 */

const PROTOCOL_VERSION = "2025-06-18";

type JsonRpcRequest = {
  jsonrpc: "2.0";
  id?: number;
  method: string;
  params?: Record<string, unknown>;
};

type JsonRpcResponse = {
  jsonrpc?: string;
  id?: number | string | null;
  result?: unknown;
  error?: { code?: number; message?: string };
};

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

/** Parse a streamable-HTTP body: plain JSON or an SSE stream of JSON-RPC messages. */
export function parseMcpBody(contentType: string, body: string): JsonRpcResponse[] {
  const trimmed = body.trim();
  if (!trimmed) return [];
  if (!contentType.toLowerCase().includes("text/event-stream")) {
    const decoded = JSON.parse(trimmed) as unknown;
    return Array.isArray(decoded) ? decoded as JsonRpcResponse[] : [decoded as JsonRpcResponse];
  }
  const messages: JsonRpcResponse[] = [];
  for (const chunk of trimmed.split(/\r?\n\r?\n/u)) {
    const data = chunk
      .split(/\r?\n/u)
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice("data:".length).trim())
      .join("\n");
    if (!data) continue;
    try {
      messages.push(JSON.parse(data) as JsonRpcResponse);
    } catch {
      // Ignore non-JSON keepalive frames.
    }
  }
  return messages;
}

/**
 * Alpaca MCP tools wrap the raw API object as `{ _alpaca_mcp_security, data }`
 * in `structuredContent`, with the same JSON repeated as text content. Tools
 * whose API response is a list wrap it once more as `data: { result: [...] }`.
 */
function unwrapListResult(data: unknown): unknown {
  const item = record(data);
  if (item && Object.keys(item).length === 1 && Array.isArray(item.result)) return item.result;
  return data;
}

export function extractToolData(result: unknown): unknown {
  const item = record(result);
  if (!item) throw new Error("MCP tool result must be an object");
  if (item.isError === true) {
    const text = Array.isArray(item.content)
      ? item.content.map((part) => String(record(part)?.text ?? "")).join(" ").trim()
      : "";
    throw new Error(`MCP tool returned an error${text ? `: ${text.slice(0, 200)}` : ""}`);
  }
  const structured = record(item.structuredContent);
  if (structured && "data" in structured) return unwrapListResult(structured.data);
  if (Array.isArray(item.content)) {
    for (const part of item.content) {
      const text = record(part)?.text;
      if (typeof text !== "string") continue;
      const decoded = record(JSON.parse(text) as unknown);
      if (decoded && "data" in decoded) return unwrapListResult(decoded.data);
    }
  }
  throw new Error("MCP tool result did not carry an Alpaca data payload");
}

export class AlpacaMcpClient {
  private sessionId: string | undefined;
  private nextId = 1;
  private initialized = false;

  constructor(
    private readonly url: string,
    private readonly timeoutMs = 8_000,
    private readonly fetchImpl: typeof fetch = fetch,
  ) {}

  private async send(payload: JsonRpcRequest): Promise<JsonRpcResponse[]> {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      Accept: "application/json, text/event-stream",
      "MCP-Protocol-Version": PROTOCOL_VERSION,
    };
    if (this.sessionId) headers["Mcp-Session-Id"] = this.sessionId;
    const response = await this.fetchImpl(this.url, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(this.timeoutMs),
    });
    const session = response.headers.get("mcp-session-id");
    if (session) this.sessionId = session;
    if (!response.ok) throw new Error(`Alpaca MCP request returned ${response.status}`);
    if (response.status === 202 || response.status === 204) return [];
    return parseMcpBody(response.headers.get("content-type") ?? "", await response.text());
  }

  private async call(method: string, params: Record<string, unknown>): Promise<unknown> {
    const id = this.nextId++;
    const messages = await this.send({ jsonrpc: "2.0", id, method, params });
    const reply = messages.find((message) => message.id === id)
      ?? messages.find((message) => message.result !== undefined || message.error !== undefined);
    if (!reply) throw new Error(`Alpaca MCP returned no response for ${method}`);
    if (reply.error) throw new Error(`Alpaca MCP ${method} failed: ${reply.error.message ?? "unknown error"}`);
    return reply.result;
  }

  async initialize(): Promise<void> {
    if (this.initialized) return;
    await this.call("initialize", {
      protocolVersion: PROTOCOL_VERSION,
      capabilities: {},
      clientInfo: { name: "mandate-autonomy-runner", version: "1.0.0" },
    });
    await this.send({ jsonrpc: "2.0", method: "notifications/initialized" });
    this.initialized = true;
  }

  /** Call a tool and return the raw Alpaca API payload it wraps. */
  async callTool(name: string, args: Record<string, unknown> = {}): Promise<unknown> {
    await this.initialize();
    return extractToolData(await this.call("tools/call", { name, arguments: args }));
  }
}

export type BrokerSnapshot = {
  account: Record<string, unknown>;
  positions: Record<string, unknown>[];
};

/** Reject any broker read whose shape could silently distort sizing. */
export function validateBrokerSnapshot(account: unknown, positions: unknown): BrokerSnapshot {
  const item = record(account);
  if (!item) throw new Error("broker account must be an object");
  const equity = Number(item.equity);
  if (!Number.isFinite(equity) || equity <= 0) throw new Error("broker account omitted numeric equity");
  if (!Array.isArray(positions)) throw new Error("broker positions must be a list");
  const items = positions.flatMap((position) => {
    const entry = record(position);
    return entry && typeof entry.symbol === "string" ? [entry] : [];
  });
  if (items.length !== positions.length) throw new Error("broker positions contained an invalid entry");
  return { account: item, positions: items };
}
