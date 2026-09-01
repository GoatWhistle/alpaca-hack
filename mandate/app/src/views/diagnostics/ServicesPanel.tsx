import { Empty, Panel } from "../../components/Panel";
import type { ServiceStatus } from "../../lib/api";

export function ServicesPanel({ services }: { services: ServiceStatus[] }) {
  return (
    <Panel title="Services" count={services.length} className="diag-panel">
      {services.length ? (
        <div className="service-rows">
          {services.map((service) => (
            <div key={service.name}>
              <i className={service.ok ? "online" : "offline"} aria-hidden="true" />
              <span>{service.name}</span>
              <small>{service.url}</small>
              <b className={service.ok ? "ok" : "down"}>
                {service.ok ? "online" : "offline"}
              </b>
            </div>
          ))}
        </div>
      ) : (
        <Empty>Service status is unavailable.</Empty>
      )}
    </Panel>
  );
}

interface FeedsPanelProps {
  runtime: Record<string, unknown>;
  qualityPass: number;
  qualityTotal: number;
}

export function FeedsPanel({ runtime, qualityPass, qualityTotal }: FeedsPanelProps) {
  const stream = (runtime.stream ?? {}) as Record<string, unknown>;
  const feed = String(runtime.market_feed ?? "—");
  const rows = [
    { label: "News stream", value: String(stream.news ?? "—") },
    { label: "Market stream", value: String(stream.market ?? "—") },
    { label: "Data feed", value: feed },
    { label: "Quality gate", value: qualityTotal > 0 ? `${qualityPass}/${qualityTotal}` : "—" },
    { label: "Discovery candidates", value: `${String(runtime.discovery_candidates ?? 0)} observed` },
    { label: "Corporate actions", value: String(runtime.corporate_action_events ?? 0) },
  ];

  return (
    <Panel title="Data feeds & streams" count={feed} className="diag-panel">
      <div className="monitor-health diagnostics-health">
        {rows.map((row) => (
          <span key={row.label}>
            <small>{row.label}</small>
            <b>{row.value}</b>
          </span>
        ))}
      </div>
    </Panel>
  );
}

export function WatchlistPanel({ symbols }: { symbols: string[] }) {
  return (
    <Panel title="Discovery watchlist" count="observation only" className="diag-panel">
      {symbols.length ? (
        <div className="watchlist">
          {symbols.map((symbol) => (
            <b key={symbol}>{symbol}</b>
          ))}
          <p className="muted">
            Movers and most-active names outside the mandate universe. Observing them never
            grants trading authority — a symbol can only be authorized by a mandate change.
          </p>
        </div>
      ) : (
        <Empty>No discovery candidates right now.</Empty>
      )}
    </Panel>
  );
}
