import { useEffect, useState } from "react";
import { updateTrajectory } from "../lib/api";

export interface TrajectoryForm {
  enabled: boolean;
  symbols: string[];
  news_poll_seconds: number;
  analysis_interval_minutes: number;
  monitoring_mode: string;
  market_data_feed: string;
  discovery_enabled: boolean;
  discovery_top: number;
  regular_hours_only: boolean;
  max_spread_bps: number;
  min_relative_volume: number;
  monitor_corporate_actions: boolean;
  options_confirmation: boolean;
  risk_posture: string;
  thesis: string;
}

export function initialForm(
  trajectory: Record<string, unknown>,
  universe: string[],
): TrajectoryForm {
  return {
    enabled: Boolean(trajectory.enabled ?? true),
    symbols: Array.isArray(trajectory.symbols) ? trajectory.symbols.map(String) : universe,
    news_poll_seconds: Number(trajectory.news_poll_seconds ?? 30),
    analysis_interval_minutes: Number(trajectory.analysis_interval_minutes ?? 3),
    monitoring_mode: String(trajectory.monitoring_mode ?? "realtime"),
    market_data_feed: String(trajectory.market_data_feed ?? "auto"),
    discovery_enabled: Boolean(trajectory.discovery_enabled ?? true),
    discovery_top: Number(trajectory.discovery_top ?? 10),
    regular_hours_only: Boolean(trajectory.regular_hours_only ?? true),
    max_spread_bps: Number(trajectory.max_spread_bps ?? 35),
    min_relative_volume: Number(trajectory.min_relative_volume ?? 0.25),
    monitor_corporate_actions: Boolean(trajectory.monitor_corporate_actions ?? true),
    options_confirmation: Boolean(trajectory.options_confirmation ?? true),
    risk_posture: String(trajectory.risk_posture ?? "opportunistic"),
    thesis: String(trajectory.thesis ?? ""),
  };
}

export function useTrajectoryForm(
  trajectory: Record<string, unknown>,
  universe: string[],
  onSaved: () => Promise<unknown>,
  onClose: () => void,
) {
  const [form, setForm] = useState(() => initialForm(trajectory, universe));
  const [reviewing, setReviewing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  const patch = (update: Partial<TrajectoryForm>) =>
    setForm((value) => ({ ...value, ...update }));

  const toggleSymbol = (symbol: string) =>
    setForm((value) => ({
      ...value,
      symbols: value.symbols.includes(symbol)
        ? value.symbols.filter((item) => item !== symbol)
        : [...value.symbols, symbol],
    }));

  const save = async () => {
    setSaving(true);
    setMessage("");
    try {
      await updateTrajectory({ ...form });
      setMessage("Applied. The runner reloads this trajectory on its next wake.");
      setReviewing(false);
      await onSaved();
      onClose();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Could not apply trajectory");
    } finally {
      setSaving(false);
    }
  };

  return { form, patch, toggleSymbol, reviewing, setReviewing, saving, message, save };
}

export function useScrollLock(open: boolean): void {
  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [open]);
}
