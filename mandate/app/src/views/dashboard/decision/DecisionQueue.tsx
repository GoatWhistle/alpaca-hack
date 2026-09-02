import { DecisionCard, type ApprovalAction } from "./DecisionCard";

interface DecisionQueueProps {
  items: Record<string, unknown>[];
  actions: Record<string, ApprovalAction>;
  live: boolean;
  hidden: boolean;
  onRespond: (item: Record<string, unknown>, approve: boolean) => void;
}

export function DecisionQueue({
  items,
  actions,
  live,
  hidden,
  onRespond,
}: DecisionQueueProps) {
  if (!items.length) return null;

  const awaiting = items.filter(
    (item) => !actions[String(item.tool_call_id ?? "")]?.outcome,
  ).length;
  const sequence = items[0]?.sequence && typeof items[0].sequence === "object"
    ? items[0].sequence as Record<string, unknown>
    : null;

  return (
    <section
      className="decisions"
      aria-label="Decisions awaiting approval"
      data-awaiting={awaiting}
      data-hidden={hidden}
    >
      <div className="decisions-heading">
        <h2>Operator decisions</h2>
        <span>
          {sequence
            ? `step ${String(sequence.current)} of ${String(sequence.total)}`
            : `${awaiting} awaiting`}
        </span>
      </div>
      <p className="sr-only" role="status">
        {awaiting === 0
          ? "No decisions await your approval"
          : `${awaiting} ${awaiting === 1 ? "decision awaits" : "decisions await"} your approval`}
        {live || awaiting === 0
          ? ""
          : ", but the paper broker is unreachable and none can be authorized"}
      </p>
      {items.map((item, index) => {
        const toolCallId = String(item.tool_call_id ?? "");
        return (
          <DecisionCard
            key={toolCallId || String(item.created_at ?? "")}
            index={index}
            item={item}
            action={actions[toolCallId]}
            live={live}
            onRespond={onRespond}
          />
        );
      })}
    </section>
  );
}

export function StandingBy({ marketOpen }: { marketOpen: boolean }) {
  return (
    <section className="standing-by">
      <svg className="standing-by-mark" viewBox="0 0 40 32" aria-hidden="true">
        <path d="M13 4 H6 V28 H13" />
        <path d="M27 4 H34 V28 H27" />
        <circle cx="20" cy="16" r="4.5" />
      </svg>
      <b>Nothing awaits you</b>
      <p>
        {marketOpen
          ? "Trading is automatic. Only explicit agent-memory changes require operator approval."
          : "The market is closed. News context continues accumulating for the next session."}
      </p>
    </section>
  );
}
