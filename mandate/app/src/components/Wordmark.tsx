export function Wordmark() {
  return (
    <div className="wordmark">
      <span className="wordmark-mark" aria-hidden="true">
        <svg viewBox="0 0 32 32">
          <path d="M10 8 H6.5 V24 H10" stroke="var(--accent)" />
          <path d="M22 8 H25.5 V24 H22" stroke="var(--accent)" />
          <circle cx="16" cy="16" r="4.5" fill="var(--ink)" stroke="none" />
        </svg>
      </span>
      <b>MANDATE</b>
    </div>
  );
}
