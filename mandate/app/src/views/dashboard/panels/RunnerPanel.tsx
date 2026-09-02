import { number, timestamp } from "../../../lib/format";

interface RunnerPanelProps {
  trajectory: Record<string, unknown>;
  runtime: Record<string, unknown>;
  decisionReason: string | null;
  qualityPass: number;
  qualityTotal: number;
}

export function RunnerPanel({
  trajectory,
  runtime,
  decisionReason,
  qualityPass,
  qualityTotal,
}: RunnerPanelProps) {
  const stale = runtime.stale === true;
  const staleSeconds = number(runtime.stale_seconds);
  const status = stale ? "stalled" : String(runtime.status ?? "not_started");
  const statusLabel = stale
    ? `stalled ${staleSeconds > 0 ? `${staleSeconds}s` : ""}`.trim()
    : status.replaceAll("_", " ");
  const stream = (runtime.stream ?? {}) as Record<string, unknown>;
  const symbols = Array.isArray(trajectory.symbols) ? trajectory.symbols : [];
  const lastAction = String(runtime.last_action ?? "");
  const candidate = typeof runtime.last_candidate === "string" ? runtime.last_candidate : "";
  const brokerTransport = typeof runtime.broker_transport === "string" ? runtime.broker_transport : "";

  const health = [
    { label: "News stream", value: String(stream.news ?? "—") },
    { label: "Market stream", value: String(stream.market ?? "—") },
    { label: "News cadence", value: `every ${String(trajectory.news_poll_seconds ?? "—")} s` },
    { label: "Forward outcomes", value: `${String(runtime.outcomes_observed ?? 0)} measured` },
    { label: "Last analysis", value: timestamp(runtime.last_analysis_at) },
    { label: "Next analysis", value: timestamp(runtime.next_analysis_at) },
    ...(brokerTransport ? [{ label: "Broker reads", value: brokerTransport }] : []),
  ];

  return (
    <article className="panel runner-panel">
      <div className="panel-heading">
        <div>
          <h2>Agent runner</h2>
        </div>
        <span
          className={`runner-status runner-status--${status}`}
          title={stale ? `No runner heartbeat for ${staleSeconds}s` : undefined}
        >
          <i aria-hidden="true" /> {statusLabel}
        </span>
      </div>

      <div className="runner-line">
        <span>{String(trajectory.monitoring_mode ?? "—")}</span>
        <span>quality {qualityTotal > 0 ? `${qualityPass}/${qualityTotal}` : "—"}</span>
        <span>{String(runtime.market_feed ?? "—")}</span>
        <span>every {String(trajectory.analysis_interval_minutes ?? "—")} min</span>
        <span>
          last action <b>{lastAction || "—"}</b>
        </span>
        {candidate && (
          <span>
            candidate <b>{candidate}</b>
          </span>
        )}
        {brokerTransport && (
          <span>
            broker reads <b>{brokerTransport}</b>
          </span>
        )}
      </div>

      {stale && (
        <div className="decision-explanation">
          <b>Runner stalled</b>
          <span>
            The persisted state is {staleSeconds}s old. The runner process is down or wedged; the
            broker figures above are still live, but no new decisions are being made.
          </span>
        </div>
      )}

      {decisionReason && (
        <div className="decision-explanation">
          <b>{lastAction === "PARK" ? "Why park" : "Last decision"}</b>
          <span>{decisionReason}</span>
        </div>
      )}

      <details className="runner-details">
        <summary>Runner &amp; trajectory details</summary>
        <div className="trajectory-summary">
          <span>{String(trajectory.risk_posture ?? "unconfigured")} trajectory</span>
          <p>
            {String(trajectory.thesis ?? "Start the runner to initialize the shared trajectory.")}
          </p>
          <div>
            {symbols.map((symbol) => (
              <b key={String(symbol)}>{String(symbol)}</b>
            ))}
          </div>
        </div>
        <div className="monitor-health">
          {health.map((item) => (
            <span key={item.label}>
              <small>{item.label}</small>
              <b>{item.value}</b>
            </span>
          ))}
        </div>
      </details>
    </article>
  );
}
