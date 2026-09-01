import type { Journal } from "../../../lib/api";

export interface JournalDay {
  key: string;
  label: string;
  entries: Journal[];
}

const dayFormat = new Intl.DateTimeFormat("en-GB", {
  weekday: "short",
  day: "2-digit",
  month: "short",
});

function dayKey(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "unknown" : parsed.toDateString();
}

function dayLabel(value: string, todayKey: string, yesterdayKey: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "Undated";
  const key = parsed.toDateString();
  if (key === todayKey) return "Today";
  if (key === yesterdayKey) return "Yesterday";
  return dayFormat.format(parsed);
}

export function groupByDay(entries: Journal[], now = new Date()): JournalDay[] {
  const todayKey = now.toDateString();
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  const yesterdayKey = yesterday.toDateString();

  const days: JournalDay[] = [];
  for (const entry of entries) {
    const key = dayKey(entry.at);
    const last = days[days.length - 1];
    if (last && last.key === key) {
      last.entries.push(entry);
      continue;
    }
    days.push({
      key,
      label: dayLabel(entry.at, todayKey, yesterdayKey),
      entries: [entry],
    });
  }
  return days;
}
