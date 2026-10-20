import { useEffect, useMemo, useRef, useState } from "react";
import type { Listener, Snapshot } from "../api";
import type { Actions } from "../actions";
import { useLocal } from "../usePorthaven";
import { colorFor, cx, duration, health, matches, mb, shortPath, type Health } from "../util";
import { Icon } from "./Icon";
import { Badge, Dot, IconButton, Menu, Sparkline, type MenuItem } from "./ui";

export type Filter = "all" | "dev" | "databases" | "web" | "network" | "pinned" | "idle" | "system";
type Group = "project" | "kind" | "none";

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

const HEALTH_TONE: Record<Health, "ok" | "warn" | "bad" | "muted" | "info"> = { up: "ok", warn: "warn", down: "bad", none: "muted", unknown: "muted" };

export function PortsView({ snap, query, actions, selected, onSelect, flash }: {
  snap: Snapshot; query: string; actions: Actions; selected: string | null; onSelect: (id: string | null) => void; flash: Set<string>;
}) {
  const [filter, setFilter] = useLocal<Filter>("porthaven.filter", "all");
  const [group, setGroup] = useLocal<Group>("porthaven.group", "project");
  const [dense, setDense] = useLocal("porthaven.dense", false);
  const [collapsed, setCollapsed] = useLocal<string[]>("porthaven.collapsed", []);
  const [cursor, setCursor] = useState(0);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const toggle = (id: string) => setPicked((p) => { const n = new Set(p); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const listRef = useRef<HTMLDivElement>(null);

  const counts = useMemo(() => Object.fromEntries(FILTERS.map((f) => [f.id, snap.listeners.filter((l) => pass(l, f.id)).length])), [snap.listeners]);
  const rows = useMemo(() => {
    // A search from "Mine" also looks through system services and desktop apps.
    const r = snap.listeners.filter((l) => matches(l, query) && (pass(l, filter) || (!!query && filter === "all")));
    return [...r].sort((a, b) => Number(!!b.meta.pinned) - Number(!!a.meta.pinned) || a.port - b.port);
  }, [snap.listeners, query, filter]);

  const groups = useMemo(() => {
    if (group === "none") return [{ key: "all", label: "", sub: "", items: rows }];
    const m = new Map<string, { key: string; label: string; sub: string; items: Listener[] }>();
    for (const l of rows) {
      let key: string, label: string, sub = "";
      if (l.meta.pinned) { key = "~pinned"; label = "Pinned"; }
      else if (group === "project") {
        if (l.project) { key = l.project.root; label = l.project.repo && l.project.repo !== l.project.name ? `${l.project.repo} › ${l.project.name}` : l.project.name; sub = shortPath(l.project.root, snap.me.home); }
        else if (l.docker) { key = "~docker"; label = "Docker"; }
        else { key = `~${l.kind}`; label = { database: "Databases", app: "Desktop apps", system: "System services", service: "Services", tool: "Porthaven", dev: "Other dev servers", other: "Other" }[l.kind]; }
      } else {
        key = l.kind; label = { dev: "Dev servers", service: "Services", database: "Databases", app: "Desktop apps", system: "System services", tool: "Porthaven", other: "Other" }[l.kind];
      }
      if (!m.has(key)) m.set(key, { key, label, sub, items: [] });
      m.get(key)!.items.push(l);
    }
    return [...m.values()].sort((a, b) => (a.key === "~pinned" ? -1 : b.key === "~pinned" ? 1 : 0) || Number(a.key.startsWith("~")) - Number(b.key.startsWith("~")) || a.label.localeCompare(b.label));
  }, [rows, group, snap.me.home]);

  const flat = useMemo(() => groups.flatMap((g) => (collapsed.includes(g.key) ? [] : g.items)), [groups, collapsed]);

  // keyboard: j/k move, Enter opens, o browser, c copy, x stop, p pin
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.closest("input,textarea,select,[role=dialog]") || e.metaKey || e.ctrlKey || e.altKey) return;
      const cur = flat[Math.min(cursor, flat.length - 1)];
      if (e.key === "j" || e.key === "ArrowDown") { setCursor((c) => Math.min(flat.length - 1, c + 1)); e.preventDefault(); }
      else if (e.key === "k" || e.key === "ArrowUp") { setCursor((c) => Math.max(0, c - 1)); e.preventDefault(); }
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

  useEffect(() => {
    listRef.current?.querySelector(`[data-idx="${cursor}"]`)?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  const cpuMax = Math.max(5, ...rows.flatMap((r) => r.spark.cpu));
  const pickedRows = snap.listeners.filter((l) => picked.has(l.id));
  useEffect(() => {
    const live = new Set(snap.listeners.map((l) => l.id));
    if ([...picked].some((id) => !live.has(id))) setPicked(new Set([...picked].filter((id) => live.has(id))));
  }, [snap.listeners, picked]);
  let idx = -1;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap items-center gap-2 pb-3">
        <div className="flex flex-wrap gap-1 rounded-xl border border-line bg-panel p-1">
          {FILTERS.map((f) => (
            <button key={f.id} onClick={() => setFilter(f.id)}
              className={cx("inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition",
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
            <button key={g} onClick={() => setGroup(g)} className={cx("rounded-lg px-2 py-1.5 font-medium capitalize transition", group === g ? "bg-panel-2 text-ink" : "text-muted hover:text-ink")}>{g === "kind" ? "type" : g}</button>
          ))}
          <span className="mx-1 h-4 border-l border-line" />
          <IconButton icon={dense ? "list" : "grid"} title={dense ? "Comfortable rows" : "Compact rows"} onClick={() => setDense(!dense)} size={14} className="h-7 w-7" />
        </div>
      </div>

      <div ref={listRef} className="card min-h-0 flex-1 overflow-auto">
        <div className="sticky top-0 z-10 grid grid-cols-[104px_minmax(220px,1.6fr)_minmax(160px,1fr)_92px_110px_84px_116px] items-center gap-3 border-b border-line bg-panel/95 px-4 py-2 text-[11px] font-medium uppercase tracking-wide text-faint backdrop-blur">
          <span>Port</span><span>What</span><span>Process</span><span>Up</span><span>CPU</span><span className="text-right">Memory</span><span />
        </div>
        {rows.length === 0 && <Empty filter={filter} query={query} />}
        {groups.map((g) => (
          <section key={g.key}>
            {group !== "none" && (
              <button onClick={() => setCollapsed(collapsed.includes(g.key) ? collapsed.filter((c) => c !== g.key) : [...collapsed, g.key])}
                className="group flex w-full items-center gap-2 border-b border-line bg-panel-2/40 px-4 py-1.5 text-left">
                <Icon name="chevron" size={12} className={cx("text-faint transition", !collapsed.includes(g.key) && "rotate-90")} />
                {!g.key.startsWith("~") && <span className="h-2.5 w-2.5 rounded-sm" style={{ background: colorFor(g.key) }} />}
                <span className="text-xs font-semibold text-ink-2">{g.label}</span>
                <span className="tnum text-[11px] text-faint">{g.items.length}</span>
                {g.sub && <span className="truncate font-mono text-[11px] text-faint opacity-0 transition group-hover:opacity-100">{g.sub}</span>}
              </button>
            )}
            {!collapsed.includes(g.key) && g.items.map((l) => {
              idx += 1;
              const i = idx;
              return <Row key={l.id} l={l} idx={i} active={i === cursor} selected={selected === l.id} dense={dense} cpuMax={cpuMax}
                picked={picked.has(l.id)} onPick={() => toggle(l.id)}
                flash={flash.has(l.id)} actions={actions} home={snap.me.home}
                onClick={() => { setCursor(i); onSelect(selected === l.id ? null : l.id); }} />;
            })}
          </section>
        ))}
      </div>
      {pickedRows.length > 0 && (
        <div className="pop mt-3 flex items-center gap-3 rounded-xl border border-accent/30 bg-accent-soft px-4 py-2.5">
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

function Row({ l, idx, active, selected, dense, cpuMax, flash, actions, onClick, home, picked, onPick }: {
  l: Listener; idx: number; active: boolean; selected: boolean; dense: boolean; cpuMax: number; flash: boolean; actions: Actions; onClick: () => void; home: string;
  picked: boolean; onPick: () => void;
}) {
  const h = health(l);
  const web = !!l.probe?.ok && !!l.probe.status;
  const locked = l.risk === "self" || l.risk === "foreign";
  const items: MenuItem[] = [
    ...(web ? [{ label: "Open in browser", icon: "external", hint: "o", onClick: () => actions.open(l) }] : []),
    { label: "Copy URL", icon: "copy", hint: "c", onClick: () => void actions.copyUrl(l) },
    { label: "Copy PID", icon: "copy", onClick: () => void actions.copyText(String(l.pid), `Copied pid ${l.pid}`) },
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
  return (
    <div data-idx={idx} onClick={onClick}
      className={cx("group grid cursor-pointer grid-cols-[104px_minmax(220px,1.6fr)_minmax(160px,1fr)_92px_110px_84px_116px] items-center gap-3 border-b border-line/70 px-4 transition",
        dense ? "py-1.5" : "py-2.5", selected ? "bg-accent-soft" : active ? "bg-panel-2/70" : "hover:bg-panel-2/50", flash && "flash")}>
      <div className="flex items-center gap-2">
        <input type="checkbox" checked={picked} onChange={onPick} onClick={(e) => e.stopPropagation()} aria-label={`Select :${l.port}`}
          disabled={locked} className={cx("h-3.5 w-3.5 accent-[var(--accent)] transition", picked ? "opacity-100" : "opacity-0 group-hover:opacity-60 disabled:hidden")} />
        <span title={l.probe ? (l.probe.ok ? `HTTP ${l.probe.status} in ${l.probe.ms} ms` : l.probe.error) : "not checked"}><Dot tone={HEALTH_TONE[h]} pulse={h === "up" && l.connections > 0} /></span>
        <span className="tnum font-mono text-[15px] font-semibold text-ink">{l.port}</span>
      </div>
      <div className="min-w-0">
        <div className="flex min-w-0 items-center gap-2">
          {l.meta.pinned && <Icon name="pin" size={12} className="shrink-0 text-accent" />}
          <span className="truncate text-sm font-medium text-ink">{l.title}</span>
          {l.framework && l.framework.label !== l.title && <Badge>{l.framework.label}</Badge>}
          {l.probe?.status && l.probe.status >= 300 && <Badge tone={l.probe.status >= 500 ? "bad" : l.probe.status >= 400 ? "warn" : "info"}>{l.probe.status}</Badge>}
          {l.exposure === "network" && <Badge tone="warn" title={`Listening on ${l.addresses.join(", ")}: other devices on your network can reach it`}><Icon name="network" size={11} />network</Badge>}
          {l.managed && <Badge tone="accent" title="Started by Porthaven; its output is in Apps">porthaven</Badge>}
          {l.meta.watched && <Icon name="bell" size={12} className="shrink-0 text-info" />}
          {l.idleFor && <Badge tone="violet" title="No connections and no CPU for this long: probably forgotten"><Icon name="moon" size={11} />idle {duration(l.idleFor)}</Badge>}
          {l.docker && <Badge tone="info"><Icon name="docker" size={11} />{l.docker.image}</Badge>}
        </div>
        {!dense && (
          <div className="mt-0.5 flex min-w-0 items-center gap-1.5 text-xs text-muted">
            {l.meta.note ? <span className="truncate italic text-ink-2">“{l.meta.note}”</span> :
              l.project ? <span className="truncate font-mono text-[11px]">{shortPath(l.cwd || l.project.root, home)}</span> :
                <span className="truncate">{l.hint || l.appBundle || ""}</span>}
          </div>
        )}
      </div>
      <div className="min-w-0">
        <div className="truncate font-mono text-xs text-ink-2" title={l.args}>{l.display}</div>
        {!dense && <div className="mt-0.5 flex items-center gap-2 text-[11px] text-faint">
          <span className="tnum">pid {l.pid}</span>
          {l.workers && l.workers.length > 0 && <span>+{l.workers.length} worker{l.workers.length > 1 ? "s" : ""}</span>}
          {l.connections > 0 && <span className="text-info">{l.connections} conn</span>}
          {l.root && <span title={l.root.display} className="truncate">via {l.root.display.split(" ").slice(0, 2).join(" ").replace(/^.*\//, "")}</span>}
        </div>}
      </div>
      <span className="tnum text-xs text-muted">{duration(l.uptime)}</span>
      <div className="flex items-center gap-2">
        <Sparkline values={l.spark.cpu} max={cpuMax} width={56} height={dense ? 16 : 20} color={(l.cpu || 0) > 50 ? "var(--warn)" : "var(--accent)"} />
        <span className="tnum w-10 text-right text-xs text-muted">{l.cpu == null ? "—" : `${l.cpu.toFixed(l.cpu < 10 ? 1 : 0)}%`}</span>
      </div>
      <span className="tnum text-right text-xs text-muted">{mb(l.memMb)}</span>
      <div className="flex items-center justify-end gap-0.5 opacity-60 transition group-hover:opacity-100">
        {web && <IconButton icon="external" title="Open in browser (o)" onClick={() => actions.open(l)} />}
        {!locked ? <IconButton icon="stop" title={l.root ? `Stop (x) · whole app: ⇧X` : "Stop (x)"} danger onClick={() => void actions.kill(l, "process")} /> :
          <span title={l.risk === "self" ? "This is Porthaven" : "Owned by another user"} className="inline-flex h-8 w-8 items-center justify-center text-faint"><Icon name="lock" size={14} /></span>}
        <Menu items={items} trigger={(open) => <IconButton icon="more" title="More" onClick={open} />} />
      </div>
    </div>
  );
}
