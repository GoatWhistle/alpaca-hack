const STEPS = [
  { key: "monitoring", label: "Monitor", detail: "prices · news" },
  { key: "risk_exit", label: "Risk exit", detail: "stops · targets" },
  { key: "signals", label: "Signals", detail: "ensemble · ATR" },
  { key: "challenge", label: "Challenge", detail: "agent critic" },
  { key: "broker", label: "Broker", detail: "account · capacity" },
  { key: "execution", label: "Order", detail: "paper broker" },
] as const;

export function LivePipeline({ runtime }: { runtime: Record<string, unknown> }) {
  const stage = String(runtime.pipeline_stage ?? (runtime.status === "analyzing" ? "signals" : "monitoring"));
  const activeIndex = Math.max(0, STEPS.findIndex((step) => step.key === stage));
  const note = String(runtime.pipeline_note ?? runtime.last_reason ?? "Watching prices, news and open positions");
  const lastAction = String(runtime.last_action ?? "");

  return (
    <section className="live-pipeline" aria-label="Live agent pipeline">
      <div className="pipeline-steps">
        {STEPS.map((step, index) => (
          <div
            className={`pipeline-step ${index === activeIndex ? "is-active" : ""} ${index < activeIndex ? "is-done" : ""}`}
            key={step.key}
          >
            <i aria-hidden="true" />
            <span><b>{step.label}</b><small>{step.detail}</small></span>
          </div>
        ))}
      </div>
      <div className="pipeline-now">
        <span><i aria-hidden="true" />Now</span>
        <strong>{note}</strong>
        {lastAction && <em className={`pipeline-outcome pipeline-outcome--${lastAction.toLowerCase()}`}>{lastAction}</em>}
      </div>
    </section>
  );
}
