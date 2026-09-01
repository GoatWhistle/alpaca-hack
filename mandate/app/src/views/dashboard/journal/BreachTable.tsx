interface Breach {
  rule: string;
  limit: string;
  projected: string;
  headroom: string;
}

function readBreaches(details: Record<string, unknown>): Breach[] {
  const raw = details.breaches;
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((item): item is Record<string, unknown> =>
      typeof item === "object" && item !== null && !Array.isArray(item))
    .map((item) => ({
      rule: String(item.rule ?? "—"),
      limit: String(item.limit ?? "—"),
      projected: String(item.projected ?? "—"),
      headroom: String(item.headroom ?? "—"),
    }));
}

export function BreachTable({ details }: { details: Record<string, unknown> }) {
  const breaches = readBreaches(details);
  if (!breaches.length) return null;

  return (
    <table className="breach-table">
      <caption>Broker responses recorded for recent paper orders</caption>
      <thead>
        <tr>
          <th scope="col">Rule</th>
          <th scope="col">Limit</th>
          <th scope="col">Projected</th>
          <th scope="col">Headroom</th>
        </tr>
      </thead>
      <tbody>
        {breaches.map((breach) => (
          <tr key={`${breach.rule}-${breach.projected}`}>
            <th scope="row">{breach.rule.replaceAll("_", " ")}</th>
            <td>{breach.limit}</td>
            <td className="breach-value">{breach.projected}</td>
            <td>{breach.headroom}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
