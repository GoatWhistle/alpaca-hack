import type { BrokerTradeOrder, TraderTimelineEvent } from "./api";
import { decodeSymbol, displaySymbol } from "./symbols";

/** One broker action the autonomous desk took, flattened for the trade log. */
export interface TradeRow {
  key: string;
  sequence: number;
  at: string;
  tradingDate: string;
  eventKind: "execution" | "risk_exit";
  side: string;
  symbol: string;
  display: string;
  kind: string;
  qty: string | null;
  limitPrice: string | null;
  filledQty: string | null;
  avgPrice: string | null;
  status: string | null;
  filled: boolean;
  reason: string | null;
  candidate: string | null;
  orderId: string | null;
  action: "entry" | "exit" | "other";
  strategyKey: string;
  multiplier: number;
  legs: TradeLeg[];
}

export interface TradeLeg {
  symbol: string;
  side: string;
  ratio: number;
  positionIntent: string | null;
}

export interface TradeHistoryRow {
  key: string;
  status: "OPEN" | "CLOSED" | "UNMATCHED";
  display: string;
  kind: string;
  direction: string;
  qty: number;
  openedAt: string | null;
  closedAt: string | null;
  entryPrice: number | null;
  exitPrice: number | null;
  pnl: number | null;
  pnlPct: number | null;
  holdingMs: number | null;
  entryReason: string | null;
  exitReason: string | null;
  entryOrderId: string | null;
  exitOrderId: string | null;
  legs: TradeLeg[];
}

export type TradeTone = "filled" | "rejected" | "working";

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function text(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function finiteNumber(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function normalizedPrice(value: unknown): string | null {
  const parsed = finiteNumber(value);
  if (parsed === null) return null;
  return String(parsed);
}

function executionLegs(order: Record<string, unknown>, broker: Record<string, unknown>): TradeLeg[] {
  const source = Array.isArray(order.legs)
    ? order.legs
    : Array.isArray(broker.legs) ? broker.legs : [];
  return source.flatMap((value) => {
    const leg = record(value);
    const symbol = text(leg.symbol);
    if (!symbol) return [];
    return [{
      symbol,
      side: (text(leg.side) ?? "").toLowerCase(),
      ratio: finiteNumber(leg.ratio_qty) ?? 1,
      positionIntent: text(leg.position_intent)?.toLowerCase() ?? null,
    }];
  });
}

function oppositeSide(side: string): string {
  return side === "buy" ? "sell" : side === "sell" ? "buy" : side;
}

/** Normalize an exit leg back to the exposure side it originally opened. */
function exposureSide(leg: TradeLeg, action: TradeRow["action"]): string {
  if (leg.positionIntent?.endsWith("_to_close")) return oppositeSide(leg.side);
  if (leg.positionIntent?.endsWith("_to_open")) return leg.side;
  return action === "exit" ? oppositeSide(leg.side) : leg.side;
}

function strategyKey(legs: TradeLeg[], symbol: string, action: TradeRow["action"]): string {
  if (legs.length < 2) return `single:${symbol}`;
  return `mleg:${legs
    .map((leg) => `${leg.symbol}:${exposureSide(leg, action)}:${leg.ratio}`)
    .sort()
    .join("|")}`;
}

function spreadDisplay(legs: TradeLeg[], fallback: string): string {
  if (legs.length < 2) return displaySymbol(fallback);
  const decoded = legs.map((leg) => ({ ...leg, option: displaySymbol(leg.symbol) }));
  const first = decoded[0];
  const root = first.option.split(" ")[0] ?? fallback;
  const expiry = first.option.split(" ")[1] ?? "";
  const strikes = decoded.map((leg) => displaySymbol(leg.symbol).split(" ").at(-1)).filter(Boolean);
  return `${root}${expiry ? ` ${expiry}` : ""} spread ${strikes.join(" / ")}`;
}

function actionFromKind(kind: string): TradeRow["action"] {
  if (kind.includes("entry")) return "entry";
  if (kind.includes("exit")) return "exit";
  return "other";
}

/** Classify a fill status into the three tones the trade log renders. */
export function tradeTone(row: Pick<TradeRow, "status" | "filled">): TradeTone {
  const status = (row.status ?? "").toLowerCase();
  if (row.filled || status === "filled") return "filled";
  if (["rejected", "canceled", "cancelled", "expired"].includes(status)) return "rejected";
  return "working";
}

function executionRow(
  event: TraderTimelineEvent,
  execution: Record<string, unknown>,
  index: number,
): TradeRow | null {
  const order = record(execution.order);
  const broker = record(execution.result);
  const kind = text(execution.kind) ?? "trade";
  const legs = executionLegs(order, broker);
  const symbol = text(order.symbol) ?? text(execution.candidate) ?? text(execution.underlying);
  if (!symbol) return null;
  const side = (text(order.side) ?? text(execution.side) ?? "").toLowerCase();
  const action = actionFromKind(kind);
  const filledQty = text(execution.filled_qty) ?? text(broker.filled_qty);
  return {
    key: `${event.sequence}:${index}`,
    sequence: event.sequence,
    at: text(broker.filled_at) ?? text(broker.submitted_at) ?? event.at,
    tradingDate: event.trading_date,
    eventKind: event.kind === "risk_exit" ? "risk_exit" : "execution",
    side,
    symbol,
    display: spreadDisplay(legs, symbol),
    kind: kind.replaceAll("_", " "),
    qty: text(order.qty),
    limitPrice: text(order.limit_price) ?? text(broker.limit_price),
    filledQty,
    avgPrice: normalizedPrice(broker.filled_avg_price),
    status: text(execution.status) ?? text(broker.status),
    filled: execution.filled === true || (finiteNumber(filledQty) ?? 0) > 0,
    reason: text(execution.reason),
    candidate: text(execution.plan_candidate_id),
    orderId: text(broker.id),
    action,
    strategyKey: strategyKey(legs, symbol, action),
    multiplier: kind.includes("option") || legs.length > 0 ? 100 : 1,
    legs,
  };
}

/** Flatten execution/risk-exit timeline events into broker-action rows, newest first. */
export function tradesFromTimeline(events: TraderTimelineEvent[]): TradeRow[] {
  const rows: TradeRow[] = [];
  for (const event of events) {
    if (event.kind !== "execution" && event.kind !== "risk_exit") continue;
    const result = record(event.details.result);
    const executions = Array.isArray(result.executions) ? result.executions : [];
    executions.forEach((value, index) => {
      const row = executionRow(event, record(value), index);
      if (row) rows.push(row);
    });
  }
  rows.sort((left, right) => right.sequence - left.sequence || right.at.localeCompare(left.at));
  return rows;
}

function brokerLegs(order: BrokerTradeOrder): TradeLeg[] {
  return order.legs.flatMap((leg) => {
    const symbol = text(leg.symbol);
    if (!symbol) return [];
    return [{
      symbol,
      side: (text(leg.side) ?? "").toLowerCase(),
      ratio: finiteNumber(leg.ratio_qty) ?? 1,
      positionIntent: text(leg.position_intent)?.toLowerCase() ?? null,
    }];
  });
}

function brokerAction(order: BrokerTradeOrder, fallback?: TradeRow): TradeRow["action"] {
  if (fallback) return fallback.action;
  const intents = [order.position_intent, ...order.legs.map((leg) => leg.position_intent)]
    .map((value) => text(value)?.toLowerCase())
    .filter((value): value is string => Boolean(value));
  if (intents.some((intent) => intent.endsWith("_to_close"))) return "exit";
  if (intents.some((intent) => intent.endsWith("_to_open"))) return "entry";
  return "other";
}

/** Use Alpaca's order ledger for completeness and the timeline for human-readable reasons. */
export function tradesFromBrokerOrders(
  orders: BrokerTradeOrder[],
  timelineRows: TradeRow[],
): TradeRow[] {
  const timelineByOrder = new Map(
    timelineRows.flatMap((row) => row.orderId ? [[row.orderId, row] as const] : []),
  );
  const ordersById = new Map(
    orders.flatMap((order) => order.id ? [[order.id, order] as const] : []),
  );
  const timelineFallback = (order: BrokerTradeOrder): TradeRow | undefined => {
    let current: BrokerTradeOrder | undefined = order;
    const seen = new Set<string>();
    while (current?.id && !seen.has(current.id)) {
      seen.add(current.id);
      const direct = timelineByOrder.get(current.id);
      if (direct) return direct;
      current = current.replaces ? ordersById.get(current.replaces) : undefined;
    }
    return undefined;
  };
  const rows: TradeRow[] = [];
  const inventory = new Map<string, number>();
  const chronological = [...orders].sort((left, right) =>
    (left.filled_at ?? left.submitted_at ?? "").localeCompare(
      right.filled_at ?? right.submitted_at ?? "",
    ));
  chronological.forEach((order, index) => {
    // `filled_qty` belongs to this concrete order, including replaced
    // ancestors and canceled orders that partially filled. Retaining each
    // positive fill is what reconstructs the actual replacement chain.
    const filledQty = finiteNumber(order.filled_qty) ?? 0;
    if (filledQty <= 0) return;
    const fallback = timelineFallback(order);
    const legs = brokerLegs(order);
    let action = brokerAction(order, fallback);
    const firstLeg = legs[0];
    const inferredRoot = firstLeg ? decodeSymbol(firstLeg.symbol).root : null;
    const symbol = text(order.symbol) ?? fallback?.symbol ?? inferredRoot;
    if (!symbol) return;
    const side = (text(order.side) ?? fallback?.side ?? "").toLowerCase();
    const inventoryKey = `single:${symbol}`;
    if (action === "other" && legs.length < 2 && (side === "buy" || side === "sell")) {
      const held = inventory.get(inventoryKey) ?? 0;
      action = side === "buy"
        ? (held < 0 ? "exit" : "entry")
        : (held > 0 ? "exit" : "entry");
    }
    if (legs.length < 2 && (side === "buy" || side === "sell")) {
      inventory.set(inventoryKey, (inventory.get(inventoryKey) ?? 0)
        + (side === "buy" ? filledQty : -filledQty));
    }
    const kind = fallback?.kind
      ?? `${legs.length > 1 ? "option spread" : order.asset_class === "us_option" ? "option" : "equity"} ${action}`;
    rows.push({
      key: `broker:${order.id ?? index}`,
      sequence: fallback?.sequence ?? index,
      at: text(order.filled_at) ?? text(order.submitted_at) ?? fallback?.at ?? "",
      tradingDate: fallback?.tradingDate ?? (text(order.filled_at) ?? "").slice(0, 10),
      eventKind: fallback?.eventKind ?? "execution",
      side,
      symbol,
      display: spreadDisplay(legs, symbol),
      kind,
      qty: text(order.qty),
      limitPrice: fallback?.limitPrice ?? null,
      filledQty: text(order.filled_qty),
      avgPrice: normalizedPrice(order.filled_avg_price),
      status: text(order.status),
      filled: true,
      reason: fallback?.reason ?? null,
      candidate: fallback?.candidate ?? null,
      orderId: text(order.id),
      action,
      strategyKey: strategyKey(legs, symbol, action),
      multiplier: order.asset_class === "us_option" || legs.length > 0 ? 100 : 1,
      legs,
    });
  });
  return rows.sort((left, right) => right.at.localeCompare(left.at));
}

interface OpenLot {
  row: TradeRow;
  remaining: number;
}

function rowExposures(row: TradeRow, qty: number): Array<{ symbol: string; signedQty: number }> {
  if (row.legs.length > 0) {
    return row.legs.map((leg) => ({
      symbol: leg.symbol,
      signedQty: qty * leg.ratio * (exposureSide(leg, "entry") === "sell" ? -1 : 1),
    }));
  }
  return [{ symbol: row.symbol, signedQty: qty * (row.side === "sell" ? -1 : 1) }];
}

function openSnapshotPnl(
  row: TradeRow,
  lotQty: number,
  positions: Record<string, Record<string, unknown>>,
  trackedExposure: Map<string, number>,
): { found: boolean; pnl: number | null; mark: number | null } {
  const exposures = rowExposures(row, lotQty);
  let found = true;
  let pnl = 0;
  let mark = 0;
  for (const exposure of exposures) {
    const position = positions[exposure.symbol];
    const liveQty = finiteNumber(position?.qty);
    const totalTracked = trackedExposure.get(exposure.symbol) ?? 0;
    if (!position || liveQty === null || liveQty === 0
      || Math.sign(liveQty) !== Math.sign(exposure.signedQty)
      || Math.abs(liveQty) + Number.EPSILON < Math.abs(totalTracked)) {
      found = false;
      break;
    }
    pnl += (finiteNumber(position.unrealized_pl) ?? 0) * Math.abs(exposure.signedQty / liveQty);
    const legMark = finiteNumber(position.market_price) ?? 0;
    // Alpaca's mleg price is signed: debit is positive, credit is negative.
    // This is the signed transaction required to close the open exposure.
    mark += row.legs.length > 1
      ? legMark * Math.abs(exposure.signedQty / lotQty) * (exposure.signedQty > 0 ? -1 : 1)
      : legMark;
  }
  return found
    ? { found: true, pnl, mark: Math.abs(mark) }
    : { found: false, pnl: null, mark: null };
}

function holdingMs(openedAt: string | null, closedAt: string | null): number | null {
  if (!openedAt) return null;
  const opened = Date.parse(openedAt);
  const closed = closedAt ? Date.parse(closedAt) : Date.now();
  return Number.isFinite(opened) && Number.isFinite(closed) ? Math.max(0, closed - opened) : null;
}

/**
 * Pair actual filled entries and exits FIFO. Open rows are marked to the live
 * broker snapshot; closed rows use the two broker fill prices. This is a desk
 * ledger, not an estimate derived from model prose.
 */
export function tradeHistory(
  trades: TradeRow[],
  positions: Record<string, Record<string, unknown>> = {},
): TradeHistoryRow[] {
  const lots = new Map<string, OpenLot[]>();
  const history: TradeHistoryRow[] = [];
  const chronological = [...trades]
    .filter((row) => row.filled)
    .sort((left, right) => left.at.localeCompare(right.at) || left.sequence - right.sequence);

  for (const row of chronological) {
    const qty = finiteNumber(row.filledQty ?? row.qty) ?? 0;
    const price = finiteNumber(row.avgPrice);
    if (qty <= 0) continue;
    if (row.action === "other") {
      history.push({
        key: `unmatched:${row.key}:${qty}`,
        status: "UNMATCHED",
        display: row.display,
        kind: row.kind,
        direction: row.side ? row.side.toUpperCase() : "UNKNOWN",
        qty,
        openedAt: null,
        closedAt: row.at,
        entryPrice: null,
        exitPrice: price,
        pnl: null,
        pnlPct: null,
        holdingMs: null,
        entryReason: null,
        exitReason: row.reason ?? "Fill direction could not be reconstructed",
        entryOrderId: null,
        exitOrderId: row.orderId,
        legs: row.legs,
      });
      continue;
    }
    if (row.action === "entry") {
      const queue = lots.get(row.strategyKey) ?? [];
      queue.push({ row, remaining: qty });
      lots.set(row.strategyKey, queue);
      continue;
    }

    let remainingExit = qty;
    const queue = lots.get(row.strategyKey) ?? [];
    while (remainingExit > 0 && queue.length > 0) {
      const lot = queue[0];
      const matched = Math.min(remainingExit, lot.remaining);
      const entryPrice = finiteNumber(lot.row.avgPrice);
      const short = lot.row.side === "sell";
      const pnl = entryPrice !== null && price !== null
        ? (lot.row.legs.length > 1
          ? -(entryPrice + price) * matched * lot.row.multiplier
          : (short ? entryPrice - price : price - entryPrice) * matched * lot.row.multiplier)
        : null;
      const basis = entryPrice !== null ? Math.abs(entryPrice * matched * lot.row.multiplier) : 0;
      history.push({
        key: `${lot.row.key}:${row.key}:${matched}`,
        status: "CLOSED",
        display: lot.row.display,
        kind: lot.row.kind,
        direction: lot.row.legs.length > 1
          ? (entryPrice !== null && entryPrice < 0 ? "CREDIT" : "DEBIT")
          : short ? "SHORT" : "LONG",
        qty: matched,
        openedAt: lot.row.at,
        closedAt: row.at,
        entryPrice,
        exitPrice: price,
        pnl,
        pnlPct: pnl !== null && basis > 0 ? pnl / basis * 100 : null,
        holdingMs: holdingMs(lot.row.at, row.at),
        entryReason: lot.row.reason,
        exitReason: row.reason,
        entryOrderId: lot.row.orderId,
        exitOrderId: row.orderId,
        legs: lot.row.legs,
      });
      lot.remaining -= matched;
      remainingExit -= matched;
      if (lot.remaining <= 0) queue.shift();
    }
    if (remainingExit > 0) {
      history.push({
        key: `unmatched:${row.key}:${remainingExit}`,
        status: "UNMATCHED",
        display: row.display,
        kind: row.kind,
        direction: row.side === "buy" ? "COVER" : "EXIT",
        qty: remainingExit,
        openedAt: null,
        closedAt: row.at,
        entryPrice: null,
        exitPrice: price,
        pnl: null,
        pnlPct: null,
        holdingMs: null,
        entryReason: null,
        exitReason: row.reason,
        entryOrderId: null,
        exitOrderId: row.orderId,
        legs: row.legs,
      });
    }
    lots.set(row.strategyKey, queue);
  }

  const trackedExposure = new Map<string, number>();
  for (const queue of lots.values()) {
    for (const lot of queue) {
      for (const exposure of rowExposures(lot.row, lot.remaining)) {
        trackedExposure.set(
          exposure.symbol,
          (trackedExposure.get(exposure.symbol) ?? 0) + exposure.signedQty,
        );
      }
    }
  }

  for (const queue of lots.values()) {
    for (const lot of queue) {
      const entryPrice = finiteNumber(lot.row.avgPrice);
      const live = openSnapshotPnl(lot.row, lot.remaining, positions, trackedExposure);
      const basis = entryPrice !== null ? Math.abs(entryPrice * lot.remaining * lot.row.multiplier) : 0;
      history.push({
        key: `open:${lot.row.key}:${lot.remaining}`,
        status: live.found ? "OPEN" : "UNMATCHED",
        display: lot.row.display,
        kind: lot.row.kind,
        direction: lot.row.legs.length > 1
          ? (entryPrice !== null && entryPrice < 0 ? "CREDIT" : "DEBIT")
          : lot.row.side === "sell" ? "SHORT" : "LONG",
        qty: lot.remaining,
        openedAt: lot.row.at,
        closedAt: null,
        entryPrice,
        exitPrice: live.mark,
        pnl: live.pnl,
        pnlPct: live.pnl !== null && basis > 0 ? live.pnl / basis * 100 : null,
        holdingMs: holdingMs(lot.row.at, null),
        entryReason: lot.row.reason,
        exitReason: live.found ? null : "No matching live position or recorded terminal exit",
        entryOrderId: lot.row.orderId,
        exitOrderId: null,
        legs: lot.row.legs,
      });
    }
  }

  return history.sort((left, right) =>
    (right.closedAt ?? right.openedAt ?? "").localeCompare(left.closedAt ?? left.openedAt ?? ""));
}
