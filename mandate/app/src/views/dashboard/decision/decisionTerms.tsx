import { hasValue, money } from "../../../lib/format";

const ORDER_TOOLS = new Set(["place_stock_order", "place_option_order"]);

export function isOrderTool(toolName: string): boolean {
  return ORDER_TOOLS.has(toolName);
}

export function decisionSummary(
  toolName: string,
  args: Record<string, unknown>,
): string {
  if (!isOrderTool(toolName)) {
    return toolName.replaceAll("_", " ");
  }
  const side = String(args.side ?? "?").toUpperCase();
  const qty = String(args.quantity ?? args.qty ?? "?");
  const rawLegs = Array.isArray(args.legs) ? args.legs : [];
  const legSymbols = rawLegs.flatMap((leg) =>
    typeof leg === "object" && leg !== null && "symbol" in leg
      ? [String((leg as Record<string, unknown>).symbol)] : []);
  const symbol = String(args.symbol ?? (legSymbols.length ? legSymbols.join(" / ") : "?"));
  const limit = args.limit_price ? ` · LIMIT ${money(args.limit_price)}` : "";
  return `${side} ${qty} ${symbol}${limit}`;
}

function notional(args: Record<string, unknown>): string {
  const quantity = args.quantity ?? args.qty;
  if (!hasValue(quantity) || !hasValue(args.limit_price)) return "—";
  const optionMultiplier = args.position_intent || args.order_class === "mleg" || Array.isArray(args.legs)
    ? 100 : 1;
  return money(Number(quantity) * Number(args.limit_price) * optionMultiplier);
}

export function OrderTerms({ args }: { args: Record<string, unknown> }) {
  const rawLegs = Array.isArray(args.legs) ? args.legs : [];
  const legs = rawLegs.flatMap((leg) => {
    if (typeof leg !== "object" || leg === null || Array.isArray(leg)) return [];
    const item = leg as Record<string, unknown>;
    return [`${String(item.side ?? "?").toUpperCase()} ${String(item.ratio_qty ?? "1")} ${String(item.symbol ?? "?")}`];
  });
  const terms = [
    { label: legs.length ? "Strategy" : "Symbol", value: legs.length ? legs.join(" · ") : String(args.symbol ?? "—") },
    { label: "Side", value: String(args.side ?? "—").toUpperCase() },
    { label: "Quantity", value: String(args.quantity ?? args.qty ?? "—") },
    { label: "Type", value: String(args.order_type ?? args.type ?? args.order_class ?? "—").toUpperCase() },
    {
      label: "Limit",
      value: args.limit_price ? money(args.limit_price) : "—",
    },
    { label: "Notional", value: notional(args) },
  ];

  return (
    <dl className="order-terms">
      {terms.map((term) => (
        <div key={term.label}>
          <dt>{term.label}</dt>
          <dd>{term.value}</dd>
        </div>
      ))}
    </dl>
  );
}
