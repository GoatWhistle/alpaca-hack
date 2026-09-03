const STEPS = [
  {
    key: "monitoring",
    label: "Monitor",
    detail: "prices · news",
    description:
      "Reads Alpaca snapshots, the news gate and every open position on each poll. Everything downstream consumes this tape.",
  },
  {
    key: "risk_exit",
    label: "Risk exit",
    detail: "stops · targets",
    description:
      "Deterministic pass over open positions — stops, targets and expiry are enforced before any new idea is considered.",
  },
  {
    key: "signals",
    label: "Signals",
    detail: "ensemble · ATR",
    description:
      "The ensemble scores momentum, reversion, breakout and news-confirmed moves; ATR sets the volatility frame.",
  },
  {
    key: "hypothesis",
    label: "Hypothesis",
    detail: "main trader focus",
    description:
      "The main trader narrows the ensemble output to one focus candidate and writes a bounded, testable thesis.",
  },
  {
    key: "challenge",
    label: "Challenge",
    detail: "agent critic",
    description:
      "An agent critic attacks the thesis from risk, market and execution angles. Advisory only — deterministic gates stay authoritative.",
  },
  {
    key: "broker",
    label: "Broker",
    detail: "account · capacity",
    description:
      "Account state, buying power and position capacity are checked against the mandate before anything is sized.",
  },
  {
    key: "execution",
    label: "Order",
    detail: "paper broker",
    description:
      "The sized order goes to the paper broker and is tracked to fill. Real money is never moved.",
  },
] as const;

export function LivePipeline({ runtime }: { runtime: Record<string, unknown> }) {
  const stage = String(runtime.pipeline_stage ?? (runtime.status === "analyzing" ? "signals" : "monitoring"));
  const activeIndex = Math.max(0, STEPS.findIndex((step) => step.key === stage));
  const note = String(runtime.pipeline_note ?? runtime.last_reason ?? "Watching prices, news and open positions");
  const lastAction = String(runtime.last_action ?? "");

  return (
    <section className="live-pipeline" aria-label="Live agent pipeline">
      <ol className="pipeline-steps">
        {STEPS.map((step, index) => {
          const state = index === activeIndex ? "is-active" : index < activeIndex ? "is-done" : "is-pending";
          const stateLine = state === "is-active"
            ? "Working now"
            : state === "is-done"
              ? "Passed this cycle"
              : "Waiting";
          return (
            <li
              className={`pipeline-step ${state}`}
              key={step.key}
              tabIndex={0}
              aria-label={`${step.label} — ${step.description} ${stateLine}.`}
            >
              <span className="pipeline-node" aria-hidden="true" />
              <b>{step.label}</b>
              <small>{step.detail}</small>
              <span className="pipeline-tip" role="tooltip" aria-hidden="true">
                <b>{step.label} · {step.detail}</b>
                {step.description}
                <i>{stateLine}</i>
              </span>
            </li>
          );
        })}
      </ol>
      <div className="pipeline-now">
        <span><i aria-hidden="true" />Now</span>
        <strong>{note}</strong>
        {lastAction && <em className={`pipeline-outcome pipeline-outcome--${lastAction.toLowerCase()}`}>{lastAction}</em>}
      </div>
    </section>
  );
}
