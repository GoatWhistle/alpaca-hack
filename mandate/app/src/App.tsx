import { useCallback, useEffect, useMemo, useState } from "react";
import { TrueForgeUI } from "@truefoundry/trueforge-ui";
import { getSnapshot, type Journal, type Snapshot } from "./api";
import { decimal, money, number, percent, shortId, timestamp } from "./format";

const REFRESH_MS = 5_000;
type View = "overview" | "agent";

function Icon({ name }: { name: "shield" | "refresh" | "external" | "pulse" }) {
  const paths = {
    shield: <path d="M12 3 5 6v5c0 4.5 2.8 8 7 10 4.2-2 7-5.5 7-10V6l-7-3Zm-3 9 2 2 4-5" />,
    refresh: <path d="M20 12a8 8 0 1 1-2.3-5.7L20 8M20 4v4h-4" />,
    external: <path d="M14 4h6v6M20 4l-9 9M18 13v6H5V6h6" />,
    pulse: <path d="M3 12h4l2-6 4 12 2-6h6" />,
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
          <time>{timestamp(entry.at)}</time>
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

export function App() {
  const [view, setView] = useState<View>("overview");
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [paused, setPaused] = useState(false);

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
  const dailyPnl = number(account.daily_pnl);
  const isOpen = data?.mandate.market_is_open ?? false;

  return (
    <div className="app-shell">
      <div className="mandate-chrome">
        <header className="topbar">
          <div className="brand">
            <span className="brand-mark"><Icon name="shield" /></span>
            <div><strong>MANDATE</strong><small>OPERATOR CONSOLE</small></div>
          </div>
          <nav className="view-tabs" aria-label="Workspace views">
            <button className={view === "overview" ? "active" : ""} onClick={() => setView("overview")}>Overview</button>
            <button className={view === "agent" ? "active" : ""} onClick={() => setView("agent")}>Agent workspace</button>
          </nav>
          <div className="top-actions">
            <span className="paper-badge">PAPER ONLY</span>
            {view === "overview" && (
              <>
                <button className="ghost" onClick={() => setPaused((value) => !value)}>
                  <i className={paused ? "offline" : "online"} /> {paused ? "Paused" : "Auto-refresh"}
                </button>
                <button className="icon-button" aria-label="Refresh" onClick={() => void refresh()} disabled={refreshing}>
                  <span className={refreshing ? "spin" : ""}><Icon name="refresh" /></span>
                </button>
              </>
            )}
            <button className="primary-button" onClick={() => setView(view === "agent" ? "overview" : "agent")}>
              {view === "agent" ? "View overview" : "Open agent"} <Icon name={view === "agent" ? "pulse" : "external"} />
            </button>
          </div>
        </header>
      </div>

      {view === "overview" ? <div className="mandate-chrome operator-view"><main>
        <section className="hero-row">
          <div>
            <div className="eyebrow"><Icon name="pulse" /> LIVE SUPERVISION</div>
            <h1>{String(rawMandate.name ?? "Waiting for mandate")}</h1>
            <p>One screen for authority, risk, broker state, and every durable agent decision.</p>
          </div>
          <div className="market-state">
            <span className={isOpen ? "market-open" : "market-closed"}>{isOpen ? "MARKET OPEN" : "MARKET CLOSED"}</span>
            <small>Updated {timestamp(data?.generated_at)}</small>
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

        <section className="content-grid">
          <div className="main-column">
            <article className="panel flow-panel">
              <div className="panel-heading">
                <div><span className="kicker">SYSTEM FLOW</span><h2>What is happening</h2></div>
                <span className="live-label"><i /> monitoring</span>
              </div>
              <div className="flow">
                <div><b>01</b><span><strong>Research</strong><small>News + price signals</small></span></div>
                <i>→</i>
                <div><b>02</b><span><strong>Mandate check</strong><small>Deterministic limits</small></span></div>
                <i>→</i>
                <div><b>03</b><span><strong>Human gate</strong><small>Approve irreversible action</small></span></div>
                <i>→</i>
                <div><b>04</b><span><strong>Paper broker</strong><small>Alpaca execution</small></span></div>
              </div>
            </article>

            <article className="panel">
              <div className="panel-heading">
                <div><span className="kicker">DURABLE AUDIT TRAIL</span><h2>Agent timeline</h2></div>
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
            <article className="panel mandate-panel">
              <div className="panel-heading">
                <div><span className="kicker">HUMAN AUTHORITY</span><h2>Mandate limits</h2></div>
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

            <article className="panel">
              <div className="panel-heading">
                <div><span className="kicker">BROKER STATE</span><h2>Positions</h2></div>
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
                <div><span className="kicker">OPERATOR ATTENTION</span><h2>Wake conditions</h2></div>
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

      <footer><span>MANDATE · TrueForge operator surface</span><span>Paper trading only · Not investment advice</span></footer></div> : (
        <section className="agent-workspace" aria-label="MANDATE agent workspace">
          <TrueForgeUI
            server={{ type: "trueforge", baseUrl: "/" }}
            layout="sidebar"
            theme={{
              preset: "trueforge",
              mode: "dark",
              brand: { name: "MANDATE" },
            }}
          />
        </section>
      )}
    </div>
  );
}
