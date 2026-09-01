export type IconName = "refresh" | "external" | "pulse" | "settings" | "close" | "check" | "blocked";

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
};

export function Icon({ name }: { name: IconName }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      {paths[name]}
    </svg>
  );
}
