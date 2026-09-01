import { Empty, Panel } from "../../../components/Panel";
import { hasValue, money } from "../../../lib/format";

interface PositionsPanelProps {
  positions: [string, Record<string, unknown>][];
  pending: Record<string, unknown>[];
  live: boolean;
}

export function PositionsPanel({ positions, pending, live }: PositionsPanelProps) {
  return (
    <Panel title="Positions & orders" count={positions.length} className="broker-panel">
      {positions.length ? (
        <div className="positions">
          {positions.map(([symbol, item]) => (
            <div key={symbol}>
              <b>{symbol}</b>
              <span>{String(item.qty ?? "0")} shares</span>
              <strong>{live && hasValue(item.market_value) ? money(item.market_value) : "—"}</strong>
              <small>
                @ {live && hasValue(item.market_price) ? money(item.market_price) : "—"}
                {live && hasValue(item.unrealized_pl) && Number(item.unrealized_pl) > 0
                  ? <em className="position-gain"> +{money(item.unrealized_pl)}</em>
                  : null}
              </small>
            </div>
          ))}
        </div>
      ) : (
        <Empty>
          {live
            ? "No open positions. The agent holds nothing on the paper account right now."
            : "Positions are withheld. The broker cannot be reached, so this panel cannot say what is held."}
        </Empty>
      )}

      <div className="subsection-title">
        <span>Pending orders</span>
        <b>{pending.length}</b>
      </div>

      {pending.length ? (
        <div className="pending-list">
          {pending.map((order, index) => (
            <div key={`${String(order.symbol)}-${index}`}>
              <b>{String(order.symbol ?? "—")}</b>
              <span>
                {String(order.side ?? "")} {String(order.remaining_qty ?? "")}
              </span>
              <small>@ {live && hasValue(order.reference_price) ? money(order.reference_price) : "—"}</small>
            </div>
          ))}
        </div>
      ) : (
        <p className="muted">
          {live
            ? "No orders are waiting at the broker."
            : "Pending orders are withheld while the broker is unreachable."}
        </p>
      )}
    </Panel>
  );
}
