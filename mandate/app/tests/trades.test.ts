import assert from "node:assert/strict";
import test from "node:test";
import type { BrokerTradeOrder } from "../src/lib/api";
import { tradeHistory, tradesFromBrokerOrders } from "../src/lib/trades";

function order(overrides: Partial<BrokerTradeOrder>): BrokerTradeOrder {
  return {
    id: null, client_order_id: null, replaces: null, replaced_by: null,
    symbol: null, asset_class: "us_equity", side: null, position_intent: null,
    ratio_qty: null, qty: null, filled_qty: null, filled_avg_price: null,
    order_class: "simple", status: "filled", submitted_at: null, filled_at: null,
    legs: [], ...overrides,
  };
}

test("pairs a debit spread with its inverse close and preserves signed cash flow", () => {
  const entryLegs = [
    order({ symbol: "GOOGL260909C00337500", side: "buy", position_intent: "buy_to_open", ratio_qty: "1" }),
    order({ symbol: "GOOGL260909C00352500", side: "sell", position_intent: "sell_to_open", ratio_qty: "1" }),
  ];
  const exitLegs = [
    order({ symbol: "GOOGL260909C00337500", side: "sell", position_intent: "sell_to_close", ratio_qty: "1" }),
    order({ symbol: "GOOGL260909C00352500", side: "buy", position_intent: "buy_to_close", ratio_qty: "1" }),
  ];
  const trades = tradesFromBrokerOrders([
    order({ id: "exit", order_class: "mleg", asset_class: "", qty: "13", filled_qty: "13",
      filled_avg_price: "-3.572308", filled_at: "2026-09-02T19:50:07Z", legs: exitLegs }),
    order({ id: "entry", order_class: "mleg", asset_class: "", qty: "13", filled_qty: "13",
      filled_avg_price: "4.26", filled_at: "2026-09-02T19:12:36Z", legs: entryLegs }),
  ], []);
  const [row] = tradeHistory(trades);
  assert.equal(row.status, "CLOSED");
  assert.equal(row.direction, "DEBIT");
  assert.equal(row.entryPrice, 4.26);
  assert.equal(row.exitPrice, -3.572308);
  assert.ok(Math.abs((row.pnl ?? 0) - -893.9996) < 0.0001);
});

test("keeps partially filled replacement ancestors and infers equity inventory", () => {
  const trades = tradesFromBrokerOrders([
    order({ id: "first", replaced_by: "second", symbol: "ARM", side: "sell", qty: "10",
      filled_qty: "4", filled_avg_price: "100", status: "replaced", filled_at: "2026-09-02T14:00:00Z" }),
    order({ id: "second", replaces: "first", symbol: "ARM", side: "sell", qty: "6",
      filled_qty: "6", filled_avg_price: "101", filled_at: "2026-09-02T14:01:00Z" }),
    order({ id: "cover", symbol: "ARM", side: "buy", qty: "10", filled_qty: "10",
      filled_avg_price: "99", filled_at: "2026-09-02T15:00:00Z" }),
  ], []);
  assert.equal(trades.length, 3);
  assert.equal(trades.find((row) => row.orderId === "first")?.status, "replaced");
  const rows = tradeHistory(trades);
  assert.equal(rows.filter((row) => row.status === "CLOSED").reduce((sum, row) => sum + row.qty, 0), 10);
  assert.equal(rows.reduce((sum, row) => sum + (row.pnl ?? 0), 0), 16);
});

test("allocates live unrealized P&L across FIFO lots once", () => {
  const trades = tradesFromBrokerOrders([
    order({ id: "a", symbol: "AAPL", side: "buy", qty: "5", filled_qty: "5",
      filled_avg_price: "100", filled_at: "2026-09-02T14:00:00Z" }),
    order({ id: "b", symbol: "AAPL", side: "buy", qty: "5", filled_qty: "5",
      filled_avg_price: "102", filled_at: "2026-09-02T14:01:00Z" }),
  ], []);
  const rows = tradeHistory(trades, {
    AAPL: { qty: "10", market_price: "103", unrealized_pl: "20" },
  });
  assert.equal(rows.length, 2);
  assert.ok(rows.every((row) => row.status === "OPEN"));
  assert.equal(rows.reduce((sum, row) => sum + (row.pnl ?? 0), 0), 20);
});
