import { useCallback, useEffect, useRef, useState } from "react";
import { getTraderTimeline, type TraderTimelineEvent } from "../../lib/api";

const POLL_MS = 3_000;

const EVENT_LABELS: Record<TraderTimelineEvent["kind"], string> = {
  critics: "Critics",
  plan: "Plan",
  execution: "Execution",
  risk_exit: "Risk exit",
  session: "Session",
};

function eventTime(at: string): string {
  const date = new Date(at);
  return Number.isNaN(date.getTime()) ? at : date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

interface TraderTimelineProps {
  onHealthChange?: (healthy: boolean) => void;
}

export function TraderTimeline({ onHealthChange }: TraderTimelineProps) {
  const [events, setEvents] = useState<TraderTimelineEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const cursor = useRef(0);
  const inFlight = useRef(false);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const page = await getTraderTimeline(cursor.current, 200, signal);
      if (page.items.length) {
        setEvents((current) => [...current, ...page.items].slice(-500));
        cursor.current = page.next_after;
      }
      setError(null);
      onHealthChange?.(true);
    } catch (reason) {
      if (signal?.aborted) return;
      setError(reason instanceof Error ? reason.message : "Could not read trader timeline");
      onHealthChange?.(false);
    } finally {
      inFlight.current = false;
    }
  }, [onHealthChange]);

  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    const timer = window.setInterval(() => void refresh(controller.signal), POLL_MS);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [refresh]);

  return (
    <section
      className="trader-timeline"
      aria-label="Read-only trader timeline"
      aria-busy={!events.length && !error}
    >
      <header>
        <div>
          <span className="stream-label">Primary stream</span>
          <strong>Autonomous trader</strong>
          <span>plans, objections, executions and hard-risk exits</span>
        </div>
        <button type="button" onClick={() => void refresh()} aria-label="Refresh trader stream">↻ Refresh</button>
      </header>
      {error && <p className="trader-timeline-error" role="alert">{error}</p>}
      <span className="sr-only" aria-live="polite">
        {error ? "Trader stream degraded" : `${events.length} trader events loaded`}
      </span>
      {!events.length && !error && (
        <div className="trader-timeline-empty">
          <strong>Waiting for the first session event</strong>
          <p>Plans, critics, executions and hard risk exits will appear here.</p>
        </div>
      )}
      <ol>
        {[...events].reverse().map((event) => (
          <li key={event.sequence} data-status={event.status}>
            <span className="trader-event-node" aria-hidden="true" />
            <div className="trader-event-meta">
              <span>{EVENT_LABELS[event.kind]}</span>
              <span>{event.status}</span>
              <time dateTime={event.at}>{event.trading_date} · {eventTime(event.at)}</time>
              <code>#{event.sequence}</code>
            </div>
            <p>{event.summary}</p>
            <details>
              <summary>Contract payload</summary>
              <pre>{JSON.stringify(event.details, null, 2)}</pre>
            </details>
          </li>
        ))}
      </ol>
    </section>
  );
}
