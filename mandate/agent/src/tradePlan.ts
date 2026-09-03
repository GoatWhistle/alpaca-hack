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

export type CriticResolution = {
  critic: CriticName;
  resolution: "ACCEPTED" | "OVERRIDDEN";
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

export type TradePlan = {
  schema: "trade.plan.v2";
  cycle_id: string;
  reason: string;
  action: "PARK" | "EXECUTE_PLAN";
  hypotheses: TradeHypothesis[];
  steps: TradePlanStep[];
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

function rootPayload(text: string): Record<string, unknown> | null {
  const lines = text.trim().split(/\r?\n/u).filter((line) => line.trim());
  const marked = lines.filter((line) => line.startsWith("TRADE_PLAN_JSON:"));
  if (marked.length !== 1 || marked[0] !== lines.at(-1)) return null;
  const raw = marked[0]?.slice("TRADE_PLAN_JSON:".length).trim() ?? "";
  try {
    return record(JSON.parse(raw) as unknown);
  } catch {
    return null;
  }
}

export function parseTradePlan(
  text: string,
  expectedCycleId: string,
  allowedHypothesisCandidates: string[],
  executableCandidates: string[] = allowedHypothesisCandidates,
): TradePlan | null {
  const payload = rootPayload(text);
  if (!payload || !exactKeys(payload, [
    "schema", "cycle_id", "reason", "action", "hypotheses", "steps",
    "critic_coverage", "critic_resolutions", "memory_events",
  ])) return null;
  if (payload.schema !== "trade.plan.v2"
    || payload.cycle_id !== expectedCycleId
    || (payload.action !== "PARK" && payload.action !== "EXECUTE_PLAN")) return null;
  const reason = boundedText(payload.reason);
  if (!reason || !Array.isArray(payload.steps) || payload.steps.length > 3) return null;

  const allowedHypotheses = new Set(allowedHypothesisCandidates);
  const allowedSteps = new Set(executableCandidates);
  if (!Array.isArray(payload.hypotheses)
    || payload.hypotheses.length < 1 || payload.hypotheses.length > 5) return null;
  const hypotheses: TradeHypothesis[] = [];
  const hypothesisCandidates = new Set<string>();
  for (const rawHypothesis of payload.hypotheses) {
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
    if (!allowedHypotheses.has(candidateId) || hypothesisCandidates.has(candidateId)
      || !thesis || !invalidation || !supports || !contradicts
      || !["low", "medium", "high"].includes(String(hypothesis.confidence))) return null;
    hypothesisCandidates.add(candidateId);
    hypotheses.push({
      candidate_id: candidateId,
      thesis,
      confidence: hypothesis.confidence as TradeHypothesis["confidence"],
      supports,
      contradicts,
      invalidation,
    });
  }
  const seenSymbols = new Set<string>();
  const steps: TradePlanStep[] = [];
  for (const rawStep of payload.steps) {
    const step = record(rawStep);
    if (!step || !exactKeys(step, ["reason", "candidate_id", "evidence_refs"])) return null;
    const candidateId = typeof step.candidate_id === "string" ? step.candidate_id.trim() : "";
    const stepReason = boundedText(step.reason);
    const evidenceRefs = evidenceList(step.evidence_refs);
    if (!CANDIDATE_ID.test(candidateId) || !stepReason || !evidenceRefs
      || seenSymbols.has(candidateId) || !allowedSteps.has(candidateId)) return null;
    seenSymbols.add(candidateId);
    steps.push({ reason: stepReason, candidate_id: candidateId, evidence_refs: evidenceRefs });
  }
  if ((payload.action === "PARK" && steps.length !== 0)
    || (payload.action === "EXECUTE_PLAN" && steps.length === 0)
    || steps.some((step) => !hypothesisCandidates.has(step.candidate_id))) return null;

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
      || (resolution.resolution !== "ACCEPTED" && resolution.resolution !== "OVERRIDDEN")) return null;
    const resolutionReason = boundedText(resolution.reason);
    if (!resolutionReason) return null;
    criticResolutions.push({
      critic: resolution.critic as CriticName,
      resolution: resolution.resolution,
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
    if (!hypothesis || !evidenceRefs || !Number.isInteger(ttlHours)
      || Number(ttlHours) < 1 || Number(ttlHours) > 168) return null;
    memoryEvents.push({ hypothesis, evidence_refs: evidenceRefs, ttl_hours: Number(ttlHours) });
  }

  return {
    schema: "trade.plan.v2",
    cycle_id: expectedCycleId,
    reason,
    action: payload.action,
    hypotheses,
    steps,
    critic_coverage: criticCoverage,
    critic_resolutions: criticResolutions,
    memory_events: memoryEvents,
  };
}

export function parkedPlan(cycleId: string, reason: string): TradePlan {
  return {
    schema: "trade.plan.v2",
    cycle_id: cycleId,
    reason,
    action: "PARK",
    hypotheses: [],
    steps: [],
    critic_coverage: [...CRITIC_NAMES],
    critic_resolutions: CRITIC_NAMES.map((critic) => ({
      critic,
      resolution: "ACCEPTED",
      reason: "No executable candidate was delegated to the advisory layer.",
    })),
    memory_events: [],
  };
}
