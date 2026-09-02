import { useCallback, useEffect, useState } from "react";
import { getBrokerTradeOrders, getTraderTimeline, type TraderTimelineEvent } from "../lib/api";
import { tradesFromBrokerOrders, tradesFromTimeline, type TradeRow } from "../lib/trades";

const REFRESH_MS = 15_000;
const PAGE_SIZE = 500;
const MAX_PAGES = 40;

async function readCompleteTimeline() {
  const items: TraderTimelineEvent[] = [];
  let after = 0;
  for (let pageNumber = 0; pageNumber < MAX_PAGES; pageNumber += 1) {
    const page = await getTraderTimeline(after, PAGE_SIZE);
    items.push(...page.items);
    if (page.items.length < PAGE_SIZE || page.next_after <= after) break;
    after = page.next_after;
  }
  return items;
}

export interface TradesState {
  trades: TradeRow[];
  loading: boolean;
  error: string | null;
}

/**
 * The dashboard's trade log. Polled rather than streamed: the live subagent
 * stream already runs over SSE in the trader room, so this surface only needs
 * the executed orders and their fill state.
 */
export function useTrades(paused: boolean): TradesState {
  const [trades, setTrades] = useState<TradeRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const timelineRows = tradesFromTimeline(await readCompleteTimeline());
      try {
        const brokerOrders = await getBrokerTradeOrders();
        const brokerRows = tradesFromBrokerOrders(brokerOrders, timelineRows);
        setTrades(brokerRows.length > 0 ? brokerRows : timelineRows);
        setError(null);
      } catch (reason) {
        setTrades(timelineRows);
        setError(reason instanceof Error
          ? `${reason.message}; showing the retained timeline only`
          : "Broker order history is unavailable; showing the retained timeline only");
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The trade log is unavailable");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (paused || document.visibilityState === "hidden") return;
    const timer = window.setInterval(() => void refresh(), REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [paused, refresh]);

  return { trades, loading, error };
}
