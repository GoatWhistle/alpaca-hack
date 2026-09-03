export type PositionWatchInput = {
  underlying: string;
  asset_class: "equity" | "option";
  side: "LONG" | "SHORT" | "MIXED";
  legs: number;
  quantity: string;
  entry_value: string;
  current_value: string;
  unrealized_pl: string;
  unrealized_plpc: string;
  thesis: string | null;
  invalidation: string | null;
  signal_direction: string | null;
  signal_strength: string | null;
  quality_pass: boolean | null;
  news_price_aligned: boolean | null;
  risk_off: boolean | null;
  blocked_by: string[];
};

export type PositionAssessment = {
  underlying: string;
  state: "HEALTHY" | "WEAKENING" | "INVALIDATED";
  recommendation: "HOLD" | "REDUCE" | "EXIT";
  reason: string;
  evidence_refs: string[];
};

export type PositionWatch = {
  schema: "position.watch.v1";
  cycle_id: string;
  assessments: PositionAssessment[];
};

const POSITION_EVIDENCE_FIELDS = new Set([
  "asset_class", "side", "legs", "quantity", "entry_value", "current_value",
  "unrealized_pl", "unrealized_plpc",
]);
const STRATEGY_EVIDENCE_FIELDS = new Set([
  "thesis", "invalidation", "signal_direction", "signal_strength", "quality_pass",
  "news_price_aligned", "risk_off", "blocked_by",
]);

export function positionEvidenceRefs(position: PositionWatchInput): string[] {
  return [
    ...[...POSITION_EVIDENCE_FIELDS].map((field) => `position.${position.underlying}.${field}`),
    ...[...STRATEGY_EVIDENCE_FIELDS].map((field) => `position.${position.underlying}.${field}`),
    ...[...STRATEGY_EVIDENCE_FIELDS].map((field) => `strategy.${position.underlying}.${field}`),
  ];
}

function groundedPositionRef(reference: string, underlying: string): boolean {
  const positionPrefix = `position.${underlying}.`;
  if (reference.startsWith(positionPrefix)) {
    const field = reference.slice(positionPrefix.length);
    return POSITION_EVIDENCE_FIELDS.has(field) || STRATEGY_EVIDENCE_FIELDS.has(field);
  }
  const strategyPrefix = `strategy.${underlying}.`;
  return reference.startsWith(strategyPrefix)
    && STRATEGY_EVIDENCE_FIELDS.has(reference.slice(strategyPrefix.length));
}

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function exactKeys(value: Record<string, unknown>, keys: string[]): boolean {
  const expected = [...keys].sort();
  const actual = Object.keys(value).sort();
  return actual.length === expected.length && actual.every((key, index) => key === expected[index]);
}

function text(value: unknown, limit: number): string | null {
  if (typeof value !== "string") return null;
  const result = value.trim();
  return result && result.length <= limit ? result : null;
}

function markedPayload(raw: string): Record<string, unknown> | null {
  const markerName = "POSITION_WATCH_JSON";
  const trimmed = raw.trim();
  const lines = trimmed.split(/\r?\n/u).filter((line) => line.trim());
  const marked = lines.filter((line) => line.startsWith(markerName));
  if (marked.length === 0 && trimmed.startsWith("{") && trimmed.endsWith("}")) {
    try {
      return record(JSON.parse(trimmed) as unknown);
    } catch {
      return null;
    }
  }
  if (marked.length !== 1 || marked[0] !== lines.at(-1)) return null;
  const suffix = marked[0]!.slice(markerName.length);
  const json = suffix.startsWith(":") ? suffix.slice(1).trim() : suffix.trim();
  if (!json.startsWith("{")) return null;
  try {
    return record(JSON.parse(json) as unknown);
  } catch {
    return null;
  }
}

export function parsePositionWatch(
  raw: string,
  cycleId: string,
  openUnderlyings: string[],
): PositionWatch | null {
  const payload = markedPayload(raw);
  if (!payload || !exactKeys(payload, ["schema", "cycle_id", "assessments"])
    || payload.schema !== "position.watch.v1" || payload.cycle_id !== cycleId
    || !Array.isArray(payload.assessments)) return null;
  const allowed = new Set(openUnderlyings.map((value) => value.toUpperCase()));
  if (payload.assessments.length !== allowed.size || allowed.size > 6) return null;
  const seen = new Set<string>();
  const assessments: PositionAssessment[] = [];
  for (const rawAssessment of payload.assessments) {
    const item = record(rawAssessment);
    if (!item || !exactKeys(item, ["underlying", "state", "recommendation", "reason", "evidence_refs"])) return null;
    const underlying = typeof item.underlying === "string" ? item.underlying.trim().toUpperCase() : "";
    const reason = text(item.reason, 240);
    const evidenceRefs = Array.isArray(item.evidence_refs)
      ? item.evidence_refs.map((value) => text(value, 160))
      : [];
    if (!allowed.has(underlying) || seen.has(underlying) || !reason
      || !["HEALTHY", "WEAKENING", "INVALIDATED"].includes(String(item.state))
      || !["HOLD", "REDUCE", "EXIT"].includes(String(item.recommendation))
      || evidenceRefs.length < 1 || evidenceRefs.length > 6
      || !evidenceRefs.every((value): value is string => value !== null
        && groundedPositionRef(value, underlying))) return null;
    seen.add(underlying);
    assessments.push({
      underlying,
      state: item.state as PositionAssessment["state"],
      recommendation: item.recommendation as PositionAssessment["recommendation"],
      reason,
      evidence_refs: evidenceRefs as string[],
    });
  }
  return { schema: "position.watch.v1", cycle_id: cycleId, assessments };
}

export function unavailablePositionWatch(cycleId: string): PositionWatch {
  return { schema: "position.watch.v1", cycle_id: cycleId, assessments: [] };
}

function hasPositionDecisionContext(position: PositionWatchInput): boolean {
  return position.thesis !== null
    || position.invalidation !== null
    || position.signal_direction !== null
    || position.signal_strength !== null
    || position.quality_pass !== null
    || position.news_price_aligned !== null;
}

function hasOpposingDirectionalSignal(position: PositionWatchInput): boolean {
  const direction = position.signal_direction?.trim().toLowerCase();
  const strength = Number(position.signal_strength);
  if (!Number.isFinite(strength) || strength < 0.15) return false;
  if (position.side === "LONG") return direction === "sell" || direction === "short";
  if (position.side === "SHORT") return direction === "buy" || direction === "long";
  return false;
}

/** Null research fields are missing context, not evidence of a weaker thesis. */
export function stabilizePositionWatch(
  watch: PositionWatch,
  positions: PositionWatchInput[],
): PositionWatch {
  const byUnderlying = new Map(positions.map((position) => [position.underlying, position]));
  return {
    ...watch,
    assessments: watch.assessments.map((assessment) => {
      const position = byUnderlying.get(assessment.underlying);
      if (assessment.recommendation === "HOLD" || !position) {
        return assessment;
      }
      const hasContext = hasPositionDecisionContext(position);
      if (hasContext && hasOpposingDirectionalSignal(position)) return assessment;
      return {
        underlying: assessment.underlying,
        state: "HEALTHY",
        recommendation: "HOLD",
        reason: hasContext
          ? "No opposing directional signal; P&L and entry-quality fields alone do not invalidate the position."
          : "Fresh thesis and signal context is unavailable; defer to deterministic hard-risk exits.",
        evidence_refs: [`position.${assessment.underlying}.unrealized_plpc`],
      };
    }),
  };
}

export function fastExitAssessments(watch: PositionWatch, limit: number): PositionAssessment[] {
  if (limit <= 0) return [];
  return watch.assessments
    .filter((item) => item.state === "INVALIDATED" && item.recommendation === "EXIT")
    .slice(0, limit);
}
