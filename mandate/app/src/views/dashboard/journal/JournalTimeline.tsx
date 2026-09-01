import { Empty } from "../../../components/Panel";
import { SkeletonTimeline } from "../../../components/Skeleton";
import { isoDate, timestamp } from "../../../lib/format";
import { emptyMessage, outcomeLabel, type TimelineFilter } from "../../../lib/outcomes";
import type { Journal } from "../../../lib/api";
import { BreachTable } from "./BreachTable";
import { groupByDay } from "./groupByDay";

function entryTitle(entry: Journal): string {
  const order = entry.details.order as Record<string, unknown> | undefined;
  if (order) {
    return `${String(order.side ?? "").toUpperCase()} ${order.qty ?? ""} ${order.symbol ?? ""}`;
  }
  const intended = entry.details.intended_action;
  if (typeof intended === "string" && intended) {
    const [side, qty, symbol] = intended.split(" ");
    return symbol ? `${side.toUpperCase()} ${qty} ${symbol}` : intended.toUpperCase();
  }
  const intent = entry.details.intent_id;
  if (typeof intent === "string" && intent) return `INTENT ${intent.toUpperCase()}`;
  return entry.action.replaceAll("_", " ").toUpperCase();
}

function entryKey(entry: Journal): string {
  const orderId = entry.details.order_id;
  if (typeof orderId === "string" && orderId) return `order:${orderId}`;
  const intentId = entry.details.intent_id;
  if (typeof intentId === "string" && intentId) return `intent:${intentId}:${entry.outcome}`;
  const intended = entry.details.intended_action;
  if (typeof intended === "string" && intended) return `intended:${intended}:${entry.outcome}`;
  return `${entry.action}:${entry.outcome}:${entry.rationale.slice(0, 40)}`;
}

function TimelineItem({
  entry,
  index,
  last,
}: {
  entry: Journal;
  index: number;
  last: boolean;
}) {
  const title = entryTitle(entry);
  const chips = [
    entry.details.intent_id
      && !title.startsWith("INTENT ")
      && `intent ${String(entry.details.intent_id)}`,
    entry.details.order_id && `order ${String(entry.details.order_id).slice(0, 14)}`,
  ].filter(Boolean) as string[];

  return (
    <article
      className={`timeline-item outcome--${entry.outcome}`}
      style={{ "--row-index": index } as React.CSSProperties}
    >
      <div className="timeline-marker">
        <i aria-hidden="true" />
        {!last && <span aria-hidden="true" />}
      </div>
      <div className="timeline-content">
        <div className="timeline-topline">
          <div>
            <b>{title}</b>
            <em>{outcomeLabel(entry.outcome)}</em>
          </div>
          <time dateTime={isoDate(entry.at)}>{timestamp(entry.at)}</time>
        </div>
        <p>{entry.rationale}</p>
        <BreachTable details={entry.details} />
        {chips.length > 0 && (
          <div className="detail-chips">
            {chips.map((chip) => (
              <span key={chip}>{chip}</span>
            ))}
          </div>
        )}
        <details>
          <summary>Raw evidence</summary>
          <pre>{JSON.stringify(entry.details, null, 2)}</pre>
        </details>
      </div>
    </article>
  );
}

interface JournalTimelineProps {
  entries: Journal[];
  filter: TimelineFilter;
  loading?: boolean;
}

export function JournalTimeline({ entries, filter, loading = false }: JournalTimelineProps) {
  if (loading) return <SkeletonTimeline />;
  if (!entries.length) return <Empty>{emptyMessage(filter)}</Empty>;

  const days = groupByDay(entries);

  return (
    <div className="timeline">
      {days.map((day) => (
        <section className="timeline-day" key={day.key}>
          <h3 className="timeline-day-heading">
            <span>{day.label}</span>
            <em>{day.entries.length}</em>
          </h3>
          {day.entries.map((entry, index) => (
            <TimelineItem
              key={entryKey(entry)}
              entry={entry}
              index={index}
              last={index === day.entries.length - 1}
            />
          ))}
        </section>
      ))}
    </div>
  );
}
