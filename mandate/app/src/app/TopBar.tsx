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
  approvalCount: number;
  onOpenApprovals: () => void;
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
  approvalCount,
  onOpenApprovals,
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
          <span
            className={`freshness${paused || hidden || stale ? " stale" : ""}`}
            title={hidden ? "Auto-refresh paused while the tab is hidden" : undefined}
          >
            {hidden ? "auto-paused" : freshness}
          </span>
          {approvalCount > 0 && (
            <button
              className="approval-badge"
              onClick={onOpenApprovals}
              title={`${approvalCount} memory change${approvalCount > 1 ? "s" : ""} awaiting approval`}
            >
              {approvalCount} memory approval{approvalCount > 1 ? "s" : ""}
            </button>
          )}
        </div>
      </header>
    </div>
  );
}
