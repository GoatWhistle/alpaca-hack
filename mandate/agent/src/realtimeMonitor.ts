import { createHash } from "node:crypto";

import type { NewsEvent, Trajectory } from "./autonomyRunner.js";

type StreamStatus = "disabled" | "connecting" | "connected" | "degraded";
export type StreamState = { news: StreamStatus; market: StreamStatus; lastEventAt?: string };
type StatusCallback = (status: StreamState) => void;
type WakeCallback = () => void;

function records(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null);
}

export function parseNewsMessages(value: unknown): NewsEvent[] {
  return records(value).flatMap((item) => {
    if (item.T !== "n" || !item.id || !item.headline || !item.created_at) return [];
    const symbols = Array.isArray(item.symbols)
      ? item.symbols.map(String).map((symbol) => symbol.trim().toUpperCase()).filter(Boolean)
      : [];
    const content = [item.headline, item.summary, item.content].map((part) => String(part ?? "")).join("\n");
    const contentHash = createHash("sha256").update(content).digest("hex");
    return [{
      key: `alpaca:${String(item.id)}:${contentHash}`,
      source: "alpaca",
      external_id: String(item.id),
      published_at: String(item.updated_at ?? item.created_at),
      headline: String(item.headline),
      summary: String(item.summary ?? ""),
      symbols,
      url: item.url ? String(item.url) : null,
      content_hash: contentHash,
    }];
  });
}

export class AlpacaRealtimeMonitor {
  private newsSocket?: WebSocket;
  private marketSocket?: WebSocket;
  private news: NewsEvent[] = [];
  private stopped = false;
  private reconnectAttempts = { news: 0, market: 0 };
  private trajectory: Trajectory;
  private lastStatusEmitMs = 0;
  private status: { news: StreamStatus; market: StreamStatus; lastEventAt?: string } = {
    news: "disabled",
    market: "disabled",
  };

  constructor(
    trajectory: Trajectory,
    private readonly onWake: WakeCallback,
    private readonly onStatus: StatusCallback,
    private readonly socketFactory: (url: string) => WebSocket = (url) => new WebSocket(url),
  ) {
    this.trajectory = trajectory;
  }

  start(): void {
    if (this.trajectory.monitoring_mode !== "realtime") return;
    if (!process.env.ALPACA_API_KEY || !process.env.ALPACA_SECRET_KEY) {
      this.status = { news: "degraded", market: "degraded" };
      this.emitStatus();
      return;
    }
    this.stopped = false;
    this.connectNews();
    this.connectMarket();
  }

  stop(): void {
    this.stopped = true;
    this.newsSocket?.close();
    this.marketSocket?.close();
  }

  updateTrajectory(trajectory: Trajectory): void {
    const changed = JSON.stringify(trajectory.symbols) !== JSON.stringify(this.trajectory.symbols)
      || trajectory.market_data_feed !== this.trajectory.market_data_feed
      || trajectory.monitoring_mode !== this.trajectory.monitoring_mode;
    this.trajectory = trajectory;
    if (!changed) return;
    this.stop();
    if (trajectory.monitoring_mode === "realtime") {
      this.stopped = false;
      this.start();
    } else {
      this.status = { news: "disabled", market: "disabled" };
      this.emitStatus();
    }
  }

  drainNews(): NewsEvent[] {
    const drained = this.news;
    this.news = [];
    return drained;
  }

  private connectNews(): void {
    this.setStatus("news", "connecting");
    const socket = this.socketFactory("wss://stream.data.alpaca.markets/v1beta1/news");
    this.newsSocket = socket;
    socket.addEventListener("open", () => this.authenticate(socket));
    socket.addEventListener("message", (event) => {
      const payload = this.decode(event.data);
      for (const item of records(payload)) {
        if (item.T === "success" && item.msg === "authenticated") {
          socket.send(JSON.stringify({ action: "subscribe", news: this.trajectory.symbols }));
          this.reconnectAttempts.news = 0;
          this.setStatus("news", "connected");
        }
      }
      const incoming = parseNewsMessages(payload).filter((item) =>
        item.symbols.some((symbol) => this.trajectory.symbols.includes(symbol))
      );
      if (incoming.length > 0) {
        this.news.push(...incoming);
        this.status.lastEventAt = new Date().toISOString();
        this.emitStatus();
        this.onWake();
      }
    });
    socket.addEventListener("error", () => this.setStatus("news", "degraded"));
    socket.addEventListener("close", () => this.reconnect("news"));
  }

  private connectMarket(): void {
    this.setStatus("market", "connecting");
    const feed = this.trajectory.market_data_feed === "sip" ? "sip" : "iex";
    const socket = this.socketFactory(`wss://stream.data.alpaca.markets/v2/${feed}`);
    this.marketSocket = socket;
    socket.addEventListener("open", () => this.authenticate(socket));
    socket.addEventListener("message", (event) => {
      const payload = this.decode(event.data);
      for (const item of records(payload)) {
        if (item.T === "success" && item.msg === "authenticated") {
          socket.send(JSON.stringify({
            action: "subscribe",
            bars: this.trajectory.symbols,
            quotes: this.trajectory.symbols,
            trades: this.trajectory.symbols,
          }));
          this.reconnectAttempts.market = 0;
          this.setStatus("market", "connected");
        } else if (["b", "q", "t"].includes(String(item.T))) {
          this.status.lastEventAt = new Date().toISOString();
          if (Date.now() - this.lastStatusEmitMs >= 5_000) this.emitStatus();
        }
      }
    });
    socket.addEventListener("error", () => this.setStatus("market", "degraded"));
    socket.addEventListener("close", () => this.reconnect("market"));
  }

  private authenticate(socket: WebSocket): void {
    const key = process.env.ALPACA_API_KEY ?? "";
    const secret = process.env.ALPACA_SECRET_KEY ?? "";
    if (!key || !secret) {
      this.setStatus(socket === this.newsSocket ? "news" : "market", "degraded");
      socket.close();
      return;
    }
    socket.send(JSON.stringify({ action: "auth", key, secret }));
  }

  private decode(value: unknown): unknown {
    try {
      return JSON.parse(typeof value === "string" ? value : String(value)) as unknown;
    } catch {
      return [];
    }
  }

  private reconnect(stream: "news" | "market"): void {
    if (this.stopped || this.trajectory.monitoring_mode !== "realtime") return;
    this.setStatus(stream, "degraded");
    const delay = Math.min(30_000, 1000 * 2 ** Math.min(this.reconnectAttempts[stream]++, 5));
    setTimeout(() => {
      if (this.stopped) return;
      if (stream === "news") this.connectNews();
      else this.connectMarket();
    }, delay);
  }

  private setStatus(stream: "news" | "market", value: StreamStatus): void {
    this.status = { ...this.status, [stream]: value };
    this.emitStatus();
  }

  private emitStatus(): void {
    this.lastStatusEmitMs = Date.now();
    this.onStatus({ ...this.status });
  }
}
