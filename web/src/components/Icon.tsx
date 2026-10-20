const PATHS: Record<string, string> = {
  search: "M11 19a8 8 0 1 1 0-16 8 8 0 0 1 0 16Zm10 2-4.35-4.35",
  external: "M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5",
  copy: "M9 9h10v10H9zM5 15H4V4h11v1",
  stop: "M7 7h10v10H7z",
  play: "M8 5v14l11-7z",
  restart: "M4 12a8 8 0 0 1 13.7-5.7L20 8M20 4v4h-4M20 12a8 8 0 0 1-13.7 5.7L4 16M4 20v-4h4",
  more: "M5 12h.01M12 12h.01M19 12h.01",
  close: "M6 6l12 12M18 6 6 18",
  pin: "M9 4h6l-1 6 4 4H6l4-4zM12 14v6",
  eye: "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Zm10 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z",
  bell: "M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10 21h4",
  folder: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
  code: "m8 8-4 4 4 4M16 8l4 4-4 4M14 4l-4 16",
  terminal: "m4 17 6-5-6-5M12 19h8",
  plus: "M12 5v14M5 12h14",
  globe: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18",
  lock: "M6 11h12v9H6zM8 11V8a4 4 0 0 1 8 0v3",
  bolt: "M13 2 4 14h7l-1 8 9-12h-7z",
  layers: "m12 3 9 5-9 5-9-5zM3 13l9 5 9-5",
  activity: "M3 12h4l3-8 4 16 3-8h4",
  grid: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
  list: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
  sun: "M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10ZM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4",
  moon: "M21 13A9 9 0 1 1 11 3a7 7 0 0 0 10 10Z",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z",
  warn: "M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z",
  check: "m5 12 5 5L20 7",
  chevron: "m9 6 6 6-6 6",
  down: "m6 9 6 6 6-6",
  tree: "M6 3v12M6 9h8a4 4 0 0 1 4 4v2M6 15a3 3 0 1 0 0 6 3 3 0 0 0 0-6ZM18 15a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z",
  edit: "M4 20h4L19 9l-4-4L4 16zM14 6l4 4",
  trash: "M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3",
  radar: "M12 12 19 5M12 21a9 9 0 1 1 9-9M12 17a5 5 0 1 1 5-5",
  sparkle: "M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6",
  network: "M12 3v6M5 21v-4a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v4M12 15V9M9 3h6v6H9zM2 21h6M16 21h6",
  docker: "M3 12h18c0 5-4 8-9 8s-8-3-9-8ZM6 9h3v3H6zM9 9h3v3H9zM12 9h3v3h-3zM9 6h3v3H9zM12 6h3v3h-3z",
  note: "M5 4h10l4 4v12H5zM14 4v5h5M8 13h8M8 17h5",
  keyboard: "M3 6h18v12H3zM7 10h.01M11 10h.01M15 10h.01M7 14h10",
  refresh: "M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7",
};

export function Icon({ name, size = 16, className = "", stroke = 1.8 }: { name: keyof typeof PATHS | string; size?: number; className?: string; stroke?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={stroke}
      strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
      <path d={PATHS[name] || PATHS.more} />
    </svg>
  );
}
