import { Icon } from "../../../components/Icon";
import type { ApprovalAction } from "./DecisionCard";

interface ApprovalControlProps {
  action: ApprovalAction | undefined;
  live: boolean;
  onRespond: (approve: boolean) => void;
}

export function ApprovalControl({ action, live, onRespond }: ApprovalControlProps) {
  if (action?.outcome) {
    return (
      <p className={`approval-outcome approval-outcome--${action.outcome}`} role="status">
        <Icon name={action.outcome === "approved" ? "check" : "close"} />
        {action.outcome === "approved" ? "Approved by you" : "Denied by you"}
      </p>
    );
  }

  if (!live) {
    return (
      <p className="approval-blocked">
        <Icon name="blocked" />
        The approval channel is unavailable while the local control plane is degraded.
      </p>
    );
  }

  return (
    <div className="approval-control">
      <button
        type="button"
        className="approval-button approval-button--approve"
        onClick={() => onRespond(true)}
        disabled={action?.busy}
      >
        <span className="approval-button-mark" aria-hidden="true"><Icon name="check" /></span>
        <span className="approval-button-text">
          <b>Approve</b>
          <small>Applies the memory change</small>
        </span>
      </button>

      <button
        type="button"
        className="approval-button approval-button--deny"
        onClick={() => onRespond(false)}
        disabled={action?.busy}
      >
        <span className="approval-button-mark" aria-hidden="true"><Icon name="close" /></span>
        <span className="approval-button-text">
          <b>Deny</b>
          <small>Keeps current memory</small>
        </span>
      </button>
    </div>
  );
}
