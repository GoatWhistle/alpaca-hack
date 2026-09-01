function decodePoint(match: string, raw: string, radix: number): string {
  const point = Number.parseInt(raw, radix);
  const valid = Number.isInteger(point)
    && point >= 0
    && point <= 0x10ffff
    && !(point >= 0xd800 && point <= 0xdfff);
  return valid ? String.fromCodePoint(point) : match;
}

export function decodeEntities(value: unknown): string {
  return String(value ?? "")
    .replace(/&#(\d+);/g, (match, code: string) => decodePoint(match, code, 10))
    .replace(/&#x([0-9a-f]+);/gi, (match, code: string) => decodePoint(match, code, 16))
    .replaceAll("&quot;", "\"")
    .replaceAll("&apos;", "'")
    .replaceAll("&#39;", "'")
    .replaceAll("&amp;", "&")
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">");
}
