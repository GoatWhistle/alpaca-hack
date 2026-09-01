import type { ReactNode } from "react";

interface PanelProps {
  title: string;
  count?: ReactNode;
  actions?: ReactNode;
  className?: string;
  children: ReactNode;
}

export function Panel({ title, count, actions, className, children }: PanelProps) {
  return (
    <article className={className ? `panel ${className}` : "panel"}>
      <div className="panel-heading">
        <div>
          <h2>{title}</h2>
        </div>
        {actions ?? (count !== undefined ? <span className="count">{count}</span> : null)}
      </div>
      {children}
    </article>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="empty">
      <span aria-hidden="true">○</span>
      <p>{children}</p>
    </div>
  );
}
