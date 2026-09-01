import { useCallback, useEffect, useState } from "react";
import { getSnapshot, type Snapshot } from "../lib/api";

const REFRESH_MS = 5_000;

export interface SnapshotState {
  snapshot: Snapshot | null;
  error: string | null;
  refreshing: boolean;
  manualRefresh: boolean;
  paused: boolean;
  hidden: boolean;
  nowMs: number;
  setPaused: (update: (value: boolean) => boolean) => void;
  refresh: (manual?: boolean) => Promise<void>;
}

export function useSnapshot(): SnapshotState {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [manualRefresh, setManualRefresh] = useState(false);
  const [paused, setPaused] = useState(false);
  const [hidden, setHidden] = useState(() => document.visibilityState === "hidden");
  const [nowMs, setNowMs] = useState(() => Date.now());

  const refresh = useCallback(async (manual = false) => {
    setRefreshing(true);
    if (manual) setManualRefresh(true);
    try {
      setSnapshot(await getSnapshot());
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Dashboard data is unavailable");
    } finally {
      setRefreshing(false);
      setManualRefresh(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (paused || hidden) return;
    const interval = snapshot?.demo.enabled ? 2_000 : REFRESH_MS;
    const timer = window.setInterval(() => void refresh(), interval);
    return () => window.clearInterval(timer);
  }, [paused, hidden, refresh, snapshot?.demo.enabled]);

  useEffect(() => {
    const onVisibility = () => setHidden(document.visibilityState === "hidden");
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => setNowMs(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, []);

  return { snapshot, error, refreshing, manualRefresh, paused, hidden, nowMs, setPaused, refresh };
}

const STALE_AFTER_S = 20;

export function snapshotAgeSeconds(snapshot: Snapshot | null, nowMs: number): number | null {
  if (!snapshot) return null;
  const parsed = Date.parse(snapshot.generated_at);
  if (Number.isNaN(parsed)) return null;
  return Math.max(0, Math.round((nowMs - parsed) / 1000));
}

export function freshnessLabel(
  snapshot: Snapshot | null,
  nowMs: number,
  paused: boolean,
): string {
  if (paused) return "paused";
  const ageS = snapshotAgeSeconds(snapshot, nowMs);
  if (ageS === null) return "no data";
  return `${ageS}s ago`;
}

export function isStale(snapshot: Snapshot | null, nowMs: number): boolean {
  const ageS = snapshotAgeSeconds(snapshot, nowMs);
  return ageS !== null && ageS > STALE_AFTER_S;
}
