const paths = {
  brand: "M5 16 8 5l10 3 1 10-9 2Z M5 16l13-8 M8 5l2 15",
  plus: "M12 5v14 M5 12h14",
  close: "m6 6 12 12 M6 18 18 6",
  down: "m7 10 5 5 5-5",
  right: "m9 5 7 7-7 7",
  arrow: "M5 12h14 m-5-5 5 5-5 5",
  external: "M14 4h6v6 M20 4 10 14 M10 4H5a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-5",
  check: "m5 12 4 4L19 6",
  model: "m12 3 9 5-9 5-9-5 9-5Z M3 12l9 5 9-5 M3 16l9 5 9-5",
  code: "m8 6-6 6 6 6 M16 6l6 6-6 6 M14 3l-4 18",
  chart: "M4 4v16h17 M8 15l4-5 4 2 5-7",
  settings: "M4 7h9 M17 7h3 M4 17h3 M11 17h9 M13 4v6 M7 14v6",
  play: "m9 5 11 7-11 7V5Z",
  download: "M12 3v12 m-5-5 5 5 5-5 M4 16v4h16v-4",
  book: "M12 5v15 M12 5C9 3 5 3 2 5v14c3-2 7-2 10 1 3-3 7-3 10-1V5c-3-2-7-2-10 0Z",
  history: "M3 11a9 9 0 1 1 2 7 M3 4v7h7 M12 7v5l3 2",
  attach: "m8 13 7-7a3 3 0 0 1 4 4l-9 9a5 5 0 0 1-7-7l9-9 M7 15l8-8",
  copy: "M8 8h12v12H8Z M4 16V4h12",
  more: "M5 12h.01 M12 12h.01 M19 12h.01",
  factory: "M3 21V10l6 3V9l6 3V3h4l2 18H3Z M7 17h1 M12 17h1 M17 17h1",
  projects: "M8 7V4h8v3 M3 7h18v14H3Z M3 12l9 3 9-3 M12 12v5",
  leaf: "M4 20 15 9 M5 17C-1 8 9 3 21 3c0 12-5 22-14 16 M8 13l5 1-1-5",
} as const;

export function Icon({ name, size = 18 }: { name: keyof typeof paths; size?: number }) {
  return <svg className="icon" width={size} height={size} viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth={name === "more" ? 3.5 : 1.7} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d={paths[name]} />
  </svg>;
}
