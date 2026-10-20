import type { Listener } from "./api";

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

export function duration(sec: number | null | undefined) {
  if (sec == null) return "—";
  if (sec < 60) return `${Math.floor(sec)}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m`;
  if (sec < 86400) {
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
    return m ? `${h}h ${m}m` : `${h}h`;
  }
  const d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600);
  return h ? `${d}d ${h}h` : `${d}d`;
}

export function ago(ts: number | null | undefined, now = Date.now() / 1000) {
  if (!ts) return "";
  const s = Math.max(0, now - ts);
  if (s < 5) return "just now";
  return `${duration(s)} ago`;
}

export function clock(ts: number) {
  return new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function mb(v: number | null | undefined) {
  if (v == null) return "—";
  return v >= 1024 ? `${(v / 1024).toFixed(1)} GB` : `${Math.round(v)} MB`;
}

export function shortPath(p: string | null | undefined, home?: string) {
  if (!p) return "";
  return home && p.startsWith(home) ? "~" + p.slice(home.length) : p;
}

export function url(l: Listener) {
  return `http://localhost:${l.port}/`;
}

export function isHttp(l: Listener) {
  return !!l.probe?.ok;
}

export type Health = "up" | "warn" | "down" | "none" | "unknown";

export function health(l: Listener): Health {
  const p = l.probe;
  if (!p) return l.kind === "database" ? "none" : "unknown";
  if (!p.ok) return p.error === "not HTTP" ? "none" : "down";
  if (!p.status) return "unknown";
  if (p.status < 400) return "up";
  if (p.status < 500) return "warn";
  return "down";
}

export const KIND_LABEL: Record<string, string> = {
  dev: "Dev server", service: "Service", database: "Database", app: "Desktop app", system: "System", tool: "Harbor", other: "Other",
};

const PALETTE = ["#2dd4bf", "#60a5fa", "#a78bfa", "#f472b6", "#fbbf24", "#34d399", "#fb923c", "#22d3ee", "#c084fc", "#f87171"];

export function colorFor(key: string) {
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) >>> 0;
  return PALETTE[h % PALETTE.length];
}

export async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

export function matches(l: Listener, q: string) {
  if (!q) return true;
  const hay = [l.port, l.pid, l.title, l.display, l.cwd, l.project?.name, l.project?.repo, l.framework?.label, l.kind,
    l.meta.note, l.meta.label, l.probe?.title, l.appBundle, l.docker?.name, l.hint].join(" ").toLowerCase();
  return q.toLowerCase().split(/\s+/).every((w) => {
    if (/^:\d+$/.test(w)) return String(l.port).startsWith(w.slice(1));
    return hay.includes(w);
  });
}
