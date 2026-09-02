import type { Journal, Snapshot } from "../../lib/api";
import { number } from "../../lib/format";
import { timelineFilters, type TimelineFilter } from "../../lib/outcomes";

export interface AttentionLine {
  level: "error" | "warn";
  text: string;
}

export function newsItems(snapshot: Snapshot | null): Record<string, unknown>[] {
  const seen = new Set<string>();
  return [...(snapshot?.autonomy.alerts ?? [])].reverse().filter((item) => {
    if (item.kind !== "news" || !item.headline) return false;
    const key = `${String(item.source ?? "")}:${String(item.external_id ?? item.url ?? item.headline)}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function filterCounts(journal: Journal[]): Record<TimelineFilter, number> {
  const counts: Record<TimelineFilter, number> = {
    all: journal.length,
    submitted: 0,
    denied: 0,
    parked: 0,
  };
  for (const entry of journal) {
    if (["submitted", "submitted_reconciled", "filled"].includes(entry.outcome)) {
      counts.submitted += 1;
    }
    if (entry.outcome === "denied" || entry.outcome === "conflict") counts.denied += 1;
    if (entry.outcome === "parked") counts.parked += 1;
  }
  return counts;
}

export function visibleJournal(journal: Journal[], filter: TimelineFilter): Journal[] {
  const active = timelineFilters.find((item) => item.key === filter) ?? timelineFilters[0];
  return active.outcomes.length
    ? journal.filter((entry) => active.outcomes.includes(entry.outcome))
    : journal;
}

/**
 * The reason behind the runner's latest decision. Every cycle carries one:
 * a PARK explains what blocked entries, a SUBMITTED cycle explains the trade.
 */
export function decisionReason(
  runtime: Record<string, unknown>,
  trajectory: Record<string, unknown>,
  marketOpen: boolean,
  qualityPass: number,
  qualityTotal: number,
): string | null {
  const lastAction = String(runtime.last_action ?? "");
  const modelReason = String(runtime.last_reason ?? "").trim();
  if (lastAction !== "PARK") return lastAction && modelReason ? modelReason : null;
  if (modelReason) return modelReason;
  if (!marketOpen && Boolean(trajectory.regular_hours_only ?? true)) {
    return "Market closed — proposals are disabled outside regular hours.";
  }
  if (qualityTotal > 0 && qualityPass < qualityTotal) {
    return `Market data gate failed: ${qualityPass} of ${qualityTotal} symbols passed spread and freshness checks.`;
  }
  return "No candidate cleared the combined signal and risk gates.";
}

export function attentionLines(
  snapshot: Snapshot | null,
  error: string | null,
): AttentionLine[] {
  const lines: AttentionLine[] = [];
  if (error) lines.push({ level: "error", text: `Dashboard API unavailable: ${error}` });
  const triggers = snapshot?.mandate.wake_triggers ?? [];
  const predecisions = snapshot?.mandate.active_predecisions ?? [];
  if (triggers.length || predecisions.length) {
    lines.push({
      level: "warn",
      text: "A configured wake trigger or predecision is active — review it in the agent chat.",
    });
  }
  const lastError = snapshot?.autonomy.runtime.last_error;
  if (lastError) lines.push({ level: "warn", text: `Runner: ${String(lastError)}` });
  return lines;
}

export function discoveryWatchlist(
  market: Record<string, unknown> | undefined,
  mandateSymbols: string[],
): string[] {
  if (!market) return [];
  const discovery = (market.discovery ?? {}) as Record<string, unknown>;
  const movers = (discovery.movers ?? {}) as Record<string, unknown>;
  const candidates = [movers.gainers, movers.losers, discovery.most_active]
    .flatMap((value) => (Array.isArray(value) ? value : []))
    .flatMap((value) => {
      if (typeof value === "string") return [value];
      if (typeof value !== "object" || value === null || Array.isArray(value)) return [];
      const symbol = (value as Record<string, unknown>).symbol;
      return typeof symbol === "string" ? [symbol] : [];
    })
    .map((value) => value.trim().toUpperCase())
    .filter((value) => /^[A-Z][A-Z0-9.-]{0,9}$/u.test(value) && !mandateSymbols.includes(value));
  return [...new Set(candidates)].slice(0, 5);
}

export function qualityCounts(runtime: Record<string, unknown>): [number, number] {
  return [number(runtime.quality_pass), number(runtime.quality_total)];
}
