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
  if (typeof explicit === "string" && explicit) return explicit;
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
    ? event.details.cycle_id
    : `event-${event.sequence}`;
  return `call-${cycle}-${name}`.replace(/[^a-zA-Z0-9_.:-]/gu, "-");
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
    content,
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
      modelTextEvent(event, `**Execution · ${event.status}**\n\n${event.summary}`, "execution-summary"),
    ];
  }
  if (event.kind === "risk_exit") {
    return [
      toolCallEvent(event),
      toolResponseEvent(event),
      modelTextEvent(event, `**Risk pass · ${event.status}**\n\n${event.summary}`, "risk-summary"),
    ];
  }
  if (event.kind === "reasoning") {
    const source = event.details.source;
    if (source !== "trader_model" && source !== "deterministic_gate") {
      return [modelTextEvent(event, "Reasoning summary omitted: provenance was not explicit.", "reasoning-omitted")];
    }
    return [{
      type: "model.message",
      id: eventId(event, "reasoning"),
      threadId: ROOT_THREAD_ID,
      content: null,
      // This is the model's explicit bounded rationale, never hidden scratchpad/CoT.
      reasoningContent: event.summary,
      createdAt: event.at,
    }];
  }
  if (event.kind === "plan") {
    const plan = record(event.details.plan);
    const decision = typeof plan.action === "string" ? plan.action : event.status.toUpperCase();
    return [
      toolResponseEvent(event, "trader.create_plan"),
      modelTextEvent(
        event,
        `**Decision · ${decision}**\n\n${event.summary}\n\n\`\`\`json\n${json(plan)}\n\`\`\``,
        "decision",
      ),
    ];
  }
  const label = event.kind === "trigger" ? "Trigger" : "Session";
  return [modelTextEvent(event, `**${label} · ${event.status}**\n\n${event.summary}`)];
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
  if (group.events.some((event) => event.kind === "execution")) return true;
  if (group.events.length === 1 && group.events[0]?.kind !== "trigger") return true;
  return tradingDate !== newYorkTradingDate() || !isLatest;
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
      consecutiveFailures = 0;
      options.onHealthChange?.(true);
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
          if (type === "trader_event" && data) {
            const value = JSON.parse(data) as unknown;
            if (!isTraderTimelineEvent(value, cursor) || value.trading_date !== tradingDate) {
              throw new Error("Trader stream violated its event contract");
            }
            cursor = value.sequence;
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

export async function watchTraderTurnStarts(
  tradingDate: string,
  onStart: (sequence: number) => void,
  signal?: AbortSignal,
  onHealthChange?: (healthy: boolean) => void,
): Promise<void> {
  const initial = await loadTimeline(tradingDate, signal);
  const after = initial.at(-1)?.sequence ?? 0;
  for await (const event of readTimelineStream(tradingDate, after, signal, {
    maxConsecutiveFailures: Number.POSITIVE_INFINITY,
    onHealthChange,
  })) {
    if (event.kind === "trigger" || event.kind === "risk_exit") onStart(event.sequence);
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
      let streamSequence = (hydratedCursor.get(requestedTurnId) ?? 0) * 4;
      for await (const event of readTimelineStream(
        tradingDate,
        hydratedCursor.get(requestedTurnId) ?? 0,
        abortSignal,
        { onHealthChange },
      )) {
        hydratedCursor.set(requestedTurnId, event.sequence);
        const incomingCycle = cycleId(event);
        if (event.kind === "trigger" && incomingCycle !== selected.group.key) {
          streamSequence += 1;
          yield {
            sequenceNumber: streamSequence,
            event: {
              type: "turn.done",
              id: `${requestedTurnId}:superseded`,
              state: { status: "done", completedAt: event.at, requiredActions: [] },
              createdAt: event.at,
              threadId: ROOT_THREAD_ID,
            },
          };
          return;
        }
        const belongsToTurn = incomingCycle === selected.group.key
          || (incomingCycle === null && event.kind === "session");
        if (!belongsToTurn) continue;
        const projectedEvents = event.kind === "trigger" ? [] : timelineEventToTurnEvents(event);
        for (const projected of projectedEvents) {
          streamSequence += 1;
          yield { sequenceNumber: streamSequence, event: projected as TurnStreamingEvent };
        }
        if (event.kind === "execution") {
          streamSequence += 1;
          yield {
            sequenceNumber: streamSequence,
            event: {
              type: "turn.done",
              id: `${requestedTurnId}:done`,
              state: { status: "done", completedAt: event.at, requiredActions: [] },
              createdAt: event.at,
              threadId: ROOT_THREAD_ID,
            },
          };
          return;
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
