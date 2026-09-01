import { timestamp } from "../../../lib/format";

interface RunnerPanelProps {
  trajectory: Record<string, unknown>;
  runtime: Record<string, unknown>;
  parkReason: string | null;
  qualityPass: number;
  qualityTotal: number;
}

export function RunnerPanel({
  trajectory,
  runtime,
  parkReason,
  qualityPass,
  qualityTotal,
}: RunnerPanelProps) {
  const status = String(runtime.status ?? "not_started");
  const stream = (runtime.stream ?? {}) as Record<string, unknown>;
  const symbols = Array.isArray(trajectory.symbols) ? trajectory.symbols : [];

  const health = [
    { label: "News stream", value: String(stream.news ?? "—") },
    { label: "Market stream", value: String(stream.market ?? "—") },
    { label: "News cadence", value: `every ${String(trajectory.news_poll_seconds ?? "—")} s` },
    { label: "Forward outcomes", value: `${String(runtime.outcomes_observed ?? 0)} measured` },
    { label: "Last analysis", value: timestamp(runtime.last_analysis_at) },
    { label: "Next analysis", value: timestamp(runtime.next_analysis_at) },
  ];

  return (
    <article className="panel runner-panel">
      <div className="panel-heading">
        <div>
          <h2>Agent runner</h2>
        </div>
        <span className={`runner-status runner-status--${status}`}>
          <i aria-hidden="true" /> {status.replaceAll("_", " ")}
        </span>
      </div>

      <div className="runner-line">
        <span>{String(trajectory.monitoring_mode ?? "—")}</span>
        <span>quality {qualityTotal > 0 ? `${qualityPass}/${qualityTotal}` : "—"}</span>
        <span>{String(runtime.market_feed ?? "—")}</span>
        <span>every {String(trajectory.analysis_interval_minutes ?? "—")} min</span>
        <span>
          last action <b>{String(runtime.last_action ?? "—")}</b>
        </span>
      </div>

      {parkReason && (
        <div className="decision-explanation">
          <b>Why park</b>
          <span>{parkReason}</span>
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
