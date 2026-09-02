import type { Snapshot } from "../../lib/api";
import { hasValue, money } from "../../lib/format";
import { displaySymbol } from "../../lib/symbols";
import { PositionCard } from "../../components/PositionCard";

export function TradingBookStrip({
  snapshot,
  live,
  equity = 0,
  contextState = "live",
}: {
  snapshot: Snapshot | null;
  live: boolean;
  equity?: number;
  contextState?: "live" | "degraded";
}) {
  const positions = Object.entries(snapshot?.session.positions ?? {});
  const pending = snapshot?.session.pending_orders ?? [];
  return (
    <section className="trading-book" aria-label="Current positions and exit plans">
      <header>
        <div>
          <span>Current book</span>
          <strong>{positions.length} open · {pending.length} working</strong>
        </div>
        <div className="trading-book-state">
          <small data-state={contextState}><i className="live-dot" />stream {contextState}</small>
          <small>{live ? "live Alpaca paper state" : "broker snapshot unavailable"}</small>
        </div>
      </header>
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
        {positions.length === 0 && pending.length === 0 && (
          <p className="trading-book-empty">
            {live ? "Flat book. No open positions or working orders." : "Waiting for a live broker snapshot."}
          </p>
        )}
      </div>
    </section>
  );
}
