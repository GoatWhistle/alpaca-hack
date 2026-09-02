import { useCallback, useMemo, useState } from "react";
import { flushSync } from "react-dom";
import { TopBar } from "./app/TopBar";
import { WorkspaceTabs, type View } from "./app/WorkspaceTabs";
import { ErrorBoundary } from "./app/ErrorBoundary";
import { useBrowserIdentity } from "./app/useBrowserIdentity";
import { freshnessLabel, isStale, useSnapshot } from "./app/useSnapshot";
import { respondToApproval } from "./lib/api";
import { TrajectoryDrawer } from "./settings/TrajectoryDrawer";
import { DashboardView } from "./views/dashboard/DashboardView";
import type { ApprovalAction } from "./views/dashboard/decision/DecisionCard";
import { newsItems } from "./views/dashboard/selectors";
import { DiagnosticsView } from "./views/diagnostics/DiagnosticsView";
import { NewsView } from "./views/news/NewsView";
import { AgentWorkspace } from "./views/agent/AgentWorkspace";
import { IpoView, ipoCandidateCount } from "./views/ipo/IpoView";
import { TradeHistoryView } from "./views/trades/TradeHistoryView";

const VIEW_AREAS: Record<View, string> = {
  overview: "The dashboard",
  trades: "Trade history",
  ipo: "The IPO scout",
  news: "The news feed",
  diagnostics: "Diagnostics",
  agent: "The trader room",
};

const VIEWS = new Set<View>(["overview", "trades", "ipo", "news", "diagnostics", "agent"]);

function initialView(): View {
  const hash = window.location.hash.slice(1) as View;
  return VIEWS.has(hash) ? hash : "overview";
}

export function App() {
  const [view, setView] = useState<View>(initialView);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [approvalActions, setApprovalActions] = useState<Record<string, ApprovalAction>>({});
  const state = useSnapshot();
  const { snapshot, error, refresh } = state;

  const news = useMemo(() => newsItems(snapshot), [snapshot]);
  const ipoCount = ipoCandidateCount(snapshot);
  const approvals = snapshot?.approvals ?? { count: 0, items: [] };
  // The approval surface is intentionally single-step. Completed decisions
  // belong in the durable journal, not in a growing stack above the dashboard.
  const decisionItems = approvals.items.slice(0, 1);
  const mandate = (snapshot?.mandate.mandate ?? {}) as Record<string, unknown>;
  const universe = Array.isArray(mandate.universe) ? mandate.universe.map(String) : [];

  const trajectory = snapshot?.autonomy.trajectory ?? {};

  const degraded = Boolean(error) || (snapshot !== null && snapshot.source !== "live");
  useBrowserIdentity(view, approvals.count, degraded);

  const selectView = useCallback(
    (next: View) => {
      if (next === view) return;
      const url = new URL(window.location.href);
      url.hash = next === "overview" ? "" : next;
      window.history.replaceState(null, "", url);
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      if (reduce || !document.startViewTransition) {
        setView(next);
        return;
      }
      document.startViewTransition(() => flushSync(() => setView(next)));
    },
    [view],
  );

  const handleRespond = useCallback(
    async (item: Record<string, unknown>, approve: boolean) => {
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
    },
    [refresh],
  );

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <TopBar
        marketOpen={snapshot?.mandate.market_is_open ?? false}
        source={error ? "degraded" : snapshot?.source ?? null}
        sourceReasons={error ? [error, ...(snapshot?.errors ?? [])] : snapshot?.errors ?? []}
        stale={isStale(snapshot, state.nowMs)}
        services={snapshot?.services ?? []}
        freshness={freshnessLabel(snapshot, state.nowMs, state.paused)}
        hidden={state.hidden}
        paused={state.paused}
        refreshing={state.refreshing}
        manualRefresh={state.manualRefresh}
        approvalCount={approvals.count}
        showRefreshControls={view !== "agent"}
        onOpenSettings={() => setSettingsOpen(true)}
        onTogglePause={() => state.setPaused((value) => !value)}
        onRefresh={() => void refresh(true)}
        onFocusApprovals={() => selectView("overview")}
      />

      <WorkspaceTabs view={view} newsCount={news.length} ipoCount={ipoCount} onSelect={selectView} />

      <div className="workspace-body">
        <ErrorBoundary key={view} area={VIEW_AREAS[view]}>
          {view === "overview" && (
            <DashboardView
              snapshot={snapshot}
              error={error}
              news={news}
              decisionItems={decisionItems}
              hidden={state.hidden}
              paused={state.paused}
              approvalActions={approvalActions}
              onRespond={(item, approve) => void handleRespond(item, approve)}
              onOpenNews={() => selectView("news")}
              onOpenTrades={() => selectView("trades")}
            />
          )}
          {view === "news" && <NewsView items={news} />}
          {view === "trades" && (
            <TradeHistoryView snapshot={snapshot} paused={state.paused || state.hidden} />
          )}
          {view === "ipo" && <IpoView snapshot={snapshot} error={error} nowMs={state.nowMs} />}
          {view === "diagnostics" && <DiagnosticsView snapshot={snapshot} />}
          {view === "agent" && <AgentWorkspace snapshot={snapshot} error={error} />}
        </ErrorBoundary>
      </div>

      <TrajectoryDrawer
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
