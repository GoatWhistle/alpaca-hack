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

function pct(value: number): string {
  return `${value > 0 ? "+" : ""}${decimal(value)}%`;
}

// The IPO researcher is a deterministic monitor (Nasdaq calendar + Alpaca
// snapshots). Its structured verdict is translated here into the one or two
// sentences an operator actually needs: what the tape shows, and what is
// still blocking action.
function researchTakeaway(item: Item): string {
  const quality = record(item.quality);
  const change = number(quality.session_change_pct);
  const relVolume = number(quality.relative_volume);
  const spread = hasValue(quality.spread_bps) ? number(quality.spread_bps) : null;
  const days = number(item.days_since_listing);

  let market: string;
  if (item.research_ready === true) {
    market = `Real momentum — ${pct(change)} on ${decimal(relVolume)}× normal volume, so this one is under active watch.`;
  } else if (Math.abs(change) >= 5) {
    market = `Moved ${pct(change)}, but only ${decimal(relVolume)}× normal volume backs it — not trusted as a signal yet.`;
  } else if (Math.abs(change) < 1 && relVolume < 1) {
    market = `${days > 0 ? `${decimal(days, 0)} days in and ` : ""}going nowhere: ${pct(change)} on ${decimal(relVolume)}× volume.`;
  } else {
    market = `${pct(change)} on ${decimal(relVolume)}× volume — below the bar for a fresh look.`;
  }

  let action: string;
  if (item.execution_ready === true) {
    action = "Execution quality passed — tradable the moment the mandate allows a new listing.";
  } else if (spread === null) {
    action = "Execution stays parked: there is no reliable spread quote to size an order against.";
  } else if (spread >= 300) {
    const cost = Math.round(spread / 100);
    action = spread >= 1000
      ? `Execution stays parked: crossing the spread would cost about ${cost}% of price.`
      : `Execution stays parked: the ${decimal(spread, 0)} bps spread is still too wide.`;
  } else {
    action = "Execution is gated by mandate rules, not by liquidity.";
  }

  return `${market} ${action}`;
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

      <p className="ipo-takeaway">
        <span className="ipo-takeaway-label">Researcher&rsquo;s read</span>
        {researchTakeaway(item)}
      </p>
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
  const runtime = record(snapshot?.autonomy.runtime);
  const pollSeconds = number(runtime.effective_poll_seconds)
    || number(trajectory.news_poll_seconds)
    || 60;
  const checkedAt = typeof market.checked_at === "string" ? Date.parse(market.checked_at) : 0;
  const fresh = checkedAt > 0 && nowMs - checkedAt < Math.max(pollSeconds, 60) * 3_000;
  const active = !error && state.enabled === true && state.status !== "degraded" && fresh;
  const degraded = !error && state.status === "degraded";
  const ready = items.filter((item) => item.research_ready === true).length;
  const executable = items.filter((item) => item.execution_ready === true).length;

  return (
    <div className="mandate-chrome ipo-view">
      <main id="main-content" tabIndex={-1}>
        <h1 className="sr-only">IPO research subagent</h1>

        <div className="ipo-summary">
          <div><span>Fresh listings</span><strong>{items.length}</strong></div>
          <div><span>Research now</span><strong className="ipo-up">{ready}</strong></div>
          <div><span>Execution quality</span><strong>{executable}</strong></div>
          <div><span>Last scan</span><strong>{timestamp(market.checked_at)}</strong></div>
        </div>

        <Panel
          title="Candidate feed"
          className="ipo-feed"
          actions={
            <>
              <span className="count">{items.length} verified via Nasdaq + Alpaca</span>
              <span
                className={`ipo-status-chip ipo-status-chip--${active ? "live" : degraded ? "degraded" : "idle"}`}
                title={active ? "Scanner is cycling fresh US listings" : degraded ? "Scanner reported a degraded source" : "Waiting for the next scan window"}
              >
                {active ? "Monitoring" : degraded ? "Degraded" : "Waiting"} · every {pollSeconds >= 60 ? `${Math.round(pollSeconds / 60)}m` : `${pollSeconds}s`}
              </span>
            </>
          }
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
