import { Icon, type IconName } from "../components/Icon";

export type View = "overview" | "trades" | "ipo" | "news" | "agents" | "diagnostics" | "agent";

interface SideRailProps {
  view: View;
  newsCount: number;
  ipoCount: number;
  paused: boolean;
  refreshing: boolean;
  manualRefresh: boolean;
  showRefreshControls: boolean;
  onOpenSettings: () => void;
  onTogglePause: () => void;
  onRefresh: () => void;
  onSelect: (view: View) => void;
}

const nav: { key: View; label: string; icon: IconName; badge?: "news" | "ipo" }[] = [
  { key: "overview", label: "Dashboard", icon: "grid" },
  { key: "trades", label: "Trade history", icon: "ledger" },
  { key: "ipo", label: "IPO scout", icon: "spark", badge: "ipo" },
  { key: "news", label: "News", icon: "news", badge: "news" },
  { key: "agents", label: "Agent topology", icon: "network" },
  { key: "diagnostics", label: "Diagnostics", icon: "gauge" },
  { key: "agent", label: "Trader room", icon: "chat" },
];

export function SideRail({
  view,
  newsCount,
  ipoCount,
  paused,
  refreshing,
  manualRefresh,
  showRefreshControls,
  onOpenSettings,
  onTogglePause,
  onRefresh,
  onSelect,
}: SideRailProps) {
  return (
    <nav className="mandate-chrome side-rail" aria-label="MANDATE workspace">
      <div className="side-rail-nav">
        {nav.map((item) => {
          const count = item.badge === "news" ? newsCount : item.badge === "ipo" ? ipoCount : 0;
          const active = view === item.key;
          return (
            <button
              key={item.key}
              type="button"
              className={active ? "active" : ""}
              aria-current={active ? "page" : undefined}
              aria-label={item.label}
              title={item.label}
              onClick={() => onSelect(item.key)}
            >
              <Icon name={item.icon} />
              {count > 0 && <em>{count > 99 ? "99+" : count}</em>}
            </button>
          );
        })}
      </div>
      <div className="side-rail-cluster">
        <button
          type="button"
          aria-label="Monitoring settings"
          title="Monitoring settings"
          onClick={onOpenSettings}
        >
          <Icon name="settings" />
        </button>
        {showRefreshControls && (
          <>
            <button
              type="button"
              className={`refresh-state refresh-state--${paused ? "paused" : "live"}`}
              aria-label={paused ? "Resume auto-refresh" : "Pause auto-refresh"}
              title={paused ? "Resume auto-refresh" : "Pause auto-refresh"}
              onClick={onTogglePause}
            >
              <Icon name="pulse" />
            </button>
            <button
              type="button"
              aria-label="Refresh"
              title="Refresh"
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
    </nav>
  );
}
