export const CRITIC_NAMES = ["risk", "market", "execution"] as const;

export type CriticName = typeof CRITIC_NAMES[number];

export type CriticAdvice = {
  critic: CriticName;
  status: "completed" | "timeout" | "error";
  model: string;
  summary: string;
};

export type TradePlanStep = {
  reason: string;
  candidate_id: string;
  evidence_refs: string[];
};

export type PositionAction = {
  underlying: string;
  action: "HOLD" | "REDUCE" | "EXIT";
  fraction: 0 | 0.5 | 1;
  reason: string;
  evidence_refs: string[];
};

export type CriticResolution = {
  critic: CriticName;
  resolution: "ACCEPTED" | "OVERRIDDEN" | "UNAVAILABLE";
  reason: string;
};

export type MemoryEvent = {
  hypothesis: string;
  evidence_refs: string[];
  ttl_hours: number;
};

export type TradeHypothesis = {
  candidate_id: string;
  thesis: string;
  confidence: "low" | "medium" | "high";
  supports: string[];
  contradicts: string[];
  invalidation: string;
};

export type TradeHypothesisDraft = {
  schema: "trade.hypotheses.v1";
  cycle_id: string;
  focus_candidate_id: string;
  hypotheses: TradeHypothesis[];
};

export type TradePlan = {
  schema: "trade.plan.v3";
  cycle_id: string;
  reason: string;
  action: "PARK" | "EXECUTE_PLAN";
  hypotheses: TradeHypothesis[];
  steps: TradePlanStep[];
  position_actions: PositionAction[];
  critic_coverage: CriticName[];
  critic_resolutions: CriticResolution[];
  memory_events: MemoryEvent[];
};

const CANDIDATE_ID = /^[A-Za-z0-9._:-]{1,80}$/u;

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function exactKeys(value: Record<string, unknown>, keys: string[]): boolean {
  const actual = Object.keys(value).sort();
  return actual.length === keys.length
    && actual.every((key, index) => key === [...keys].sort()[index]);
}

function boundedText(value: unknown, limit = 500): string | null {
  if (typeof value !== "string") return null;
  const text = value.trim();
  return text.length > 0 && text.length <= limit ? text : null;
}

function evidenceList(value: unknown): string[] | null {
  if (!Array.isArray(value) || value.length < 1 || value.length > 12) return null;
  const items = value.map((item) => boundedText(item, 300));
  return items.every((item): item is string => item !== null) ? items : null;
}

function optionalEvidenceList(value: unknown): string[] | null {
  if (!Array.isArray(value) || value.length > 8) return null;
  const items = value.map((item) => boundedText(item, 300));
  return items.every((item): item is string => item !== null) ? items : null;
}

function markedPayload(text: string, marker: string): Record<string, unknown> | null {
  const lines = text.trim().split(/\r?\n/u).filter((line) => line.trim());
  const marked = lines.filter((line) => line.startsWith(marker));
  if (marked.length !== 1 || marked[0] !== lines.at(-1)) return null;
  const raw = marked[0]?.slice(marker.length).trim() ?? "";
  try {
    return record(JSON.parse(raw) as unknown);
  } catch {
    return null;
  }
}

const NEWS_EVIDENCE_REF = /^news\.[a-f0-9]{64}$/iu;

function evidenceIsGrounded(reference: string, allowedNewsEvidence?: Set<string>): boolean {
  return !reference.toLowerCase().startsWith("news.")
    || (NEWS_EVIDENCE_REF.test(reference) && (allowedNewsEvidence?.has(reference) ?? true));
}

function parseHypotheses(
  value: unknown,
  allowedCandidates: Set<string>,
  allowedNewsEvidence?: Set<string>,
  allowEmpty = false,
): TradeHypothesis[] | null {
  if (!Array.isArray(value) || (!allowEmpty && value.length < 1) || value.length > 5) return null;
  const hypotheses: TradeHypothesis[] = [];
  const seen = new Set<string>();
  for (const rawHypothesis of value) {
    const hypothesis = record(rawHypothesis);
    if (!hypothesis || !exactKeys(hypothesis, [
      "candidate_id", "thesis", "confidence", "supports", "contradicts", "invalidation",
    ])) return null;
    const candidateId = typeof hypothesis.candidate_id === "string"
      ? hypothesis.candidate_id.trim()
      : "";
    const thesis = boundedText(hypothesis.thesis, 240);
    const invalidation = boundedText(hypothesis.invalidation, 240);
    const supports = evidenceList(hypothesis.supports);
    const contradicts = optionalEvidenceList(hypothesis.contradicts);
    if (!allowedCandidates.has(candidateId) || seen.has(candidateId)
      || !thesis || !invalidation || !supports || !contradicts
      || [...supports, ...contradicts].some((reference) => !evidenceIsGrounded(reference, allowedNewsEvidence))
      || !["low", "medium", "high"].includes(String(hypothesis.confidence))) return null;
    seen.add(candidateId);
    hypotheses.push({
      candidate_id: candidateId,
      thesis,
      confidence: hypothesis.confidence as TradeHypothesis["confidence"],
      supports,
      contradicts,
      invalidation,
    });
  }
  return hypotheses;
}

export function parseTradeHypothesisDraft(
  text: string,
  expectedCycleId: string,
  allowedCandidates: string[],
  allowedNewsEvidenceRefs?: string[],
): TradeHypothesisDraft | null {
  const payload = markedPayload(text, "TRADE_HYPOTHESES_JSON:");
  if (!payload || !exactKeys(payload, [
    "schema", "cycle_id", "focus_candidate_id", "hypotheses",
  ])) return null;
  const focusCandidateId = typeof payload.focus_candidate_id === "string"
    ? payload.focus_candidate_id.trim()
    : "";
  const allowed = new Set(allowedCandidates);
  const allowedNewsEvidence = allowedNewsEvidenceRefs
    ? new Set(allowedNewsEvidenceRefs)
    : undefined;
  const hypotheses = parseHypotheses(payload.hypotheses, allowed, allowedNewsEvidence);
  if (payload.schema !== "trade.hypotheses.v1" || payload.cycle_id !== expectedCycleId
    || !allowed.has(focusCandidateId) || !hypotheses
    || !hypotheses.some((hypothesis) => hypothesis.candidate_id === focusCandidateId)) return null;
  return {
    schema: "trade.hypotheses.v1",
    cycle_id: expectedCycleId,
    focus_candidate_id: focusCandidateId,
    hypotheses,
  };
}

export function parseTradePlan(
  text: string,
  expectedCycleId: string,
  allowedHypothesisCandidates: string[],
  executableCandidates: string[] = allowedHypothesisCandidates,
  allowedNewsEvidenceRefs?: string[],
  allowedOpenUnderlyings: string[] = [],
  allowedPositionEvidenceRefs?: string[],
): TradePlan | null {
  const payload = markedPayload(text, "TRADE_PLAN_JSON:");
  if (!payload || !exactKeys(payload, [
    "schema", "cycle_id", "reason", "action", "hypotheses", "steps",
    "position_actions", "critic_coverage", "critic_resolutions", "memory_events",
  ])) return null;
  if (payload.schema !== "trade.plan.v3"
    || payload.cycle_id !== expectedCycleId
    || (payload.action !== "PARK" && payload.action !== "EXECUTE_PLAN")) return null;
  const reason = boundedText(payload.reason);
  if (!reason || !Array.isArray(payload.steps) || payload.steps.length > 3) return null;

  const allowedHypotheses = new Set(allowedHypothesisCandidates);
  const allowedSteps = new Set(executableCandidates);
  const allowedNewsEvidence = allowedNewsEvidenceRefs
    ? new Set(allowedNewsEvidenceRefs)
    : undefined;
  const hypotheses = parseHypotheses(payload.hypotheses, allowedHypotheses, allowedNewsEvidence, true);
  if (!hypotheses) return null;
  const hypothesisCandidates = new Set(hypotheses.map((hypothesis) => hypothesis.candidate_id));
  const seenSymbols = new Set<string>();
  const steps: TradePlanStep[] = [];
  for (const rawStep of payload.steps) {
    const step = record(rawStep);
    if (!step || !exactKeys(step, ["reason", "candidate_id", "evidence_refs"])) return null;
    const candidateId = typeof step.candidate_id === "string" ? step.candidate_id.trim() : "";
    const stepReason = boundedText(step.reason);
    const evidenceRefs = evidenceList(step.evidence_refs);
    if (!CANDIDATE_ID.test(candidateId) || !stepReason || !evidenceRefs
      || evidenceRefs.some((reference) => !evidenceIsGrounded(reference, allowedNewsEvidence))
      || seenSymbols.has(candidateId) || !allowedSteps.has(candidateId)) return null;
    seenSymbols.add(candidateId);
    steps.push({ reason: stepReason, candidate_id: candidateId, evidence_refs: evidenceRefs });
  }
  if ((payload.action === "PARK" && steps.length !== 0)
    || (payload.action === "EXECUTE_PLAN" && steps.length === 0)
    || steps.some((step) => !hypothesisCandidates.has(step.candidate_id))) return null;

  if (!Array.isArray(payload.position_actions) || payload.position_actions.length > 6) return null;
  const openUnderlyings = new Set(allowedOpenUnderlyings.map((value) => value.trim().toUpperCase()));
  const allowedPositionEvidence = allowedPositionEvidenceRefs
    ? new Set(allowedPositionEvidenceRefs)
    : undefined;
  const seenUnderlyings = new Set<string>();
  const positionActions: PositionAction[] = [];
  for (const rawAction of payload.position_actions) {
    const item = record(rawAction);
    if (!item || !exactKeys(item, ["underlying", "action", "fraction", "reason", "evidence_refs"])) return null;
    const underlying = typeof item.underlying === "string" ? item.underlying.trim().toUpperCase() : "";
    const action = String(item.action);
    const fraction = Number(item.fraction);
    const actionReason = boundedText(item.reason, 240);
    const evidenceRefs = evidenceList(item.evidence_refs);
    const fractionValid = (action === "HOLD" && fraction === 0)
      || (action === "REDUCE" && fraction === 0.5)
      || (action === "EXIT" && fraction === 1);
    if (!/^[A-Z][A-Z0-9.-]{0,9}$/u.test(underlying) || !openUnderlyings.has(underlying)
      || seenUnderlyings.has(underlying) || !fractionValid || !actionReason || !evidenceRefs
      || (allowedPositionEvidence !== undefined
        && evidenceRefs.some((reference) => !allowedPositionEvidence.has(reference)))
      || evidenceRefs.some((reference) => !evidenceIsGrounded(reference, allowedNewsEvidence))) return null;
    seenUnderlyings.add(underlying);
    positionActions.push({
      underlying,
      action: action as PositionAction["action"],
      fraction: fraction as PositionAction["fraction"],
      reason: actionReason,
      evidence_refs: evidenceRefs,
    });
  }
  // The model may omit an unchanged position. The runner, which owns the live
  // open-underlying set, deterministically fills every omission with HOLD
  // before the plan can reach Python execution.

  if (!Array.isArray(payload.critic_coverage)
    || payload.critic_coverage.length !== CRITIC_NAMES.length) return null;
  const criticCoverage = payload.critic_coverage.map(String) as CriticName[];
  if (!CRITIC_NAMES.every((critic) => criticCoverage.filter((item) => item === critic).length === 1)) return null;

  if (!Array.isArray(payload.critic_resolutions)
    || payload.critic_resolutions.length !== CRITIC_NAMES.length) return null;
  const criticResolutions: CriticResolution[] = [];
  for (const rawResolution of payload.critic_resolutions) {
    const resolution = record(rawResolution);
    if (!resolution || !exactKeys(resolution, ["critic", "resolution", "reason"])) return null;
    if (!CRITIC_NAMES.includes(resolution.critic as CriticName)
      || !["ACCEPTED", "OVERRIDDEN", "UNAVAILABLE"].includes(String(resolution.resolution))) return null;
    const resolutionReason = boundedText(resolution.reason);
    if (!resolutionReason) return null;
    criticResolutions.push({
      critic: resolution.critic as CriticName,
      resolution: resolution.resolution as CriticResolution["resolution"],
      reason: resolutionReason,
    });
  }
  if (!CRITIC_NAMES.every((critic) =>
    criticResolutions.filter((item) => item.critic === critic).length === 1)) return null;

  if (!Array.isArray(payload.memory_events) || payload.memory_events.length > 5) return null;
  const memoryEvents: MemoryEvent[] = [];
  for (const rawMemory of payload.memory_events) {
    const memory = record(rawMemory);
    if (!memory || !exactKeys(memory, ["hypothesis", "evidence_refs", "ttl_hours"])) return null;
    const hypothesis = boundedText(memory.hypothesis, 500);
    const evidenceRefs = evidenceList(memory.evidence_refs);
    const ttlHours = memory.ttl_hours;
    if (!hypothesis || !evidenceRefs
      || evidenceRefs.some((reference) => !evidenceIsGrounded(reference, allowedNewsEvidence))
      || !Number.isInteger(ttlHours)
      || Number(ttlHours) < 1 || Number(ttlHours) > 168) return null;
    memoryEvents.push({ hypothesis, evidence_refs: evidenceRefs, ttl_hours: Number(ttlHours) });
  }

  return {
    schema: "trade.plan.v3",
    cycle_id: expectedCycleId,
    reason,
    action: payload.action,
    hypotheses,
    steps,
    position_actions: positionActions,
    critic_coverage: criticCoverage,
    critic_resolutions: criticResolutions,
    memory_events: memoryEvents,
  };
}

export function normalizeCriticResolutions(
  plan: TradePlan,
  critics: CriticAdvice[],
): TradePlan {
  const actual = new Map(critics.map((critic) => [critic.critic, critic]));
  const proposed = new Map(plan.critic_resolutions.map((resolution) => [resolution.critic, resolution]));
  return {
    ...plan,
    critic_resolutions: CRITIC_NAMES.map((critic) => {
      const advice = actual.get(critic);
      if (!advice || advice.status !== "completed") {
        return {
          critic,
          resolution: "UNAVAILABLE" as const,
          reason: (advice
            ? `${advice.status}: ${advice.summary}`
            : "error: critic result was not returned.").slice(0, 500),
        };
      }
      return proposed.get(critic) ?? {
        critic,
        resolution: "UNAVAILABLE" as const,
        reason: "error: completed critic was not resolved by the main trader.",
      };
    }),
  };
}

export function parkedPlan(
  cycleId: string,
  reason: string,
  openUnderlyings: string[] = [],
): TradePlan {
  return {
    schema: "trade.plan.v3",
    cycle_id: cycleId,
    reason,
    action: "PARK",
    hypotheses: [],
    steps: [],
    // A runner-issued park never proposes a position change, but the executor
    // requires an explicit decision for every open underlying, so fail closed
    // to HOLD instead of emitting an uncovered plan.
    position_actions: [...new Set(openUnderlyings.map((value) => value.trim().toUpperCase()))]
      .filter((underlying) => underlying)
      .slice(0, 6)
      .map((underlying) => ({
        underlying,
        action: "HOLD" as const,
        fraction: 0 as const,
        reason: "Runner parked before the trader decided; open positions fail closed to HOLD.",
        evidence_refs: [`position.${underlying}.runner_park`],
      })),
    critic_coverage: [...CRITIC_NAMES],
    critic_resolutions: CRITIC_NAMES.map((critic) => ({
      critic,
      resolution: "ACCEPTED",
      reason: "No executable candidate was delegated to the advisory layer.",
    })),
    memory_events: [],
  };
}

export function positionExitPlan(
  cycleId: string,
  reason: string,
  openUnderlyings: string[],
  exits: { underlying: string; reason: string; evidence_refs: string[] }[],
): TradePlan {
  const requested = new Map(exits.map((item) => [item.underlying.trim().toUpperCase(), item]));
  const base = parkedPlan(cycleId, reason, openUnderlyings);
  return {
    ...base,
    critic_resolutions: CRITIC_NAMES.map((critic) => ({
      critic,
      resolution: "OVERRIDDEN" as const,
      reason: "Watcher invalidation fast-exit bypassed advisory critics; deterministic executor remains authoritative.",
    })),
    position_actions: base.position_actions.map((held) => {
      const exit = requested.get(held.underlying);
      return exit ? {
        underlying: held.underlying,
        action: "EXIT" as const,
        fraction: 1 as const,
        reason: `Position watcher invalidation: ${exit.reason}`.slice(0, 240),
        evidence_refs: exit.evidence_refs,
      } : held;
    }),
  };
}
