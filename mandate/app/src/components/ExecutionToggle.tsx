export type ExecutionMode = "approval" | "auto_paper";

interface ExecutionToggleProps {
  mode: ExecutionMode;
  busy: boolean;
  disabled: boolean;
  onToggle: () => void;
}

export function ExecutionToggle({ mode, busy, disabled, onToggle }: ExecutionToggleProps) {
  const auto = mode === "auto_paper";
  const label = busy ? "Switching" : auto ? "Mode: auto paper" : "Mode: approval";
  return (
    <button
      className={`execution-toggle execution-toggle--${auto ? "auto" : "approval"}`}
      onClick={onToggle}
      disabled={disabled || busy}
      aria-pressed={auto}
      title={auto
        ? "Automatic paper submission is enabled. Click to require approval before every order."
        : "Every order waits for your approval. Click to enable automatic paper submission."}
    >
      <span aria-hidden="true" />
      {label}
    </button>
  );
}

export function readExecutionMode(trajectory: Record<string, unknown>): ExecutionMode {
  return String(trajectory.execution_mode ?? "approval") === "auto_paper"
    ? "auto_paper"
    : "approval";
}
