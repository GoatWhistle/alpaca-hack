import { useMemo } from "react";
import { Panel } from "../../components/Panel";
import type { Snapshot } from "../../lib/api";
import { useTrades } from "../../app/useTrades";
import { NewsCard } from "../news/NewsCard";
import { LivePipeline } from "./LivePipeline";
import { DegradedNotice } from "./panels/DegradedNotice";
import { AttentionBanner, MetricsBlock } from "./panels/MetricsBlock";
import { OpenBookPanel } from "./panels/OpenBookPanel";
import { RunnerPanel } from "./panels/RunnerPanel";
import { TradeLogPanel } from "./panels/TradeLogPanel";
import { attentionLines, decisionReason, qualityCounts } from "./selectors";

interface DashboardViewProps {
  snapshot: Snapshot | null;
  error: string | null;
  news: Record<string, unknown>[];
  hidden: boolean;
  paused: boolean;
  onOpenNews: () => void;
  onOpenTrades: () => void;
}

export function DashboardView({
  snapshot,
  error,
  news,
  hidden,
  paused,
  onOpenNews,
  onOpenTrades,
}: DashboardViewProps) {
  const { trades, loading: tradesLoading, error: tradesError } = useTrades(paused || hidden);

  const mandate = (snapshot?.mandate.mandate ?? {}) as Record<string, unknown>;
  const limits = (mandate.limits ?? {}) as Record<string, unknown>;
  const usage = snapshot?.mandate.usage ?? {};
  const account = snapshot?.session.account ?? {};
  const runtime = snapshot?.autonomy.runtime ?? {};
  const trajectory = snapshot?.autonomy.trajectory ?? {};
  const marketOpen = snapshot?.mandate.market_is_open ?? false;
  const live = snapshot?.source === "live" && !error;
  const universe = Array.isArray(mandate.universe) ? mandate.universe.map(String) : [];
  const equity = Number(account.equity ?? 0) || 0;

  const lines = useMemo(() => attentionLines(snapshot, error), [snapshot, error]);
  const [qualityPass, qualityTotal] = qualityCounts(runtime);

  return (
    <div className="mandate-chrome operator-view">
      <main id="main-content" tabIndex={-1}>
        <h1 className="sr-only">Operator dashboard</h1>
        {!live && (
          <DegradedNotice
            reasons={error ? [error, ...(snapshot?.errors ?? [])] : snapshot?.errors ?? []}
            offlineServices={(snapshot?.services ?? [])
              .filter((service) => !service.ok)
              .map((service) => service.name)}
          />
        )}
        <AttentionBanner lines={lines} />
        <LivePipeline runtime={runtime} />

        <MetricsBlock
          account={account}
          limits={limits}
          usage={usage}
          ordersToday={snapshot?.session.orders_today ?? 0}
          universe={universe}
          live={live}
        />

        <OpenBookPanel
          positions={Object.entries(snapshot?.session.positions ?? {})}
          pending={snapshot?.session.pending_orders ?? []}
          live={live}
          equity={equity}
        />

        {news[0] && (
          <Panel
            title="Latest news"
            className="latest-news-panel"
            actions={
              <button className="text-button" onClick={onOpenNews}>
                Open news feed
              </button>
            }
          >
            <NewsCard item={news[0]} featured />
          </Panel>
        )}

        <section className="dashboard-grid">
          <div className="main-column">
            <TradeLogPanel
              trades={trades}
              loading={tradesLoading}
              error={tradesError}
              onOpenHistory={onOpenTrades}
            />
          </div>

          <aside className="side-column">
            <RunnerPanel
              trajectory={trajectory}
              runtime={runtime}
              decisionReason={decisionReason(runtime, trajectory, marketOpen, qualityPass, qualityTotal)}
              qualityPass={qualityPass}
              qualityTotal={qualityTotal}
            />
          </aside>
        </section>
      </main>
    </div>
  );
}
