import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { Listener, Snapshot } from "../api";
import type { Actions } from "../actions";
import { useLocal } from "../usePorthaven";
import { ago, colorFor, cx, duration, health, matches, mb, shortPath, type Health } from "../util";
import { Icon } from "./Icon";
import { PortMap } from "./PortMap";
import { Badge, Dot, IconButton, Menu, Sparkline, type MenuItem } from "./ui";

export type Filter = "all" | "dev" | "databases" | "web" | "network" | "pinned" | "idle" | "system";
type Group = "project" | "kind" | "none";
type SortKey = "port" | "name" | "http" | "uptime" | "cpu" | "mem";
type Sort = { key: SortKey; dir: 1 | -1 };

const FILTERS: { id: Filter; label: string; icon: string }[] = [
  { id: "all", label: "Mine", icon: "layers" },
  { id: "web", label: "Web", icon: "globe" },
  { id: "dev", label: "Dev servers", icon: "code" },
  { id: "databases", label: "Databases", icon: "grid" },
  { id: "network", label: "On network", icon: "network" },
  { id: "pinned", label: "Pinned", icon: "pin" },
  { id: "idle", label: "Idle", icon: "moon" },
  { id: "system", label: "System & apps", icon: "settings" },
];

function pass(l: Listener, f: Filter) {
  const sys = l.kind === "system" || l.kind === "app";
  switch (f) {
    case "all": return !sys;
    case "dev": return l.kind === "dev" || l.kind === "tool";
    case "databases": return l.kind === "database";
    case "web": return !sys && !!l.probe?.ok && !!l.probe.status;
    case "network": return l.exposure === "network";
    case "pinned": return !!l.meta.pinned;
    case "idle": return !!l.idleFor;
    case "system": return sys;
  }
}

// a search from "Mine" also looks through system services and desktop apps
const visible = (l: Listener, query: string, filter: Filter) => matches(l, query) && (pass(l, filter) || (!!query && filter === "all"));

const HEALTH_TONE: Record<Health, "ok" | "warn" | "bad" | "muted" | "info"> = { up: "ok", warn: "warn", down: "bad", none: "muted", unknown: "muted" };
const HEALTH_TEXT: Record<Health, string> = { up: "answering", warn: "answering with an error", down: "not answering", none: "not HTTP", unknown: "not checked yet" };

// Sorting: a value per column (null sorts last either way) and the direction a first click uses.
const SORT_VALUE: Record<SortKey, (l: Listener) => number | string | null> = {
  port: (l) => l.port,
  name: (l) => l.title.toLowerCase(),
  // slowest (and broken) first when descending; ports that do not speak HTTP go last
  http: (l) => (l.probe?.ok && l.probe.status ? (l.probe.status >= 500 ? 1e9 : l.probe.ms ?? 0) : l.probe && !l.probe.ok && l.probe.error !== "not HTTP" ? 2e9 : null),
  uptime: (l) => l.uptime,
  cpu: (l) => l.cpu,
  mem: (l) => l.memMb,
};
const FIRST_DIR: Record<SortKey, 1 | -1> = { port: 1, name: 1, http: -1, uptime: -1, cpu: -1, mem: -1 };

function compare(a: Listener, b: Listener, s: Sort) {
  const pin = Number(!!b.meta.pinned) - Number(!!a.meta.pinned);
  if (pin) return pin;
  const va = SORT_VALUE[s.key](a), vb = SORT_VALUE[s.key](b);
  if (va == null || vb == null) return va == null && vb == null ? a.port - b.port : va == null ? 1 : -1;
  const c = typeof va === "string" ? va.localeCompare(vb as string) : va - (vb as number);
  return c * s.dir || a.port - b.port;
}

// One template for the header, rows and ghost rows: port · what · http · up · cpu · memory · actions
// below ~900px of table width the CPU sparkline and memory bar give way, so the table never needs a sideways scroll
const COLS = "grid-cols-[92px_minmax(240px,1fr)_104px_64px_118px_136px_100px] @max-4xl:grid-cols-[84px_minmax(180px,1fr)_92px_52px_52px_64px_96px] @max-4xl:gap-2";
const GHOST_MS = 10_000;

type Ghost = { l: Listener; at: number };
type Item = { l: Listener; ghost?: Ghost };
type GroupT = { key: string; label: string; sub: string; root: string | null; items: Item[] };

export function PortsView({ snap, query, actions, selected, onSelect, flash }: {
  snap: Snapshot; query: string; actions: Actions; selected: string | null; onSelect: (id: string | null) => void; flash: Set<string>;
}) {
  const [filter, setFilter] = useLocal<Filter>("porthaven.filter", "all");
  const [group, setGroup] = useLocal<Group>("porthaven.group", "project");
  const [dense, setDense] = useLocal("porthaven.dense", false);
  const [sort, setSort] = useLocal<Sort>("porthaven.sort", { key: "port", dir: 1 });
  const [showMap, setShowMap] = useLocal("porthaven.map", true);
  const [collapsed, setCollapsed] = useLocal<string[]>("porthaven.collapsed", []);
  const [cursor, setCursor] = useState(0);
  const [hoverPort, setHoverPort] = useState<number | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const toggle = (id: string) => setPicked((p) => { const n = new Set(p); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const listRef = useRef<HTMLDivElement>(null);

  // Rows that just appeared slide in; rows that went away stay a few seconds as "stopped", with Restart.
  const seen = useRef<Set<string> | null>(null);
  const fresh = useMemo(() => {
    const before = seen.current, f = new Set<string>();
    if (before) for (const l of snap.listeners) if (!before.has(l.id)) f.add(l.id);
    seen.current = new Set(snap.listeners.map((l) => l.id));
    return f;
  }, [snap.listeners]);
  const [ghosts, setGhosts] = useState<Map<string, Ghost>>(new Map());
  const prev = useRef<Listener[] | null>(null);
  useEffect(() => {
    const before = prev.current;
    prev.current = snap.listeners;
    const live = new Set(snap.listeners.map((l) => l.id)), livePorts = new Set(snap.listeners.map((l) => l.port));
    setGhosts((g) => {
      const n = new Map([...g].filter(([, v]) => !livePorts.has(v.l.port)));   // back on its port: no ghost
      for (const l of before || []) if (!live.has(l.id) && !livePorts.has(l.port) && l.risk !== "self") n.set(l.id, { l, at: Date.now() });
      return n.size === g.size && [...n.keys()].every((k) => g.has(k)) ? g : n;
    });
  }, [snap.listeners]);
  useEffect(() => {
    if (!ghosts.size) return;
    const t = window.setInterval(() => setGhosts((g) => new Map([...g].filter(([, v]) => Date.now() - v.at < GHOST_MS))), 500);
    return () => window.clearInterval(t);
  }, [ghosts.size]);
  const dismiss = (id: string) => setGhosts((g) => { const n = new Map(g); n.delete(id); return n; });

  const counts = useMemo(() => Object.fromEntries(FILTERS.map((f) => [f.id, snap.listeners.filter((l) => pass(l, f.id)).length])), [snap.listeners]);
  const rows = useMemo(() => snap.listeners.filter((l) => visible(l, query, filter)).sort((a, b) => compare(a, b, sort)), [snap.listeners, query, filter, sort]);
  const items = useMemo<Item[]>(() => [...rows.map((l) => ({ l })),
    ...[...ghosts.values()].filter((g) => visible(g.l, query, filter)).map((g) => ({ l: g.l, ghost: g }))].sort((a, b) => compare(a.l, b.l, sort)),
  [rows, ghosts, query, filter, sort]);

  const groups = useMemo(() => {
    if (group === "none") return [{ key: "all", label: "", sub: "", root: null, items }] as GroupT[];
    const m = new Map<string, GroupT>();
    for (const it of items) {
      const l = it.l;
      let key: string, label: string, sub = "", root: string | null = null;
      if (l.meta.pinned) { key = "~pinned"; label = "Pinned"; }
      else if (group === "project") {
        if (l.project) {
          key = l.project.root; root = l.project.root; sub = shortPath(l.project.root, snap.me.home);
          label = l.project.repo && l.project.repo !== l.project.name ? `${l.project.repo} › ${l.project.name}` : l.project.name;
        }
        else if (l.docker) { key = "~docker"; label = "Docker"; }
        else { key = `~${l.kind}`; label = { database: "Databases", app: "Desktop apps", system: "System services", service: "Services", tool: "Porthaven", dev: "Other dev servers", other: "Other" }[l.kind]; }
      } else {
        key = l.kind; label = { dev: "Dev servers", service: "Services", database: "Databases", app: "Desktop apps", system: "System services", tool: "Porthaven", other: "Other" }[l.kind];
      }
      if (!m.has(key)) m.set(key, { key, label, sub, root, items: [] });
      m.get(key)!.items.push(it);
    }
    return [...m.values()].sort((a, b) => (a.key === "~pinned" ? -1 : b.key === "~pinned" ? 1 : 0) || Number(a.key.startsWith("~")) - Number(b.key.startsWith("~")) || a.label.localeCompare(b.label));
  }, [items, group, snap.me.home]);

  // keyboard order: live rows only, in the order they are drawn
  const flat = useMemo(() => groups.flatMap((g) => (collapsed.includes(g.key) ? [] : g.items.filter((it) => !it.ghost).map((it) => it.l))), [groups, collapsed]);

  // keyboard: j/k move, Enter opens, o browser, c copy, x stop, p pin
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.closest("input,textarea,select,[role=dialog]") || e.metaKey || e.ctrlKey || e.altKey) return;
      if ((e.key === "Enter" || e.key === " ") && t.closest("button,a")) return;   // let the focused control have its own key
      const cur = flat[Math.min(cursor, flat.length - 1)];
      if (e.key === "j" || e.key === "ArrowDown") { setCursor((c) => Math.min(flat.length - 1, c + 1)); e.preventDefault(); }
      else if (e.key === "k" || e.key === "ArrowUp") { setCursor((c) => Math.max(0, c - 1)); e.preventDefault(); }
      else if (e.key === "Home") { setCursor(0); e.preventDefault(); }
      else if (e.key === "End") { setCursor(flat.length - 1); e.preventDefault(); }
      else if (!cur) return;
      else if (e.key === "Enter") onSelect(cur.id);
      else if (e.key === "o") actions.open(cur);
      else if (e.key === "c") void actions.copyUrl(cur);
      else if (e.key === "x") void actions.kill(cur, "process");
      else if (e.key === "X") void actions.kill(cur, "app");
      else if (e.key === "p") void actions.meta(cur, { pinned: !cur.meta.pinned });
      else if (e.key === "w") void actions.meta(cur, { watched: !cur.meta.watched });
      else if (e.key === " ") { e.preventDefault(); toggle(cur.id); }
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [flat, cursor, actions, onSelect]);

  // The cursor row keeps keyboard focus while focus is in the table, so screen readers follow j/k.
  useEffect(() => {
    const list = listRef.current, el = list?.querySelector<HTMLElement>(`[data-idx="${cursor}"]`);
    if (!list || !el) return;
    if (list.contains(document.activeElement) && document.activeElement !== el && document.activeElement?.getAttribute("role") === "row") el.focus({ preventScroll: true });
    el.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  const cpuMax = Math.max(5, ...rows.flatMap((r) => r.spark.cpu));
  const memMax = Math.max(64, ...rows.map((r) => r.memMb || 0));
  const pickedRows = snap.listeners.filter((l) => picked.has(l.id));
  useEffect(() => {
    const live = new Set(snap.listeners.map((l) => l.id));
    if ([...picked].some((id) => !live.has(id))) setPicked(new Set([...picked].filter((id) => live.has(id))));
  }, [snap.listeners, picked]);

  const sortBy = (key: SortKey) => setSort(sort.key === key ? { key, dir: sort.dir === 1 ? -1 : 1 } : { key, dir: FIRST_DIR[key] });
  const head = (key: SortKey | null, label: string, right = false) => {
    if (!key) return <span role="columnheader" className={right ? "text-right" : ""}>{label}</span>;
    const on = sort.key === key;
    return (
      <span role="columnheader" aria-sort={on ? (sort.dir === 1 ? "ascending" : "descending") : "none"} className={right ? "text-right" : ""}>
        <button type="button" onClick={() => sortBy(key)} title={`Sort by ${label.toLowerCase()}`}
          className={cx("inline-flex items-center gap-1 rounded uppercase tracking-wide transition hover:text-ink focus-visible:outline-2 focus-visible:outline-accent",
            on ? "text-ink-2" : "", right && "flex-row-reverse")}>
          {label}
          <Icon name="down" size={11} className={cx("transition", on ? "opacity-100" : "opacity-0", on && sort.dir === 1 && "rotate-180")} />
        </button>
      </span>
    );
  };
  let idx = -1;

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      <div className="flex flex-wrap items-center gap-2 pb-3">
        <div className="flex flex-wrap gap-1 rounded-xl border border-line bg-panel p-1" role="tablist" aria-label="Filter ports">
          {FILTERS.map((f) => (
            <button key={f.id} onClick={() => setFilter(f.id)} role="tab" aria-selected={filter === f.id}
              className={cx("inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition focus-visible:outline-2 focus-visible:outline-accent",
                filter === f.id ? "bg-accent-soft text-accent-ink" : "text-muted hover:text-ink")}>
              <Icon name={f.icon} size={13} />
              {f.label}
              <span className={cx("tnum rounded px-1 text-[10px]", filter === f.id ? "bg-accent/15" : "bg-panel-2")}>{counts[f.id]}</span>
            </button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-1 rounded-xl border border-line bg-panel p-1 text-xs">
          <span className="px-1.5 text-faint">Group</span>
          {(["project", "kind", "none"] as Group[]).map((g) => (
            <button key={g} onClick={() => setGroup(g)} aria-pressed={group === g}
              className={cx("rounded-lg px-2 py-1.5 font-medium capitalize transition focus-visible:outline-2 focus-visible:outline-accent", group === g ? "bg-panel-2 text-ink" : "text-muted hover:text-ink")}>{g === "kind" ? "type" : g}</button>
          ))}
          <span className="mx-1 h-4 border-l border-line" />
          <IconButton icon="radar" title={showMap ? "Hide the port map" : "Show the port map"} active={showMap} onClick={() => setShowMap(!showMap)} size={14} className="h-7 w-7" />
          <IconButton icon="list" title={dense ? "Comfortable rows" : "Compact rows"} active={dense} onClick={() => setDense(!dense)} size={14} className="h-7 w-7" />
        </div>
      </div>

      {showMap && <PortMap listeners={rows} all={snap.listeners} apps={query || !["all", "dev", "web"].includes(filter) ? [] : snap.apps}
        hoverPort={hoverPort} onHover={setHoverPort} selected={selected}
        onPick={(l) => { const i = flat.findIndex((x) => x.id === l.id); if (i >= 0) setCursor(i); onSelect(l.id); }} actions={actions} />}

      <div ref={listRef} className="card @container min-h-0 flex-1 overflow-auto" role="grid" aria-label="Listening ports">
        <div role="row" className={cx("sticky top-0 z-10 grid items-center gap-3 border-b border-line bg-panel/95 px-4 py-2 text-[11px] font-medium uppercase tracking-wide text-faint backdrop-blur", COLS)}>
          {head("port", "Port")}{head("name", "What")}{head("http", "HTTP")}{head("uptime", "Up")}{head("cpu", "CPU")}{head("mem", "Memory", true)}{head(null, "")}
        </div>
        {items.length === 0 && <Empty filter={filter} query={query} />}
        {groups.map((g) => {
          const open = !collapsed.includes(g.key);
          const live = g.items.filter((it) => !it.ghost).map((it) => it.l);
          const stoppable = live.filter((l) => l.risk !== "self" && l.risk !== "foreign");
          const mem = live.reduce((s, l) => s + (l.memMb || 0), 0);
          return (
            <section key={g.key} role="rowgroup" aria-label={g.label || undefined}>
              {group !== "none" && (
                <div role="row" className="group/h flex items-center gap-2 border-b border-line bg-panel-2/40 py-1 pl-4 pr-3">
                  <button type="button" aria-expanded={open} onClick={() => setCollapsed(open ? [...collapsed, g.key] : collapsed.filter((c) => c !== g.key))}
                    className="flex min-w-0 shrink-0 items-center gap-2 rounded text-left focus-visible:outline-2 focus-visible:outline-accent">
                    <Icon name="chevron" size={12} className={cx("text-faint transition", open && "rotate-90")} />
                    {!g.key.startsWith("~") && <span className="h-2.5 w-2.5 rounded-sm" style={{ background: colorFor(g.key) }} />}
                    <span className="text-xs font-semibold text-ink-2">{g.label}</span>
                    <span className="tnum text-[11px] text-faint">{live.length}</span>
                  </button>
                  {g.sub && <span className="min-w-0 truncate font-mono text-[11px] text-faint" title={g.root || undefined}>{g.sub}</span>}
                  <span className="ml-auto flex shrink-0 items-center gap-2">
                    <span className="flex items-center opacity-0 transition group-hover/h:opacity-100 focus-within:opacity-100">
                      {g.root && <IconButton icon="code" size={13} className="h-6 w-6" title={`Open ${g.label} in your editor`} onClick={() => void actions.reveal(g.root, "editor")} />}
                      {g.root && <IconButton icon="terminal" size={13} className="h-6 w-6" title={`Open a terminal in ${g.sub}`} onClick={() => void actions.reveal(g.root, "terminal")} />}
                      {stoppable.length > 0 && <IconButton icon="stop" danger size={13} className="h-6 w-6" title={`Stop all ${stoppable.length} in ${g.label}`}
                        onClick={() => void actions.killMany(stoppable, "app", `Stop everything in ${g.label}?`)} />}
                    </span>
                    {mem > 0 && live.length > 1 && <span className="tnum w-16 text-right text-[11px] text-faint" title={`${g.label} holds ${mb(mem)}`}>{mb(mem)}</span>}
                  </span>
                </div>
              )}
              {open && g.items.map((it) => {
                if (it.ghost) return <GhostRow key={`ghost-${it.l.id}`} g={it.ghost} dense={dense} onDismiss={() => dismiss(it.l.id)}
                  onRestart={() => { dismiss(it.l.id); void actions.restartFrom(it.l); }} />;
                const l = it.l;
                idx += 1;
                const i = idx;
                return <Row key={l.id} l={l} idx={i} active={i === cursor} selected={selected === l.id} dense={dense} cpuMax={cpuMax} memMax={memMax}
                  picked={picked.has(l.id)} onPick={() => toggle(l.id)} fresh={fresh.has(l.id)} hovered={hoverPort === l.port}
                  onHover={(on) => setHoverPort(on ? l.port : null)} showPath={group !== "project"}
                  flash={flash.has(l.id)} actions={actions} home={snap.me.home}
                  onFocus={() => setCursor(i)}
                  onClick={() => { setCursor(i); onSelect(selected === l.id ? null : l.id); }} />;
              })}
            </section>
          );
        })}
      </div>
      {pickedRows.length > 0 && (
        <div className="pop mt-3 flex items-center gap-3 rounded-xl border border-accent/30 bg-accent-soft px-4 py-2.5" role="region" aria-label="Selected ports">
          <span className="text-sm font-medium text-accent-ink">{pickedRows.length} selected</span>
          <span className="truncate text-xs text-muted">{pickedRows.map((l) => `:${l.port}`).join("  ")}</span>
          <div className="ml-auto flex gap-2">
            <button className="text-xs text-muted hover:text-ink" onClick={() => setPicked(new Set())}>Clear</button>
            <button className="rounded-lg border border-line-2 bg-panel px-3 py-1.5 text-xs font-medium text-ink-2 hover:text-ink"
              onClick={() => void actions.killMany(pickedRows, "process").then((ok) => ok && setPicked(new Set()))}>Stop processes</button>
            <button className="rounded-lg bg-bad/90 px-3 py-1.5 text-xs font-semibold text-white hover:bg-bad"
              onClick={() => void actions.killMany(pickedRows, "app").then((ok) => ok && setPicked(new Set()))}>Stop whole apps</button>
          </div>
        </div>
      )}
    </div>
  );
}

function Empty({ filter, query }: { filter: Filter; query: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-20 text-center">
      <div className="rounded-2xl bg-accent-soft p-3 text-accent"><Icon name="radar" size={26} /></div>
      <p className="text-sm font-medium text-ink">{query ? `Nothing matches “${query}”` : filter === "pinned" ? "Nothing pinned yet" : "Nothing here"}</p>
      <p className="max-w-sm text-xs text-muted">{query ? "Search covers port, title, project, folder, command and notes. Try :51 for ports starting with 51." :
        filter === "pinned" ? "Pin the ports you care about (press p on a row) and they stay at the top." :
        filter === "idle" ? "No forgotten servers: everything listening has been used recently." : "Start a dev server and it appears here within two seconds."}</p>
    </div>
  );
}

/** Badges in order of importance; the row shows the first few and folds the rest into "+n". */
function badges(l: Listener): { key: string; label: string; node: ReactNode }[] {
  const out: { key: string; label: string; node: ReactNode }[] = [];
  if (l.exposureRisk && l.exposureRisk.level !== "medium") {
    out.push({ key: "risk", label: `${l.exposureRisk.level}: ${l.exposureRisk.title}`, node: (
      <Badge tone="bad" className={l.exposureRisk.level === "critical" ? "animate-pulse" : ""} title={`${l.exposureRisk.title}. ${l.exposureRisk.fix}`}><Icon name="warn" size={11} />{l.exposureRisk.level}</Badge>) });
  } else if (l.exposure === "network") {
    out.push({ key: "net", label: "reachable from your network", node: (
      <Badge tone="warn" title={`Listening on ${l.addresses.join(", ")}: other devices on your network can reach it`}><Icon name="network" size={11} />network</Badge>) });
  }
  if (l.framework && l.framework.label !== l.title) out.push({ key: "fw", label: l.framework.label, node: <Badge>{l.framework.label}</Badge> });
  const git = l.project?.git;
  if (git?.branch && git.branch !== "main" && git.branch !== "master") {
    out.push({ key: "git", label: `branch ${git.branch}`, node: (
      <Badge tone="violet" title={git.worktree ? `git worktree of ${git.repo}` : `branch of ${git.repo}`}>⎇ {git.branch}{git.worktree ? " · wt" : ""}</Badge>) });
  }
  if (l.idleFor) out.push({ key: "idle", label: `idle ${duration(l.idleFor)}`, node: (
    <Badge tone="violet" title="No connections and no CPU for this long: probably forgotten"><Icon name="moon" size={11} />idle {duration(l.idleFor)}</Badge>) });
  if (l.docker) out.push({ key: "docker", label: `Docker ${l.docker.image}`, node: <Badge tone="info"><Icon name="docker" size={11} />{l.docker.image}</Badge> });
  if (l.managed) out.push({ key: "ph", label: "started by Porthaven", node: <Badge tone="accent" title="Started by Porthaven; its output is in Apps">porthaven</Badge> });
  return out;
}

function HttpCell({ l }: { l: Listener }) {
  const p = l.probe, h = l.health;
  const checks = h && h.n ? ` · ${h.up}/${h.n} checks OK` : "";
  if (!p) return <span className="text-xs text-faint" title={l.kind === "database" ? "Databases are not checked over HTTP" : "Not checked yet"}>{l.kind === "database" ? "—" : "…"}</span>;
  if (!p.ok) {
    if (p.error === "not HTTP") return <span className="text-xs text-faint" title="Does not speak HTTP">—</span>;
    return <span className="inline-flex items-center gap-1 text-xs font-medium text-bad" title={`${p.error}${checks}`}><Icon name="warn" size={12} />down</span>;
  }
  const s = p.status || 0;
  const tone = s >= 500 ? "text-bad" : s >= 400 ? "text-warn" : s >= 300 ? "text-info" : "text-ok";
  const slow = (p.ms ?? 0) >= 1000;
  return (
    <span className="inline-flex items-baseline gap-1.5" title={`HTTP ${s}${p.reason ? ` ${p.reason}` : ""} in ${p.ms} ms${p.title ? ` · ${p.title}` : ""}${checks}`}>
      <span className={cx("tnum font-mono text-xs font-semibold", tone)}>{s}</span>
      <span className={cx("tnum text-[11px]", slow ? "text-warn" : "text-muted")}>{p.ms != null ? (p.ms >= 1000 ? `${(p.ms / 1000).toFixed(1)} s` : `${p.ms} ms`) : ""}</span>
    </span>
  );
}

function MemCell({ v, max }: { v: number | null; max: number }) {
  const pct = v ? Math.max(3, Math.min(100, (v / max) * 100)) : 0;
  return (
    <div className="flex items-center justify-end gap-2" title={v ? `${mb(v)} of memory` : undefined}>
      <span className="h-1.5 w-14 overflow-hidden rounded-full bg-panel-2 @max-4xl:hidden" aria-hidden="true">
        <span className={cx("block h-full rounded-full transition-[width] duration-500", (v || 0) >= 1024 ? "bg-warn" : "bg-accent/70")} style={{ width: `${pct}%` }} />
      </span>
      <span className="tnum w-14 text-right text-xs text-muted">{mb(v)}</span>
    </div>
  );
}

function Row({ l, idx, active, selected, dense, cpuMax, memMax, flash, fresh, hovered, actions, onClick, onFocus, onHover, home, showPath, picked, onPick }: {
  l: Listener; idx: number; active: boolean; selected: boolean; dense: boolean; cpuMax: number; memMax: number; flash: boolean; fresh: boolean; hovered: boolean;
  actions: Actions; onClick: () => void; onFocus: () => void; onHover: (on: boolean) => void; home: string; showPath: boolean; picked: boolean; onPick: () => void;
}) {
  const h = health(l);
  const web = !!l.probe?.ok && !!l.probe.status;
  const locked = l.risk === "self" || l.risk === "foreign";
  const all = badges(l);
  const shown = all.slice(0, dense ? 2 : 3), more = all.slice(shown.length);
  const items: MenuItem[] = [
    ...(web ? [{ label: "Open in browser", icon: "external", hint: "o", onClick: () => actions.open(l) }] : []),
    { label: "Copy URL", icon: "copy", hint: "c", onClick: () => void actions.copyUrl(l) },
    { label: "Copy PID", icon: "copy", onClick: () => void actions.copyText(String(l.pid), `Copied pid ${l.pid}`) },
    { label: "Copy command", icon: "copy", onClick: () => void actions.copyText(l.args, "Copied the command") },
    { label: "Check again", icon: "refresh", onClick: () => void actions.probe(l) },
    "sep",
    { label: l.meta.pinned ? "Unpin" : "Pin to top", icon: "pin", hint: "p", onClick: () => void actions.meta(l, { pinned: !l.meta.pinned }) },
    { label: l.meta.watched ? "Stop watching" : "Watch (notify when it goes down)", icon: "bell", hint: "w", onClick: () => void actions.meta(l, { watched: !l.meta.watched }) },
    ...(l.cwd ? [
      "sep" as const,
      { label: "Open folder", icon: "folder", onClick: () => void actions.reveal(l.project?.root || l.cwd, "finder") },
      { label: "Open in editor", icon: "code", onClick: () => void actions.reveal(l.project?.root || l.cwd, "editor") },
      { label: "Open terminal here", icon: "terminal", onClick: () => void actions.reveal(l.project?.root || l.cwd, "terminal") },
    ] : []),
    ...(!locked && l.cwd && !l.managed ? ["sep" as const, { label: "Save as app", icon: "plus", onClick: () => void actions.saveApp(l) },
      { label: "Restart (Porthaven keeps logs)", icon: "restart", onClick: () => void actions.restart(l) }] : []),
    ...(!locked ? ["sep" as const,
      { label: `Stop process ${l.pid}`, icon: "stop", hint: "x", danger: true, onClick: () => void actions.kill(l, "process") },
      ...(l.root ? [{ label: `Stop whole app (${l.root.count})`, icon: "stop", hint: "⇧X", danger: true, onClick: () => void actions.kill(l, "app") }] : []),
    ] : []),
  ];
  const launcher = l.root ? l.root.display.split(" ").slice(0, 2).join(" ").replace(/^.*\//, "") : null;
  return (
    <div role="row" data-idx={idx} aria-selected={selected} tabIndex={active ? 0 : -1} onClick={onClick} onFocus={(e) => e.target === e.currentTarget && onFocus()}
      onMouseEnter={() => onHover(true)} onMouseLeave={() => onHover(false)}
      className={cx("group grid cursor-pointer items-center gap-3 border-b border-line/70 px-4 outline-none transition-colors",
        "focus-visible:shadow-[inset_2px_0_0_var(--accent)] focus-visible:bg-panel-2/70", COLS,
        dense ? "py-1.5" : "py-2.5", selected ? "bg-accent-soft" : active ? "bg-panel-2/70" : hovered ? "bg-panel-2/70 shadow-[inset_2px_0_0_var(--accent)]" : "hover:bg-panel-2/50",
        flash && "flash", fresh && "row-in")}>
      <div role="gridcell" className="flex items-center gap-2">
        <input type="checkbox" checked={picked} onChange={onPick} onClick={(e) => e.stopPropagation()} aria-label={`Select :${l.port}`} tabIndex={-1}
          disabled={locked} className={cx("h-3.5 w-3.5 accent-[var(--accent)] transition", picked ? "opacity-100" : "opacity-0 group-hover:opacity-60 group-focus-visible:opacity-60 disabled:invisible")} />
        <span title={l.probe ? (l.probe.ok ? `HTTP ${l.probe.status} in ${l.probe.ms} ms` : l.probe.error) : "not checked"}>
          <Dot tone={HEALTH_TONE[h]} pulse={h === "up" && l.connections > 0} /><span className="sr-only">{HEALTH_TEXT[h]}</span>
        </span>
        <span className="tnum font-mono text-[15px] font-semibold text-ink">{l.port}</span>
      </div>
      <div role="gridcell" className="min-w-0">
        <div className="flex min-w-0 items-center gap-2">
          {l.meta.pinned && <Icon name="pin" size={12} className="shrink-0 text-accent" />}
          <span className="min-w-[4.5rem] truncate text-sm font-medium text-ink" title={l.title}>{l.title}</span>
          <span className="flex shrink-0 items-center gap-1">
            {shown.map((b) => <span key={b.key} className="contents">{b.node}</span>)}
            {more.length > 0 && <Badge title={more.map((b) => b.label).join(" · ")}>+{more.length}</Badge>}
          </span>
          {l.meta.watched && <Icon name="bell" size={12} className="shrink-0 text-info" />}
        </div>
        {!dense && (
          <div className="mt-0.5 flex min-w-0 items-center gap-1.5 text-[11px] text-faint">
            {l.meta.note ? <span className="truncate italic text-ink-2">“{l.meta.note}”</span> : <>
              {showPath && (l.cwd || l.project) && <><span className="max-w-[40%] shrink-0 truncate font-mono">{shortPath(l.cwd || l.project?.root, home)}</span><span aria-hidden="true">·</span></>}
              <span className="min-w-0 truncate font-mono text-muted" title={l.args}>{l.display || l.hint || l.appBundle}</span>
            </>}
            <span aria-hidden="true">·</span>
            <span className="tnum shrink-0">pid {l.pid}</span>
            {launcher && <span className="shrink-0" title={l.root!.display}>via {launcher}</span>}
            {l.workers && l.workers.length > 0 && <span className="shrink-0">+{l.workers.length} worker{l.workers.length > 1 ? "s" : ""}</span>}
            {l.connections > 0 && <span className="shrink-0 text-info">{l.connections} conn</span>}
          </div>
        )}
      </div>
      <div role="gridcell"><HttpCell l={l} /></div>
      <span role="gridcell" className="tnum text-xs text-muted">{duration(l.uptime)}</span>
      <div role="gridcell" className="flex items-center gap-2">
        <span className="@max-4xl:hidden"><Sparkline values={l.spark.cpu} max={cpuMax} width={56} height={dense ? 16 : 20} color={(l.cpu || 0) > 50 ? "var(--warn)" : "var(--accent)"} /></span>
        <span className="tnum w-10 text-right text-xs text-muted">{l.cpu == null ? "—" : `${l.cpu.toFixed(l.cpu < 10 ? 1 : 0)}%`}</span>
      </div>
      <div role="gridcell"><MemCell v={l.memMb} max={memMax} /></div>
      <div role="gridcell" className="flex items-center justify-end gap-0.5 opacity-60 transition group-hover:opacity-100 group-focus-visible:opacity-100 focus-within:opacity-100">
        {web && <IconButton icon="external" title="Open in browser (o)" onClick={() => actions.open(l)} />}
        {!locked ? <IconButton icon="stop" title={l.root ? `Stop (x) · whole app: ⇧X` : "Stop (x)"} danger onClick={() => void actions.kill(l, "process")} /> :
          <span title={l.risk === "self" ? "This is Porthaven" : "Owned by another user"} className="inline-flex h-8 w-8 items-center justify-center text-faint"><Icon name="lock" size={14} /></span>}
        <Menu items={items} trigger={(open) => <IconButton icon="more" title="More" onClick={open} />} />
      </div>
    </div>
  );
}

/** A port that just stopped listening: stays in place for a few seconds with a way to run it again. */
function GhostRow({ g, dense, onRestart, onDismiss }: { g: Ghost; dense: boolean; onRestart: () => void; onDismiss: () => void }) {
  const l = g.l;
  const canRestart = !!(l.appId || l.cwd) && l.risk !== "foreign" && l.risk !== "system" && l.risk !== "app";
  return (
    <div role="row" aria-label={`:${l.port} ${l.title} stopped`} className={cx("ghost grid items-center gap-3 border-b border-line/70 px-4 text-muted", COLS, dense ? "py-1.5" : "py-2.5")}
      style={{ animationDuration: `${GHOST_MS}ms` }}>
      <div role="gridcell" className="flex items-center gap-2 pl-[22px]">
        <Dot tone="muted" />
        <span className="tnum font-mono text-[15px] font-semibold text-faint line-through decoration-faint/60">{l.port}</span>
      </div>
      <div role="gridcell" className="min-w-0">
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate text-sm font-medium text-ink-2">{l.title}</span>
          <Badge><Icon name="stop" size={10} />stopped</Badge>
        </div>
        {!dense && <div className="mt-0.5 text-[11px] text-faint">Stopped listening {ago(g.at / 1000)} · was {mb(l.memMb)} · pid {l.pid}</div>}
      </div>
      <span role="gridcell" className="text-xs text-faint">—</span>
      <span role="gridcell" className="text-xs text-faint">—</span>
      <span role="gridcell" className="text-xs text-faint">—</span>
      <span role="gridcell" className="text-right text-xs text-faint">—</span>
      <div role="gridcell" className="flex items-center justify-end gap-1">
        {canRestart && <button type="button" onClick={onRestart}
          className="inline-flex h-7 items-center gap-1 rounded-lg px-2 text-xs font-semibold text-accent transition hover:bg-accent-soft focus-visible:outline-2 focus-visible:outline-accent">
          <Icon name="restart" size={13} />Restart</button>}
        <IconButton icon="close" title="Dismiss" size={14} className="h-7 w-7" onClick={onDismiss} />
      </div>
    </div>
  );
}
