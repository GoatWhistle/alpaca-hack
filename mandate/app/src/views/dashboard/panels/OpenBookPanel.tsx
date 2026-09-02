import { Empty, Panel } from "../../../components/Panel";
import { PositionCard } from "../../../components/PositionCard";
import { hasValue, money, number } from "../../../lib/format";
import { displaySymbol } from "../../../lib/symbols";

interface OpenBookPanelProps {
  positions: [string, Record<string, unknown>][];
  pending: Record<string, unknown>[];
  live: boolean;
  equity: number;
}

function WorkingOrder({ order }: { order: Record<string, unknown> }) {
  const legs = number(order.legs);
  const symbol = String(order.symbol ?? "").trim();
  const side = String(order.side ?? "").toLowerCase();
  return (
    <div className="working-order" data-side={side}>
      <em className={`badge badge--${side === "sell" ? "short" : "long"}`}>{side || "order"}</em>
      <b>{symbol ? displaySymbol(symbol) : legs > 0 ? `multi-leg ×${legs}` : "—"}</b>
      <span>
        {String(order.qty ?? "—")}{hasValue(order.filled_qty) && number(order.filled_qty) > 0
          ? ` · filled ${String(order.filled_qty)}`
          : ""}
      </span>
      <small>
        {String(order.type ?? "limit")} @ {hasValue(order.limit_price) ? money(order.limit_price) : "—"}
      </small>
    </div>
  );
}

/** Live broker state: what the desk holds and what is working at the broker. */
export function OpenBookPanel({ positions, pending, live, equity }: OpenBookPanelProps) {
  return (
    <Panel
      title="Open book"
      count={`${positions.length} open · ${pending.length} working`}
      className="open-book-panel"
    >
      {positions.length ? (
        <div className="open-book-grid">
          {positions.map(([symbol, item]) => (
            <PositionCard key={symbol} symbol={symbol} item={item} live={live} equity={equity} />
          ))}
        </div>
      ) : (
        <Empty>
          {live
            ? "No open positions. The agent holds nothing on the paper account right now."
            : "Positions are withheld. The broker cannot be reached, so this panel cannot say what is held."}
        </Empty>
      )}

      {pending.length > 0 && (
        <>
          <div className="subsection-title">
            <span>Working orders</span>
            <b>{pending.length}</b>
          </div>
          <div className="working-orders">
            {pending.map((order, index) => {
              const symbol = String(order.symbol ?? "").trim();
              return <WorkingOrder key={`${String(order.id ?? symbol)}-${index}`} order={order} />;
            })}
          </div>
        </>
      )}
    </Panel>
  );
}
