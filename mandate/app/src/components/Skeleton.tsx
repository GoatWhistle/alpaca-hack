export function SkeletonTimeline({ rows = 4 }: { rows?: number }) {
  return (
    <div className="timeline" aria-busy="true" aria-label="Loading agent decisions">
      {Array.from({ length: rows }, (_, index) => (
        <div className="skeleton-row" key={index}>
          <span className="skeleton-marker" />
          <div>
            <span className="skeleton-line skeleton-line--title" />
            <span className="skeleton-line skeleton-line--body" />
            <span className="skeleton-line skeleton-line--short" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function SkeletonRows({ rows = 3 }: { rows?: number }) {
  return (
    <div className="skeleton-rows" aria-busy="true">
      {Array.from({ length: rows }, (_, index) => (
        <div key={index}>
          <span className="skeleton-line skeleton-line--short" />
          <span className="skeleton-line skeleton-line--body" />
        </div>
      ))}
    </div>
  );
}
