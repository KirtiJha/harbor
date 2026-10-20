import { useEffect, useMemo, useState } from "react";
import { api, type Activity, type Insights, type Listener, type Snapshot } from "../api";
import { useLocal, useNow } from "../useHarbor";
import { colorFor, cx, duration, mb } from "../util";
import { Heatmap, StackedBars } from "./charts";
import { Icon } from "./Icon";
import { Badge, Button, Spinner } from "./ui";

export type Range = "1h" | "6h" | "24h" | "7d";
export const RANGES: { id: Range; label: string; seconds: number; bucket: number }[] = [
  { id: "1h", label: "1 hour", seconds: 3600, bucket: 300 },
  { id: "6h", label: "6 hours", seconds: 6 * 3600, bucket: 900 },
  { id: "24h", label: "24 hours", seconds: 86400, bucket: 3600 },
  { id: "7d", label: "7 days", seconds: 7 * 86400, bucket: 6 * 3600 },
];

export const EVENT: Record<Activity["type"], { label: string; color: string; icon: string; verb: string }> = {
  opened: { label: "Started listening", color: "#34d399", icon: "play", verb: "started listening on" },
  ready: { label: "Ready", color: "#2dd4bf", icon: "check", verb: "is ready on" },
  started: { label: "Launched", color: "#22d3ee", icon: "bolt", verb: "launched by Harbor" },
  closed: { label: "Stopped listening", color: "#64748b", icon: "stop", verb: "stopped listening on" },
  stopped: { label: "Stopped", color: "#94a3b8", icon: "stop", verb: "stopped" },
  exited: { label: "Exited", color: "#94a3b8", icon: "stop", verb: "exited" },
  killed: { label: "Stopped from Harbor", color: "#fb923c", icon: "stop", verb: "stopped from Harbor" },
  crashed: { label: "Crashed", color: "#f87171", icon: "warn", verb: "crashed" },
  conflict: { label: "Port conflict", color: "#fbbf24", icon: "warn", verb: "could not get" },
};
const TYPES = Object.keys(EVENT) as Activity["type"][];

export function useInsights(range: Range, bump: number) {
  const [data, setData] = useState<Insights | null>(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    let live = true;
    const load = () => { setLoading(true); api.insights(range).then((d) => live && setData(d)).catch(() => {}).finally(() => live && setLoading(false)); };
    load();
    const t = window.setInterval(load, 30000);
    return () => { live = false; window.clearInterval(t); };
  }, [range, bump]);
  return { data: data?.range === range ? data : data, loading };
}

/* ------------------------------------------------------------------ lanes: when each port was up */

type Seg = { start: number; end: number; live: boolean; pid?: number; title: string; mem?: number | null };
type Mark = { ts: number; type: Activity["type"]; detail?: string; title: string };
export type Lane = { key: string; port: number; title: string; project: string | null; color: string; live: Listener | null; segs: Seg[]; marks: Mark[]; last: number };

/** Short-lived servers on random high ports (test runs, tool callbacks) clutter the timeline. */
export function isBrief(l: Lane) {
  return !l.live && l.port >= 32768 && l.segs.every((s) => s.end - s.start < 120) && !l.marks.some((m) => m.type === "crashed" || m.type === "conflict");
}

export function buildLanes(events: Activity[], listeners: Listener[], start: number, now: number): Lane[] {
  const lanes = new Map<string, Lane>();
  const get = (port: number, title: string, project: string | null | undefined) => {
    const key = String(port);   // one lane per port; each bar keeps the title it had then
    if (!lanes.has(key)) lanes.set(key, { key, port, title, project: project || null, color: colorFor(project || title), live: null, segs: [], marks: [], last: 0 });
    return lanes.get(key)!;
  };
  for (const l of listeners) {
    if (l.kind === "system" || l.kind === "app") continue;
    const lane = get(l.port, l.title, l.project?.name);
    lane.live = l;
    lane.title = l.title;
    lane.segs.push({ start: Math.max(start, now - (l.uptime || 0)), end: now, live: true, pid: l.pid, title: l.title, mem: l.memMb });
    lane.last = now;
  }
  const opens = new Map<string, number>();
  for (const e of [...events].sort((a, b) => a.ts - b.ts)) {
    if (e.port == null || e.kind === "system" || e.kind === "app") continue;
    const lane = get(e.port, e.title, e.project);
    lane.last = Math.max(lane.last, e.ts);
    if (e.type === "opened") opens.set(`${e.pid}:${e.port}`, e.ts);
    else if (e.type === "closed") {
      const began = opens.get(`${e.pid}:${e.port}`) ?? (e.ranFor ? e.ts - e.ranFor : start);
      if (e.ts > start) lane.segs.push({ start: Math.max(start, began), end: e.ts, live: false, pid: e.pid, title: e.title, mem: e.memMb });
    }
    if (!["opened", "closed"].includes(e.type)) lane.marks.push({ ts: e.ts, type: e.type, detail: e.detail, title: e.title });
  }
  return [...lanes.values()].filter((l) => l.segs.length || l.marks.length)
    .sort((a, b) => Number(!!b.live) - Number(!!a.live) || (a.live ? a.port - b.port : b.last - a.last));
}

function Timeline({ lanes: everyLane, start, now, onOpenPort }: { lanes: Lane[]; start: number; now: number; onOpenPort: (l: Listener) => void }) {
  const [all, setAll] = useState(false);
  const [brief, setBrief] = useLocal("harbor.showBrief", false);
  const hidden = everyLane.filter(isBrief).length;
  const lanes = brief ? everyLane : everyLane.filter((l) => !isBrief(l));
  const [tip, setTip] = useState<{ x: number; y: number; body: React.ReactNode } | null>(null);
  const span = now - start;
  const pct = (t: number) => `${((t - start) / span) * 100}%`;
  const ticks = Array.from({ length: 7 }, (_, i) => start + (span * i) / 6);
  const shown = all ? lanes : lanes.slice(0, 14);
  const fmtT = (t: number) => new Date(t * 1000).toLocaleString([], span > 2 * 86400 ? { weekday: "short", hour: "2-digit", minute: "2-digit" } : { hour: "2-digit", minute: "2-digit" });

  if (!everyLane.length) return <p className="py-10 text-center text-sm text-muted">Nothing ran in this window.</p>;
  return (
    <div className="relative" onMouseLeave={() => setTip(null)}>
      <div className="grid grid-cols-[230px_1fr] items-end gap-3 pb-1">
        <span />
        <div className="relative h-5">
          {ticks.map((t, i) => (
            <span key={t} className="absolute -translate-x-1/2 text-[10px] text-faint" style={{ left: pct(t), transform: i === 0 ? "none" : i === 6 ? "translateX(-100%)" : undefined }}>
              {i === 6 ? "now" : fmtT(t)}
            </span>
          ))}
        </div>
      </div>
      <div className="space-y-1">
        {shown.map((lane) => (
          <div key={lane.key} className="group grid grid-cols-[230px_1fr] items-center gap-3">
            <button onClick={() => lane.live && onOpenPort(lane.live)} disabled={!lane.live}
              className="flex min-w-0 items-center gap-2 rounded-md px-1.5 py-1 text-left hover:bg-panel-2 disabled:hover:bg-transparent">
              <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: lane.color }} />
              <span className="tnum w-11 shrink-0 font-mono text-xs font-semibold text-ink">:{lane.port}</span>
              <span className={cx("truncate text-xs", lane.live ? "text-ink-2" : "text-muted")}>{lane.title}</span>
              {lane.live && <span className="pulse ml-auto h-1.5 w-1.5 shrink-0 rounded-full bg-ok text-ok" />}
            </button>
            <div className="relative h-7 rounded-md bg-panel-2/50">
              {ticks.slice(1, -1).map((t) => <span key={t} className="absolute inset-y-0 border-l border-line/60" style={{ left: pct(t) }} />)}
              {lane.segs.map((s, i) => (
                <span key={i}
                  onMouseMove={(e) => setTip({ x: e.clientX, y: e.clientY, body: (
                    <>
                      <div className="text-xs font-semibold text-ink">{s.title} <span className="font-mono text-muted">:{lane.port}</span></div>
                      <div className="mt-0.5 text-[11px] text-muted">{fmtT(s.start)} → {s.live ? "now" : fmtT(s.end)} · {duration(s.end - s.start)}{s.start <= start + 1 ? "+" : ""}</div>
                      <div className="text-[11px] text-faint">{s.pid ? `pid ${s.pid}` : ""}{s.mem ? ` · ${mb(s.mem)}` : ""}{s.live ? " · running" : ""}</div>
                    </>) })}
                  className={cx("absolute top-1 bottom-1 rounded-[5px] transition hover:brightness-125", s.live && "shadow-[0_0_8px_-3px_var(--c)]")}
                  style={{ left: pct(s.start), width: `max(3px, calc(${pct(s.end)} - ${pct(s.start)}))`, background: `linear-gradient(90deg, ${lane.color}55, ${lane.color}${s.live ? "cc" : "88"})`, ["--c" as string]: lane.color }} />
              ))}
              {lane.marks.map((m, i) => (
                <span key={i}
                  onMouseMove={(e) => setTip({ x: e.clientX, y: e.clientY, body: (
                    <>
                      <div className="text-xs font-semibold" style={{ color: EVENT[m.type].color }}>{EVENT[m.type].label}</div>
                      <div className="text-[11px] text-muted">{m.title} · {fmtT(m.ts)}</div>
                      {m.detail && <div className="text-[11px] text-faint">{m.detail}</div>}
                    </>) })}
                  className="absolute top-1/2 z-[1] h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rotate-45 rounded-[2px] ring-2 ring-[var(--panel)]"
                  style={{ left: pct(m.ts), background: EVENT[m.type].color }} />
              ))}
            </div>
          </div>
        ))}
      </div>
      <div className="mt-2 flex gap-4">
        {lanes.length > 14 && <button className="text-xs font-medium text-accent hover:underline" onClick={() => setAll(!all)}>{all ? "Show fewer" : `Show all ${lanes.length} ports`}</button>}
        {hidden > 0 && <button className="text-xs text-muted hover:text-ink" onClick={() => setBrief(!brief)}>{brief ? "Hide" : "Show"} {hidden} short-lived port{hidden > 1 ? "s" : ""} (under 2 min, random high ports)</button>}
      </div>
      {tip && <div className="card pointer-events-none fixed z-50 px-3 py-2" style={{ left: tip.x + 14, top: tip.y + 14 }}>{tip.body}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ the view */

export function ActivityView({ snap, onOpenPort, onClear }: { snap: Snapshot; onOpenPort: (l: Listener) => void; onClear: () => void }) {
  const [range, setRange] = useLocal<Range>("harbor.activityRange", "24h");
  const [off, setOff] = useLocal<string[]>("harbor.activityOff", []);
  const [q, setQ] = useState("");
  const { data, loading } = useInsights(range, snap.activity.length);
  const week = useInsights("7d", snap.activity.length);
  const now = useNow(30000);
  const r = RANGES.find((x) => x.id === range)!;
  const start = now - r.seconds;

  const events = useMemo(() => (data?.activity || []).filter((e) => e.ts >= start), [data, start]);
  const visible = useMemo(() => events.filter((e) => !off.includes(e.type) && (!q || `${e.title} ${e.port} ${e.project || ""} ${e.detail || ""}`.toLowerCase().includes(q.toLowerCase()))), [events, off, q]);
  const counts = useMemo(() => Object.fromEntries(TYPES.map((t) => [t, events.filter((e) => e.type === t).length])) as Record<string, number>, [events]);
  const lanes = useMemo(() => buildLanes(visible, snap.listeners, start, now), [visible, snap.listeners, start, now]);

  const buckets = useMemo(() => {
    const n = Math.ceil(r.seconds / r.bucket);
    const b = Array.from({ length: n }, (_, i) => ({ t: start + i * r.bucket, counts: {} as Record<string, number> }));
    for (const e of visible) {
      const i = Math.min(n - 1, Math.floor((e.ts - start) / r.bucket));
      if (i >= 0) b[i].counts[e.type] = (b[i].counts[e.type] || 0) + 1;
    }
    return b;
  }, [visible, start, r]);

  const heat = useMemo(() => {
    const cells = Array.from({ length: 7 }, () => Array(24).fill(0) as number[]);
    for (const e of week.data?.activity || []) {
      const d = new Date(e.ts * 1000);
      cells[(d.getDay() + 6) % 7][d.getHours()] += 1;
    }
    return cells;
  }, [week.data]);

  const restarts = useMemo(() => {
    const byPort = new Map<number, number>();
    for (const e of events) if (e.type === "opened" && e.port) byPort.set(e.port, (byPort.get(e.port) || 0) + 1);
    return [...byPort.values()].reduce((a, n) => a + Math.max(0, n - 1), 0);
  }, [events]);
  const busiest = useMemo(() => buckets.reduce((best, b) => {
    const n = Object.values(b.counts).reduce((a, x) => a + x, 0);
    return n > best.n ? { t: b.t, n } : best;
  }, { t: 0, n: 0 }), [buckets]);

  const stats = [
    { label: "Servers started", value: counts.opened + counts.started, icon: "play", tone: "text-ok" },
    { label: "Stopped", value: counts.closed + counts.stopped + counts.killed + counts.exited, icon: "stop", tone: "text-muted" },
    { label: "Restarts", value: restarts, icon: "restart", tone: "text-info" },
    { label: "Crashes", value: counts.crashed, icon: "warn", tone: counts.crashed ? "text-bad" : "text-muted" },
    { label: "Port conflicts", value: counts.conflict, icon: "network", tone: counts.conflict ? "text-warn" : "text-muted" },
    { label: "Busiest", value: busiest.n ? new Date(busiest.t * 1000).toLocaleTimeString([], range === "7d" ? { weekday: "short", hour: "2-digit" } : { hour: "2-digit", minute: "2-digit" }) : "—", icon: "activity", tone: "text-accent", sub: busiest.n ? `${busiest.n} events` : "" },
  ];

  return (
    <div className="min-h-0 flex-1 space-y-4 overflow-y-auto pr-1">
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <h2 className="text-lg font-semibold text-ink">Activity</h2>
          <p className="text-xs text-muted">What ran on which port, when, and what happened to it.</p>
        </div>
        {loading && <Spinner />}
        <div className="ml-auto flex items-center gap-2">
          <div className="flex items-center gap-1.5 rounded-lg border border-line bg-panel px-2.5 py-1.5">
            <Icon name="search" size={13} className="text-faint" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter events" className="w-36 bg-transparent text-xs text-ink outline-none placeholder:text-faint" />
          </div>
          <div className="flex rounded-lg border border-line bg-panel p-0.5 text-xs">
            {RANGES.map((x) => (
              <button key={x.id} onClick={() => setRange(x.id)} className={cx("rounded-md px-2.5 py-1 font-medium", range === x.id ? "bg-accent-soft text-accent-ink" : "text-muted hover:text-ink")}>{x.id}</button>
            ))}
          </div>
          <Button size="sm" variant="ghost" icon="trash" onClick={onClear}>Clear</Button>
        </div>
      </div>

      <div className="grid grid-cols-6 gap-3">
        {stats.map((s) => (
          <div key={s.label} className="card px-4 py-3">
            <div className="flex items-center gap-1.5 text-[11px] text-muted"><Icon name={s.icon} size={12} className={s.tone} />{s.label}</div>
            <div className="tnum mt-1 text-2xl font-semibold text-ink">{s.value}</div>
            {"sub" in s && s.sub && <div className="text-[11px] text-faint">{s.sub}</div>}
          </div>
        ))}
      </div>

      <section className="card p-4">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <h3 className="text-sm font-semibold text-ink">Timeline</h3>
          <span className="text-xs text-muted">bars show when each port was listening; diamonds mark launches, crashes, stops and conflicts</span>
          <div className="ml-auto flex flex-wrap gap-1">
            {TYPES.filter((t) => counts[t]).map((t) => (
              <button key={t} onClick={() => setOff(off.includes(t) ? off.filter((x) => x !== t) : [...off, t])}
                className={cx("flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-[11px] transition", off.includes(t) ? "border-line text-faint line-through" : "border-line-2 text-ink-2")}>
                <span className="h-2 w-2 rotate-45 rounded-[1px]" style={{ background: EVENT[t].color, opacity: off.includes(t) ? 0.3 : 1 }} />{EVENT[t].label}<span className="tnum text-faint">{counts[t]}</span>
              </button>
            ))}
          </div>
        </div>
        <Timeline lanes={lanes} start={start} now={now} onOpenPort={onOpenPort} />
      </section>

      <div className="grid grid-cols-[1.4fr_1fr] gap-4">
        <section className="card p-4">
          <h3 className="mb-2 text-sm font-semibold text-ink">Events over time</h3>
          <StackedBars buckets={buckets} keys={TYPES.filter((t) => !off.includes(t))} start={start} end={now}
            colors={Object.fromEntries(TYPES.map((t) => [t, EVENT[t].color]))} labels={Object.fromEntries(TYPES.map((t) => [t, EVENT[t].label]))} />
        </section>
        <section className="card p-4">
          <h3 className="mb-3 text-sm font-semibold text-ink">When things happen <span className="font-normal text-muted">· last 7 days</span></h3>
          <Heatmap cells={heat} />
        </section>
      </div>

      <Feed events={visible} snap={snap} onOpenPort={onOpenPort} />
    </div>
  );
}

function Feed({ events, snap, onOpenPort }: { events: Activity[]; snap: Snapshot; onOpenPort: (l: Listener) => void }) {
  const [limit, setLimit] = useState(60);
  const days = useMemo(() => {
    const m = new Map<string, Activity[]>();
    const today = new Date().toDateString(), yest = new Date(Date.now() - 86400000).toDateString();
    for (const e of [...events].reverse().slice(0, limit)) {
      const d = new Date(e.ts * 1000).toDateString();
      const label = d === today ? "Today" : d === yest ? "Yesterday" : new Date(e.ts * 1000).toLocaleDateString([], { weekday: "long", day: "numeric", month: "short" });
      if (!m.has(label)) m.set(label, []);
      m.get(label)!.push(e);
    }
    return [...m.entries()];
  }, [events, limit]);
  const live = new Map(snap.listeners.map((l) => [l.port, l]));

  return (
    <section className="card p-4">
      <h3 className="mb-3 text-sm font-semibold text-ink">Event log <span className="font-normal text-muted">· {events.length}</span></h3>
      {events.length === 0 && <p className="py-6 text-center text-xs text-muted">No events in this window. Start or stop a server and it shows up here.</p>}
      {days.map(([label, list]) => (
        <div key={label} className="mb-3">
          <div className="sticky top-0 z-[1] mb-1 bg-panel py-1 text-[11px] font-semibold uppercase tracking-wider text-faint">{label}</div>
          <ol className="relative ml-3 border-l border-line pl-5">
            {list.map((e) => {
              const ev = EVENT[e.type] || EVENT.opened;
              const l = e.port ? live.get(e.port) : undefined;
              return (
                <li key={e.id} className="group relative py-1.5">
                  <span className="absolute -left-[31px] top-1.5 flex h-5 w-5 items-center justify-center rounded-full ring-4 ring-[var(--panel)]" style={{ background: `${ev.color}26`, color: ev.color }}>
                    <Icon name={ev.icon} size={11} stroke={2.4} />
                  </span>
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[13px]">
                    <span className="font-medium text-ink">{e.title}</span>
                    <span className="text-muted">{ev.verb}</span>
                    {e.port != null && (
                      <button disabled={!l} onClick={() => l && onOpenPort(l)} className={cx("tnum rounded-md px-1.5 font-mono text-xs", l ? "bg-accent-soft text-accent-ink hover:brightness-110" : "bg-panel-2 text-muted")}>:{e.port}</button>
                    )}
                    {e.framework && <Badge>{e.framework}</Badge>}
                    {e.type === "closed" && e.ranFor ? <span className="text-xs text-faint">after {duration(e.ranFor)}</span> : null}
                    {e.memMb ? <span className="text-xs text-faint">· {mb(e.memMb)}</span> : null}
                    {e.detail && <span className="text-xs text-faint">· {e.detail}</span>}
                    <time className="tnum ml-auto text-[11px] text-faint" title={new Date(e.ts * 1000).toLocaleString()}>{new Date(e.ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time>
                  </div>
                  {e.project && e.project !== e.title && <div className="text-[11px] text-faint">{e.project}</div>}
                </li>
              );
            })}
          </ol>
        </div>
      ))}
      {events.length > limit && <button className="text-xs font-medium text-accent hover:underline" onClick={() => setLimit(limit + 100)}>Show older events</button>}
    </section>
  );
}
