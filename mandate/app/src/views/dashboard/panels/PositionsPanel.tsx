import { Empty, Panel } from "../../../components/Panel";
import { hasValue, money, number, percent } from "../../../lib/format";

interface PositionsPanelProps {
  positions: [string, Record<string, unknown>][];
  pending: Record<string, unknown>[];
  live: boolean;
}

const OCC_SYMBOL = /^([A-Z]{1,6})(\d{2})(\d{2})(\d{2})([CP])(\d{8})$/u;

/** Render an OCC option symbol as "NVDA 09/09 222.5C"; equities pass through. */
export function displaySymbol(symbol: string): string {
  const match = OCC_SYMBOL.exec(symbol);
  if (!match) return symbol;
  const [, root, , month, day, kind, rawStrike] = match;
  const strike = Number(rawStrike) / 1000;
  return `${root} ${month}/${day} ${strike}${kind}`;
}

function unitLabel(item: Record<string, unknown>): string {
  const qty = Math.abs(number(item.qty));
  const option = item.asset_class === "us_option";
  const unit = option ? "contract" : "share";
  return `${qty} ${unit}${qty === 1 ? "" : "s"}`;
}

function PositionPnl({ item, live }: { item: Record<string, unknown>; live: boolean }) {
  if (!live || !hasValue(item.unrealized_pl)) return null;
  const pnl = number(item.unrealized_pl);
  const tone = pnl > 0 ? "position-gain" : pnl < 0 ? "position-loss" : "position-flat";
  const sign = pnl > 0 ? "+" : "";
  const plpc = hasValue(item.unrealized_plpc) ? ` (${sign}${percent(number(item.unrealized_plpc) * 100)})` : "";
  return <em className={tone}> {sign}{money(pnl)}{plpc}</em>;
}

export function PositionsPanel({ positions, pending, live }: PositionsPanelProps) {
  return (
    <Panel title="Positions & orders" count={positions.length} className="broker-panel">
      {positions.length ? (
        <div className="positions">
          {positions.map(([symbol, item]) => (
            <div key={symbol} title={symbol}>
              <b>{displaySymbol(symbol)}</b>
              <span>
                {String(item.side ?? (number(item.qty) < 0 ? "short" : "long"))} · {unitLabel(item)}
              </span>
              <strong>{live && hasValue(item.market_value) ? money(item.market_value) : "—"}</strong>
              <small>
                @ {live && hasValue(item.market_price) ? money(item.market_price) : "—"}
                <PositionPnl item={item} live={live} />
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
          {pending.map((order, index) => {
            const legs = number(order.legs);
            const symbol = String(order.symbol ?? "").trim();
            return (
              <div key={`${String(order.id ?? symbol)}-${index}`}>
                <b>{symbol ? displaySymbol(symbol) : legs > 0 ? "multi-leg" : "—"}</b>
                <span>
                  {String(order.side ?? "")} {String(order.qty ?? "")}
                  {legs > 0 ? ` · mleg ×${legs}` : ""}
                  {hasValue(order.filled_qty) && number(order.filled_qty) > 0
                    ? ` · filled ${String(order.filled_qty)}`
                    : ""}
                </span>
                <small>
                  {String(order.type ?? "")} @ {live && hasValue(order.limit_price) ? money(order.limit_price) : "—"}
                </small>
              </div>
            );
          })}
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
