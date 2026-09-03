import { useEffect } from "react";
import type { View } from "./SideRail";

const VIEW_TITLES: Record<View, string> = {
  overview: "Dashboard",
  trades: "Trade history",
  ipo: "IPO scout",
  news: "News",
  agents: "Agent topology",
  diagnostics: "Diagnostics",
  agent: "Trader room",
};

export type IdentityState = "idle" | "pending" | "degraded";

function faviconMarkup(state: IdentityState): string {
  const disc = state === "degraded" ? "#e24756" : state === "pending" ? "#83c3ff" : "#fafafa";
  const bracket = state === "degraded" ? "#e24756" : "#83c3ff";
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="32" height="32">
  <rect width="32" height="32" rx="6" fill="#080809"/>
  <path d="M10 8 H6.5 V24 H10" fill="none" stroke="${bracket}" stroke-width="2.5" stroke-linecap="square"/>
  <path d="M22 8 H25.5 V24 H22" fill="none" stroke="${bracket}" stroke-width="2.5" stroke-linecap="square"/>
  <circle cx="16" cy="16" r="4.5" fill="${disc}"/>
</svg>`;
}

export function useBrowserIdentity(
  view: View,
  pendingCount: number,
  degraded: boolean,
): void {
  useEffect(() => {
    const prefix = pendingCount > 0 ? `(${pendingCount}) ` : "";
    document.title = `${prefix}${VIEW_TITLES[view]} — MANDATE`;
  }, [view, pendingCount]);

  useEffect(() => {
    const state: IdentityState = degraded ? "degraded" : pendingCount > 0 ? "pending" : "idle";
    const href = `data:image/svg+xml,${encodeURIComponent(faviconMarkup(state))}`;
    let link = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
    if (!link) {
      link = document.createElement("link");
      link.rel = "icon";
      document.head.appendChild(link);
    }
    link.type = "image/svg+xml";
    link.href = href;
  }, [pendingCount, degraded]);

  useEffect(() => {
    const meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
    if (meta) meta.content = degraded ? "#160d0e" : "#080809";
  }, [degraded]);
}
