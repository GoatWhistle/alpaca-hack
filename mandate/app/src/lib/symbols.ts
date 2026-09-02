const OCC_SYMBOL = /^([A-Z]{1,6})(\d{2})(\d{2})(\d{2})([CP])(\d{8})$/u;

export interface DecodedSymbol {
  root: string;
  option: boolean;
  monthDay?: string;
  kind?: "C" | "P";
  strike?: number;
}

export function decodeSymbol(symbol: string): DecodedSymbol {
  const match = OCC_SYMBOL.exec(symbol);
  if (!match) return { root: symbol, option: false };
  const [, root, , month, day, kind, rawStrike] = match;
  return {
    root,
    option: true,
    monthDay: `${month}/${day}`,
    kind: kind as "C" | "P",
    strike: Number(rawStrike) / 1000,
  };
}

/** Render an OCC option symbol as "NVDA 09/09 222.5C"; equities pass through. */
export function displaySymbol(symbol: string): string {
  const decoded = decodeSymbol(symbol);
  if (!decoded.option) return symbol;
  return `${decoded.root} ${decoded.monthDay} ${decoded.strike}${decoded.kind}`;
}
