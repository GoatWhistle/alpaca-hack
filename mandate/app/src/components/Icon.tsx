export type IconName =
  | "refresh"
  | "external"
  | "pulse"
  | "settings"
  | "close"
  | "check"
  | "blocked"
  | "grid"
  | "ledger"
  | "spark"
  | "news"
  | "gauge"
  | "network"
  | "chat";

const paths: Record<IconName, React.ReactNode> = {
  refresh: <path d="M20 12a8 8 0 1 1-2.3-5.7L20 8M20 4v4h-4" />,
  external: <path d="M14 4h6v6M20 4l-9 9M18 13v6H5V6h6" />,
  pulse: <path d="M3 12h4l2-6 4 12 2-6h6" />,
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1a1.7 1.7 0 0 0 1.9.3A1.7 1.7 0 0 0 10 3V2.8h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9A1.7 1.7 0 0 0 21 10h.2v4H21a1.7 1.7 0 0 0-1.6 1Z" />
    </>
  ),
  close: <path d="m6 6 12 12M18 6 6 18" />,
  check: <path d="m5 13 4.5 4.5L19 7" />,
  blocked: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="m6 18 12-12" />
    </>
  ),
  grid: (
    <>
      <rect x="4" y="4" width="7" height="7" />
      <rect x="13" y="4" width="7" height="7" />
      <rect x="4" y="13" width="7" height="7" />
      <rect x="13" y="13" width="7" height="7" />
    </>
  ),
  ledger: (
    <>
      <path d="M7 3h10a1 1 0 0 1 1 1v17l-3-2-3 2-3-2-3 2V4a1 1 0 0 1 1-1Z" />
      <path d="M9 8h6M9 12h6" />
    </>
  ),
  spark: <path d="M12 3l2 5 5 2-5 2-2 5-2-5-5-2 5-2 2-5ZM19 16.5l.9 2.1 2.1.9-2.1.9-.9 2.1-.9-2.1-2.1-.9 2.1-.9.9-2.1Z" />,
  news: (
    <>
      <path d="M16.5 4H4v14a2 2 0 0 0 2 2h12.5a1.5 1.5 0 0 0 1.5-1.5V5.5A1.5 1.5 0 0 0 18.5 4Z" />
      <path d="M4 16h14" />
      <path d="M7 8h7M7 12h4" />
    </>
  ),
  gauge: (
    <>
      <path d="M4 15a8 8 0 1 1 16 0" />
      <path d="M12 15l4.5-4.5" />
      <circle cx="12" cy="15" r="1.2" />
    </>
  ),
  network: (
    <>
      <circle cx="5" cy="6" r="2" />
      <circle cx="19" cy="6" r="2" />
      <circle cx="12" cy="18" r="2" />
      <path d="M7 7l4 9M17 7l-4 9M7 6h10" />
    </>
  ),
  chat: (
    <>
      <path d="M4 6h16v11H9l-5 4V6Z" />
      <path d="M8 10h8M8 13h5" />
    </>
  ),
};

export function Icon({ name }: { name: IconName }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      {paths[name]}
    </svg>
  );
}
