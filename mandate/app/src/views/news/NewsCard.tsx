import { Icon } from "../../components/Icon";
import { timestamp } from "../../lib/format";
import { decodeEntities } from "./decodeEntities";

interface NewsCardProps {
  item: Record<string, unknown>;
  featured?: boolean;
}

export function NewsCard({ item, featured = false }: NewsCardProps) {
  const symbols = Array.isArray(item.symbols) ? item.symbols.map(String) : [];
  const url = typeof item.url === "string" ? item.url : "";

  return (
    <article className={`news-card${featured ? " news-card--featured" : ""}`}>
      <div className="news-meta">
        <span>{String(item.source ?? "news")}</span>
        <time dateTime={String(item.published_at ?? "")}>
          {timestamp(item.published_at)}
        </time>
        <div>
          {symbols.map((symbol) => (
            <b key={symbol}>{symbol}</b>
          ))}
        </div>
      </div>
      <div className="news-copy">
        <h3>{decodeEntities(item.headline ?? "Untitled market update")}</h3>
        {item.summary ? <p>{decodeEntities(item.summary)}</p> : null}
      </div>
      {url ? (
        <a href={url} target="_blank" rel="noreferrer">
          Read full article <Icon name="external" />
        </a>
      ) : null}
    </article>
  );
}
