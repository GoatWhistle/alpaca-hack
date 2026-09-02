import type {
  AgentUIServer,
  ListResult,
  Session,
  SessionEventItem,
  Turn,
  TurnStreamData,
  TurnStreamingEvent,
} from "@truefoundry/trueforge-ui";
import {
  getTraderStreamUrl,
  getTraderTimeline,
  isTraderTimelineEvent,
  type TraderTimelineEvent,
} from "../../lib/api";

const NEW_YORK_TIME_ZONE = "America/New_York";
const SESSION_PREFIX = "mandate-trader-day-";
const TRADER_AGENT_NAME = "mandate-paper-agent";
const ROOT_THREAD_ID = "main";
const PAGE_SIZE = 500;
type NativeTurnEvent = Exclude<
  TurnStreamingEvent,
  { type: "model.message.delta" | "turn.created" | "turn.done" }
>;

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

export function newYorkTradingDate(now = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: NEW_YORK_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now);
  const value = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${value.year}-${value.month}-${value.day}`;
}

export function traderDaySessionId(tradingDate: string): string {
  return `${SESSION_PREFIX}${tradingDate}`;
}

function sessionDate(sessionId: string): string {
  const tradingDate = sessionId.startsWith(SESSION_PREFIX)
    ? sessionId.slice(SESSION_PREFIX.length)
    : "";
  if (!/^\d{4}-\d{2}-\d{2}$/u.test(tradingDate)) {
    throw new Error(`Unknown autonomous trader session: ${sessionId}`);
  }
  return tradingDate;
}

function eventId(event: TraderTimelineEvent, suffix: string): string {
  return `trader-${event.sequence}-${suffix}`;
}

function json(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function boundedString(value: unknown, limit = 500): string | null {
  if (typeof value !== "string") return null;
  const text = value.trim();
  return text ? text.slice(0, limit) : null;
}

function markdownText(value: unknown, limit = 500): string | null {
  const text = boundedString(value, limit);
  return text?.replace(/([\\`*_[\]{}()<>#+.!|-])/gu, "\\$1") ?? null;
}

function stringList(value: unknown, limit = 12): string[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    const text = boundedString(item, 300);
    return text ? [text] : [];
  }).slice(0, limit);
}

function evidenceRefs(value: unknown): string {
  const refs = stringList(value).map((item) => `\`${item.replace(/\s+/gu, " ").replaceAll("`", "")}\``);
  return refs.length > 0 ? refs.join(", ") : "none";
}

function capJournal(journal: string): string {
  const maximum = 20_000;
  return journal.length <= maximum
    ? journal
    : `${journal.slice(0, maximum)}\n\n…journal truncated; full contract remains in the tool result.`;
}

function decisionJournal(plan: Record<string, unknown>, fallback: string): string {
  const decision = markdownText(plan.action, 40) ?? "UNKNOWN";
  const reason = markdownText(plan.reason, 800) ?? markdownText(fallback, 800) ?? "No reason supplied.";
  const sections = [`**Decision · ${decision}**`, reason];

  const hypotheses = Array.isArray(plan.hypotheses) ? plan.hypotheses.slice(0, 5) : [];
  if (hypotheses.length > 0) {
    const rendered = hypotheses.map((value, index) => {
      const hypothesis = record(value);
      const candidate = markdownText(hypothesis.candidate_id, 80) ?? `candidate ${index + 1}`;
      const confidence = markdownText(hypothesis.confidence, 20) ?? "unknown";
      const thesis = markdownText(hypothesis.thesis, 500) ?? "No thesis supplied.";
      const invalidation = markdownText(hypothesis.invalidation, 500) ?? "Not supplied.";
      return [
        `**${index + 1}. ${candidate} · confidence ${confidence}**`,
        thesis,
        `- Supports: ${evidenceRefs(hypothesis.supports)}`,
        `- Contradicts: ${evidenceRefs(hypothesis.contradicts)}`,
        `- Invalidated when: ${invalidation}`,
      ].join("\n");
    });
    sections.push(`### Hypotheses\n\n${rendered.join("\n\n")}`);
  }

  const steps = Array.isArray(plan.steps) ? plan.steps.slice(0, 3) : [];
  if (steps.length > 0) {
    const rendered = steps.map((value, index) => {
      const step = record(value);
      const candidate = markdownText(step.candidate_id, 80) ?? `candidate ${index + 1}`;
      const stepReason = markdownText(step.reason, 500) ?? "No reason supplied.";
      return `${index + 1}. **${candidate}** — ${stepReason}\n   Evidence: ${evidenceRefs(step.evidence_refs)}`;
    });
    sections.push(`### Candidate plan\n\n${rendered.join("\n")}`);
  }

  const resolutions = Array.isArray(plan.critic_resolutions)
    ? plan.critic_resolutions.slice(0, 3)
    : [];
  if (resolutions.length > 0) {
    const rendered = resolutions.map((value) => {
      const resolution = record(value);
      const critic = markdownText(resolution.critic, 40) ?? "critic";
      const outcome = markdownText(resolution.resolution, 40) ?? "unknown";
      const resolutionReason = markdownText(resolution.reason, 500) ?? "No reason supplied.";
      return `- **${critic} · ${outcome}** — ${resolutionReason}`;
    });
    sections.push(`### Critic synthesis\n\n${rendered.join("\n")}`);
  }

  const memories = Array.isArray(plan.memory_events) ? plan.memory_events.slice(0, 5) : [];
  if (memories.length > 0) {
    const rendered = memories.map((value) => {
      const memory = record(value);
      const hypothesis = markdownText(memory.hypothesis, 500) ?? "Unnamed hypothesis";
      const ttl = typeof memory.ttl_hours === "number" ? `${memory.ttl_hours}h` : "bounded";
      return `- ${hypothesis} · TTL ${ttl}\n  Evidence: ${evidenceRefs(memory.evidence_refs)}`;
    });
    sections.push(`### Durable memory\n\n${rendered.join("\n")}`);
  }

  return capJournal(sections.join("\n\n"));
}

function executionJournal(event: TraderTimelineEvent): string {
  const result = record(event.details.result);
  const executions = Array.isArray(result.executions) ? result.executions.slice(0, 24) : [];
  if (executions.length === 0) {
    return `**Trade activity · ${event.status}**\n\n${markdownText(event.summary, 4_000) ?? "No summary supplied."}`;
  }
  const cards = executions.map((value, index) => {
    const execution = record(value);
    const order = record(execution.order);
    const broker = record(execution.result);
    const side = (markdownText(order.side, 20) ?? markdownText(execution.side, 20) ?? "order").toUpperCase();
    const symbol = markdownText(order.symbol, 40)
      ?? markdownText(execution.candidate, 40)
      ?? markdownText(execution.underlying, 40)
      ?? `action ${index + 1}`;
    const kind = markdownText((boundedString(execution.kind, 40) ?? "trade").replaceAll("_", " "), 40) ?? "trade";
    const status = markdownText(execution.status, 40) ?? "unknown";
    const filled = markdownText(execution.filled_qty, 40) ?? "0";
    const requested = markdownText(order.qty, 40) ?? "—";
    const limit = markdownText(order.limit_price, 60) ?? "—";
    const average = markdownText(broker.filled_avg_price, 60);
    const occurredAt = markdownText(broker.filled_at, 80) ?? markdownText(broker.submitted_at, 80);
    const rationale = markdownText(execution.reason, 800) ?? "No execution rationale supplied.";
    const candidate = boundedString(execution.plan_candidate_id, 100)
      ?.replace(/\s+/gu, " ").replaceAll("`", "") ?? null;
    const policy = record(execution.exit_policy);
    const policyItems = Object.entries(policy).flatMap(([label, raw]) => {
      const text = markdownText(raw, 300);
      const safeLabel = markdownText(label.replaceAll("_", " "), 80) ?? "rule";
      return text ? [`${safeLabel}: ${text}`] : [];
    }).slice(0, 6);
    const lines = [
      `**${index + 1}. ${side} ${symbol} · ${status}**`,
      `${kind} · filled ${filled}/${requested} · ${average ? `avg ${average}` : `limit ${limit}`}${occurredAt ? ` · ${occurredAt}` : ""}`,
      `- Why: ${rationale}`,
    ];
    if (candidate) lines.push(`- Candidate: \`${candidate.replaceAll("`", "")}\``);
    if (policyItems.length > 0) {
      lines.push(`- Exit plan: ${policyItems.join(" · ")}`);
    } else if (!kind.includes("exit") && Number(filled) > 0) {
      lines.push("- Exit plan: managed by the hard-risk engine; exact thresholds were not attached to this legacy fill.");
    }
    return lines.join("\n");
  });
  const errors = stringList(result.errors, 3).map((error) => markdownText(error, 300) ?? "Unknown warning");
  const suffix = errors.length > 0
    ? `\n\n### Execution warnings\n\n${errors.map((error) => `- ${error}`).join("\n")}`
    : "";
  const summary = markdownText(event.summary, 4_000) ?? "No summary supplied.";
  return capJournal(`**Trade activity · ${event.status}**\n\n${summary}\n\n### Orders\n\n${cards.join("\n\n")}${suffix}`);
}

function safeForPublicChat(value: unknown, depth = 0): unknown {
  if (depth > 6) return "[truncated]";
  if (typeof value === "string") return value.length > 2_000 ? `${value.slice(0, 2_000)}…` : value;
  if (Array.isArray(value)) return value.slice(0, 50).map((item) => safeForPublicChat(item, depth + 1));
  if (typeof value !== "object" || value === null) return value;
  const safe: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value)) {
    if (/(authorization|api[_-]?key|secret|token|account[_-]?id)/iu.test(key)) {
      safe[key] = "[redacted]";
    } else {
      safe[key] = safeForPublicChat(item, depth + 1);
    }
  }
  return safe;
}

function toolName(event: TraderTimelineEvent): string {
  const explicit = event.details.tool;
  if (typeof explicit === "string" && explicit.trim()) {
    return explicit.trim().replace(/[^a-zA-Z0-9_.:-]/gu, "-").slice(0, 120);
  }
  if (event.kind === "risk_exit") return "risk.evaluate_open_positions";
  if (event.kind === "plan") return "trader.create_plan";
  if (event.kind === "critics") {
    const first = Array.isArray(event.details.items) ? record(event.details.items[0]) : {};
    return `critic.${String(first.critic ?? "advisory")}`;
  }
  if (event.kind === "execution") return "alpaca.execute_trade_plan";
  return "mandate.runtime";
}

function toolCallId(event: TraderTimelineEvent, name = toolName(event)): string {
  const cycle = typeof event.details.cycle_id === "string"
    ? event.details.cycle_id.slice(0, 160)
    : `event-${event.sequence}`;
  return `call-${cycle}-${name}`.replace(/[^a-zA-Z0-9_.:-]/gu, "-").slice(0, 240);
}

function toolCallEvent(event: TraderTimelineEvent, name = toolName(event)): NativeTurnEvent {
  const args = event.details.arguments ?? {
    trigger: event.details.trigger,
    trading_date: event.trading_date,
  };
  return {
    type: "model.message",
    id: eventId(event, "tool-call"),
    threadId: ROOT_THREAD_ID,
    content: null,
    toolCalls: [{
      id: toolCallId(event, name),
      type: "function",
      function: { name, arguments: json(safeForPublicChat(args)) },
      toolInfo: {
        type: "mcp",
        serverId: "mandate-runtime",
        serverName: "Mandate runtime",
        name,
      },
    }],
    finishReason: "tool_calls",
    createdAt: event.at,
  };
}

function toolResponseEvent(event: TraderTimelineEvent, name = toolName(event)): NativeTurnEvent {
  return {
    type: "tool.response",
    id: eventId(event, "tool-response"),
    threadId: ROOT_THREAD_ID,
    toolCallId: toolCallId(event, name),
    content: json({
      status: event.status,
      summary: event.summary,
      result: safeForPublicChat(event.details.result ?? event.details.items ?? event.details),
    }),
    createdAt: event.at,
  };
}

function modelTextEvent(event: TraderTimelineEvent, content: string, suffix = "message"): NativeTurnEvent {
  return {
    type: "model.message",
    id: eventId(event, suffix),
    threadId: ROOT_THREAD_ID,
    content: capJournal(content),
    finishReason: "stop",
    createdAt: event.at,
  };
}

/**
 * Project the append-only desk journal onto the same event protocol emitted by
 * a native TrueForge turn. The UI therefore renders its own reasoning cards,
 * tool cards and assistant messages; no trading-specific message component is
 * involved.
 */
export function timelineEventToTurnEvents(event: TraderTimelineEvent): NativeTurnEvent[] {
  if (event.kind === "tool_call") return [toolCallEvent(event)];
  if (event.kind === "tool_result" || event.kind === "critics") {
    return [toolResponseEvent(event)];
  }
  if (event.kind === "execution") {
    return [
      toolResponseEvent(event),
      modelTextEvent(event, executionJournal(event), "execution-summary"),
    ];
  }
  if (event.kind === "risk_exit") {
    return [
      toolCallEvent(event),
      toolResponseEvent(event),
      modelTextEvent(event, executionJournal(event), "risk-summary"),
    ];
  }
  if (event.kind === "reasoning") {
    const source = event.details.source;
    if (source !== "trader_model" && source !== "deterministic_gate") {
      return [modelTextEvent(event, "Reasoning summary omitted: provenance was not explicit.", "reasoning-omitted")];
    }
    return [
      {
        type: "model.message",
        id: eventId(event, "reasoning"),
        threadId: ROOT_THREAD_ID,
        content: null,
        // This is the model's explicit bounded rationale, never hidden scratchpad/CoT.
        reasoningContent: event.summary.slice(0, 4_000),
        createdAt: event.at,
      },
      modelTextEvent(
        event,
        `**${source === "trader_model" ? "Trader rationale" : "Gate rationale"}**\n\n${markdownText(event.summary, 4_000) ?? "No rationale supplied."}`,
        "reasoning-summary",
      ),
    ];
  }
  if (event.kind === "plan") {
    const plan = record(event.details.plan);
    return [
      toolResponseEvent(event, "trader.create_plan"),
      modelTextEvent(
        event,
        decisionJournal(plan, event.summary),
        "decision",
      ),
    ];
  }
  const label = event.kind === "trigger" ? "Trigger" : "Session";
  return [modelTextEvent(event, `**${label} · ${event.status}**\n\n${markdownText(event.summary, 4_000) ?? "No summary supplied."}`)];
}

async function loadTimeline(tradingDate?: string, signal?: AbortSignal): Promise<TraderTimelineEvent[]> {
  const events: TraderTimelineEvent[] = [];
  let after = 0;
  while (true) {
    const page = await getTraderTimeline(after, PAGE_SIZE, signal, tradingDate);
    events.push(...page.items);
    if (page.items.length < PAGE_SIZE) break;
    if (page.next_after <= after) throw new Error("Trader timeline cursor did not advance");
    after = page.next_after;
  }
  return events;
}

function dateFallbackTimestamp(tradingDate: string): string {
  return `${tradingDate}T00:00:00.000Z`;
}

function toSession(tradingDate: string, events: TraderTimelineEvent[]): Session {
  const first = events[0]?.at ?? dateFallbackTimestamp(tradingDate);
  const last = events.at(-1)?.at ?? first;
  return {
    id: traderDaySessionId(tradingDate),
    title: `Trading desk · ${tradingDate}`,
    agentName: TRADER_AGENT_NAME,
    isMutable: false,
    createdAt: first,
    updatedAt: last,
  };
}

type DayTurnGroup = {
  key: string;
  input: string;
  events: TraderTimelineEvent[];
};

function cycleId(event: TraderTimelineEvent): string | null {
  return typeof event.details.cycle_id === "string" && event.details.cycle_id
    ? event.details.cycle_id
    : null;
}

function groupDayEvents(events: TraderTimelineEvent[]): DayTurnGroup[] {
  const groups: DayTurnGroup[] = [];
  const byKey = new Map<string, DayTurnGroup>();
  let activeCycle: DayTurnGroup | null = null;
  for (const event of events) {
    const explicitCycle = cycleId(event);
    if (event.kind === "trigger") {
      const key = explicitCycle ?? `trigger-${event.sequence}`;
      const group = { key, input: event.summary, events: [event] };
      groups.push(group);
      byKey.set(key, group);
      activeCycle = group;
      continue;
    }
    if (explicitCycle) {
      let group = byKey.get(explicitCycle);
      if (!group) {
        group = { key: explicitCycle, input: `Autonomous cycle ${explicitCycle}`, events: [] };
        groups.push(group);
        byKey.set(explicitCycle, group);
      }
      group.events.push(event);
      activeCycle = group;
      continue;
    }
    if (event.kind === "session" && activeCycle) {
      activeCycle.events.push(event);
      continue;
    }
    const key = `${event.kind}-${event.sequence}`;
    groups.push({ key, input: event.summary, events: [event] });
  }
  return groups;
}

function groupTurnId(sessionId: string, group: DayTurnGroup): string {
  return `${sessionId}:turn:${group.key}`.replace(/[^a-zA-Z0-9_.:-]/gu, "-");
}

function groupIsComplete(group: DayTurnGroup, isLatest: boolean, tradingDate: string): boolean {
  // Keep one stable native turn open for the current day. It is the live tail;
  // completed cycles become separate turns after a refresh/day rollover.
  if (tradingDate === newYorkTradingDate() && isLatest) return false;
  if (group.events.some((event) => event.kind === "execution")) return true;
  if (group.events.length === 1 && group.events[0]?.kind !== "trigger") return true;
  return true;
}

function toTurn(
  sessionId: string,
  tradingDate: string,
  group: DayTurnGroup,
  previousTurnId: string | null,
  isLatest: boolean,
  nextCreatedAt?: string,
): Turn {
  const createdAt = group.events[0]?.at ?? dateFallbackTimestamp(tradingDate);
  const completedAt = group.events.at(-1)?.at ?? nextCreatedAt ?? createdAt;
  const complete = groupIsComplete(group, isLatest, tradingDate);
  return {
    id: groupTurnId(sessionId, group),
    sessionId,
    previousTurnId,
    input: [{
      type: "user.message",
      content: group.input,
    }],
    state: complete
      ? { status: "done", completedAt, requiredActions: [] }
      : { status: "running" },
    createdAt,
  };
}

function groupedTurns(
  sessionId: string,
  tradingDate: string,
  events: TraderTimelineEvent[],
): Array<{ group: DayTurnGroup; turn: Turn }> {
  const groups = groupDayEvents(events);
  if (groups.length === 0 && tradingDate === newYorkTradingDate()) {
    groups.push({
      key: "day-watch",
      input: `Autonomous trader stream for New York trading day ${tradingDate}.`,
      events: [],
    });
  }
  let previousTurnId: string | null = null;
  return groups.map((group, index) => {
    const turn = toTurn(
      sessionId,
      tradingDate,
      group,
      previousTurnId,
      index === groups.length - 1,
      groups[index + 1]?.events[0]?.at,
    );
    previousTurnId = turn.id;
    return { group, turn };
  });
}

function projectedGroupEvents(group: DayTurnGroup): NativeTurnEvent[] {
  return group.events
    .filter((event) => event.kind !== "trigger")
    .flatMap(timelineEventToTurnEvents);
}

function sessionItems(sessionId: string, tradingDate: string, events: TraderTimelineEvent[]): SessionEventItem[] {
  const items: SessionEventItem[] = [];
  for (const { group, turn } of groupedTurns(sessionId, tradingDate, events)) {
    items.push({
      turnId: turn.id,
      event: {
        type: "turn.created",
        id: `${turn.id}:created`,
        turnId: turn.id,
        previousTurnId: turn.previousTurnId,
        input: turn.input,
        state: { status: "running" },
        createdAt: turn.createdAt,
        threadId: ROOT_THREAD_ID,
      },
    });
    for (const projected of projectedGroupEvents(group)) {
      items.push({ turnId: turn.id, event: projected });
    }
    if (turn.state.status !== "running") {
      items.push({
        turnId: turn.id,
        event: {
          type: "turn.done",
          id: `${turn.id}:done`,
          state: turn.state,
          createdAt: turn.state.completedAt,
          threadId: ROOT_THREAD_ID,
        },
      });
    }
  }
  return items;
}

function page<T>(items: T[], limit = 100, pageToken?: string): ListResult<T> {
  if (!Number.isInteger(limit) || limit < 1 || limit > 1_000) {
    throw new Error("Page limit must be an integer from 1 to 1000");
  }
  const offset = pageToken ? Number(pageToken) : 0;
  if (!Number.isInteger(offset) || offset < 0) throw new Error("Invalid page token");
  const data = items.slice(offset, offset + limit);
  const next = offset + data.length;
  return next < items.length ? { data, nextPageToken: String(next) } : { data };
}

function abortableDelay(milliseconds: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const timer = window.setTimeout(resolve, milliseconds);
    signal?.addEventListener("abort", () => {
      window.clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    }, { once: true });
  });
}

async function* readTimelineStream(
  tradingDate: string,
  after: number,
  signal?: AbortSignal,
  options: {
    maxConsecutiveFailures?: number;
    onHealthChange?: (healthy: boolean) => void;
  } = {},
): AsyncGenerator<TraderTimelineEvent> {
  let cursor = after;
  let consecutiveFailures = 0;
  while (!signal?.aborted) {
    try {
      const response = await fetch(getTraderStreamUrl(cursor, tradingDate), {
        headers: { Accept: "text/event-stream" },
        cache: "no-store",
        signal,
      });
      if (!response.ok || !response.body) throw new Error(`Trader stream returned ${response.status}`);
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (!signal?.aborted) {
        const chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true }).replace(/\r\n/gu, "\n");
        if (buffer.length > 1_000_000) throw new Error("Trader stream frame exceeded 1 MB");
        let boundary = buffer.indexOf("\n\n");
        while (boundary >= 0) {
          const frame = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          const lines = frame.split("\n");
          const type = lines.find((line) => line.startsWith("event:"))?.slice(6).trim();
          const data = lines.filter((line) => line.startsWith("data:"))
            .map((line) => line.slice(5).trimStart()).join("\n");
          if (type === "stream_error") throw new Error("Trader stream reported a journal error");
          if (lines.some((line) => line.trim() === ": keepalive")) {
            consecutiveFailures = 0;
            options.onHealthChange?.(true);
          }
          if (type === "trader_event" && data) {
            const value = JSON.parse(data) as unknown;
            if (!isTraderTimelineEvent(value, cursor) || value.trading_date !== tradingDate) {
              throw new Error("Trader stream violated its event contract");
            }
            cursor = value.sequence;
            consecutiveFailures = 0;
            options.onHealthChange?.(true);
            yield value;
          }
          boundary = buffer.indexOf("\n\n");
        }
      }
      if (!signal?.aborted) throw new Error("Trader stream closed unexpectedly");
    } catch (error) {
      if (signal?.aborted || (error instanceof Error && error.name === "AbortError")) return;
      consecutiveFailures += 1;
      options.onHealthChange?.(false);
      if (consecutiveFailures >= (options.maxConsecutiveFailures ?? 5)) throw error;
      await abortableDelay(1_000, signal);
    }
  }
}

export function createTraderChatServer(
  onHealthChange?: (healthy: boolean) => void,
): AgentUIServer {
  const hydratedCursor = new Map<string, number>();
  return {
    async createSession() {
      const tradingDate = newYorkTradingDate();
      return toSession(tradingDate, await loadTimeline(tradingDate));
    },
    async listSessions({ limit = 100, pageToken, order = "desc", agentId } = {}) {
      if (agentId != null && agentId !== TRADER_AGENT_NAME) return { data: [] };
      const all = await loadTimeline();
      const byDate = new Map<string, TraderTimelineEvent[]>();
      for (const event of all) {
        const bucket = byDate.get(event.trading_date) ?? [];
        bucket.push(event);
        byDate.set(event.trading_date, bucket);
      }
      if (!byDate.has(newYorkTradingDate())) byDate.set(newYorkTradingDate(), []);
      const sessions = [...byDate.entries()].map(([date, events]) => toSession(date, events))
        .sort((left, right) => left.id.localeCompare(right.id) * (order === "asc" ? 1 : -1));
      return page(sessions, limit, pageToken);
    },
    async getSession({ sessionId }) {
      const tradingDate = sessionDate(sessionId);
      return toSession(tradingDate, await loadTimeline(tradingDate));
    },
    async updateSession({ sessionId }) {
      const tradingDate = sessionDate(sessionId);
      return toSession(tradingDate, await loadTimeline(tradingDate));
    },
    async *createTurn(): AsyncIterable<TurnStreamData> {
      throw new Error("The autonomous trader stream is read-only; use the operator fork to ask questions.");
    },
    async cancelSession() {
      // Cancelling a browser subscription must never stop the autonomous desk.
    },
    async listTurns({ sessionId, limit = 100, pageToken, order = "desc" }) {
      const tradingDate = sessionDate(sessionId);
      const events = await loadTimeline(tradingDate);
      const turns = groupedTurns(sessionId, tradingDate, events).map((item) => item.turn);
      if (order === "desc") turns.reverse();
      return page(turns, limit, pageToken);
    },
    async getTurn({ sessionId, turnId: requestedTurnId }) {
      const tradingDate = sessionDate(sessionId);
      const turns = groupedTurns(sessionId, tradingDate, await loadTimeline(tradingDate));
      const found = turns.find((item) => item.turn.id === requestedTurnId)?.turn;
      if (!found) throw new Error("Unknown trader turn");
      return found;
    },
    async listEvents({ sessionId, limit = 200, pageToken }) {
      const tradingDate = sessionDate(sessionId);
      const events = await loadTimeline(tradingDate);
      // TrueForge hydrates the open tip separately through listTurnEvents().
      // Session history must contain completed turns only or the tip is folded twice.
      const runningIds = new Set(
        groupedTurns(sessionId, tradingDate, events)
          .filter((item) => item.turn.state.status === "running")
          .map((item) => item.turn.id),
      );
      const newestFirst = sessionItems(sessionId, tradingDate, events)
        .filter((item) => !runningIds.has(item.turnId))
        .reverse();
      return page(newestFirst, limit, pageToken);
    },
    async listTurnEvents({ sessionId, turnId: requestedTurnId, limit = 200, pageToken, order = "asc" }) {
      const tradingDate = sessionDate(sessionId);
      const timeline = await loadTimeline(tradingDate);
      const selected = groupedTurns(sessionId, tradingDate, timeline)
        .find((item) => item.turn.id === requestedTurnId);
      if (!selected) throw new Error("Unknown trader turn");
      hydratedCursor.set(requestedTurnId, timeline.at(-1)?.sequence ?? 0);
      const events = projectedGroupEvents(selected.group);
      if (order === "desc") events.reverse();
      return page(events, limit, pageToken);
    },
    async *subscribeToTurn({ sessionId, turnId: requestedTurnId, abortSignal }): AsyncIterable<TurnStreamData> {
      const tradingDate = sessionDate(sessionId);
      const initial = await loadTimeline(tradingDate, abortSignal);
      const selected = groupedTurns(sessionId, tradingDate, initial)
        .find((item) => item.turn.id === requestedTurnId);
      if (!selected) throw new Error("Unknown trader turn");
      let activeCycleKey = selected.group.key;
      let streamSequence = 0;
      const hydratedThrough = hydratedCursor.get(requestedTurnId) ?? 0;
      // Some TrueForge UI paths subscribe to a running turn without first
      // calling listTurnEvents. Hydrate only this turn's missing events once,
      // then start SSE at the journal tip. Streaming from sequence zero would
      // fold every earlier daily cycle into the open turn on each connection.
      for (const timelineEvent of selected.group.events) {
        if (timelineEvent.kind === "trigger" || timelineEvent.sequence <= hydratedThrough) continue;
        for (const projected of timelineEventToTurnEvents(timelineEvent)) {
          streamSequence += 1;
          yield { sequenceNumber: streamSequence, event: projected as TurnStreamingEvent };
        }
      }
      let cursor = Math.max(hydratedThrough, initial.at(-1)?.sequence ?? 0);
      hydratedCursor.set(requestedTurnId, cursor);
      for await (const event of readTimelineStream(
        tradingDate,
        cursor,
        abortSignal,
        { onHealthChange },
      )) {
        cursor = event.sequence;
        hydratedCursor.set(requestedTurnId, cursor);
        const incomingCycle = cycleId(event);
        if (event.kind === "trigger") {
          activeCycleKey = incomingCycle ?? `trigger-${event.sequence}`;
          streamSequence += 1;
          yield {
            sequenceNumber: streamSequence,
            event: modelTextEvent(
              event,
              `**Trigger · ${event.status}**\n\n${event.summary}`,
              "live-trigger",
            ),
          };
          continue;
        }
        const belongsToTurn = incomingCycle === activeCycleKey
          || (incomingCycle === null && (event.kind === "session" || event.kind === "risk_exit"));
        if (!belongsToTurn) continue;
        const projectedEvents = timelineEventToTurnEvents(event);
        for (const projected of projectedEvents) {
          streamSequence += 1;
          yield { sequenceNumber: streamSequence, event: projected as TurnStreamingEvent };
        }
      }
    },
    async getCapabilities() {
      return {
        data: {
          sandbox: { enabled: false },
          skill: { enabled: false, reason: "Autonomous stream is read-only" },
          settings: { enabled: false },
        },
      };
    },
    async getModels() { return []; },
    async getSkills() { return []; },
    async getMcp() { return []; },
    async searchAgents() {
      return [{ name: TRADER_AGENT_NAME, agentId: TRADER_AGENT_NAME }];
    },
    async saveAgent() {
      throw new Error("The autonomous trader agent is provisioned by the control plane.");
    },
  };
}
