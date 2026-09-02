import { isoDate, timestamp } from "../../../lib/format";
import { Icon } from "../../../components/Icon";
import { decisionSummary } from "./decisionTerms";
import { ApprovalControl } from "./ApprovalControl";

export interface ApprovalAction {
  busy: boolean;
  outcome?: "approved" | "denied";
  error?: string;
}

interface DecisionCardProps {
  item: Record<string, unknown>;
  action: ApprovalAction | undefined;
  live: boolean;
  index: number;
  onRespond: (item: Record<string, unknown>, approve: boolean) => void;
}

export function DecisionCard({
  item,
  action,
  live,
  index,
  onRespond,
}: DecisionCardProps) {
  const args = (item.arguments && typeof item.arguments === "object"
    ? item.arguments
    : {}) as Record<string, unknown>;
  const toolName = String(item.tool_name ?? "tool");
  const safetyChecks = Array.isArray(args.safety_checks)
    ? args.safety_checks.map(String).slice(0, 6)
    : [];
  return (
    <article
      className={`decision-card${action?.outcome ? " decided" : ""}`}
      style={{ "--card-index": index } as React.CSSProperties}
    >
      <div className="decision-actions">
        <ApprovalControl
          action={action}
          live={live}
          onRespond={(approve) => onRespond(item, approve)}
        />
        {action?.error ? <p className="decision-error" role="alert">{action.error}</p> : null}
      </div>

      <div className="decision-main">
        <div className="decision-topline">
          <b>{decisionSummary(toolName, args)}</b>
          <time dateTime={isoDate(item.created_at)}>{timestamp(item.created_at)}</time>
        </div>

        {safetyChecks.length > 0 && (
          <div className="safety-rail" aria-label="Safety checks passed">
            {safetyChecks.map((check, checkIndex) => (
              <span key={check} className={checkIndex === safetyChecks.length - 1 ? "human-gate" : ""}>
                <Icon name={checkIndex === safetyChecks.length - 1 ? "blocked" : "check"} />
                {check}
              </span>
            ))}
          </div>
        )}

        {args.rationale ? (
          <p className="decision-rationale">{String(args.rationale)}</p>
        ) : null}

        <div className="decision-meta">
          <span>{String(item.session_title ?? "") || String(item.session_id ?? "")}</span>
          {args.intent_id ? <span>intent {String(args.intent_id)}</span> : null}
        </div>

        <details className="decision-audit">
          <summary>Memory change payload</summary>
          <pre>{JSON.stringify({ tool: toolName, arguments: item.arguments ?? {} }, null, 2)}</pre>
        </details>
      </div>

    </article>
  );
}
