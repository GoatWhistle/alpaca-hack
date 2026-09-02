import { hasValue, money, number, percent } from "../lib/format";
import { decodeSymbol, displaySymbol } from "../lib/symbols";

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

/**
 * One open position as a desk card: side accent, entry→mark move, unrealized
 * P&L and — in the full variant — the share of equity and the exit plan.
 */
export function PositionCard({
  symbol,
  item,
  live,
  equity = 0,
  variant = "full",
}: {
  symbol: string;
  item: Record<string, unknown>;
  live: boolean;
  equity?: number;
  variant?: "full" | "compact";
}) {
  const decoded = decodeSymbol(symbol);
  const qty = Math.abs(number(item.qty));
  const side = String(item.side ?? (number(item.qty) < 0 ? "short" : "long"));
  const option = decoded.option || item.asset_class === "us_option";
  const unit = option ? "contract" : "share";
  const entry = number(item.avg_entry_price);
  const mark = number(item.market_price);
  const movePct = entry > 0 && hasValue(item.market_price) ? (mark - entry) / entry * 100 : null;
  const favorableMovePct = movePct === null ? null : movePct * (side === "short" ? -1 : 1);
  const pnl = number(item.unrealized_pl);
  const pnlPct = number(item.unrealized_plpc) * 100;
  const hasPnl = live && hasValue(item.unrealized_pl);
  const pnlTone = pnl > 0 ? "gain" : pnl < 0 ? "loss" : "flat";
  const exposure = equity > 0 ? Math.abs(number(item.market_value)) / equity * 100 : null;
  const rules = variant === "full" ? exitRules(item) : [];

  return (
    <article className="position-card" data-side={side} data-variant={variant} title={symbol}>
      <header>
        <b>{displaySymbol(symbol)}</b>
        <div className="position-badges">
          {option && <em className="badge badge--instrument">{decoded.kind ?? "opt"}</em>}
          <em className={`badge badge--${side === "short" ? "short" : "long"}`}>{side}</em>
        </div>
      </header>

      <p className="position-size">
        {qty} {unit}{qty === 1 ? "" : "s"}
        <span>
          entry {hasValue(item.avg_entry_price) ? money(entry) : "—"}
          {" → "}
          mark {live && hasValue(item.market_price) ? money(mark) : "—"}
          {movePct !== null && (
            <i data-tone={(favorableMovePct ?? 0) >= 0 ? "gain" : "loss"}>
              {movePct >= 0 ? " ▲ " : " ▼ "}{percent(Math.abs(movePct))}
            </i>
          )}
        </span>
      </p>

      <strong className="position-pnl" data-tone={hasPnl ? pnlTone : "flat"}>
        {hasPnl
          ? `${pnl > 0 ? "+" : ""}${money(pnl)}${hasValue(item.unrealized_plpc) ? ` · ${pnlPct > 0 ? "+" : ""}${percent(pnlPct)}` : ""}`
          : "P&L needs the broker"}
      </strong>

      {variant === "full" && (
        <>
          {exposure !== null && (
            <div className="position-exposure" title="Share of account equity">
              <span>{live ? percent(exposure) : "—"}<i> of equity</i></span>
              <div className="meter"><div style={{ width: `${Math.min(100, Math.max(1.5, exposure))}%` }} /></div>
            </div>
          )}
          <details className="position-exit">
            <summary>Exit plan</summary>
            {rules.length > 0
              ? <ul>{rules.map((rule) => <li key={rule}>{rule}</li>)}</ul>
              : <p>Hard-risk engine evaluates stop, target, time-stop and session flatten.</p>}
          </details>
        </>
      )}
    </article>
  );
}
