import assert from "node:assert/strict";
import test from "node:test";

import {
  fastExitAssessments, parsePositionWatch, positionEvidenceRefs, stabilizePositionWatch,
} from "./positionWatch.js";

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
  assert.equal(parsePositionWatch(raw.slice(raw.indexOf("{")).trim(), "cycle-1", ["AAPL"])?.assessments.length, 1);
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

test("missing research context cannot masquerade as a weakening thesis", () => {
  const watch = parsePositionWatch(response([{
    underlying: "AAPL",
    state: "WEAKENING",
    recommendation: "REDUCE",
    reason: "Signal and quality fields are null, so reduce exposure.",
    evidence_refs: ["strategy.AAPL.signal_direction"],
  }]), "cycle-1", ["AAPL"]);
  assert.ok(watch);
  const stabilized = stabilizePositionWatch(watch, [{
    underlying: "AAPL", asset_class: "equity", side: "LONG", legs: 1,
    quantity: "10", entry_value: "1000", current_value: "980",
    unrealized_pl: "-20", unrealized_plpc: "-0.02", thesis: null,
    invalidation: null, signal_direction: null, signal_strength: null,
    quality_pass: null, news_price_aligned: null, risk_off: true, blocked_by: ["stale_quote"],
  }]);
  assert.deepEqual(stabilized.assessments[0], {
    underlying: "AAPL",
    state: "HEALTHY",
    recommendation: "HOLD",
    reason: "Fresh thesis and signal context is unavailable; defer to deterministic hard-risk exits.",
    evidence_refs: ["position.AAPL.unrealized_plpc"],
  });
});

test("an evidence-backed watcher change is preserved", () => {
  const watch = parsePositionWatch(response([{
    underlying: "AAPL",
    state: "WEAKENING",
    recommendation: "REDUCE",
    reason: "The current sell signal opposes the retained long thesis.",
    evidence_refs: ["strategy.AAPL.signal_direction"],
  }]), "cycle-1", ["AAPL"]);
  assert.ok(watch);
  const stabilized = stabilizePositionWatch(watch, [{
    underlying: "AAPL", asset_class: "equity", side: "LONG", legs: 1,
    quantity: "10", entry_value: "1000", current_value: "980",
    unrealized_pl: "-20", unrealized_plpc: "-0.02", thesis: "Breakout continuation",
    invalidation: "Sell signal below VWAP", signal_direction: "sell", signal_strength: "0.4",
    quality_pass: true, news_price_aligned: null, risk_off: true, blocked_by: [],
  }]);
  assert.equal(stabilized.assessments[0]?.recommendation, "REDUCE");
});

test("loss and entry quality alone cannot reduce a position against an intact signal", () => {
  const watch = parsePositionWatch(response([{
    underlying: "MSFT",
    state: "WEAKENING",
    recommendation: "REDUCE",
    reason: "Loss and a wide spread weaken conviction.",
    evidence_refs: ["position.MSFT.unrealized_plpc", "strategy.MSFT.quality_pass"],
  }]), "cycle-1", ["MSFT"]);
  assert.ok(watch);
  const stabilized = stabilizePositionWatch(watch, [{
    underlying: "MSFT", asset_class: "option", side: "LONG", legs: 2,
    quantity: "long:2,short:-2", entry_value: "1282", current_value: "1128",
    unrealized_pl: "-154", unrealized_plpc: "-0.12", thesis: null,
    invalidation: null, signal_direction: "buy", signal_strength: "0.72",
    quality_pass: false, news_price_aligned: true, risk_off: false, blocked_by: ["quality_gate"],
  }]);
  assert.equal(stabilized.assessments[0]?.recommendation, "HOLD");
  assert.match(stabilized.assessments[0]?.reason ?? "", /entry-quality fields alone/u);
});
