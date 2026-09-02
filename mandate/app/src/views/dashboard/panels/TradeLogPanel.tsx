import { Empty, Panel } from "../../../components/Panel";
import { SkeletonTimeline } from "../../../components/Skeleton";
import { timestamp } from "../../../lib/format";
import { tradeTone, type TradeRow } from "../../../lib/trades";

function FillRow({ row }: { row: TradeRow }) {
  const tone = tradeTone(row);
  return (
    <article className="trade-row" data-tone={tone}>
      <div className="trade-main">
        <div className="trade-title">
          <em className={`badge badge--${row.side === "sell" ? "short" : "long"}`}>
            {row.side || "order"}
          </em>
          <b>{row.display}</b>
          <span className="trade-kind">{row.kind}</span>
        </div>
        <div className="trade-terms">
          <span>
            {row.qty ?? "—"} @ {row.limitPrice ?? "—"}
            {row.avgPrice ? ` · avg ${row.avgPrice}` : ""}
            {row.filledQty ? ` · filled ${row.filledQty}` : ""}
          </span>
          <time dateTime={row.at}>{timestamp(row.at)}</time>
        </div>
      </div>
      <div className="trade-side">
        <em data-tone={tone}>{tone === "working" ? "working" : row.status ?? "unknown"}</em>
        {row.eventKind === "risk_exit" && <small>risk exit</small>}
      </div>
      {row.reason && (
        <details className="trade-reason">
          <summary>Why</summary>
          <p>{row.reason}</p>
          {row.candidate && <small>candidate {row.candidate}</small>}
        </details>
      )}
    </article>
  );
}

/**
 * The dashboard's tail of executed orders — the purchase log lifted out of the
 * trader chat. The paired FIFO ledger with realized P&L lives on the trade
 * history tab; this surface answers "what did the desk just do".
 */
export function TradeLogPanel({
  trades,
  loading,
  error,
  onOpenHistory,
}: {
  trades: TradeRow[];
  loading: boolean;
  error: string | null;
  onOpenHistory: () => void;
}) {
  const recent = trades.slice(0, 12);
  return (
    <Panel
      title="Recent fills"
      count={trades.length ? `${trades.length} order${trades.length === 1 ? "" : "s"}` : undefined}
      className="trade-log-panel"
      actions={
        <button className="text-button" onClick={onOpenHistory}>
          Open trade history
        </button>
      }
    >
      {error && <p className="trade-log-error">{error}</p>}
      {loading && trades.length === 0 ? (
        <SkeletonTimeline />
      ) : recent.length ? (
        <div className="trade-list">
          {recent.map((row) => (
            <FillRow key={row.key} row={row} />
          ))}
        </div>
      ) : (
        <Empty>
          {error
            ? "The trade log could not be read from the desk journal."
            : "No orders have been executed in the retained journal window."}
        </Empty>
      )}
    </Panel>
  );
}
