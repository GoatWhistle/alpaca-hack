import { Metric } from "../../../components/Metric";
import { Withheld } from "../../../components/SourceBadge";
import { hasValue, money, number, percent } from "../../../lib/format";

interface MetricsBlockProps {
  account: Record<string, unknown>;
  limits: Record<string, unknown>;
  usage: Record<string, unknown>;
  ordersToday: number;
  universe: string[];
  live: boolean;
}

export function MetricsBlock({
  account,
  limits,
  usage,
  ordersToday,
  universe,
  live,
}: MetricsBlockProps) {
  const dailyPnl = number(account.daily_pnl);
  const exposureLimit = number(limits.max_gross_exposure_pct);
  const exposureUsed = number(account.gross_exposure_pct);
  const exposureTone = exposureLimit > 0 && exposureUsed / exposureLimit >= 0.8 ? "warn" : "default";

  return (
    <section className="metrics-block">
      <div className="metrics-grid">
        <Metric
          label="Account equity"
          value={live && hasValue(account.equity) ? money(account.equity) : <Withheld />}
          hint={live ? "Alpaca paper account" : "Needs the broker"}
        />
        <Metric
          label="Daily P&L"
          value={live && hasValue(dailyPnl) ? money(dailyPnl) : <Withheld />}
          tone={live && dailyPnl !== 0 ? (dailyPnl > 0 ? "good" : "bad") : "default"}
          hint={live ? undefined : "Needs the broker"}
          used={live ? number(usage.daily_loss_pct) : undefined}
          limit={live ? number(limits.max_daily_loss_pct) : undefined}
        />
        <Metric
          label="Gross exposure"
          value={live ? percent(exposureUsed) : <Withheld />}
          tone={live ? exposureTone : "default"}
          hint={live ? undefined : "Needs the broker"}
          used={live ? exposureUsed : undefined}
          limit={live ? exposureLimit : undefined}
        />
        <Metric
          label="Orders today"
          value={live ? String(ordersToday) : <Withheld />}
          hint={live ? undefined : "Needs the broker"}
          used={live ? ordersToday : undefined}
          limit={live ? number(limits.max_orders_per_day) : undefined}
          unit=""
          digits={0}
        />
      </div>
      <div className="metrics-footer">
        <div className="universe-chips">
          <span>Universe</span>
          <div>
            {universe.length
              ? universe.map((symbol) => <b key={symbol}>{symbol}</b>)
              : "—"}
          </div>
        </div>
      </div>
    </section>
  );
}

export function AttentionBanner({
  lines,
}: {
  lines: { level: "error" | "warn"; text: string }[];
}) {
  if (!lines.length) return null;
  const hasError = lines.some((line) => line.level === "error");
  return (
    <section
      className={`attention-banner${hasError ? " attention-banner--error" : ""}`}
      role="status"
      aria-live="polite"
    >
      <b>{hasError ? "Needs attention" : "Operator decision"}</b>
      <ul>
        {lines.map((line, index) => (
          <li key={index}>{line.text}</li>
        ))}
      </ul>
    </section>
  );
}
