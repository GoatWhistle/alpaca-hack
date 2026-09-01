import { ExecutionToggle, type ExecutionMode } from "../components/ExecutionToggle";
import { Icon } from "../components/Icon";
import { SourceBadge } from "../components/SourceBadge";
import { Wordmark } from "../components/Wordmark";
import type { ServiceStatus } from "../lib/api";

function ServiceHealth({ services }: { services: ServiceStatus[] }) {
  const offline = services.filter((service) => !service.ok);
  const title = services
    .map((service) => `${service.name}: ${service.ok ? "online" : "offline"}\n${service.url}`)
    .join("\n\n");
  return (
    <div
      className={`service-health${offline.length ? " has-offline" : ""}`}
      title={title}
      role="status"
      aria-live="polite"
      aria-label={offline.length
        ? `${offline.length} of ${services.length} services offline: ${offline.map((s) => s.name).join(", ")}`
        : `All ${services.length} services online`}
    >
      {services.map((service) => (
        <i key={service.name} className={service.ok ? "online" : "offline"} aria-hidden="true" />
      ))}
      {offline.length > 0 && <span>{offline.length} down</span>}
    </div>
  );
}

interface TopBarProps {
  marketOpen: boolean;
  source: "live" | "degraded" | null;
  sourceReasons: string[];
  stale: boolean;
  services: ServiceStatus[];
  freshness: string;
  hidden: boolean;
  paused: boolean;
  refreshing: boolean;
  manualRefresh: boolean;
  approvalCount: number;
  executionMode: ExecutionMode;
  executionBusy: boolean;
  demoActive: boolean;
  demoBusy: boolean;
  showRefreshControls: boolean;
  onOpenSettings: () => void;
  onTogglePause: () => void;
  onRefresh: () => void;
  onFocusApprovals: () => void;
  onToggleExecution: () => void;
  onToggleDemo: () => void;
}

export function TopBar({
  marketOpen,
  source,
  sourceReasons,
  stale,
  services,
  freshness,
  hidden,
  paused,
  refreshing,
  manualRefresh,
  approvalCount,
  executionMode,
  executionBusy,
  demoActive,
  demoBusy,
  showRefreshControls,
  onOpenSettings,
  onTogglePause,
  onRefresh,
  onFocusApprovals,
  onToggleExecution,
  onToggleDemo,
}: TopBarProps) {
  return (
    <div className="mandate-chrome topbar-shell">
      <header className="topbar">
        <div className="top-status">
          <Wordmark />
          <span className={`market-pill ${marketOpen ? "market-open" : "market-closed"}`}>
            {marketOpen ? "MARKET OPEN" : "MARKET CLOSED"}
          </span>
          <span className="paper-badge">PAPER</span>
          <SourceBadge source={source} reasons={sourceReasons} />
          {services.length > 0 && <ServiceHealth services={services} />}
        </div>
        <div className="top-actions">
          <ExecutionToggle
            mode={executionMode}
            busy={executionBusy}
            disabled={source === null}
            onToggle={onToggleExecution}
          />
          <button
            className={`simulation-toggle${demoActive ? " simulation-toggle--active" : ""}`}
            onClick={onToggleDemo}
            disabled={demoBusy}
            title={demoActive ? "Stop the safety rehearsal" : "Start a manual-approval rehearsal"}
          >
            {demoActive ? "REHEARSAL" : "REHEARSE"}
          </button>
          <span
            className={`freshness${paused || hidden || stale ? " stale" : ""}`}
            title={hidden ? "Auto-refresh paused while the tab is hidden" : undefined}
          >
            {hidden ? "auto-paused" : freshness}
          </span>
          {approvalCount > 0 && (
            <button
              className="approval-badge"
              onClick={onFocusApprovals}
              title={`${approvalCount} agent decision${approvalCount > 1 ? "s" : ""} awaiting approval`}
            >
              {approvalCount} awaiting approval
            </button>
          )}
          <button
            className="icon-button settings-button"
            aria-label="Monitoring settings"
            title="Monitoring settings"
            onClick={onOpenSettings}
          >
            <Icon name="settings" />
          </button>
          {showRefreshControls && (
            <>
              <button
                className={`icon-button refresh-state refresh-state--${paused ? "paused" : "live"}`}
                aria-label={paused ? "Resume auto-refresh" : "Pause auto-refresh"}
                title={paused ? "Resume auto-refresh" : "Pause auto-refresh"}
                onClick={onTogglePause}
              >
                <Icon name="pulse" />
              </button>
              <button
                className="icon-button"
                aria-label="Refresh"
                onClick={onRefresh}
                disabled={refreshing}
              >
                <span className={manualRefresh ? "spin" : ""}>
                  <Icon name="refresh" />
                </span>
              </button>
            </>
          )}
        </div>
      </header>
    </div>
  );
}
