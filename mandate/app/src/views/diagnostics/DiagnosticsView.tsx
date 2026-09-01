import type { Snapshot } from "../../lib/api";
import { discoveryWatchlist, qualityCounts } from "../dashboard/selectors";
import { ScorecardTable } from "./ScorecardTable";
import { FeedsPanel, ServicesPanel, WatchlistPanel } from "./ServicesPanel";

export function DiagnosticsView({ snapshot }: { snapshot: Snapshot | null }) {
  const runtime = snapshot?.autonomy.runtime ?? {};
  const market = snapshot?.autonomy.market ?? {};
  const mandate = (snapshot?.mandate.mandate ?? {}) as Record<string, unknown>;
  const universe = Array.isArray(mandate.universe) ? mandate.universe.map(String) : [];
  const [qualityPass, qualityTotal] = qualityCounts(runtime);

  const rawScorecard = snapshot?.autonomy.outcomes.scorecard;
  const scorecard = rawScorecard && typeof rawScorecard === "object" && !Array.isArray(rawScorecard)
    ? Object.entries(rawScorecard as Record<string, unknown>)
    : [];

  return (
    <div className="mandate-chrome diagnostics-view">
      <main id="main-content" tabIndex={-1}>
        <h1 className="sr-only">Diagnostics</h1>
        <section className="dashboard-grid">
          <ServicesPanel services={snapshot?.services ?? []} />
          <FeedsPanel
            runtime={runtime}
            qualityPass={qualityPass}
            qualityTotal={qualityTotal}
          />
          <ScorecardTable rows={scorecard} />
          <WatchlistPanel symbols={discoveryWatchlist(market, universe)} />
        </section>
      </main>
    </div>
  );
}
