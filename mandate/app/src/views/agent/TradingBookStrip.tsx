import type { Snapshot } from "../../lib/api";
import { hasValue, money, number, percent } from "../../lib/format";
import { displaySymbol } from "../dashboard/panels/PositionsPanel";

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function exitRules(item: Record<string, unknown>): string[] {
  return Object.entries(record(item.exit_policy)).flatMap(([label, value]) => {
    if (typeof value !== "string" || !value.trim()) return [];
    return [`${label.replaceAll("_", " ")}: ${value.trim().slice(0, 240)}`];
  }).slice(0, 6);
}

export function TradingBookStrip({ snapshot, live }: { snapshot: Snapshot | null; live: boolean }) {
  const positions = Object.entries(snapshot?.session.positions ?? {});
  const pending = snapshot?.session.pending_orders ?? [];
  return (
    <section className="trading-book" aria-label="Current positions and exit plans">
      <header>
        <div>
          <span>Current book</span>
          <strong>{positions.length} open · {pending.length} working</strong>
        </div>
        <small>{live ? "live Alpaca paper state" : "broker snapshot unavailable"}</small>
      </header>
      <div className="trading-book-cards">
        {positions.map(([symbol, item]) => {
          const side = String(item.side ?? (number(item.qty) < 0 ? "short" : "long"));
          const pnl = number(item.unrealized_pl);
          const pnlPct = number(item.unrealized_plpc) * 100;
          const rules = exitRules(item);
          return (
            <article className="book-position" key={symbol} data-side={side} title={symbol}>
              <div className="book-position-title">
                <b>{displaySymbol(symbol)}</b>
                <em>{side} · {Math.abs(number(item.qty))}</em>
              </div>
              <div className="book-position-price">
                <span>entry {hasValue(item.avg_entry_price) ? money(item.avg_entry_price) : "—"}</span>
                <span>mark {live && hasValue(item.market_price) ? money(item.market_price) : "—"}</span>
                <strong data-tone={pnl > 0 ? "gain" : pnl < 0 ? "loss" : "flat"}>
                  {pnl > 0 ? "+" : ""}{live && hasValue(item.unrealized_pl) ? money(pnl) : "—"}
                  {live && hasValue(item.unrealized_plpc) ? ` · ${pnlPct > 0 ? "+" : ""}${percent(pnlPct)}` : ""}
                </strong>
              </div>
              <details>
                <summary>When this position exits</summary>
                {rules.length > 0
                  ? <ul>{rules.map((rule) => <li key={rule}>{rule}</li>)}</ul>
                  : <p>Hard-risk engine evaluates stop, target, time-stop and session flatten.</p>}
              </details>
            </article>
          );
        })}
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
