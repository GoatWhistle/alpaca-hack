import { Panel } from "../../components/Panel";

interface ScorecardTableProps {
  rows: [string, unknown][];
}

const columns = [
  { key: "observations", label: "Obs", title: "Completed 60-minute outcomes" },
  { key: "mean_signed_return_pct", label: "Mean", suffix: "%", signed: true, title: "Mean signed forward return" },
  { key: "directional_accuracy_pct", label: "Hit rate", suffix: "%", title: "Share of correct directions" },
  { key: "sharpe_like", label: "Sharpe-like", signed: true, title: "Mean over standard deviation" },
  { key: "adaptive_multiplier", label: "Weight", suffix: "×", title: "Evidence-shrunk bounded multiplier" },
];

function cellValue(raw: unknown, column: { suffix?: string; signed?: boolean }): string {
  if (raw === undefined || raw === null || raw === "") return "—";
  const text = String(raw);
  const numeric = Number(text);
  const signed = column.signed && Number.isFinite(numeric) && numeric > 0 ? `+${text}` : text;
  return `${signed}${column.suffix ?? ""}`;
}

function toneOf(raw: unknown, signed?: boolean): string | undefined {
  if (!signed) return undefined;
  const numeric = Number(raw);
  if (!Number.isFinite(numeric) || numeric === 0) return undefined;
  return numeric > 0 ? "cell--up" : "cell--down";
}

export function ScorecardTable({ rows }: ScorecardTableProps) {
  return (
    <Panel
      title="60m strategy scorecard"
      count={`${rows.length} strategies`}
      className="diag-panel diag-panel--wide"
    >
      {rows.length ? (
        <div className="outcome-scorecard scorecard-standalone">
          <table>
            <thead>
              <tr>
                <th scope="col">Strategy</th>
                {columns.map((column) => (
                  <th key={column.key} scope="col" title={column.title}>
                    {column.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map(([name, raw]) => {
                const item = (raw ?? {}) as Record<string, unknown>;
                return (
                  <tr key={name}>
                    <th scope="row">{name.replaceAll("_", " ")}</th>
                    {columns.map((column) => (
                      <td key={column.key} className={toneOf(item[column.key], column.signed)}>
                        {cellValue(item[column.key], column)}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted">
          Appears after any evaluated signal receives a 60-minute counterfactual outcome.
          Both parked and proposed cycles contribute evidence.
        </p>
      )}
    </Panel>
  );
}
