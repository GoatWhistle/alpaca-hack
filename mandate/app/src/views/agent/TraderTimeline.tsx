import { useCallback, useEffect, useRef, useState } from "react";
import { getTraderTimeline, type TraderTimelineEvent } from "../../lib/api";

const POLL_MS = 3_000;

function eventTime(at: string): string {
  const date = new Date(at);
  return Number.isNaN(date.getTime()) ? at : date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function TraderTimeline() {
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
    } catch (reason) {
      if (signal?.aborted) return;
      setError(reason instanceof Error ? reason.message : "Could not read trader timeline");
    } finally {
      inFlight.current = false;
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    const timer = window.setInterval(() => void refresh(), POLL_MS);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [refresh]);

  return (
    <section className="trader-timeline" aria-label="Read-only trader timeline">
      <header>
        <div>
          <strong>Trader</strong>
          <span>automatic paper session · read only</span>
        </div>
        <button type="button" onClick={() => void refresh()}>Refresh</button>
      </header>
      {error && <p className="trader-timeline-error" role="alert">{error}</p>}
      {!events.length && !error && (
        <div className="trader-timeline-empty">
          <strong>Waiting for the first session event</strong>
          <p>Plans, critics, executions and hard risk exits will appear here.</p>
        </div>
      )}
      <ol>
        {[...events].reverse().map((event) => (
          <li key={event.sequence} data-status={event.status}>
            <div className="trader-event-meta">
              <span>{event.kind.replace("_", " ")}</span>
              <span>{event.status}</span>
              <time dateTime={event.at}>{eventTime(event.at)}</time>
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
