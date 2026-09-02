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
