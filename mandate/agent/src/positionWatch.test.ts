import assert from "node:assert/strict";
import test from "node:test";

import { fastExitAssessments, parsePositionWatch, positionEvidenceRefs } from "./positionWatch.js";

function response(assessments: Record<string, unknown>[]): string {
  return `POSITION_WATCH_JSON: ${JSON.stringify({
    schema: "position.watch.v1",
    cycle_id: "cycle-1",
    assessments,
  })}`;
}

test("position watcher requires exactly one grounded assessment per open underlying", () => {
  const raw = response([{
    underlying: "AAPL",
    state: "WEAKENING",
    recommendation: "REDUCE",
    reason: "The signal reversed while the original thesis is only partially intact.",
    evidence_refs: ["position.AAPL.unrealized_plpc", "strategy.AAPL.signal_direction"],
  }]);
  assert.equal(parsePositionWatch(raw, "cycle-1", ["AAPL"])?.assessments[0]?.recommendation, "REDUCE");
  assert.equal(parsePositionWatch(raw, "cycle-1", ["AAPL", "MSFT"]), null);
  assert.equal(parsePositionWatch(raw, "another-cycle", ["AAPL"]), null);
  assert.equal(parsePositionWatch(raw.replace("POSITION_WATCH_JSON:", "POSITION_WATCH_JSON"), "cycle-1", ["AAPL"])?.assessments.length, 1);
});

test("position watcher rejects fabricated evidence and non-open symbols", () => {
  const fabricated = response([{
    underlying: "AAPL",
    state: "HEALTHY",
    recommendation: "HOLD",
    reason: "Thesis remains intact.",
    evidence_refs: ["news.fabricated"],
  }]);
  assert.equal(parsePositionWatch(fabricated, "cycle-1", ["AAPL"]), null);
  assert.equal(parsePositionWatch(fabricated.replaceAll("AAPL", "MSFT"), "cycle-1", ["AAPL"]), null);
});

test("only an invalidated thesis reaches the fast exit lane", () => {
  const watch = parsePositionWatch(response([
    {
      underlying: "AAPL", state: "INVALIDATED", recommendation: "EXIT",
      reason: "The breakout that opened the position fully reversed below its trigger.",
      evidence_refs: ["position.AAPL.unrealized_plpc"],
    },
    {
      underlying: "MSFT", state: "WEAKENING", recommendation: "REDUCE",
      reason: "Momentum faded but the thesis is intact.",
      evidence_refs: ["strategy.MSFT.signal_direction"],
    },
    {
      underlying: "NVDA", state: "INVALIDATED", recommendation: "REDUCE",
      reason: "State and recommendation disagree, so the main trader decides.",
      evidence_refs: ["strategy.NVDA.invalidation"],
    },
  ]), "cycle-1", ["AAPL", "MSFT", "NVDA"]);
  assert.ok(watch);
  assert.deepEqual(fastExitAssessments(watch, 2).map((item) => item.underlying), ["AAPL"]);
  assert.deepEqual(fastExitAssessments(watch, 0), []);
});

test("main trader may ground a decision in any supplied position fact", () => {
  const refs = positionEvidenceRefs({
    underlying: "AAPL", asset_class: "equity", side: "LONG", legs: 1,
    quantity: "10", entry_value: "1000", current_value: "1020",
    unrealized_pl: "20", unrealized_plpc: "2", thesis: "breakout",
    invalidation: "below VWAP", signal_direction: "sell", signal_strength: "0.2",
    quality_pass: true, news_price_aligned: false, risk_off: false, blocked_by: [],
  });
  assert.ok(refs.includes("position.AAPL.current_value"));
  assert.ok(refs.includes("strategy.AAPL.invalidation"));
  assert.ok(refs.includes("position.AAPL.blocked_by"));
});
