import { useCallback, useEffect, useMemo, useState } from "react";
import { TrueForgeUI } from "@truefoundry/trueforge-ui";
import { getSnapshot, updateTrajectory, type Journal, type Snapshot } from "./api";
import { decimal, money, number, percent, shortId } from "./format";

const REFRESH_MS = 5_000;
type View = "overview" | "news" | "agent";

function Icon({ name }: { name: "shield" | "refresh" | "external" | "pulse" | "settings" | "close" }) {
  const paths = {
    shield: <path d="M12 3 5 6v5c0 4.5 2.8 8 7 10 4.2-2 7-5.5 7-10V6l-7-3Zm-3 9 2 2 4-5" />,
    refresh: <path d="M20 12a8 8 0 1 1-2.3-5.7L20 8M20 4v4h-4" />,
    external: <path d="M14 4h6v6M20 4l-9 9M18 13v6H5V6h6" />,
    pulse: <path d="M3 12h4l2-6 4 12 2-6h6" />,
    settings: <><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1a1.7 1.7 0 0 0 1.9.3A1.7 1.7 0 0 0 10 3V2.8h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9A1.7 1.7 0 0 0 21 10h.2v4H21a1.7 1.7 0 0 0-1.6 1Z" /></>,
    close: <path d="m6 6 12 12M18 6 6 18" />,
  };
  return <svg aria-hidden="true" viewBox="0 0 24 24">{paths[name]}</svg>;
}

function Metric({ label, value, hint, tone = "default" }: { label: string; value: string; hint: string; tone?: "default" | "good" | "bad" }) {
  return (
    <article className={`metric metric--${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{hint}</small>
    </article>
  );
}

function LimitBar({ label, used, limit, unit = "%" }: { label: string; used: number; limit: number; unit?: string }) {
  const ratio = limit > 0 ? Math.min(Math.max((used / limit) * 100, 0), 100) : 0;
  const danger = ratio >= 80;
  return (
    <div className="limit-row">
      <div className="limit-label">
        <span>{label}</span>
        <span><b>{decimal(used)}</b> / {decimal(limit)}{unit}</span>
      </div>
      <div className="bar" aria-label={`${label}: ${ratio.toFixed(0)}% used`}>
        <i className={danger ? "danger" : ""} style={{ width: `${ratio}%` }} />
      </div>
      <small>{decimal(Math.max(limit - used, 0))}{unit} headroom</small>
    </div>
  );
}

function StatusStrip({ services }: { services: Snapshot["services"] }) {
  return (
    <div className="status-strip">
      {services.map((service) => (
        <div className="service" key={service.name} title={service.url}>
          <i className={service.ok ? "online" : "offline"} />
          <span>{service.name}</span>
          <small>{service.ok ? "online" : "offline"}</small>
        </div>
      ))}
    </div>
  );
}

const outcomeLabels: Record<string, string> = {
  prepared: "Prepared",
  submitted: "Submitted",
  deduplicated: "Deduplicated",
  denied: "Denied",
  parked: "Parked",
  conflict: "Conflict",
};

function TimelineItem({ entry, last }: { entry: Journal; last: boolean }) {
  const order = entry.details.order as Record<string, unknown> | undefined;
  const title = entry.action === "submit_order" && order
    ? `${String(order.side ?? "").toUpperCase()} ${order.qty ?? ""} ${order.symbol ?? ""}`
    : entry.action.replaceAll("_", " ");
  return (
    <article className={`timeline-item outcome--${entry.outcome}`}>
      <div className="timeline-marker"><i />{!last && <span />}</div>
      <div className="timeline-content">
        <div className="timeline-topline">
          <div><b>{title}</b><em>{outcomeLabels[entry.outcome] ?? entry.outcome}</em></div>
        </div>
        <p>{entry.rationale}</p>
        {Boolean(entry.details.intent_id || entry.details.order_id || entry.details.intended_action) && (
          <div className="detail-chips">
            {Boolean(entry.details.intent_id) && <span>intent {shortId(entry.details.intent_id)}</span>}
            {Boolean(entry.details.order_id) && <span>order {shortId(entry.details.order_id)}</span>}
            {Boolean(entry.details.intended_action) && <span>{String(entry.details.intended_action)}</span>}
          </div>
        )}
        <details>
          <summary>Raw evidence</summary>
          <pre>{JSON.stringify(entry.details, null, 2)}</pre>
        </details>
      </div>
    </article>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="empty"><span>○</span><p>{children}</p></div>;
}

function newsText(value: unknown): string {
  const decodePoint = (match: string, raw: string, radix: number) => {
    const point = Number.parseInt(raw, radix);
    return Number.isInteger(point) && point >= 0 && point <= 0x10ffff && !(point >= 0xd800 && point <= 0xdfff)
      ? String.fromCodePoint(point)
      : match;
  };
  return String(value ?? "")
    .replace(/&#(\d+);/g, (match, code: string) => decodePoint(match, code, 10))
    .replace(/&#x([0-9a-f]+);/gi, (match, code: string) => decodePoint(match, code, 16))
    .replaceAll("&quot;", "\"")
    .replaceAll("&apos;", "'")
    .replaceAll("&#39;", "'")
    .replaceAll("&amp;", "&")
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">");
}

function NewsCard({ item, featured = false }: { item: Record<string, unknown>; featured?: boolean }) {
  const symbols = Array.isArray(item.symbols) ? item.symbols.map(String) : [];
  const url = typeof item.url === "string" ? item.url : "";
  return <article className={`news-card${featured ? " news-card--featured" : ""}`}>
    <div className="news-meta">
      <span>{String(item.source ?? "news")}</span>
      <div>{symbols.map((symbol) => <b key={symbol}>{symbol}</b>)}</div>
    </div>
    <h3>{newsText(item.headline ?? "Untitled market update")}</h3>
    {item.summary ? <p>{newsText(item.summary)}</p> : null}
    {url ? <a href={url} target="_blank" rel="noreferrer">Read full article <Icon name="external" /></a> : null}
  </article>;
}

function TrajectorySettings({ trajectory, universe, open, onClose, onSaved }: {
  trajectory: Record<string, unknown>;
  universe: string[];
  open: boolean;
  onClose: () => void;
  onSaved: () => Promise<unknown>;
}) {
  const [reviewing, setReviewing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [form, setForm] = useState({
    enabled: Boolean(trajectory.enabled ?? true),
    symbols: Array.isArray(trajectory.symbols) ? trajectory.symbols.map(String) : universe,
    news_poll_seconds: Number(trajectory.news_poll_seconds ?? 60),
    analysis_interval_minutes: Number(trajectory.analysis_interval_minutes ?? 15),
    monitoring_mode: String(trajectory.monitoring_mode ?? "realtime"),
    market_data_feed: String(trajectory.market_data_feed ?? "auto"),
    discovery_enabled: Boolean(trajectory.discovery_enabled ?? true),
    discovery_top: Number(trajectory.discovery_top ?? 10),
    regular_hours_only: Boolean(trajectory.regular_hours_only ?? true),
    max_spread_bps: Number(trajectory.max_spread_bps ?? 35),
    min_relative_volume: Number(trajectory.min_relative_volume ?? 0.25),
    monitor_corporate_actions: Boolean(trajectory.monitor_corporate_actions ?? true),
    options_confirmation: Boolean(trajectory.options_confirmation ?? false),
    risk_posture: String(trajectory.risk_posture ?? "balanced"),
    thesis: String(trajectory.thesis ?? ""),
  });
  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [open, onClose]);
  const toggleSymbol = (symbol: string) => setForm((value) => ({
    ...value,
    symbols: value.symbols.includes(symbol)
      ? value.symbols.filter((item) => item !== symbol)
      : [...value.symbols, symbol],
  }));
  const save = async () => {
    setSaving(true);
    setMessage("");
    try {
      await updateTrajectory(form);
      setMessage("Applied. The runner will reload this trajectory on its next wake.");
      setReviewing(false);
      await onSaved();
      onClose();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Could not apply trajectory");
    } finally { setSaving(false); }
  };
  if (!open) return null;
  return <div className="mandate-chrome settings-backdrop" onMouseDown={onClose}>
    <aside className="settings-drawer" role="dialog" aria-modal="true" aria-labelledby="monitoring-settings-title" onMouseDown={(event) => event.stopPropagation()}>
      <header className="settings-drawer-header">
        <div><span className="kicker">CONTROL PLANE</span><h2 id="monitoring-settings-title">Monitoring settings</h2></div>
        <button className="icon-button" aria-label="Close monitoring settings" onClick={onClose}><Icon name="close" /></button>
      </header>
      <div className="settings-form">
      <div className="settings-grid">
        <label>Mode<select value={form.monitoring_mode} onChange={(event) => setForm({ ...form, monitoring_mode: event.target.value })}><option value="realtime">Realtime + REST fallback</option><option value="polling">REST polling</option></select></label>
        <label>Market feed<select value={form.market_data_feed} onChange={(event) => setForm({ ...form, market_data_feed: event.target.value })}><option value="auto">Auto / IEX</option><option value="iex">IEX</option><option value="sip">SIP (entitlement required)</option></select></label>
        <label>News fallback, sec<input type="number" min="30" max="3600" value={form.news_poll_seconds} onChange={(event) => setForm({ ...form, news_poll_seconds: Number(event.target.value) })} /></label>
        <label>Full analysis, min<input type="number" min="5" max="1440" value={form.analysis_interval_minutes} onChange={(event) => setForm({ ...form, analysis_interval_minutes: Number(event.target.value) })} /></label>
        <label>Max spread, bps<input type="number" min="1" max="1000" value={form.max_spread_bps} onChange={(event) => setForm({ ...form, max_spread_bps: Number(event.target.value) })} /></label>
        <label>Min volume ratio<input type="number" min="0" max="100" step="0.05" value={form.min_relative_volume} onChange={(event) => setForm({ ...form, min_relative_volume: Number(event.target.value) })} /></label>
        <label>Discovery top<input type="number" min="1" max="50" value={form.discovery_top} onChange={(event) => setForm({ ...form, discovery_top: Number(event.target.value) })} /></label>
        <label>Risk posture<select value={form.risk_posture} onChange={(event) => setForm({ ...form, risk_posture: event.target.value })}><option value="defensive">Defensive</option><option value="balanced">Balanced</option><option value="opportunistic">Opportunistic</option></select></label>
      </div>
      <div className="symbol-picker"><small>Monitored mandate universe</small><div>{universe.map((symbol) => <button className={form.symbols.includes(symbol) ? "selected" : ""} key={symbol} onClick={() => toggleSymbol(symbol)}>{symbol}</button>)}</div></div>
      <div className="check-grid">
        {([
          ["enabled", "Runner enabled"], ["regular_hours_only", "Proposals in regular hours only"],
          ["discovery_enabled", "Movers / most active discovery"], ["monitor_corporate_actions", "Corporate-action alerts"],
          ["options_confirmation", "Options confirmation (extra data calls)"],
        ] as const).map(([key, label]) => <label key={key}><input type="checkbox" checked={form[key]} onChange={(event) => setForm({ ...form, [key]: event.target.checked })} />{label}</label>)}
      </div>
      <label className="thesis-field">Research trajectory<textarea maxLength={2000} value={form.thesis} onChange={(event) => setForm({ ...form, thesis: event.target.value })} /></label>
      {!reviewing ? <button className="settings-save" disabled={!form.symbols.length} onClick={() => setReviewing(true)}>Review changes</button> : <div className="confirm-box"><p>This changes monitoring and proposal logic only. It cannot place an order or expand the mandate universe.</p><button disabled={saving} onClick={() => void save()}>{saving ? "Applying…" : "Confirm & apply"}</button><button onClick={() => setReviewing(false)}>Back</button></div>}
      {message && <p className="settings-message">{message}</p>}
      </div>
    </aside>
  </div>;
}

export function App() {
  const [view, setView] = useState<View>("overview");
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [paused, setPaused] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    const controller = new AbortController();
    try {
      setSnapshot(await getSnapshot(controller.signal));
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Dashboard data is unavailable");
    } finally {
      setRefreshing(false);
    }
    return () => controller.abort();
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    if (paused) return;
    const timer = window.setInterval(() => void refresh(), REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [paused, refresh]);

  const data = snapshot;
  const account = data?.session.account ?? {};
  const rawMandate = data?.mandate.mandate ?? {};
  const limits = (rawMandate.limits ?? {}) as Record<string, unknown>;
  const usage = data?.mandate.usage ?? {};
  const positions = Object.entries(data?.session.positions ?? {});
  const journal = useMemo(() => [...(data?.session.journal ?? [])].reverse(), [data]);
  const pending = data?.session.pending_orders ?? [];
  const trajectory = data?.autonomy.trajectory ?? {};
  const autonomyRuntime = data?.autonomy.runtime ?? {};
  const rawScorecard = data?.autonomy.outcomes.scorecard;
  const outcomeScorecard = rawScorecard && typeof rawScorecard === "object" && !Array.isArray(rawScorecard)
    ? Object.entries(rawScorecard as Record<string, unknown>)
    : [];
  const newsItems = useMemo(() => {
    const seen = new Set<string>();
    return [...(data?.autonomy.alerts ?? [])].reverse().filter((item) => {
      if (item.kind !== "news" || !item.headline) return false;
      const key = `${String(item.source ?? "")}:${String(item.external_id ?? item.url ?? item.headline)}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }, [data]);
  const latestNews = newsItems[0];
  const autonomyStatus = String(autonomyRuntime.status ?? "not_started");
  const dailyPnl = number(account.daily_pnl);
  const isOpen = data?.mandate.market_is_open ?? false;
  const universe = Array.isArray(rawMandate.universe) ? rawMandate.universe.map(String) : [];
  const qualityPass = number(autonomyRuntime.quality_pass);
  const qualityTotal = number(autonomyRuntime.quality_total);
  const parkReason = String(autonomyRuntime.last_action ?? "") === "PARK"
    ? (!isOpen && Boolean(trajectory.regular_hours_only ?? true)
      ? "Market closed — proposals are disabled outside regular hours."
      : qualityTotal > 0 && qualityPass < qualityTotal
        ? `Market data gate failed: ${qualityPass} of ${qualityTotal} symbols passed spread and freshness checks.`
        : "No candidate cleared the combined signal and risk gates.")
    : null;

  return (
    <div className="app-shell">
      <div className="mandate-chrome topbar-shell">
        <header className="topbar">
          <div className="brand">
            <span className="brand-mark"><Icon name="shield" /></span>
            <strong>MANDATE</strong>
          </div>
          <div className="top-actions">
            <span className="paper-badge">PAPER</span>
            <button className="icon-button settings-button" aria-label="Monitoring settings" title="Monitoring settings" onClick={() => setSettingsOpen(true)}>
              <Icon name="settings" />
            </button>
            {view !== "agent" && (
              <>
                <button
                  className={`icon-button refresh-state refresh-state--${paused ? "paused" : "live"}`}
                  aria-label={paused ? "Resume auto-refresh" : "Pause auto-refresh"}
                  title={paused ? "Resume auto-refresh" : "Pause auto-refresh"}
                  onClick={() => setPaused((value) => !value)}
                >
                  <Icon name="pulse" />
                </button>
                <button className="icon-button" aria-label="Refresh" onClick={() => void refresh()} disabled={refreshing}>
                  <span className={refreshing ? "spin" : ""}><Icon name="refresh" /></span>
                </button>
              </>
            )}
          </div>
        </header>
      </div>

      <div className="mandate-chrome workspace-nav-shell">
        <nav className="workspace-tabs" aria-label="MANDATE workspace">
          <button className={view === "overview" ? "active" : ""} onClick={() => setView("overview")}>Dashboard</button>
          <button className={view === "news" ? "active" : ""} onClick={() => setView("news")}>News</button>
          <button className={view === "agent" ? "active" : ""} onClick={() => setView("agent")}>Agent chat</button>
        </nav>
      </div>

      {view === "overview" ? <div className="mandate-chrome operator-view"><main>
        <section className="hero-row">
          <div className="market-state">
            <span className={isOpen ? "market-open" : "market-closed"}>{isOpen ? "MARKET OPEN" : "MARKET CLOSED"}</span>
          </div>
        </section>

        {Boolean(error || data?.source === "degraded" || data?.errors.length) && (
          <section className="notice" role="status">
            <b>{error ? "Dashboard API unavailable" : "Degraded read-only mode"}</b>
            <span>{error ?? data?.errors.join(" · ") ?? "Live guard data is unavailable; showing durable local evidence."}</span>
          </section>
        )}

        {data && <StatusStrip services={data.services} />}

        <section className="metrics-grid">
          <Metric label="Account equity" value={data?.source === "live" ? money(account.equity) : "—"} hint="Alpaca paper account" />
          <Metric label="Daily P&L" value={data?.source === "live" ? money(dailyPnl) : "—"} hint="vs. previous equity" tone={dailyPnl > 0 ? "good" : dailyPnl < 0 ? "bad" : "default"} />
          <Metric label="Gross exposure" value={data?.source === "live" ? percent(account.gross_exposure_pct) : "—"} hint={`limit ${decimal(limits.max_gross_exposure_pct)}%`} />
          <Metric label="Orders today" value={String(data?.session.orders_today ?? 0)} hint={`of ${limits.max_orders_per_day ?? "—"} authorized`} />
        </section>

        <section className="dashboard-grid">
          <div className="main-column">
            <article className="panel timeline-panel">
              <div className="panel-heading">
                <div><h2>Agent decisions</h2></div>
                <span className="count">{journal.length} events</span>
              </div>
              <div className="timeline">
                {journal.length ? journal.map((entry, index) => (
                  <TimelineItem entry={entry} last={index === journal.length - 1} key={`${entry.at}-${index}`} />
                )) : <Empty>No agent decisions have been recorded yet.</Empty>}
              </div>
            </article>
          </div>

          <aside className="side-column">
            <article className="panel autonomy-panel monitor-panel">
              <div className="panel-heading">
                <div><h2>Live monitoring</h2></div>
                <span className={`runner-status runner-status--${autonomyStatus}`}><i /> {autonomyStatus.replace("_", " ")}</span>
              </div>
              <div className="autonomy-body">
                <div className="autonomy-facts">
                  <span><small>Last action</small><b>{String(autonomyRuntime.last_action ?? "—")}</b></span>
                  <span><small>Analysis cadence</small><b>Every {String(trajectory.analysis_interval_minutes ?? "—")} min</b></span>
                  <span><small>News cadence</small><b>Every {String(trajectory.news_poll_seconds ?? "—")} sec</b></span>
                </div>
                {parkReason ? <div className="decision-explanation"><b>Why PARK</b><span>{parkReason}</span></div> : null}
                <div className="trajectory-summary">
                  <span>{String(trajectory.risk_posture ?? "unconfigured")} trajectory</span>
                  <p>{String(trajectory.thesis ?? "Start the runner to initialize the shared trajectory.")}</p>
                  <div>{Array.isArray(trajectory.symbols) && trajectory.symbols.map((symbol) => <b key={String(symbol)}>{String(symbol)}</b>)}</div>
                </div>
                <div className="monitor-health">
                  <span><small>News stream</small><b>{String((autonomyRuntime.stream as Record<string, unknown> | undefined)?.news ?? "—")}</b></span>
                  <span><small>Market stream</small><b>{String((autonomyRuntime.stream as Record<string, unknown> | undefined)?.market ?? "—")}</b></span>
                  <span><small>Quality</small><b>{String(autonomyRuntime.quality_pass ?? 0)} / {String(autonomyRuntime.quality_total ?? 0)}</b></span>
                  <span><small>Discovery</small><b>{String(autonomyRuntime.discovery_candidates ?? 0)} observed</b></span>
                  <span><small>Data feed</small><b>{String(autonomyRuntime.market_feed ?? "—")}</b></span>
                  <span><small>Forward outcomes</small><b>{String(autonomyRuntime.outcomes_observed ?? 0)} measured</b></span>
                </div>
                <div className="outcome-scorecard">
                  <div className="subsection-title"><span>60m strategy scorecard</span><b>{outcomeScorecard.length}</b></div>
                  {outcomeScorecard.length ? <table>
                    <thead><tr><th>Strategy</th><th>N</th><th>Mean</th><th>Hit</th><th>Weight</th></tr></thead>
                    <tbody>{outcomeScorecard.map(([name, raw]) => {
                      const item = raw as Record<string, unknown>;
                      return <tr key={name}>
                        <td>{name.replaceAll("_", " ")}</td>
                        <td>{String(item.observations ?? 0)}</td>
                        <td>{String(item.mean_signed_return_pct ?? "—")}%</td>
                        <td>{String(item.directional_accuracy_pct ?? "—")}%</td>
                        <td>{String(item.adaptive_multiplier ?? "—")}×</td>
                      </tr>;
                    })}</tbody>
                  </table> : <p className="muted">Appears after any evaluated signal receives a 60-minute counterfactual outcome.</p>}
                </div>
                <div className="latest-news">
                  <div className="subsection-title"><span>Latest news</span><button onClick={() => setView("news")}>All news · {newsItems.length}</button></div>
                  {latestNews ? <NewsCard item={latestNews} featured /> : <p className="muted">No new headline has crossed the durable alert cursor.</p>}
                </div>
                {autonomyRuntime.last_error ? <div className="attention">{String(autonomyRuntime.last_error)}</div> : null}
              </div>
            </article>

            <article className="panel mandate-panel risk-panel">
              <div className="panel-heading">
                <div><h2>Risk limits</h2></div>
                <span className="verified">✓ VALID</span>
              </div>
              <LimitBar label="Largest position" used={number(usage.max_position_pct)} limit={number(limits.max_position_pct)} />
              <LimitBar label="Gross exposure" used={number(usage.gross_exposure_pct)} limit={number(limits.max_gross_exposure_pct)} />
              <LimitBar label="Daily loss" used={number(usage.daily_loss_pct)} limit={number(limits.max_daily_loss_pct)} />
              <LimitBar label="Orders" used={number(data?.session.orders_today)} limit={number(limits.max_orders_per_day)} unit="" />
              <div className="universe">
                <span>Authorized universe</span>
                <div>{Array.isArray(rawMandate.universe) ? rawMandate.universe.map((symbol) => <b key={String(symbol)}>{String(symbol)}</b>) : "—"}</div>
              </div>
            </article>

            <article className="panel broker-panel">
              <div className="panel-heading">
                <div><h2>Positions & orders</h2></div>
                <span className="count">{positions.length}</span>
              </div>
              {positions.length ? (
                <div className="positions">
                  {positions.map(([symbol, item]) => (
                    <div key={symbol}>
                      <b>{symbol}</b>
                      <span>{String(item.qty ?? "0")} shares</span>
                      <strong>{money(item.market_value)}</strong>
                      <small>@ {money(item.market_price)}</small>
                    </div>
                  ))}
                </div>
              ) : <Empty>No open positions.</Empty>}
              <div className="subsection-title"><span>Pending orders</span><b>{pending.length}</b></div>
              {pending.length ? (
                <div className="pending-list">
                  {pending.map((order, index) => <div key={index}><b>{String(order.symbol ?? "—")}</b><span>{String(order.side ?? "")} {String(order.remaining_qty ?? "")}</span><small>@ {money(order.reference_price)}</small></div>)}
                </div>
              ) : <p className="muted">No orders are waiting at the broker.</p>}
            </article>

            <article className="panel attention-panel">
              <div className="panel-heading">
                <div><h2>Operator attention</h2></div>
              </div>
              {data?.mandate.wake_triggers.length || data?.mandate.active_predecisions.length ? (
                <div className="attention">Action required: a configured trigger or predecision is active.</div>
              ) : (
                <div className="all-clear"><span>✓</span><div><b>No active triggers</b><small>The agent remains inside delegated authority.</small></div></div>
              )}
            </article>
          </aside>
        </section>
      </main>

      </div> : view === "news" ? (
        <div className="mandate-chrome news-view"><main>
          <section className="news-page-heading">
            <div><span className="kicker">MARKET INTELLIGENCE</span><h1>News</h1></div>
            <span>{newsItems.length} unique stories</span>
          </section>
          {newsItems.length ? <section className="news-grid">
            {newsItems.map((item, index) => <NewsCard item={item} featured={index === 0} key={`${String(item.source)}:${String(item.external_id ?? item.url)}:${index}`} />)}
          </section> : <Empty>No news has been received yet.</Empty>}
        </main></div>
      ) : (
        <section className="agent-workspace" aria-label="MANDATE agent workspace">
          <TrueForgeUI
            server={{ type: "trueforge", baseUrl: "/" }}
            layout="sidebar"
            agentConfig={{ mode: "SingleAgent", name: "mandate-paper-agent" }}
            theme={{
              preset: "trueforge",
              mode: "dark",
              brand: { name: "MANDATE" },
            }}
          />
        </section>
      )}
      <TrajectorySettings
        key={String(trajectory.version ?? "new")}
        trajectory={trajectory}
        universe={universe}
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        onSaved={refresh}
      />
    </div>
  );
}
