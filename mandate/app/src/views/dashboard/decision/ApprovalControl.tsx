import { Icon } from "../../../components/Icon";
import type { ApprovalAction } from "./DecisionCard";

interface ApprovalControlProps {
  action: ApprovalAction | undefined;
  live: boolean;
  isOrder: boolean;
  onRespond: (approve: boolean) => void;
}

export function ApprovalControl({ action, live, isOrder, onRespond }: ApprovalControlProps) {
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
        Cannot be submitted while the paper broker is unreachable. The order stays queued.
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
          <small>{isOrder ? "Submits the paper order" : "Lets the agent proceed"}</small>
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
          <small>{isOrder ? "Agent replans" : "Agent stands down"}</small>
        </span>
      </button>
    </div>
  );
}
