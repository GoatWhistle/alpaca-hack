import { Empty } from "../../components/Panel";
import { NewsCard } from "./NewsCard";

export function NewsView({ items }: { items: Record<string, unknown>[] }) {
  return (
    <div className="mandate-chrome news-view">
      <main id="main-content" tabIndex={-1}>
        <section className="news-page-heading">
          <div>
            <h1>News</h1>
          </div>
          <span>{items.length} unique stories</span>
        </section>

        {items.length ? (
          <section className="news-stream">
            {items.map((item, index) => (
              <NewsCard
                key={`${String(item.source)}:${String(item.external_id ?? item.url)}:${index}`}
                item={item}
                featured={index === 0}
              />
            ))}
          </section>
        ) : (
          <Empty>
            No news has been received yet. The runner subscribes to Alpaca, SEC EDGAR and
            attributable issuer feeds, and files every headline here as untrusted data.
          </Empty>
        )}
      </main>
    </div>
  );
}
