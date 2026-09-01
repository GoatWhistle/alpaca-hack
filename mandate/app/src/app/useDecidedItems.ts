import { useCallback, useEffect, useRef, useState } from "react";

const KEEP_VISIBLE_MS = 12_000;

export interface DecidedItems {
  merge: (items: Record<string, unknown>[]) => Record<string, unknown>[];
  retain: (item: Record<string, unknown>) => void;
}

export function useDecidedItems(): DecidedItems {
  const [retained, setRetained] = useState<Record<string, unknown>[]>([]);
  const timers = useRef<Record<string, number>>({});

  const retain = useCallback((item: Record<string, unknown>) => {
    const id = String(item.tool_call_id ?? "");
    if (!id || timers.current[id]) return;
    setRetained((previous) => [...previous, item]);
    timers.current[id] = window.setTimeout(() => {
      delete timers.current[id];
      setRetained((previous) =>
        previous.filter((entry) => String(entry.tool_call_id ?? "") !== id),
      );
    }, KEEP_VISIBLE_MS);
  }, []);

  useEffect(() => {
    const pending = timers.current;
    return () => {
      for (const timer of Object.values(pending)) window.clearTimeout(timer);
    };
  }, []);

  const merge = useCallback(
    (items: Record<string, unknown>[]) => {
      const liveIds = new Set(items.map((entry) => String(entry.tool_call_id ?? "")));
      return [
        ...items,
        ...retained.filter((entry) => !liveIds.has(String(entry.tool_call_id ?? ""))),
      ];
    },
    [retained],
  );

  return { merge, retain };
}
