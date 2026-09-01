interface DegradedNoticeProps {
  reasons: string[];
  offlineServices: string[];
}

export function DegradedNotice({ reasons, offlineServices }: DegradedNoticeProps) {
  return (
    <section className="degraded-notice" role="alert" aria-live="assertive">
      <div className="degraded-heading">
        <b>Degraded — read only</b>
        <span>Live broker values are withheld, not stale</span>
      </div>
      <p>
        The Alpaca paper broker is not answering, so equity, exposure and buying power cannot be verified.
        The journal below is read from the durable local record and is still accurate;
        every value that would come from the broker shows a dash instead of its last
        known figure.
      </p>
      {(reasons.length > 0 || offlineServices.length > 0) && (
        <dl className="degraded-facts">
          {offlineServices.length > 0 && (
            <div>
              <dt>Offline</dt>
              <dd>{offlineServices.join(", ")}</dd>
            </div>
          )}
          {reasons.map((reason) => (
            <div key={reason}>
              <dt>Reason</dt>
              <dd>{reason}</dd>
            </div>
          ))}
        </dl>
      )}
      <p className="degraded-consequence">
        Approvals stay disabled while the broker is down. An order cannot be submitted
        without current paper-account state.
      </p>
    </section>
  );
}
