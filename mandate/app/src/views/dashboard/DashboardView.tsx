import { useMemo, useState } from "react";
import { Panel } from "../../components/Panel";
import type { Snapshot } from "../../lib/api";
import { timelineFilters, type TimelineFilter } from "../../lib/outcomes";
import { NewsCard } from "../news/NewsCard";
import type { ApprovalAction } from "./decision/DecisionCard";
import { DecisionQueue, StandingBy } from "./decision/DecisionQueue";
import { JournalTimeline } from "./journal/JournalTimeline";
import { LivePipeline } from "./LivePipeline";
import { DegradedNotice } from "./panels/DegradedNotice";
import { AttentionBanner, MetricsBlock } from "./panels/MetricsBlock";
import { PositionsPanel } from "./panels/PositionsPanel";
import { RunnerPanel } from "./panels/RunnerPanel";
import {
  attentionLines,
  filterCounts,
  parkReason,
  qualityCounts,
  visibleJournal,
} from "./selectors";

interface DashboardViewProps {
  snapshot: Snapshot | null;
  error: string | null;
  news: Record<string, unknown>[];
  decisionItems: Record<string, unknown>[];
  hidden: boolean;
  approvalActions: Record<string, ApprovalAction>;
  onRespond: (item: Record<string, unknown>, approve: boolean) => void;
  onOpenNews: () => void;
}

export function DashboardView({
  snapshot,
  error,
  news,
  decisionItems,
  hidden,
  approvalActions,
  onRespond,
  onOpenNews,
}: DashboardViewProps) {
  const [filter, setFilter] = useState<TimelineFilter>("all");

  const mandate = (snapshot?.mandate.mandate ?? {}) as Record<string, unknown>;
  const limits = (mandate.limits ?? {}) as Record<string, unknown>;
  const headroom = snapshot?.mandate.headroom ?? {};
  const usage = snapshot?.mandate.usage ?? {};
  const account = snapshot?.session.account ?? {};
  const runtime = snapshot?.autonomy.runtime ?? {};
  const trajectory = snapshot?.autonomy.trajectory ?? {};
  const marketOpen = snapshot?.mandate.market_is_open ?? false;
  const live = snapshot?.source === "live" && !error;
  const universe = Array.isArray(mandate.universe) ? mandate.universe.map(String) : [];

  const journal = useMemo(
    () => [...(snapshot?.session.journal ?? [])].reverse(),
    [snapshot],
  );
  const counts = useMemo(() => filterCounts(journal), [journal]);
  const visible = useMemo(() => visibleJournal(journal, filter), [journal, filter]);
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

        {decisionItems.length > 0 ? (
          <DecisionQueue
            items={decisionItems}
            headroom={headroom}
            limits={limits}
            actions={approvalActions}
            live={live}
            hidden={hidden}
            onRespond={onRespond}
          />
        ) : live ? (
          <StandingBy marketOpen={marketOpen} />
        ) : null}

        <MetricsBlock
          account={account}
          limits={limits}
          usage={usage}
          ordersToday={snapshot?.session.orders_today ?? 0}
          universe={universe}
          live={live}
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
            <Panel
              title="Agent decisions"
              className="timeline-panel"
              actions={
                <div className="filter-chips">
                  {timelineFilters.map((item) => (
                    <button
                      key={item.key}
                      className={filter === item.key ? "active" : ""}
                      onClick={() => setFilter(item.key)}
                    >
                      {item.label}
                      <em>{counts[item.key]}</em>
                    </button>
                  ))}
                </div>
              }
            >
              <JournalTimeline entries={visible} filter={filter} loading={snapshot === null} />
            </Panel>
          </div>

          <aside className="side-column">
            <PositionsPanel
              positions={Object.entries(snapshot?.session.positions ?? {})}
              pending={snapshot?.session.pending_orders ?? []}
              live={live}
            />
            <RunnerPanel
              trajectory={trajectory}
              runtime={runtime}
              parkReason={parkReason(runtime, trajectory, marketOpen, qualityPass, qualityTotal)}
              qualityPass={qualityPass}
              qualityTotal={qualityTotal}
            />
          </aside>
        </section>
      </main>
    </div>
  );
}
