import type { TrajectoryForm } from "./useTrajectoryForm";

interface FieldsProps {
  form: TrajectoryForm;
  patch: (update: Partial<TrajectoryForm>) => void;
}

export function CadenceSection({ form, patch }: FieldsProps) {
  return (
    <section className="settings-section">
      <h3>Cadence &amp; mode</h3>
      <div className="settings-grid">
        <label>
          Monitoring mode
          <select
            value={form.monitoring_mode}
            onChange={(event) => patch({ monitoring_mode: event.target.value })}
          >
            <option value="realtime">Realtime + REST fallback</option>
            <option value="polling">REST polling</option>
          </select>
        </label>
        <label>
          Market feed
          <select
            value={form.market_data_feed}
            onChange={(event) => patch({ market_data_feed: event.target.value })}
          >
            <option value="auto">Auto / IEX</option>
            <option value="iex">IEX</option>
            <option value="sip">SIP (entitlement required)</option>
          </select>
        </label>
        <label>
          News polling, seconds
          <input
            type="number"
            min="15"
            max="3600"
            value={form.news_poll_seconds}
            onChange={(event) => patch({ news_poll_seconds: Number(event.target.value) })}
          />
        </label>
        <label>
          Full analysis, minutes
          <input
            type="number"
            min="1"
            max="1440"
            value={form.analysis_interval_minutes}
            onChange={(event) =>
              patch({ analysis_interval_minutes: Number(event.target.value) })}
          />
        </label>
      </div>
    </section>
  );
}

export function GatesSection({ form, patch }: FieldsProps) {
  return (
    <section className="settings-section">
      <h3>Data quality gates</h3>
      <div className="settings-grid">
        <label>
          Max spread, bps
          <input
            type="number"
            min="1"
            max="1000"
            value={form.max_spread_bps}
            onChange={(event) => patch({ max_spread_bps: Number(event.target.value) })}
          />
        </label>
        <label>
          Min relative volume
          <input
            type="number"
            min="0"
            max="100"
            step="0.05"
            value={form.min_relative_volume}
            onChange={(event) => patch({ min_relative_volume: Number(event.target.value) })}
          />
        </label>
      </div>
      <div className="check-grid">
        <label>
          <input
            type="checkbox"
            checked={form.regular_hours_only}
            onChange={(event) => patch({ regular_hours_only: event.target.checked })}
          />
          Proposals in regular market hours only
        </label>
      </div>
    </section>
  );
}

export function DiscoverySection({ form, patch }: FieldsProps) {
  return (
    <section className="settings-section">
      <h3>Discovery &amp; events</h3>
      <div className="settings-grid">
        <label>
          Discovery list size
          <input
            type="number"
            min="1"
            max="50"
            value={form.discovery_top}
            onChange={(event) => patch({ discovery_top: Number(event.target.value) })}
          />
        </label>
      </div>
      <div className="check-grid">
        <label>
          <input
            type="checkbox"
            checked={form.discovery_enabled}
            onChange={(event) => patch({ discovery_enabled: event.target.checked })}
          />
          Movers / most active discovery
        </label>
        <label>
          <input
            type="checkbox"
            checked={form.monitor_corporate_actions}
            onChange={(event) => patch({ monitor_corporate_actions: event.target.checked })}
          />
          Corporate-action alerts
        </label>
        <label>
          <input
            type="checkbox"
            checked={form.options_confirmation}
            onChange={(event) => patch({ options_confirmation: event.target.checked })}
          />
          Options confirmation (extra data calls)
        </label>
      </div>
    </section>
  );
}
