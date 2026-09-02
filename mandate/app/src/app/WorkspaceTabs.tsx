import { useEffect, useLayoutEffect, useRef, useState } from "react";

export type View = "overview" | "trades" | "ipo" | "news" | "diagnostics" | "agent";

interface WorkspaceTabsProps {
  view: View;
  newsCount: number;
  ipoCount: number;
  onSelect: (view: View) => void;
}

const tabs: { key: View; label: string }[] = [
  { key: "overview", label: "Dashboard" },
  { key: "trades", label: "Trade history" },
  { key: "ipo", label: "IPO scout" },
  { key: "news", label: "News" },
  { key: "diagnostics", label: "Diagnostics" },
  { key: "agent", label: "Trader room" },
];

export function WorkspaceTabs({ view, newsCount, ipoCount, onSelect }: WorkspaceTabsProps) {
  const navRef = useRef<HTMLElement>(null);
  const [rail, setRail] = useState<{ x: number; width: number } | null>(null);

  useLayoutEffect(() => {
    const measure = () => {
      const nav = navRef.current;
      const active = nav?.querySelector<HTMLButtonElement>("button.active");
      if (!nav || !active) return;
      setRail({
        x: active.offsetLeft - nav.scrollLeft,
        width: active.offsetWidth,
      });
    };
    measure();
    const frame = requestAnimationFrame(measure);
    return () => cancelAnimationFrame(frame);
  }, [view, newsCount]);

  useEffect(() => {
    const nav = navRef.current;
    if (!nav) return;
    const measure = () => {
      const active = nav.querySelector<HTMLButtonElement>("button.active");
      if (active) setRail({ x: active.offsetLeft - nav.scrollLeft, width: active.offsetWidth });
    };
    const observer = new ResizeObserver(measure);
    observer.observe(nav);
    return () => observer.disconnect();
  }, []);

  return (
    <div className="mandate-chrome workspace-nav-shell">
      <nav ref={navRef} className="workspace-tabs" aria-label="MANDATE workspace">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            className={view === tab.key ? "active" : ""}
            aria-current={view === tab.key ? "page" : undefined}
            onClick={() => onSelect(tab.key)}
          >
            {tab.label}
            {tab.key === "ipo" && ipoCount > 0 && <em className="tab-badge">{ipoCount}</em>}
            {tab.key === "news" && newsCount > 0 && <em className="tab-badge">{newsCount}</em>}
          </button>
        ))}
        {rail && (
          <span
            className="tab-rail"
            aria-hidden="true"
            style={{
              transform: `translateX(${rail.x}px) scaleX(${rail.width / 100})`,
            }}
          />
        )}
      </nav>
    </div>
  );
}
