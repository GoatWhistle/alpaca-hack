import { decimal, number } from "../../../lib/format";

interface Rule {
  key: string;
  label: string;
  unit: string;
  digits?: number;
}

const RULES: Rule[] = [
  { key: "max_position_pct", label: "Position", unit: "%" },
  { key: "max_gross_exposure_pct", label: "Gross exposure", unit: "%" },
  { key: "max_daily_loss_pct", label: "Daily loss", unit: "%" },
  { key: "max_orders_per_day", label: "Orders today", unit: "", digits: 0 },
];

interface MandateAuthorityProps {
  headroom: Record<string, unknown>;
  limits: Record<string, unknown>;
}

export function MandateAuthority({ headroom, limits }: MandateAuthorityProps) {
  const rows = RULES.filter((rule) => headroom[rule.key] !== undefined).map((rule) => {
    const limit = number(limits[rule.key]);
    const left = number(headroom[rule.key]);
    const used = limit - left;
    return { ...rule, limit, left, used, tight: limit > 0 && left / limit <= 0.2 };
  });

  if (!rows.length) return null;

  return (
    <section className="authority" aria-label="Mandate authority for this order">
      <h3>Authority remaining under the mandate</h3>
      <table>
        <thead>
          <tr>
            <th scope="col">Rule</th>
            <th scope="col">Used</th>
            <th scope="col">Limit</th>
            <th scope="col">Headroom</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key} className={row.tight ? "tight" : undefined}>
              <th scope="row">{row.label}</th>
              <td>{decimal(row.used, row.digits)}{row.unit}</td>
              <td>{decimal(row.limit, row.digits)}{row.unit}</td>
              <td>
                {decimal(row.left, row.digits)}{row.unit}
                {row.tight && <em> tight</em>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p>
        Alpaca remains the execution authority and rejects orders the paper account cannot accept.
        Approval cannot override a mandate rule.
      </p>
    </section>
  );
}
