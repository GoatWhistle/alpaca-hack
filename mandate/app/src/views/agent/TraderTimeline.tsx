import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  getTraderStreamUrl,
  getTraderTimeline,
  isTraderTimelineEvent,
  type TraderTimelineEvent,
} from "../../lib/api";

function eventTime(at: string): string {
  const date = new Date(at);
  return Number.isNaN(date.getTime()) ? at : date.toLocaleTimeString([], {
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function toolName(event: TraderTimelineEvent): string {
  const name = event.details.tool;
  if (typeof name === "string") return name;
  if (event.kind === "risk_exit") return "risk.evaluate_open_positions";
  if (event.kind === "execution") return "alpaca.execute_trade_plan";
  return "tool";
}

function toolResultSummary(event: TraderTimelineEvent): string {
  if (event.kind === "execution" && event.status === "parked") return "Completed · no order submitted";
  if (event.status === "submitted") return "Completed · order submitted";
  if (event.status === "degraded") return "Completed with an error";
  return event.summary;
}

function JsonDisclosure({ label, value }: { label: string; value: unknown }) {
  const [open, setOpen] = useState(false);
  return (
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>{label}</summary>
      {open && <pre>{JSON.stringify(value, null, 2)}</pre>}
    </details>
  );
}

function TranscriptEvent({ event }: { event: TraderTimelineEvent }) {
  if (event.kind === "trigger" || event.kind === "session") {
    return (
      <li className="transcript-system" data-kind={event.kind}>
        <span>{event.kind === "trigger" ? "Trigger" : "Session"} · {event.status}</span>
        <p>{event.summary}</p>
        <time dateTime={event.at}>{event.trading_date} · {eventTime(event.at)} · #{event.sequence}</time>
      </li>
    );
  }

  if (event.kind === "tool_call") {
    return (
      <li className="transcript-tool" data-status={event.status}>
        <span className="transcript-tool-icon" aria-hidden="true">↗</span>
        <div>
          <span className="transcript-kicker">Tool call</span>
          <strong>{toolName(event)}</strong>
          <p>{event.summary}</p>
          <JsonDisclosure label="Arguments" value={event.details.arguments ?? event.details} />
        </div>
        <time dateTime={event.at}>{eventTime(event.at)}</time>
      </li>
    );
  }

  if (["tool_result", "execution", "risk_exit"].includes(event.kind)) {
    const result = event.details.result ?? event.details;
    return (
      <li className="transcript-tool transcript-tool-result" data-status={event.status}>
        <span className="transcript-tool-icon" aria-hidden="true">✓</span>
        <div>
          <span className="transcript-kicker">Tool result</span>
          <strong>{toolName(event)}</strong>
          <p>{toolResultSummary(event)}</p>
          <JsonDisclosure label="Result" value={result} />
        </div>
        <time dateTime={event.at}>{eventTime(event.at)}</time>
      </li>
    );
  }

  if (event.kind === "reasoning") {
    return (
      <li className="transcript-reasoning">
        <details open><summary><span aria-hidden="true">◇</span> Reasoning summary</summary><p>{event.summary}</p></details>
        <time dateTime={event.at}>{eventTime(event.at)}</time>
      </li>
    );
  }

  if (event.kind === "critics") {
    const items = Array.isArray(event.details.items) ? event.details.items : [];
    return (
      <li className="transcript-message transcript-critics">
        <span className="transcript-avatar" aria-hidden="true">C</span>
        <div className="transcript-message-body">
          <div className="transcript-message-author">Critic swarm <time dateTime={event.at}>{eventTime(event.at)}</time></div>
          {items.length ? items.map((raw, index) => {
            const item = record(raw);
            return (
              <div className="critic-line" key={`${String(item.critic)}-${index}`} data-status={String(item.status)}>
                <strong>{String(item.critic ?? "critic")}</strong>
                <span>{String(item.summary ?? "No response")}</span>
              </div>
            );
          }) : <p>{event.summary}</p>}
        </div>
      </li>
    );
  }

  const plan = record(event.details.plan);
  return (
    <li className="transcript-message transcript-assistant" data-status={event.status}>
      <span className="transcript-avatar" aria-hidden="true">T</span>
      <div className="transcript-message-body">
        <div className="transcript-message-author">
          Autonomous trader <span>{event.status}</span><time dateTime={event.at}>{eventTime(event.at)}</time>
        </div>
        <p>{event.summary}</p>
        <JsonDisclosure label={typeof plan.action === "string" ? plan.action : "Trade plan"} value={event.details} />
      </div>
    </li>
  );
}

interface TraderTimelineProps {
  onHealthChange?: (healthy: boolean) => void;
}

export function TraderTimeline({ onHealthChange }: TraderTimelineProps) {
  const [events, setEvents] = useState<TraderTimelineEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const cursor = useRef(0);
  const inFlight = useRef(false);
  const scroller = useRef<HTMLElement>(null);
  const followTail = useRef(true);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const page = await getTraderTimeline(cursor.current, 200, signal);
      if (page.items.length) {
        setEvents((current) => {
          const merged = new Map(current.map((item) => [item.sequence, item]));
          for (const item of page.items) merged.set(item.sequence, item);
          return [...merged.values()].sort((left, right) => left.sequence - right.sequence).slice(-500);
        });
        cursor.current = page.next_after;
      }
      setError(null);
      onHealthChange?.(true);
    } catch (reason) {
      if (signal?.aborted) return;
      setError(reason instanceof Error ? reason.message : "Could not read trader transcript");
      onHealthChange?.(false);
    } finally {
      inFlight.current = false;
    }
  }, [onHealthChange]);

  useEffect(() => {
    const controller = new AbortController();
    let source: EventSource | undefined;
    void refresh(controller.signal).then(() => {
      if (controller.signal.aborted) return;
      source = new EventSource(getTraderStreamUrl(cursor.current));
      source.addEventListener("trader_event", (message) => {
        try {
          const event = JSON.parse((message as MessageEvent<string>).data) as unknown;
          if (!isTraderTimelineEvent(event, cursor.current)) return;
          cursor.current = event.sequence;
          setEvents((current) => [...current.filter((item) => item.sequence !== event.sequence), event]
            .sort((left, right) => left.sequence - right.sequence).slice(-500));
          setError(null);
          onHealthChange?.(true);
        } catch {
          setError("Trader stream sent an invalid event");
          onHealthChange?.(false);
        }
      });
      source.addEventListener("stream_error", () => {
        setError("Trader stream is temporarily degraded");
        onHealthChange?.(false);
      });
      source.onopen = () => {
        setError(null);
        onHealthChange?.(true);
      };
      source.onerror = () => {
        setError("Trader stream reconnecting…");
        onHealthChange?.(false);
      };
    });
    return () => {
      controller.abort();
      source?.close();
    };
  }, [refresh]);

  useLayoutEffect(() => {
    const element = scroller.current;
    if (element && followTail.current) element.scrollTop = element.scrollHeight;
  }, [events]);

  return (
    <section
      ref={scroller}
      className="trader-timeline"
      aria-label="Live autonomous trader transcript"
      aria-busy={!events.length && !error}
      onScroll={(event) => {
        const element = event.currentTarget;
        followTail.current = element.scrollHeight - element.scrollTop - element.clientHeight < 96;
      }}
    >
      <header>
        <div>
          <span className="stream-label">Live transcript</span>
          <strong>Autonomous trader</strong>
          <span>triggers · reasoning · tools · decisions</span>
        </div>
        <button type="button" onClick={() => void refresh()} aria-label="Refresh trader transcript">↻ Refresh</button>
      </header>
      {error && <p className="trader-timeline-error" role="alert">{error}</p>}
      <span className="sr-only" aria-live="polite">
        {error ? "Trader transcript degraded" : events.at(-1)?.summary ?? "Waiting for trader events"}
      </span>
      {!events.length && !error && (
        <div className="trader-timeline-empty">
          <strong>Waiting for the trader</strong>
          <p>The next trigger, reasoning step and tool result will appear here.</p>
        </div>
      )}
      <ol className="trader-transcript">
        {events.map((event) => <TranscriptEvent event={event} key={event.sequence} />)}
      </ol>
    </section>
  );
}
