import { useEffect } from "react";
import { Icon } from "../../../components/Icon";
import { DecisionQueue } from "./DecisionQueue";
import type { ApprovalAction } from "./DecisionCard";

interface ApprovalModalProps {
  open: boolean;
  items: Record<string, unknown>[];
  actions: Record<string, ApprovalAction>;
  live: boolean;
  hidden: boolean;
  onClose: () => void;
  onRespond: (item: Record<string, unknown>, approve: boolean) => void;
}

export function ApprovalModal({
  open,
  items,
  actions,
  live,
  hidden,
  onClose,
  onRespond,
}: ApprovalModalProps) {
  useEffect(() => {
    if (!open) return undefined;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose, open]);

  if (!open || items.length === 0) return null;

  return (
    <div className="mandate-chrome approval-modal-backdrop" onMouseDown={onClose}>
      <section
        className="approval-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="approval-modal-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header>
          <div>
            <span>Operator action required</span>
            <h2 id="approval-modal-title">Review memory change</h2>
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close approval">
            <Icon name="close" />
          </button>
        </header>
        <DecisionQueue
          items={items}
          actions={actions}
          live={live}
          hidden={hidden}
          onRespond={onRespond}
        />
      </section>
    </div>
  );
}
