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
