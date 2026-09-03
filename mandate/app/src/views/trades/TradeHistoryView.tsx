import { useMemo, useState } from "react";
import { useTrades } from "../../app/useTrades";
import { decimal, money } from "../../lib/format";
import type { Snapshot } from "../../lib/api";
import { tradeHistory, type TradeHistoryRow } from "../../lib/trades";

type StatusFilter = "ALL" | "OPEN" | "CLOSED";

function dateTime(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(parsed);
}

function duration(value: number | null): string {
  if (value === null) return "—";
  const totalMinutes = Math.max(0, Math.floor(value / 60_000));
  const days = Math.floor(totalMinutes / 1440);
  const hours = Math.floor((totalMinutes % 1440) / 60);
  const minutes = totalMinutes % 60;
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

function pnlTone(row: TradeHistoryRow): "gain" | "loss" | "flat" {
  if (row.pnl === null || row.pnl === 0) return "flat";
  return row.pnl > 0 ? "gain" : "loss";
}

function HistoryRow({ row }: { row: TradeHistoryRow }) {
  const tone = pnlTone(row);
  return (
    <tr>
      <td><span className="history-status" data-status={row.status}>{row.status}</span></td>
      <td className="history-instrument">
        <strong>{row.display}</strong>
        <small>{row.kind}</small>
        {row.legs.length > 1 && (
          <details>
            <summary>{row.legs.length} legs</summary>
            {row.legs.map((leg) => (
              <span key={`${leg.symbol}:${leg.side}`}>{leg.side.toUpperCase()} {leg.ratio}× {leg.symbol}</span>
            ))}
          </details>
        )}
      </td>
      <td>{row.direction}</td>
      <td className="numeric">{decimal(row.qty, 0)}</td>
      <td><time dateTime={row.openedAt ?? undefined}>{dateTime(row.openedAt)}</time></td>
      <td className="numeric">{row.entryPrice === null ? "—" : money(row.entryPrice)}</td>
      <td><time dateTime={row.closedAt ?? undefined}>{row.status === "OPEN" ? "OPEN" : dateTime(row.closedAt)}</time></td>
      <td className="numeric">{row.exitPrice === null ? "—" : money(row.exitPrice)}</td>
      <td className="numeric">{duration(row.holdingMs)}</td>
      <td className="numeric history-pnl" data-tone={tone}>
        {row.pnl === null ? "—" : `${row.pnl > 0 ? "+" : ""}${money(row.pnl)}`}
      </td>
      <td className="numeric history-pnl" data-tone={tone}>
        {row.pnlPct === null ? "—" : `${row.pnlPct > 0 ? "+" : ""}${decimal(row.pnlPct)}%`}
      </td>
      <td className="history-reason">
        <span>{row.exitReason ?? (row.status === "OPEN" ? "Position still open" : "No recorded reason")}</span>
        {row.entryReason && <details><summary>Entry thesis</summary><p>{row.entryReason}</p></details>}
      </td>
    </tr>
  );
}

export function TradeHistoryView({
  snapshot,
  paused,
}: {
  snapshot: Snapshot | null;
  paused: boolean;
}) {
  const { trades, loading, error } = useTrades(paused);
  const [filter, setFilter] = useState<StatusFilter>("ALL");
  const [query, setQuery] = useState("");
  const rows = useMemo(
    () => tradeHistory(trades, snapshot?.session.positions ?? {}),
    [snapshot?.session.positions, trades],
  );
  const visible = useMemo(() => {
    const needle = query.trim().toUpperCase();
    return rows.filter((row) =>
      (filter === "ALL" || row.status === filter)
      && (!needle || row.display.toUpperCase().includes(needle)));
  }, [filter, query, rows]);
  const closed = rows.filter((row) => row.status === "CLOSED" && row.pnl !== null);
  const open = rows.filter((row) => row.status === "OPEN" && row.pnl !== null);
  const realized = closed.reduce((sum, row) => sum + (row.pnl ?? 0), 0);
  const unrealized = open.reduce((sum, row) => sum + (row.pnl ?? 0), 0);
  const wins = closed.filter((row) => (row.pnl ?? 0) > 0).length;
  const unmatched = rows.filter((row) => row.status === "UNMATCHED").length;

  return (
    <div className="trade-history-view">
      <main id="main-content" tabIndex={-1}>
        <h1 className="sr-only">Trade history</h1>

        <section className="history-summary" aria-label="Trade results summary">
          <div><span>Matched realized P&L</span><strong data-tone={realized >= 0 ? "gain" : "loss"}>{realized >= 0 ? "+" : ""}{money(realized)}</strong></div>
          <div><span>Open P&L</span><strong data-tone={unrealized >= 0 ? "gain" : "loss"}>{unrealized >= 0 ? "+" : ""}{money(unrealized)}</strong></div>
          <div><span>Closed bets</span><strong>{closed.length}</strong></div>
          <div><span>Win rate</span><strong>{closed.length ? `${decimal(wins / closed.length * 100)}%` : "—"}</strong></div>
          <div><span>Open bets</span><strong>{rows.filter((row) => row.status === "OPEN").length}</strong></div>
          <div><span>Unmatched records</span><strong data-tone={unmatched > 0 ? "loss" : "gain"}>{unmatched}</strong></div>
        </section>

        <section className="history-ledger">
          <header className="history-controls">
            <div className="history-filters" aria-label="Trade status filter">
              {(["ALL", "OPEN", "CLOSED"] as const).map((value) => (
                <button key={value} className={filter === value ? "active" : ""} onClick={() => setFilter(value)}>
                  {value}
                </button>
              ))}
            </div>
            <label>
              <span className="sr-only">Filter by instrument</span>
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter symbol…" />
            </label>
            <span className="history-source">
              <i data-live={snapshot?.source === "live"} />
              {snapshot?.source === "live" ? "LIVE PAPER DATA" : "DEGRADED"}
            </span>
            <small>{visible.length} rows · newest first</small>
          </header>

          {error && <p className="history-error">{error}</p>}
          <div className="history-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Status</th>
                  <th>Position / strategy</th>
                  <th>Side</th>
                  <th>Qty</th>
                  <th>Entered</th>
                  <th>Entry</th>
                  <th>Exited</th>
                  <th>Exit / mark</th>
                  <th>Held</th>
                  <th>P&L</th>
                  <th>Return</th>
                  <th>Why exited</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((row) => <HistoryRow key={row.key} row={row} />)}
              </tbody>
            </table>
            {!loading && visible.length === 0 && <p className="history-empty">No matching filled trades.</p>}
            {loading && rows.length === 0 && <p className="history-empty">Loading broker fills…</p>}
          </div>
        </section>
      </main>
    </div>
  );
}
