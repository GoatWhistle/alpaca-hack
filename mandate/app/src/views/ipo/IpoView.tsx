import { Empty, Panel } from "../../components/Panel";
import { decimal, hasValue, money, number, timestamp } from "../../lib/format";
import type { Snapshot } from "../../lib/schema";

type Item = Record<string, unknown>;

function record(value: unknown): Item {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Item
    : {};
}

function ipoState(snapshot: Snapshot | null): Item {
  const market = record(snapshot?.autonomy.market);
  const discovery = record(market.discovery);
  return record(discovery.ipos);
}

function candidates(snapshot: Snapshot | null): Item[] {
  const raw = ipoState(snapshot).candidates;
  return Array.isArray(raw)
    ? raw.filter((item): item is Item => typeof item === "object" && item !== null && !Array.isArray(item))
    : [];
}

export function ipoCandidateCount(snapshot: Snapshot | null): number {
  return candidates(snapshot).filter((item) => item.research_ready === true).length;
}

function warningLabel(value: unknown): string {
  const labels: Record<string, string> = {
    missing_spread: "No reliable spread",
    spread: "Spread too wide",
    stale: "Execution quote stale",
    relative_volume: "Volume not confirmed",
    missing_relative_volume: "No volume baseline",
    missing_timestamp: "No live timestamp",
  };
  return labels[String(value)] ?? String(value).replaceAll("_", " ");
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: "up" | "down" }) {
  return (
    <div className="ipo-metric">
      <span>{label}</span>
      <strong className={tone ? `ipo-${tone}` : undefined}>{value}</strong>
    </div>
  );
}

function CandidateCard({ item }: { item: Item }) {
  const quality = record(item.quality);
  const alpaca = record(item.alpaca);
  const change = number(quality.session_change_pct);
  const warnings = Array.isArray(item.research_warnings) ? item.research_warnings : [];
  const researchReady = item.research_ready === true;
  const executionReady = item.execution_ready === true;
  return (
    <article className={`ipo-card${researchReady ? " ipo-card--ready" : ""}`}>
      <header>
        <div>
          <span className="ipo-symbol">{String(item.symbol ?? "—")}</span>
          <h2>{String(item.company ?? "New listing")}</h2>
        </div>
        <span className={`ipo-state ${researchReady ? "ipo-state--ready" : ""}`}>
          {researchReady ? "Research now" : "Watching"}
        </span>
      </header>

      <div className="ipo-context">
        <span>Listed {String(item.listing_date ?? "—")}</span>
        <span>{String(item.exchange ?? "US")}</span>
        {item.offer_price ? <span>Offer {String(item.offer_price)}</span> : null}
      </div>

      <div className="ipo-metrics">
        <Metric
          label="Session"
          value={hasValue(quality.session_change_pct) ? `${change > 0 ? "+" : ""}${decimal(change)}%` : "—"}
          tone={change > 0 ? "up" : change < 0 ? "down" : undefined}
        />
        <Metric label="Relative volume" value={hasValue(quality.relative_volume) ? `${decimal(quality.relative_volume)}×` : "—"} />
        <Metric label="Last" value={hasValue(quality.last) ? money(quality.last) : "—"} />
        <Metric label="Spread" value={hasValue(quality.spread_bps) ? `${decimal(quality.spread_bps)} bps` : "—"} />
      </div>

      <div className="ipo-gates">
        <span className={executionReady ? "pass" : "blocked"}>
          {executionReady ? "Execution quality passed" : "Execution gated"}
        </span>
        <span>{alpaca.fractionable === true ? "Fractional" : "Whole shares"}</span>
        <span>{alpaca.shortable === true ? "Shortable" : "Long only"}</span>
        <span className="outside">Outside mandate</span>
      </div>

      {warnings.length > 0 && (
        <div className="ipo-warnings">
          {warnings.map((warning) => <span key={String(warning)}>{warningLabel(warning)}</span>)}
        </div>
      )}
    </article>
  );
}

export function IpoView({ snapshot, error, nowMs }: {
  snapshot: Snapshot | null;
  error: string | null;
  nowMs: number;
}) {
  const state = ipoState(snapshot);
  const items = candidates(snapshot);
  const market = record(snapshot?.autonomy.market);
  const trajectory = record(snapshot?.autonomy.trajectory);
  const checkedAt = typeof market.checked_at === "string" ? Date.parse(market.checked_at) : 0;
  const fresh = checkedAt > 0 && nowMs - checkedAt < Math.max(number(trajectory.news_poll_seconds), 60) * 3_000;
  const active = !error && state.enabled === true && state.status !== "degraded" && fresh;
  const ready = items.filter((item) => item.research_ready === true).length;
  const executable = items.filter((item) => item.execution_ready === true).length;

  return (
    <div className="mandate-chrome ipo-view">
      <main id="main-content" tabIndex={-1}>
        <h1 className="sr-only">IPO research subagent</h1>
        <section className="ipo-hero">
          <div className={`ipo-agent-orb${active ? " active" : ""}`} aria-hidden="true"><i /></div>
          <div className="ipo-agent-copy">
            <span className="kicker">Read-only subagent</span>
            <h2>IPO Researcher</h2>
            <p>Continuously scans fresh US listings, rejects obvious SPACs, verifies Alpaca access and challenges momentum with live liquidity.</p>
          </div>
          <div className="ipo-agent-status">
            <strong>{active ? "Monitoring" : state.status === "degraded" ? "Degraded" : "Waiting"}</strong>
            <span>every {number(trajectory.news_poll_seconds) || 60}s</span>
          </div>
        </section>

        <div className="ipo-summary">
          <div><span>Fresh listings</span><strong>{items.length}</strong></div>
          <div><span>Research now</span><strong className="ipo-up">{ready}</strong></div>
          <div><span>Execution quality</span><strong>{executable}</strong></div>
          <div><span>Last scan</span><strong>{timestamp(market.checked_at)}</strong></div>
        </div>

        <Panel
          title="Candidate feed"
          count={`${items.length} verified via Nasdaq + Alpaca`}
          className="ipo-feed"
        >
          {items.length > 0 ? (
            <div className="ipo-card-grid">{items.map((item) => <CandidateCard key={String(item.symbol)} item={item} />)}</div>
          ) : (
            <Empty>{error ?? "No recent tradable IPOs passed source validation yet."}</Empty>
          )}
        </Panel>
      </main>
    </div>
  );
}
