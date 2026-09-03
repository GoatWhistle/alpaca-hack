import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { getTraderTimeline, type Snapshot, type TraderTimelineEvent } from "../../lib/api";

type Tone = "running" | "healthy" | "degraded" | "idle";

interface GraphNode {
  id: string;
  name: string;
  kind: string;
  tone: Tone;
  status: string;
  task: string;
  result?: string;
  problem?: string;
  meta?: string;
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function text(value: unknown, fallback = "—"): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function sourceName(id: string): string {
  const names: Record<string, string> = {
    alpaca: "Alpaca News",
    sec_edgar_atom: "SEC EDGAR 8-K / 6-K",
    apple_newsroom_atom: "Apple Newsroom",
    nvidia_ir_rss: "NVIDIA IR",
    microsoft_official_rss: "Microsoft Official",
    google_official_rss: "Google Official",
    aws_official_rss: "AWS Official",
    meta_official_rss: "Meta Official",
    federal_reserve_rss: "Federal Reserve",
  };
  return names[id] ?? id.replaceAll("_", " ").replace(/\b\w/gu, (letter) => letter.toUpperCase());
}

function latest(events: TraderTimelineEvent[], kind: TraderTimelineEvent["kind"]): TraderTimelineEvent | undefined {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    if (events[index]?.kind === kind) return events[index];
  }
  return undefined;
}

function compact(value: string, limit = 180): string {
  return value.length <= limit ? value : `${value.slice(0, limit - 1).trimEnd()}…`;
}

function sourceNodes(runtime: Record<string, unknown>): GraphNode[] {
  const aggregated = new Map<string, { checks: number; ok: number; events: number; problem?: string }>();
  for (const perSymbol of Object.values(record(runtime.news_sources))) {
    for (const [source, rawHealth] of Object.entries(record(perSymbol))) {
      const health = record(rawHealth);
      const current = aggregated.get(source) ?? { checks: 0, ok: 0, events: 0 };
      current.checks += 1;
      if (health.status === "ok") current.ok += 1;
      current.events += Number(health.events ?? 0) || 0;
      if (health.status !== "ok") {
        current.problem = `${text(health.status, "error")}${health.http_status ? ` · HTTP ${String(health.http_status)}` : ""}${health.error_type ? ` · ${String(health.error_type)}` : ""}`;
      }
      aggregated.set(source, current);
    }
  }
  if (aggregated.size === 0) {
    for (const source of ["alpaca", "sec_edgar_atom"]) {
      aggregated.set(source, { checks: 0, ok: 0, events: 0 });
    }
  }
  return [...aggregated.entries()].map(([source, health]) => {
    const healthy = health.checks > 0 && health.ok === health.checks;
    const partial = health.ok > 0 && health.ok < health.checks;
    return {
      id: `source-${source}`,
      name: sourceName(source),
      kind: "news researcher",
      tone: healthy ? "healthy" : partial ? "degraded" : health.checks ? "degraded" : "idle",
      status: healthy ? "monitoring" : partial ? "partial" : health.checks ? "failed" : "awaiting telemetry",
      task: "Collect attributable market events",
      result: `${health.events} bounded event${health.events === 1 ? "" : "s"} · ${health.ok}/${health.checks || "?"} probes healthy`,
      problem: health.problem,
    };
  });
}

/* ── Graph geometry ───────────────────────────────────────────────────────
   Nodes live on a normalized 100×100 canvas rendered at a fixed height;
   edges are drawn in pixel space so curves and dash patterns stay uniform. */

type Pos = { x: number; y: number };

const POS: Record<string, Pos> = {
  news: { x: 9, y: 18 },
  ipo: { x: 9, y: 45 },
  market: { x: 9, y: 72 },
  newsgate: { x: 37, y: 18 },
  signals: { x: 37, y: 55 },
  trader: { x: 63, y: 30 },
  operator: { x: 63, y: 7 },
  criticRisk: { x: 50, y: 66 },
  criticMarket: { x: 62, y: 77 },
  criticExec: { x: 74, y: 66 },
  executor: { x: 89, y: 30 },
  broker: { x: 89, y: 68 },
};

type EdgeKind = "flow" | "return" | "ondemand";

interface Edge {
  id: string;
  from: keyof typeof POS;
  to: keyof typeof POS;
  kind?: EdgeKind;
  bend?: Pos;
  stages?: string[];
  label?: Pos;
}

const EDGES: Edge[] = [
  { id: "e-news-gate", from: "news", to: "newsgate", stages: ["monitoring"] },
  { id: "e-ipo-signals", from: "ipo", to: "signals", bend: { x: -5, y: 0 }, stages: ["monitoring"] },
  { id: "e-market-signals", from: "market", to: "signals", bend: { x: -5, y: 0 }, stages: ["monitoring"] },
  { id: "e-gate-trader", from: "newsgate", to: "trader", bend: { x: 0, y: -6 }, stages: ["hypothesis", "challenge"], label: { x: 50, y: 22 } },
  { id: "e-signals-trader", from: "signals", to: "trader", bend: { x: 0, y: 5 }, stages: ["signals", "hypothesis"] },
  { id: "e-fan-risk", from: "trader", to: "criticRisk", bend: { x: -11, y: 0 }, stages: ["challenge"] },
  { id: "e-fan-market", from: "trader", to: "criticMarket", bend: { x: -7, y: 0 }, stages: ["challenge"] },
  { id: "e-fan-exec", from: "trader", to: "criticExec", bend: { x: 11, y: 0 }, stages: ["challenge"] },
  { id: "e-ret-risk", from: "criticRisk", to: "trader", kind: "return", bend: { x: -2, y: -7 } },
  { id: "e-ret-market", from: "criticMarket", to: "trader", kind: "return", bend: { x: -1, y: -8 } },
  { id: "e-ret-exec", from: "criticExec", to: "trader", kind: "return", bend: { x: 2, y: -7 } },
  { id: "e-operator", from: "operator", to: "trader", kind: "ondemand" },
  { id: "e-plan", from: "trader", to: "executor", stages: ["broker", "execution", "risk_exit"], label: { x: 76, y: 22 } },
  { id: "e-broker", from: "executor", to: "broker", bend: { x: 7, y: 0 } },
];

const EDGE_LABELS: { text: string; at: Pos }[] = [
  { text: "events · tape", at: { x: 23, y: 35 } },
  { text: "evidence", at: { x: 50, y: 22 } },
  { text: "trade.plan.v2", at: { x: 76, y: 22 } },
  { text: "hypothesis ⇄ critic results", at: { x: 63, y: 57 } },
];

const NODE_STAGES: Record<string, string[]> = {
  news: ["monitoring"],
  ipo: ["monitoring"],
  market: ["monitoring"],
  newsgate: ["signals", "hypothesis"],
  signals: ["signals"],
  trader: ["hypothesis", "challenge"],
  criticRisk: ["challenge"],
  criticMarket: ["challenge"],
  criticExec: ["challenge"],
  executor: ["risk_exit", "broker", "execution"],
  broker: ["execution"],
};

function edgePath(a: Pos, b: Pos, bend: Pos | undefined, w: number, h: number): string {
  const x1 = (a.x / 100) * w;
  const y1 = (a.y / 100) * h;
  const x2 = (b.x / 100) * w;
  const y2 = (b.y / 100) * h;
  const cx = ((a.x + b.x) / 2 + (bend?.x ?? 0)) / 100 * w;
  const cy = ((a.y + b.y) / 2 + (bend?.y ?? 0)) / 100 * h;
  return `M ${x1} ${y1} Q ${cx} ${cy} ${x2} ${y2}`;
}

function nodeTooltip(node: GraphNode): ReactNode {
  return (
    <>
      <b>{node.name} · {node.kind}</b>
      {node.task}
      {node.result && <i>Last result — {node.result}</i>}
      {node.meta && <i>{node.meta}</i>}
      <i>{node.status}</i>
    </>
  );
}

interface ChipProps {
  at: Pos;
  name: string;
  tone: Tone;
  live: boolean;
  primary?: boolean;
  label?: string;
  problem?: string;
  aria: string;
  tooltip: ReactNode;
}

function Chip({ at, name, tone, live, primary, label, problem, aria, tooltip }: ChipProps) {
  // The hover card opens ON TOP of the node, hiding it. Edge- and corner-most
  // nodes clamp the card toward the canvas centre so it never clips.
  const hAnchor = at.x <= 20 ? " agent-chip--west" : at.x >= 80 ? " agent-chip--east" : "";
  const vAnchor = at.y <= 15 ? " agent-chip--south" : at.y >= 82 ? " agent-chip--north" : "";
  return (
    <div
      className={`agent-chip${primary ? " agent-chip--primary" : ""}${live ? " is-live" : ""}${hAnchor}${vAnchor}`}
      data-tone={tone}
      style={{ left: `${at.x}%`, top: `${at.y}%` }}
      tabIndex={0}
      aria-label={aria}
    >
      <i aria-hidden="true" />
      <b>{label ?? name}</b>
      {problem && <small>{compact(problem, 110)}</small>}
      <span className="agent-tip" role="tooltip" aria-hidden="true">{tooltip}</span>
    </div>
  );
}

function chipAria(node: GraphNode): string {
  return `${node.name}, ${node.kind}, ${node.status}. ${node.task}${node.result ? ` Last result: ${node.result}.` : ""}`;
}

export function AgentsView({ snapshot, paused }: { snapshot: Snapshot | null; paused: boolean }) {
  const [events, setEvents] = useState<TraderTimelineEvent[]>([]);
  const [timelineError, setTimelineError] = useState<string | null>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const [canvasSize, setCanvasSize] = useState({ w: 1000, h: 580 });

  useEffect(() => {
    const controller = new AbortController();
    void getTraderTimeline(0, 200, controller.signal, undefined, 200)
      .then((page) => {
        setEvents(page.items);
        setTimelineError(null);
      })
      .catch((error) => {
        if (error instanceof Error && error.name === "AbortError") return;
        setTimelineError(error instanceof Error ? error.message : "Timeline unavailable");
      });
    return () => controller.abort();
  }, [snapshot?.generated_at, paused]);

  useLayoutEffect(() => {
    const el = canvasRef.current;
    if (!el) return;
    const measure = () => setCanvasSize({ w: el.clientWidth, h: el.clientHeight });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const graph = useMemo(() => {
    const runtime = snapshot?.autonomy.runtime ?? {};
    const roster = Array.isArray(runtime.agent_roster) ? runtime.agent_roster.map(record) : [];
    const modelFor = (role: string, fallback: string) =>
      text(roster.find((item) => item.role === role)?.model, fallback);
    const idFor = (role: string, fallback: string) =>
      text(roster.find((item) => item.role === role)?.id, fallback);
    const hypothesis = latest(events, "hypothesis");
    const criticsEvent = latest(events, "critics");
    const plan = latest(events, "plan");
    const research = latest(events, "tool_result");
    const execution = latest(events, "execution") ?? latest(events, "risk_exit");
    const stage = text(runtime.pipeline_stage, "monitoring");
    const runnerHealthy = runtime.status !== "degraded" && !runtime.last_error;
    const planReason = text(record(record(plan?.details).plan).reason, plan?.summary ?? "No completed plan yet");
    const traderProblem = planReason.startsWith("Trader unavailable")
      ? planReason
      : runtime.last_error ? text(runtime.last_error) : undefined;
    const criticItems = Array.isArray(record(criticsEvent?.details).items)
      ? (record(criticsEvent?.details).items as unknown[]).map(record)
      : [];
    const critic = (name: "risk" | "market" | "execution"): GraphNode => {
      const item = criticItems.find((entry) => entry.critic === name);
      const current = stage === "challenge";
      const completed = item?.status === "completed";
      const status = text(item?.status, current ? "working" : "waiting");
      return {
        id: idFor(`${name}_critic`, `mandate-${name}-critic`),
        name: `${name[0]?.toUpperCase()}${name.slice(1)} critic`,
        kind: "advisory agent",
        tone: current ? "running" : completed ? "healthy" : item ? "degraded" : "idle",
        status,
        task: current ? "Testing the main trader hypothesis" : "Wait for the next hypothesis draft",
        result: item?.summary ? compact(String(item.summary)) : "No result in the retained timeline",
        // "Waiting for the next draft" is not a failure — only an actual
        // degraded/errored run deserves the visible problem line.
        problem: item && (item.status === "degraded" || item.status === "error")
          ? compact(text(item.summary, "critic run failed"))
          : undefined,
        meta: modelFor(`${name}_critic`, "zai/glm-4-5-air"),
      };
    };
    const sourceList = sourceNodes(runtime);
    const market = snapshot?.autonomy.market ?? {};
    const services = snapshot?.services ?? [];
    const brokerService = services.find((service) => /alpaca|research/iu.test(service.name));
    return {
      stage,
      sources: [
        ...sourceList,
        {
          id: "ipo-researcher",
          name: "IPO Researcher",
          kind: "discovery worker",
          tone: runtime.ipo_monitor_status === "degraded" ? "degraded" : "healthy",
          status: text(runtime.ipo_monitor_status, "monitoring"),
          task: "Scan new listings and verify execution quality",
          result: `${Number(runtime.ipo_candidates ?? 0)} candidates · ${Number(runtime.ipo_research_ready ?? 0)} research-ready`,
          problem: runtime.ipo_monitor_status === "degraded" ? "One or more IPO discovery sources are degraded" : undefined,
          meta: "Nasdaq + Alpaca",
        } satisfies GraphNode,
        {
          id: "market-monitor",
          name: "Market Monitor",
          kind: "realtime worker",
          tone: runnerHealthy ? "healthy" : "degraded",
          status: text(record(runtime.stream).status, text(runtime.status, "waiting")),
          task: "Collect quotes, bars, movers and open-position wakes",
          result: `${Number(runtime.quality_pass ?? 0)}/${Number(runtime.quality_total ?? 0)} symbols pass quality · ${text(runtime.market_feed, "feed unknown")}`,
          problem: !runnerHealthy ? text(runtime.last_error) : undefined,
          meta: text(market.checked_at, text(runtime.last_poll_at, "No poll yet")),
        } satisfies GraphNode,
      ],
      research: [
        {
          id: idFor("news_gate", "news-relevance-gate"),
          name: "News Relevance Gate",
          kind: "classification agent",
          tone: Number(runtime.news_gate_errors ?? 0) > 0 ? "degraded" : "healthy",
          status: Number(runtime.news_gate_errors ?? 0) > 0 ? "degraded" : "running",
          task: "PASS or SKIP each new story before trader context",
          result: `${Number(runtime.news_events_passed ?? 0)}/${Number(runtime.news_events_collected ?? 0)} events passed`,
          problem: Number(runtime.news_gate_errors ?? 0) > 0 ? `${Number(runtime.news_gate_errors)} gate errors in the last poll` : undefined,
          meta: modelFor("news_gate", "zai/glm-4.5-air"),
        } satisfies GraphNode,
        {
          id: "signal-researcher",
          name: "Signal Researcher",
          kind: "deterministic research",
          tone: research?.status === "degraded" ? "degraded" : stage === "signals" ? "running" : "healthy",
          status: stage === "signals" ? "working" : text(research?.status, "ready"),
          task: "Build ensemble, regime, ATR and executable candidates",
          result: compact(research?.summary ?? "Waiting for the first evaluated cycle"),
          problem: research?.status === "degraded" ? compact(research.summary) : undefined,
          meta: "research.evaluate_trajectory",
        } satisfies GraphNode,
      ],
      trader: {
        id: idFor("main_trader", "mandate-paper-agent"),
        name: "Main Trader Brain",
        kind: "decision agent",
        tone: traderProblem ? "degraded" : runtime.status === "analyzing" ? "running" : "healthy",
        status: traderProblem ? "problem" : text(runtime.status, "waiting"),
        task: text(runtime.pipeline_note, "Waiting for the next analysis trigger"),
        result: compact(planReason),
        problem: traderProblem ? compact(traderProblem) : timelineError ?? undefined,
        meta: modelFor("main_trader", "zai/glm-5-3-flash"),
      } satisfies GraphNode,
      critics: [critic("risk"), critic("market"), critic("execution")],
      operator: {
        id: idFor("operator", "mandate-operator-agent"),
        name: "Operator Agent",
        kind: "human context fork",
        tone: (snapshot?.approvals.count ?? 0) > 0 ? "running" : "idle",
        status: (snapshot?.approvals.count ?? 0) > 0 ? "awaiting approval" : "on demand",
        task: "Answer questions and propose approval-gated memory changes",
        result: `${snapshot?.approvals.count ?? 0} memory approvals pending`,
        meta: modelFor("operator", "zai/glm-4-5-air"),
      } satisfies GraphNode,
      action: [
        {
          id: "deterministic-executor",
          name: "Risk & Order Executor",
          kind: "deterministic worker",
          tone: execution?.status === "degraded" ? "degraded" : stage === "execution" || stage === "risk_exit" ? "running" : "healthy",
          status: stage === "execution" || stage === "risk_exit" ? "working" : text(execution?.status, "ready"),
          task: "Enforce exits, limits and submit the canonical paper plan",
          result: compact(execution?.summary ?? "No execution event retained"),
          problem: execution?.status === "degraded" ? compact(execution.summary) : undefined,
          meta: "paper-only · no LLM authority",
        } satisfies GraphNode,
        {
          id: "alpaca-paper",
          name: "Alpaca Paper Broker",
          kind: "external dependency",
          tone: snapshot?.source === "live" && brokerService?.ok !== false ? "healthy" : "degraded",
          status: snapshot?.source === "live" ? "connected" : "degraded",
          task: "Account state, positions, orders and paper fills",
          result: `reads via ${text(runtime.broker_transport, "rest")} · ${snapshot?.session.pending_orders.length ?? 0} working orders`,
          problem: text(runtime.broker_transport_error, "") || (snapshot?.source !== "live" ? snapshot?.errors.join(" · ") : undefined),
          meta: "paper-api.alpaca.markets",
        } satisfies GraphNode,
      ],
      hypothesis: hypothesis?.summary,
    };
  }, [events, snapshot, timelineError]);

  const allNodes = [...graph.sources, ...graph.research, graph.trader, ...graph.critics, graph.operator, ...graph.action];
  const degradedCount = allNodes.filter((node) => node.tone === "degraded").length;
  const feeds = graph.sources.filter((node) => node.id.startsWith("source-"));
  const feedTone: Tone = feeds.some((f) => f.tone === "degraded")
    ? "degraded"
    : feeds.every((f) => f.tone === "healthy") ? "healthy" : "idle";
  const feedProblem = feeds.find((f) => f.problem)?.problem;

  const isLive = (stages?: string[]) => Boolean(stages?.includes(graph.stage));
  const { w, h } = canvasSize;

  return (
    <div className="mandate-chrome agents-view">
      <main id="main-content" tabIndex={-1}>
        <h1 className="sr-only">Agent topology</h1>
        <section className="agents-panel" aria-label="Agent dependency graph">
          <header className="agents-head">
            <h2>Dependency map</h2>
            <p className={degradedCount > 0 ? "has-problems" : ""}>
              {degradedCount > 0
                ? `${degradedCount} problem${degradedCount === 1 ? "" : "s"} visible · stage ${graph.stage}`
                : `all observed nodes healthy · stage ${graph.stage}`}
            </p>
          </header>

          <div className="agent-canvas-wrap">
            <div className="agent-canvas" ref={canvasRef}>
              <svg className="agent-edges" width={w} height={h} aria-hidden="true">
                {EDGES.map((edge) => (
                  <path
                    key={edge.id}
                    className={[
                      "agent-edge",
                      edge.kind === "return" ? "agent-edge--return" : "",
                      edge.kind === "ondemand" ? "agent-edge--ondemand" : "",
                      isLive(edge.stages) ? "is-live" : "",
                    ].filter(Boolean).join(" ")}
                    d={edgePath(POS[edge.from], POS[edge.to], edge.bend, w, h)}
                  />
                ))}
              </svg>

              {EDGE_LABELS.map((label) => (
                <span
                  key={label.text}
                  className="agent-edge-label"
                  style={{ left: `${label.at.x}%`, top: `${label.at.y}%` }}
                >
                  {label.text}
                </span>
              ))}

              <Chip
                at={POS.news}
                name="News feeds"
                label={`News feeds · ${feeds.length}`}
                tone={feedTone}
                live={isLive(NODE_STAGES.news)}
                problem={feedProblem}
                aria={`${feeds.length} news source researchers. ${feeds.map((f) => `${f.name}: ${f.status}`).join("; ")}`}
                tooltip={
                  <>
                    <b>News feeds · {feeds.length} source researchers</b>
                    {feeds.map((feed) => (
                      <i key={feed.id}>{feed.name} — {feed.status} · {feed.result}</i>
                    ))}
                    <i>Collect attributable market events</i>
                  </>
                }
              />
              {graph.sources
                .filter((node) => node.id === "ipo-researcher" || node.id === "market-monitor")
                .map((node) => (
                  <Chip
                    key={node.id}
                    at={node.id === "ipo-researcher" ? POS.ipo : POS.market}
                    name={node.name}
                    label={node.id === "ipo-researcher" ? "IPO researcher" : "Market monitor"}
                    tone={node.tone}
                    live={isLive(NODE_STAGES[node.id === "ipo-researcher" ? "ipo" : "market"])}
                    problem={node.problem}
                    aria={chipAria(node)}
                    tooltip={nodeTooltip(node)}
                  />
                ))}

              {graph.research.map((node, index) => (
                <Chip
                  key={node.id}
                  at={index === 0 ? POS.newsgate : POS.signals}
                  name={node.name}
                  label={index === 0 ? "News gate" : "Signals"}
                  tone={node.tone}
                  live={isLive(index === 0 ? NODE_STAGES.newsgate : NODE_STAGES.signals)}
                  problem={node.problem}
                  aria={chipAria(node)}
                  tooltip={nodeTooltip(node)}
                />
              ))}

              <Chip
                at={POS.operator}
                name={graph.operator.name}
                label="Operator"
                tone={graph.operator.tone}
                live={graph.operator.tone === "running"}
                aria={chipAria(graph.operator)}
                tooltip={nodeTooltip(graph.operator)}
              />

              <Chip
                at={POS.trader}
                name={graph.trader.name}
                label="Main trader"
                tone={graph.trader.tone}
                live={isLive(NODE_STAGES.trader)}
                primary
                problem={graph.trader.problem}
                aria={chipAria(graph.trader)}
                tooltip={nodeTooltip(graph.trader)}
              />

              {graph.critics.map((node, index) => (
                <Chip
                  key={node.id}
                  at={[POS.criticRisk, POS.criticMarket, POS.criticExec][index]}
                  name={node.name}
                  label={["Risk critic", "Market critic", "Exec critic"][index]}
                  tone={node.tone}
                  live={isLive(NODE_STAGES.criticRisk)}
                  problem={node.problem}
                  aria={chipAria(node)}
                  tooltip={nodeTooltip(node)}
                />
              ))}

              {graph.action.map((node, index) => (
                <Chip
                  key={node.id}
                  at={index === 0 ? POS.executor : POS.broker}
                  name={node.name}
                  label={index === 0 ? "Risk & orders" : "Alpaca paper"}
                  tone={node.tone}
                  live={isLive(index === 0 ? NODE_STAGES.executor : NODE_STAGES.broker)}
                  problem={node.problem}
                  aria={chipAria(node)}
                  tooltip={nodeTooltip(node)}
                />
              ))}
            </div>
          </div>

          {graph.hypothesis && (
            <footer className="agents-foot">
              <span>current hypothesis</span>
              <p>{compact(graph.hypothesis, 220)}</p>
            </footer>
          )}
        </section>
      </main>
    </div>
  );
}
