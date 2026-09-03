import assert from "node:assert/strict";
import test from "node:test";

import {
  normalizeCriticResolutions,
  parseTradeHypothesisDraft,
  parseTradePlan,
} from "./tradePlan.js";

function validPayload(): Record<string, unknown> {
  return {
    schema: "trade.plan.v2",
    cycle_id: "cycle-1",
    reason: "AAPL has the strongest deterministic evidence.",
    action: "EXECUTE_PLAN",
    hypotheses: [{
      candidate_id: "entry-1-AAPL",
      thesis: "Aligned momentum can continue while liquidity stays elevated.",
      confidence: "medium",
      supports: ["evaluation.trade_candidates.0.evidence"],
      contradicts: ["scorecard.momentum"],
      invalidation: "Price confirmation or relative volume falls below its gate.",
    }],
    steps: [{
      reason: "Momentum and liquidity gates agree.",
      candidate_id: "entry-1-AAPL",
      evidence_refs: ["evaluation.trade_candidates.0.evidence"],
    }],
    critic_coverage: ["risk", "market", "execution"],
    critic_resolutions: [
      { critic: "risk", resolution: "ACCEPTED", reason: "Risk evidence supports the bounded entry." },
      { critic: "market", resolution: "ACCEPTED", reason: "The regime is aligned." },
      { critic: "execution", resolution: "OVERRIDDEN", reason: "The quoted spread remains inside the hard gate." },
    ],
    memory_events: [{
      hypothesis: "Relative volume may remain elevated into the next session.",
      evidence_refs: ["evaluation.trade_candidates.0.evidence.relative_volume"],
      ttl_hours: 24,
    }],
  };
}

function line(payload: Record<string, unknown>): string {
  return `TRADE_PLAN_JSON: ${JSON.stringify(payload)}`;
}

test("hypothesis draft names the main trader's active focus", () => {
  const hypothesis = (validPayload().hypotheses as Record<string, unknown>[])[0]!;
  const draft = {
    schema: "trade.hypotheses.v1",
    cycle_id: "cycle-1",
    focus_candidate_id: "entry-1-AAPL",
    hypotheses: [hypothesis],
  };
  const parsed = parseTradeHypothesisDraft(
    `TRADE_HYPOTHESES_JSON: ${JSON.stringify(draft)}`,
    "cycle-1",
    ["entry-1-AAPL"],
  );
  assert.equal(parsed?.focus_candidate_id, "entry-1-AAPL");
  assert.equal(parsed?.hypotheses[0]?.thesis, hypothesis.thesis);
  assert.equal(parseTradeHypothesisDraft(
    `TRADE_HYPOTHESES_JSON: ${JSON.stringify({ ...draft, focus_candidate_id: "unknown" })}`,
    "cycle-1",
    ["entry-1-AAPL"],
  ), null);
});

test("strict parser accepts the exact canonical root", () => {
  const plan = parseTradePlan(line(validPayload()), "cycle-1", ["entry-1-AAPL"]);
  assert.equal(plan?.action, "EXECUTE_PLAN");
  assert.equal(plan?.steps[0]?.candidate_id, "entry-1-AAPL");
  assert.equal(plan?.hypotheses[0]?.confidence, "medium");
  assert.equal(plan?.memory_events[0]?.ttl_hours, 24);
});

test("hypotheses are bounded, candidate-linked, and carry explicit invalidation", () => {
  const unknown = validPayload();
  (unknown.hypotheses as Record<string, unknown>[])[0]!.candidate_id = "entry-2-MSFT";
  assert.equal(parseTradePlan(line(unknown), "cycle-1", ["entry-1-AAPL"]), null);
  const missing = validPayload();
  missing.hypotheses = [];
  assert.equal(parseTradePlan(line(missing), "cycle-1", ["entry-1-AAPL"]), null);
  const invalidConfidence = validPayload();
  (invalidConfidence.hypotheses as Record<string, unknown>[])[0]!.confidence = "certain";
  assert.equal(parseTradePlan(line(invalidConfidence), "cycle-1", ["entry-1-AAPL"]), null);
  const uncoveredStep = validPayload();
  (uncoveredStep.steps as Record<string, unknown>[])[0]!.candidate_id = "entry-2-MSFT";
  assert.equal(
    parseTradePlan(line(uncoveredStep), "cycle-1", ["entry-1-AAPL", "entry-2-MSFT"]),
    null,
  );
});

test("strict parser rejects extra keys, wrong cycle and unknown candidates", () => {
  assert.equal(parseTradePlan(line({ ...validPayload(), symbol: "AAPL" }), "cycle-1", ["entry-1-AAPL"]), null);
  assert.equal(parseTradePlan(line(validPayload()), "another-cycle", ["entry-1-AAPL"]), null);
  assert.equal(parseTradePlan(line(validPayload()), "cycle-1", ["entry-2-MSFT"]), null);
});

test("strict parser requires all three critic resolutions exactly once", () => {
  const missing = validPayload();
  missing.critic_resolutions = (missing.critic_resolutions as unknown[]).slice(0, 2);
  assert.equal(parseTradePlan(line(missing), "cycle-1", ["entry-1-AAPL"]), null);
  const duplicate = validPayload();
  duplicate.critic_coverage = ["risk", "risk", "execution"];
  assert.equal(parseTradePlan(line(duplicate), "cycle-1", ["entry-1-AAPL"]), null);
});

test("critic timeout is represented as unavailable even when the model calls it accepted", () => {
  const plan = parseTradePlan(line(validPayload()), "cycle-1", ["entry-1-AAPL"]);
  assert.ok(plan);
  const normalized = normalizeCriticResolutions(plan, [
    { critic: "risk", status: "completed", model: "fixture", summary: "bounded" },
    { critic: "market", status: "timeout", model: "fixture", summary: "deadline" },
    { critic: "execution", status: "completed", model: "fixture", summary: "liquid" },
  ]);
  assert.deepEqual(normalized.critic_resolutions.map(({ critic, resolution }) => ({ critic, resolution })), [
    { critic: "risk", resolution: "ACCEPTED" },
    { critic: "market", resolution: "UNAVAILABLE" },
    { critic: "execution", resolution: "OVERRIDDEN" },
  ]);
});

test("news evidence refs must exactly match the supplied canonical catalogue", () => {
  const eventId = "a".repeat(64);
  const payload = validPayload();
  (payload.hypotheses as Record<string, unknown>[])[0]!.supports = [`news.${eventId}`];
  assert.ok(parseTradePlan(line(payload), "cycle-1", ["entry-1-AAPL"], ["entry-1-AAPL"], [`news.${eventId}`]));
  assert.equal(
    parseTradePlan(line(payload), "cycle-1", ["entry-1-AAPL"], ["entry-1-AAPL"], [`news.${"b".repeat(64)}`]),
    null,
  );
});

test("PARK has no steps and EXECUTE_PLAN has one to three unique steps", () => {
  const parked = validPayload();
  parked.action = "PARK";
  parked.steps = [];
  assert.equal(parseTradePlan(line(parked), "cycle-1", ["entry-1-AAPL"])?.action, "PARK");

  const tooMany = validPayload();
  tooMany.steps = Array.from({ length: 4 }, (_, index) => ({
    reason: "ranked", candidate_id: `candidate-${index}`, evidence_refs: ["evaluation"],
  }));
  assert.equal(parseTradePlan(line(tooMany), "cycle-1", ["candidate-0", "candidate-1", "candidate-2", "candidate-3"]), null);
});

test("a PARK assessment may hypothesize on non-executable context but cannot trade it", () => {
  const assessment = validPayload();
  assessment.action = "PARK";
  assessment.steps = [];
  (assessment.hypotheses as Record<string, unknown>[])[0]!.candidate_id = "watch-news-1-AVGO";
  assert.equal(
    parseTradePlan(line(assessment), "cycle-1", ["watch-news-1-AVGO"], [])?.action,
    "PARK",
  );

  assessment.action = "EXECUTE_PLAN";
  assessment.steps = [{
    reason: "News is material.",
    candidate_id: "watch-news-1-AVGO",
    evidence_refs: ["news.0"],
  }];
  assert.equal(parseTradePlan(line(assessment), "cycle-1", ["watch-news-1-AVGO"], []), null);
});

test("memory events are structured, bounded to five, and expire within seven days", () => {
  for (const ttl of [0, 169, 1.5]) {
    const payload = validPayload();
    payload.memory_events = [{ hypothesis: "test", evidence_refs: ["evaluation"], ttl_hours: ttl }];
    assert.equal(parseTradePlan(line(payload), "cycle-1", ["entry-1-AAPL"]), null);
  }
  const payload = validPayload();
  payload.memory_events = Array.from({ length: 6 }, () => ({
    hypothesis: "test", evidence_refs: ["evaluation"], ttl_hours: 1,
  }));
  assert.equal(parseTradePlan(line(payload), "cycle-1", ["entry-1-AAPL"]), null);
});

test("the marked object must be the single final non-empty line", () => {
  const canonical = line(validPayload());
  assert.equal(parseTradePlan(`${canonical}\nafter`, "cycle-1", ["entry-1-AAPL"]), null);
  assert.equal(parseTradePlan(`${canonical}\n${canonical}`, "cycle-1", ["entry-1-AAPL"]), null);
});
