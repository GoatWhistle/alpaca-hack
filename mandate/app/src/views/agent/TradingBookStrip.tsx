import type { Snapshot } from "../../lib/api";
import { hasValue, money } from "../../lib/format";
import { displaySymbol } from "../../lib/symbols";
import { PositionCard } from "../../components/PositionCard";

export function TradingBookStrip({
  snapshot,
  live,
  equity = 0,
}: {
  snapshot: Snapshot | null;
  live: boolean;
  equity?: number;
}) {
  const positions = Object.entries(snapshot?.session.positions ?? {});
  const pending = snapshot?.session.pending_orders ?? [];
  if (positions.length === 0 && pending.length === 0) return null;

  return (
    <section className="trading-book" aria-label="Current positions and exit plans">
      <div className="trading-book-cards">
        {positions.map(([symbol, item]) => (
          <PositionCard
            key={symbol}
            symbol={symbol}
            item={item}
            live={live}
            equity={equity}
            variant="compact"
          />
        ))}
        {pending.map((order, index) => {
          const symbol = String(order.symbol ?? "").trim() || "multi-leg";
          return (
            <article className="book-order" key={`${String(order.id ?? symbol)}-${index}`}>
              <div className="book-position-title">
                <b>{displaySymbol(symbol)}</b>
                <em>working order</em>
              </div>
              <p>
                {String(order.side ?? "").toUpperCase()} {String(order.qty ?? "—")}
                {hasValue(order.limit_price) ? ` @ ${money(order.limit_price)}` : ""}
              </p>
              <small>{String(order.status ?? order.type ?? "pending")}</small>
            </article>
          );
        })}
      </div>
    </section>
  );
}
