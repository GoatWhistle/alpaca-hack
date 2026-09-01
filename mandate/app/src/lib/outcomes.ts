export type TimelineFilter = "all" | "submitted" | "denied" | "parked";

export const outcomeLabels: Record<string, string> = {
  prepared: "Prepared",
  submitted: "Submitted",
  submitted_reconciled: "Reconciled",
  filled: "Filled",
  unfilled_cancelled: "Unfilled / cancelled",
  deduplicated: "Deduplicated",
  denied: "Denied",
  parked: "Parked",
  conflict: "Conflict",
};

export const outcomeShapes: Record<string, string> = {
  prepared: "dash",
  submitted: "disc",
  submitted_reconciled: "disc",
  filled: "disc",
  unfilled_cancelled: "ring",
  deduplicated: "dash",
  denied: "ring",
  parked: "square",
  conflict: "double-ring",
};

export const timelineFilters: {
  key: TimelineFilter;
  label: string;
  outcomes: string[];
}[] = [
  { key: "all", label: "All", outcomes: [] },
  { key: "submitted", label: "Submitted", outcomes: ["submitted", "submitted_reconciled", "filled"] },
  { key: "denied", label: "Refused", outcomes: ["denied", "conflict", "unfilled_cancelled"] },
  { key: "parked", label: "Parked", outcomes: ["parked"] },
];

export function outcomeLabel(outcome: string): string {
  return outcomeLabels[outcome] ?? outcome;
}

export function emptyMessage(filter: TimelineFilter): string {
  if (filter === "all") {
    return "No decisions recorded yet. The agent writes here when it prepares, submits, parks, or is denied an order.";
  }
  const label = timelineFilters.find((item) => item.key === filter)?.label ?? filter;
  return `No ${label.toLowerCase()} decisions in this session yet.`;
}
