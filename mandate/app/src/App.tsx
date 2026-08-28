import { useCallback, useEffect, useMemo, useState } from "react";
import { ToolApprovalBar, TrueForgeUI } from "@truefoundry/trueforge-ui";
import { getSnapshot, respondToApproval, updateTrajectory, type Journal, type Snapshot } from "./api";
import { decimal, money, number, percent, timestamp } from "./format";

const REFRESH_MS = 5_000;
type View = "overview" | "news" | "diagnostics" | "agent";
type TimelineFilter = "all" | "submitted" | "denied" | "parked";

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

function Metric({ label, value, hint, tone = "default", used, limit, unit = "%" }: {
  label: string;
  value: string;
  hint?: string;
  tone?: "default" | "good" | "bad" | "warn";
  used?: number;
  limit?: number;
  unit?: string;
}) {
  const hasBar = limit !== undefined && used !== undefined && limit > 0;
  const ratio = hasBar ? Math.min(Math.max((used / limit) * 100, 0), 100) : 0;
  const barDanger = (hasBar && ratio >= 80) || tone === "bad";
  return (
    <article className={`metric metric--${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {hasBar ? (
        <div className="metric-bar">
          <div className="bar"><i className={barDanger ? "danger" : ""} style={{ width: `${ratio}%` }} /></div>
          <small>{decimal(used)} / {decimal(limit)}{unit}</small>
        </div>
      ) : (
        <small>{hint}</small>
      )}
    </article>
  );
}

function ServiceHealth({ services }: { services: Snapshot["services"] }) {
  const offline = services.filter((service) => !service.ok);
  const title = services.map((service) => `${service.name}: ${service.ok ? "online" : "offline"}\n${service.url}`).join("\n\n");
  return (
    <div className={`service-health${offline.length ? " has-offline" : ""}`} title={title}>
      {services.map((service) => <i key={service.name} className={service.ok ? "online" : "offline"} />)}
      {offline.length > 0 && <span>{offline.length} down</span>}
    </div>
  );
}

function AttentionBanner({ lines }: { lines: { level: "error" | "warn"; text: string }[] }) {
  if (!lines.length) return null;
  const hasError = lines.some((line) => line.level === "error");
  return (
    <section className={`attention-banner${hasError ? " attention-banner--error" : ""}`} role="status">
      <b>{hasError ? "Needs attention" : "Operator decision"}</b>
      <ul>{lines.map((line, index) => <li key={index}>{line.text}</li>)}</ul>
    </section>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="empty"><span>○</span><p>{children}</p></div>;
}

type ApprovalAction = { busy: boolean; outcome?: "approved" | "denied"; error?: string };

function DecisionCard({ item, action, onRespond }: {
  item: Record<string, unknown>;
  action: ApprovalAction | undefined;
  onRespond: (item: Record<string, unknown>, approve: boolean) => void;
}) {
  const args = (item.arguments && typeof item.arguments === "object"
    ? item.arguments
    : {}) as Record<string, unknown>;
  const toolName = String(item.tool_name ?? "tool");
  const isOrder = toolName === "submit_order_under_mandate";
  const summary = isOrder
    ? `${String(args.side ?? "?").toUpperCase()} ${String(args.qty ?? "?")} ${String(args.symbol ?? "?")}${args.limit_price ? ` limit ${String(args.limit_price)}` : ""}`
    : toolName.replaceAll("_", " ");
  const status = action?.outcome
    ? { type: action.outcome as "approved" | "denied", label: action.outcome === "approved" ? "Approved" : "Denied" }
    : undefined;
  return (
    <article className={`decision-card${action?.outcome ? " decided" : ""}`}>
      <div className="decision-main">
        <div className="decision-topline">
          <b>{summary}</b>
          <time>{timestamp(item.created_at)}</time>
        </div>
        {isOrder
          ? <p className="decision-warning">An executed paper order is irreversible. The guard re-checks every mandate limit before submission.</p>
          : null}
        {args.rationale ? <p className="decision-rationale">{String(args.rationale)}</p> : null}
        <div className="decision-meta">
          <span>{String(item.session_title ?? "") || String(item.session_id ?? "")}</span>
        </div>
        <details>
          <summary>Tool request</summary>
          <pre>{JSON.stringify({ tool: toolName, arguments: item.arguments ?? {} }, null, 2)}</pre>
        </details>
      </div>
      <div className="decision-actions">
        <ToolApprovalBar
          toolName={toolName}
          approveOptions={[{ id: "allow", label: "Approve", variant: "primary" }]}
          denyOptions={[{ id: "deny", label: "Deny", variant: "destructive" }]}
          onSelect={(optionId) => onRespond(item, optionId === "allow")}
          status={status}
          disabled={action?.busy || Boolean(action?.outcome)}
        />
        {action?.error ? <p className="decision-error">{action.error}</p> : null}
      </div>
    </article>
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

const timelineFilters: { key: TimelineFilter; label: string; outcomes: string[] }[] = [
  { key: "all", label: "All", outcomes: [] },
  { key: "submitted", label: "Submitted", outcomes: ["submitted"] },
  { key: "denied", label: "Denied", outcomes: ["denied", "conflict"] },
  { key: "parked", label: "Parked", outcomes: ["parked"] },
];

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
          <time>{timestamp(entry.at)}</time>
        </div>
        <p>{entry.rationale}</p>
        {Boolean(entry.details.intent_id || entry.details.order_id || entry.details.intended_action) && (
          <div className="detail-chips">
            {Boolean(entry.details.intent_id) && <span>intent {String(entry.details.intent_id).slice(0, 14)}</span>}
            {Boolean(entry.details.order_id) && <span>order {String(entry.details.order_id).slice(0, 14)}</span>}
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
    <div className="news-copy">
      <h3>{newsText(item.headline ?? "Untitled market update")}</h3>
      {item.summary ? <p>{newsText(item.summary)}</p> : null}
    </div>
    {url ? <a href={url} target="_blank" rel="noreferrer">Read full article <Icon name="external" /></a> : null}
  </article>;
}

function discoveryWatchlist(market: Record<string, unknown> | undefined, mandateSymbols: string[]): string[] {
  if (!market) return [];
  const discovery = (market.discovery ?? {}) as Record<string, unknown>;
  const movers = (discovery.movers ?? {}) as Record<string, unknown>;
  const candidates = [movers.gainers, movers.losers, discovery.most_active]
    .flatMap((value) => Array.isArray(value) ? value : [])
    .flatMap((value) => {
      if (typeof value === "string") return [value];
      if (typeof value !== "object" || value === null || Array.isArray(value)) return [];
      const symbol = (value as Record<string, unknown>).symbol;
      return typeof symbol === "string" ? [symbol] : [];
    })
    .map((value) => value.trim().toUpperCase())
    .filter((value) => /^[A-Z][A-Z0-9.-]{0,9}$/u.test(value) && !mandateSymbols.includes(value));
  return [...new Set(candidates)].slice(0, 5);
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
        <section className="settings-section">
          <small>Cadence &amp; mode</small>
          <div className="settings-grid">
            <label>Monitoring mode<select value={form.monitoring_mode} onChange={(event) => setForm({ ...form, monitoring_mode: event.target.value })}><option value="realtime">Realtime + REST fallback</option><option value="polling">REST polling</option></select></label>
            <label>Market feed<select value={form.market_data_feed} onChange={(event) => setForm({ ...form, market_data_feed: event.target.value })}><option value="auto">Auto / IEX</option><option value="iex">IEX</option><option value="sip">SIP (entitlement required)</option></select></label>
            <label>News polling, seconds<input type="number" min="30" max="3600" value={form.news_poll_seconds} onChange={(event) => setForm({ ...form, news_poll_seconds: Number(event.target.value) })} /></label>
            <label>Full analysis, minutes<input type="number" min="5" max="1440" value={form.analysis_interval_minutes} onChange={(event) => setForm({ ...form, analysis_interval_minutes: Number(event.target.value) })} /></label>
          </div>
        </section>
        <section className="settings-section">
          <small>Data quality gates</small>
          <div className="settings-grid">
            <label>Max spread, bps<input type="number" min="1" max="1000" value={form.max_spread_bps} onChange={(event) => setForm({ ...form, max_spread_bps: Number(event.target.value) })} /></label>
            <label>Min relative volume<input type="number" min="0" max="100" step="0.05" value={form.min_relative_volume} onChange={(event) => setForm({ ...form, min_relative_volume: Number(event.target.value) })} /></label>
          </div>
          <div className="check-grid">
            <label><input type="checkbox" checked={form.regular_hours_only} onChange={(event) => setForm({ ...form, regular_hours_only: event.target.checked })} />Proposals in regular market hours only</label>
          </div>
        </section>
        <section className="settings-section">
          <small>Discovery &amp; events</small>
          <div className="settings-grid">
            <label>Discovery list size<input type="number" min="1" max="50" value={form.discovery_top} onChange={(event) => setForm({ ...form, discovery_top: Number(event.target.value) })} /></label>
          </div>
          <div className="check-grid">
            <label><input type="checkbox" checked={form.discovery_enabled} onChange={(event) => setForm({ ...form, discovery_enabled: event.target.checked })} />Movers / most active discovery</label>
            <label><input type="checkbox" checked={form.monitor_corporate_actions} onChange={(event) => setForm({ ...form, monitor_corporate_actions: event.target.checked })} />Corporate-action alerts</label>
            <label><input type="checkbox" checked={form.options_confirmation} onChange={(event) => setForm({ ...form, options_confirmation: event.target.checked })} />Options confirmation (extra data calls)</label>
          </div>
        </section>
        <section className="settings-section">
          <small>Posture &amp; authority</small>
          <div className="settings-grid">
            <label>Risk posture<select value={form.risk_posture} onChange={(event) => setForm({ ...form, risk_posture: event.target.value })}><option value="defensive">Defensive</option><option value="balanced">Balanced</option><option value="opportunistic">Opportunistic</option></select></label>
            <label>Runner state<select value={form.enabled ? "enabled" : "paused"} onChange={(event) => setForm({ ...form, enabled: event.target.value === "enabled" })}><option value="enabled">Enabled</option><option value="paused">Paused</option></select></label>
          </div>
          <div className="symbol-picker"><small>Monitored mandate universe</small><div>{universe.map((symbol) => <button className={form.symbols.includes(symbol) ? "selected" : ""} key={symbol} onClick={() => toggleSymbol(symbol)}>{symbol}</button>)}</div></div>
          <label className="thesis-field">Research trajectory<textarea maxLength={2000} value={form.thesis} onChange={(event) => setForm({ ...form, thesis: event.target.value })} /></label>
        </section>
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
  const [hidden, setHidden] = useState(() => document.visibilityState === "hidden");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [timelineFilter, setTimelineFilter] = useState<TimelineFilter>("all");
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [approvalActions, setApprovalActions] = useState<Record<string, ApprovalAction>>({});

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
    if (paused || hidden) return;
    const timer = window.setInterval(() => void refresh(), REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [paused, hidden, refresh]);
  useEffect(() => {
    const onVisibility = () => setHidden(document.visibilityState === "hidden");
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);
  useEffect(() => {
    const timer = window.setInterval(() => setNowMs(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, []);

  const data = snapshot;
  const account = data?.session.account ?? {};
  const rawMandate = data?.mandate.mandate ?? {};
  const limits = (rawMandate.limits ?? {}) as Record<string, unknown>;
  const usage = data?.mandate.usage ?? {};
  const positions = Object.entries(data?.session.positions ?? {});
  const pending = data?.session.pending_orders ?? [];
  const trajectory = data?.autonomy.trajectory ?? {};
  const autonomyRuntime = data?.autonomy.runtime ?? {};
  const autonomyMarket = data?.autonomy.market ?? {};
  const rawScorecard = data?.autonomy.outcomes.scorecard;
  const outcomeScorecard = rawScorecard && typeof rawScorecard === "object" && !Array.isArray(rawScorecard)
    ? Object.entries(rawScorecard as Record<string, unknown>)
    : [];
  const journal = useMemo(() => [...(data?.session.journal ?? [])].reverse(), [data]);
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
  const autonomyStatus = String(autonomyRuntime.status ?? "not_started");
  const dailyPnl = number(account.daily_pnl);
  const isOpen = data?.mandate.market_is_open ?? false;
  const universe = Array.isArray(rawMandate.universe) ? rawMandate.universe.map(String) : [];
  const qualityPass = number(autonomyRuntime.quality_pass);
  const qualityTotal = number(autonomyRuntime.quality_total);
  const watchlist = useMemo(() => discoveryWatchlist(autonomyMarket, universe), [autonomyMarket, universe]);
  const parkReason = String(autonomyRuntime.last_action ?? "") === "PARK"
    ? (!isOpen && Boolean(trajectory.regular_hours_only ?? true)
      ? "Market closed — proposals are disabled outside regular hours."
      : qualityTotal > 0 && qualityPass < qualityTotal
        ? `Market data gate failed: ${qualityPass} of ${qualityTotal} symbols passed spread and freshness checks.`
        : "No candidate cleared the combined signal and risk gates.")
    : null;
  const liveSource = data?.source === "live";
  const exposureLimit = number(limits.max_gross_exposure_pct);
  const exposureUsed = number(account.gross_exposure_pct);
  const exposureTone = exposureLimit > 0 && exposureUsed / exposureLimit >= 0.8 ? "warn" : "default";
  const filterCounts = useMemo(() => {
    const counts: Record<TimelineFilter, number> = { all: journal.length, submitted: 0, denied: 0, parked: 0 };
    for (const entry of journal) {
      if (entry.outcome === "submitted") counts.submitted += 1;
      if (entry.outcome === "denied" || entry.outcome === "conflict") counts.denied += 1;
      if (entry.outcome === "parked") counts.parked += 1;
    }
    return counts;
  }, [journal]);
  const activeFilter = timelineFilters.find((filter) => filter.key === timelineFilter) ?? timelineFilters[0];
  const visibleJournal = activeFilter.outcomes.length
    ? journal.filter((entry) => activeFilter.outcomes.includes(entry.outcome))
    : journal;
  const runnerMode = String(trajectory.monitoring_mode ?? "—");
  const runnerFeed = String(autonomyRuntime.market_feed ?? "—");
  const attentionLines = useMemo(() => {
    const lines: { level: "error" | "warn"; text: string }[] = [];
    if (error) lines.push({ level: "error", text: `Dashboard API unavailable: ${error}` });
    if (data?.source === "degraded") {
      for (const item of data?.errors ?? []) lines.push({ level: "warn", text: `Degraded read-only mode — ${item}` });
    }
    if ((data?.mandate.wake_triggers ?? []).length || (data?.mandate.active_predecisions ?? []).length) {
      lines.push({ level: "warn", text: "A configured wake trigger or predecision is active — review it in the agent chat." });
    }
    const lastError = autonomyRuntime.last_error;
    if (lastError) lines.push({ level: "warn", text: `Runner: ${String(lastError)}` });
    if (data && data.approvals && data.approvals.count > 0) {
      lines.push({
        level: "warn",
        text: `${data.approvals.count} agent decision${data.approvals.count > 1 ? "s are" : " is"} waiting for your approval.`,
      });
    }
    return lines;
  }, [error, data, autonomyRuntime.last_error]);
  const generatedAgeS = data ? Math.max(0, Math.round((nowMs - Date.parse(data.generated_at)) / 1000)) : null;
  const freshness = paused
    ? "paused"
    : generatedAgeS === null
      ? "no data"
      : `${generatedAgeS}s ago`;
  const stream = (autonomyRuntime.stream ?? {}) as Record<string, unknown>;
  const approvals = data?.approvals ?? { count: 0, items: [] };
  const handleApprovalRespond = useCallback(async (item: Record<string, unknown>, approve: boolean) => {
    const toolCallId = String(item.tool_call_id ?? "");
    if (!toolCallId) return;
    setApprovalActions((previous) => ({ ...previous, [toolCallId]: { busy: true } }));
    try {
      await respondToApproval({
        sessionId: String(item.session_id ?? ""),
        toolCallId,
        threadId: String(item.thread_id ?? ""),
        approve,
      });
      setApprovalActions((previous) => ({
        ...previous,
        [toolCallId]: { busy: false, outcome: approve ? "approved" : "denied" },
      }));
      await refresh();
    } catch (reason) {
      setApprovalActions((previous) => ({
        ...previous,
        [toolCallId]: {
          busy: false,
          error: reason instanceof Error ? reason.message : "Could not deliver the decision",
        },
      }));
    }
  }, [refresh]);

  return (
    <div className="app-shell">
      <div className="mandate-chrome topbar-shell">
        <header className="topbar">
          <div className="brand">
            <span className="brand-mark"><Icon name="shield" /></span>
            <strong>MANDATE</strong>
          </div>
          <div className="top-status">
            <span className={`market-pill ${isOpen ? "market-open" : "market-closed"}`}>{isOpen ? "MARKET OPEN" : "MARKET CLOSED"}</span>
            <span className="paper-badge">PAPER</span>
            {data && <ServiceHealth services={data.services} />}
          </div>
          <div className="top-actions">
            <span className={`freshness${paused || hidden ? " stale" : ""}`} title={hidden ? "Auto-refresh paused while the tab is hidden" : undefined}>
              {hidden ? "auto-paused" : freshness}
            </span>
            {approvals.count > 0 && (
              <button
                className="approval-badge"
                onClick={() => setView("overview")}
                title={`${approvals.count} agent decision${approvals.count > 1 ? "s" : ""} awaiting approval`}
              >
                {approvals.count} awaiting approval
              </button>
            )}
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
          <button className={view === "news" ? "active" : ""} onClick={() => setView("news")}>
            News{newsItems.length > 0 && <em className="tab-badge">{newsItems.length}</em>}
          </button>
          <button className={view === "diagnostics" ? "active" : ""} onClick={() => setView("diagnostics")}>Diagnostics</button>
          <button className={view === "agent" ? "active" : ""} onClick={() => setView("agent")}>Agent chat</button>
        </nav>
      </div>

      {view === "overview" ? <div className="mandate-chrome operator-view"><main>
        <AttentionBanner lines={attentionLines} />

        {approvals.count > 0 && (
          <section className="decisions">
            <div className="decisions-heading">
              <h2>Operator decisions</h2>
              <span>{approvals.count} awaiting</span>
            </div>
            {approvals.items.map((item) => {
              const toolCallId = String(item.tool_call_id ?? "");
              return (
                <DecisionCard
                  key={toolCallId || String(item.created_at ?? "")}
                  item={item}
                  action={approvalActions[toolCallId]}
                  onRespond={(entry, approve) => void handleApprovalRespond(entry, approve)}
                />
              );
            })}
          </section>
        )}

        <section className="metrics-block">
          <div className="metrics-grid">
            <Metric label="Account equity" value={liveSource ? money(account.equity) : "—"} hint="Alpaca paper account" />
            <Metric label="Daily P&L" value={liveSource ? money(dailyPnl) : "—"} tone={dailyPnl > 0 ? "good" : dailyPnl < 0 ? "bad" : "default"} used={number(usage.daily_loss_pct)} limit={number(limits.max_daily_loss_pct)} />
            <Metric label="Gross exposure" value={liveSource ? percent(exposureUsed) : "—"} tone={exposureTone} used={exposureUsed} limit={exposureLimit} />
            <Metric label="Orders today" value={String(data?.session.orders_today ?? 0)} used={number(data?.session.orders_today)} limit={number(limits.max_orders_per_day)} unit="" />
          </div>
          <div className="metrics-footer">
            <div className="universe-chips">
              <span>Universe</span>
              <div>{universe.length ? universe.map((symbol) => <b key={symbol}>{symbol}</b>) : "—"}</div>
            </div>
          </div>
        </section>

        {newsItems[0] && (
          <section className="panel latest-news-panel">
            <div className="panel-heading">
              <div><h2>Latest news</h2></div>
              <button className="text-button" onClick={() => setView("news")}>Open news feed</button>
            </div>
            <NewsCard item={newsItems[0]} featured />
          </section>
        )}

        <section className="dashboard-grid">
          <div className="main-column">
            <article className="panel timeline-panel">
              <div className="panel-heading">
                <div><h2>Agent decisions</h2></div>
                <div className="filter-chips">
                  {timelineFilters.map((filter) => (
                    <button
                      key={filter.key}
                      className={timelineFilter === filter.key ? "active" : ""}
                      onClick={() => setTimelineFilter(filter.key)}
                    >
                      {filter.label}<em>{filterCounts[filter.key]}</em>
                    </button>
                  ))}
                </div>
              </div>
              <div className="timeline">
                {visibleJournal.length ? visibleJournal.map((entry, index) => (
                  <TimelineItem entry={entry} last={index === visibleJournal.length - 1} key={`${entry.at}-${index}`} />
                )) : <Empty>No {timelineFilter === "all" ? "agent decisions have been" : `${activeFilter.label.toLowerCase()} decisions are`} recorded yet.</Empty>}
              </div>
            </article>
          </div>

          <aside className="side-column">
            <article className="panel broker-panel">
              <div className="panel-heading">
                <div><h2>Positions &amp; orders</h2></div>
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

            <article className="panel runner-panel">
              <div className="panel-heading">
                <div><h2>Agent runner</h2></div>
                <span className={`runner-status runner-status--${autonomyStatus}`}><i /> {autonomyStatus.replaceAll("_", " ")}</span>
              </div>
              <div className="runner-line">
                <span>{runnerMode}</span>
                <span>quality {qualityTotal > 0 ? `${qualityPass}/${qualityTotal}` : "—"}</span>
                <span>{runnerFeed}</span>
                <span>every {String(trajectory.analysis_interval_minutes ?? "—")} min</span>
                <span>last action <b>{String(autonomyRuntime.last_action ?? "—")}</b></span>
              </div>
              {parkReason ? <div className="decision-explanation"><b>Why PARK</b><span>{parkReason}</span></div> : null}
              <details className="runner-details">
                <summary>Runner &amp; trajectory details</summary>
                <div className="trajectory-summary">
                  <span>{String(trajectory.risk_posture ?? "unconfigured")} trajectory</span>
                  <p>{String(trajectory.thesis ?? "Start the runner to initialize the shared trajectory.")}</p>
                  <div>{Array.isArray(trajectory.symbols) && trajectory.symbols.map((symbol) => <b key={String(symbol)}>{String(symbol)}</b>)}</div>
                </div>
                <div className="monitor-health">
                  <span><small>News stream</small><b>{String(stream.news ?? "—")}</b></span>
                  <span><small>Market stream</small><b>{String(stream.market ?? "—")}</b></span>
                  <span><small>News cadence</small><b>every {String(trajectory.news_poll_seconds ?? "—")} s</b></span>
                  <span><small>Forward outcomes</small><b>{String(autonomyRuntime.outcomes_observed ?? 0)} measured</b></span>
                  <span><small>Last analysis</small><b>{timestamp(autonomyRuntime.last_analysis_at)}</b></span>
                  <span><small>Next analysis</small><b>{timestamp(autonomyRuntime.next_analysis_at)}</b></span>
                </div>
              </details>
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
          {newsItems.length ? <section className="news-stream">
            {newsItems.map((item, index) => <NewsCard item={item} featured={index === 0} key={`${String(item.source)}:${String(item.external_id ?? item.url)}:${index}`} />)}
          </section> : <Empty>No news has been received yet.</Empty>}
        </main></div>
      ) : view === "diagnostics" ? (
        <div className="mandate-chrome diagnostics-view"><main>
          <section className="news-page-heading">
            <div><span className="kicker">OPERATIONS</span><h1>Diagnostics</h1></div>
            <span>feeds, streams and measured outcomes</span>
          </section>
          <section className="dashboard-grid">
            <article className="panel diag-panel">
              <div className="panel-heading"><div><h2>Services</h2></div><span className="count">{data?.services.length ?? 0}</span></div>
              {data?.services.length ? <div className="service-rows">
                {data.services.map((service) => (
                  <div key={service.name}>
                    <i className={service.ok ? "online" : "offline"} />
                    <span>{service.name}</span>
                    <small>{service.url}</small>
                    <b className={service.ok ? "ok" : "down"}>{service.ok ? "online" : "offline"}</b>
                  </div>
                ))}
              </div> : <Empty>Service status is unavailable.</Empty>}
            </article>

            <article className="panel diag-panel">
              <div className="panel-heading"><div><h2>Data feeds &amp; streams</h2></div><span className="count">{runnerFeed}</span></div>
              <div className="monitor-health diagnostics-health">
                <span><small>News stream</small><b>{String(stream.news ?? "—")}</b></span>
                <span><small>Market stream</small><b>{String(stream.market ?? "—")}</b></span>
                <span><small>Data feed</small><b>{runnerFeed}</b></span>
                <span><small>Quality gate</small><b>{qualityTotal > 0 ? `${qualityPass}/${qualityTotal}` : "—"}</b></span>
                <span><small>Discovery candidates</small><b>{String(autonomyRuntime.discovery_candidates ?? 0)} observed</b></span>
                <span><small>Corporate actions</small><b>{String(autonomyRuntime.corporate_action_events ?? 0)}</b></span>
              </div>
            </article>

            <article className="panel diag-panel">
              <div className="panel-heading"><div><h2>60m strategy scorecard</h2></div><span className="count">{outcomeScorecard.length} strategies</span></div>
              {outcomeScorecard.length ? <div className="outcome-scorecard scorecard-standalone">
                <table>
                  <thead><tr><th>Strategy</th><th>N</th><th>Mean</th><th>Hit</th><th>Sharpe-like</th><th>Weight</th></tr></thead>
                  <tbody>{outcomeScorecard.map(([name, raw]) => {
                    const item = raw as Record<string, unknown>;
                    return <tr key={name}>
                      <td>{name.replaceAll("_", " ")}</td>
                      <td>{String(item.observations ?? 0)}</td>
                      <td>{String(item.mean_signed_return_pct ?? "—")}%</td>
                      <td>{String(item.directional_accuracy_pct ?? "—")}%</td>
                      <td>{String(item.sharpe_like ?? "—")}</td>
                      <td>{String(item.adaptive_multiplier ?? "—")}×</td>
                    </tr>;
                  })}</tbody>
                </table>
              </div> : <p className="muted">Appears after any evaluated signal receives a 60-minute counterfactual outcome.</p>}
            </article>

            <article className="panel diag-panel">
              <div className="panel-heading"><div><h2>Discovery watchlist</h2></div><span className="count">observation only</span></div>
              {watchlist.length ? <div className="watchlist">
                {watchlist.map((symbol) => <b key={symbol}>{symbol}</b>)}
                <p className="muted">Movers and most-active names outside the mandate universe. Observing them never grants trading authority — a symbol can only be authorized by a mandate change.</p>
              </div> : <Empty>No discovery candidates right now.</Empty>}
            </article>
          </section>
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
