import { useLayoutEffect, useMemo, useRef, useState } from "react";
import type { App, Listener } from "../api";
import type { Actions } from "../actions";
import { colorFor, cx, duration, health, mb } from "../util";
import { Icon } from "./Icon";

type Node = { port: number; l: Listener | null; extra: number; app: App | null; conflict: boolean };

const CHIP = 68;          // chip width in px
const FREE_FROM = [3000, 5173, 8000];

/** Space between two neighbouring ports: adjacent ports touch, far-apart ports get more room, on a log scale. */
const gapFor = (delta: number) => (delta <= 1 ? 4 : Math.min(110, 14 + 20 * Math.log10(delta)));

function nextFree(from: number, taken: Set<number>) {
  for (let p = from; p <= 65535; p++) if (!taken.has(p)) return p;
  return null;
}

/** Every visible port on one line, in order: neighbours sit close, big jumps are broken, saved apps that are
 * not running hold a dashed place, and a port someone else took from a saved app is marked as a conflict. */
export function PortMap({ listeners, all, apps, hoverPort, onHover, selected, onPick, actions }: {
  listeners: Listener[]; all: Listener[]; apps: App[]; hoverPort: number | null; onHover: (port: number | null) => void;
  selected: string | null; onPick: (l: Listener) => void; actions: Actions;
}) {
  const track = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(1000);
  const [tip, setTip] = useState<number | null>(null);
  const taken = useMemo(() => new Set([...all.map((l) => l.port), ...apps.map((a) => a.port).filter(Boolean) as number[]]), [all, apps]);
  const nodes = useMemo(() => {
    const m = new Map<number, Node>();
    for (const l of listeners) {
      const n = m.get(l.port);
      if (n) n.extra += 1;
      else m.set(l.port, { port: l.port, l, extra: 0, app: null, conflict: false });
    }
    for (const a of apps) {
      if (!a.port || a.state === "running" || a.state === "starting") continue;
      const n = m.get(a.port);
      const holder = all.find((l) => l.port === a.port);
      if (n) { n.app = a; n.conflict = !!holder && holder.appId !== a.id; }
      else m.set(a.port, { port: a.port, l: null, extra: 0, app: a, conflict: !!holder && holder.appId !== a.id });
    }
    return [...m.values()].sort((a, b) => a.port - b.port);
  }, [listeners, apps, all]);

  const shown = nodes.length > 0;
  useLayoutEffect(() => {   // the track only exists while there are ports to draw
    const el = track.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    setWidth(el.clientWidth);
    return () => ro.disconnect();
  }, [shown]);

  const layout = useMemo(() => {
    const gaps = nodes.map((n, i) => (i ? gapFor(n.port - nodes[i - 1].port) : 0));
    const sum = gaps.reduce((s, g) => s + g, 0), base = nodes.length * CHIP;
    const k = base + sum < width && sum > 0 ? Math.min(3, (width - 24 - base) / sum) : 1;
    let x = 0;
    const xs = nodes.map((_, i) => (x += (i ? CHIP : 0) + gaps[i] * k));
    const total = (xs.at(-1) ?? 0) + CHIP;
    const off = Math.max(12, (width - total) / 2);
    return { xs: xs.map((v) => v + off), total: total + off * 2 };
  }, [nodes, width]);

  if (!shown) return null;
  const tipNode = tip == null ? null : nodes.find((n) => n.port === tip) || null;
  const tipX = tipNode ? layout.xs[nodes.indexOf(tipNode)] + CHIP / 2 : 0;
  const free = FREE_FROM.map((p) => nextFree(p, taken)).filter((p): p is number => p != null);

  return (
    <div className="card relative mb-3 px-3 pb-2 pt-2.5" role="group" aria-label="Port map">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-1 text-[11px] text-faint">
        <span className="flex items-center gap-1.5 text-xs font-semibold text-ink-2"><Icon name="radar" size={13} />Port map</span>
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-3.5 rounded-sm border border-line-2 bg-panel-2" />listening</span>
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-3.5 rounded-sm border border-dashed border-faint" />saved app, not running</span>
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-3.5 rounded-sm border border-warn/70 bg-warn/10" />reachable from network</span>
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-3.5 rounded-sm border border-dashed border-bad" />taken from a saved app</span>
        <span className="ml-auto flex items-center gap-1.5">
          Free
          {free.map((p) => (
            <button key={p} type="button" title={`:${p} is not in use. Click to copy.`} onClick={() => void actions.copyText(String(p), `Copied :${p}`)}
              className="tnum rounded-md border border-ok/25 bg-ok/10 px-1.5 py-px font-mono text-[11px] font-medium text-ok transition hover:bg-ok/20 focus-visible:outline-2 focus-visible:outline-accent">:{p}</button>
          ))}
        </span>
      </div>

      <div ref={track} className="relative mt-1 overflow-x-auto overflow-y-hidden" onMouseLeave={() => { setTip(null); onHover(null); }} onScroll={() => setTip(null)}>
        <div className="relative h-[60px]" style={{ width: Math.max(layout.total, width) }}>
          <div className="absolute top-[30px] h-px bg-line-2" style={{ left: layout.xs[0], width: (layout.xs.at(-1) ?? 0) - layout.xs[0] + CHIP }} />
          {nodes.map((n, i) => {
            if (!i) return null;
            const delta = n.port - nodes[i - 1].port;
            if (delta < 1000) return null;
            const mid = (layout.xs[i - 1] + CHIP + layout.xs[i]) / 2;
            return <span key={`b${n.port}`} title={`${delta.toLocaleString()} ports apart`} aria-hidden="true" style={{ left: mid }}
              className="absolute top-[21px] -translate-x-1/2 bg-panel px-1 font-mono text-[13px] leading-[18px] text-faint">≈</span>;
          })}
          {nodes.map((n, i) => {
            const l = n.l, h = l ? health(l) : null;
            const hot = hoverPort === n.port || tip === n.port, sel = !!l && selected === l.id;
            const risk = l?.exposureRisk && l.exposureRisk.level !== "medium";
            const color = l?.project ? colorFor(l.project.root) : n.app?.color || "var(--faint)";
            const label = l ? (l.framework?.id || l.kind) : "saved";
            const desc = l ? `:${n.port} ${l.title}${l.exposure === "network" ? ", reachable from your network" : ""}${n.conflict ? `, wanted by ${n.app!.name}` : ""}`
              : `:${n.port} ${n.app!.name}, saved app not running${n.conflict ? ", port taken by another process" : ""}`;
            return (
              <button key={n.port} type="button" aria-label={desc} aria-pressed={sel}
                onClick={() => l && onPick(l)} onMouseEnter={() => { setTip(n.port); onHover(n.port); }}
                onFocus={() => { setTip(n.port); onHover(n.port); }} onBlur={() => { setTip(null); onHover(null); }}
                style={{ left: layout.xs[i], width: CHIP, borderTopColor: l ? color : undefined }}
                className={cx("absolute top-[10px] flex h-10 flex-col items-center justify-center rounded-lg border text-center transition duration-150",
                  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
                  l ? "border-t-[3px] bg-panel-2" : "border-dashed bg-transparent",
                  n.conflict ? "border-bad" : risk ? "border-bad/70" : l?.exposure === "network" ? "border-warn/70 bg-warn/10" : l ? "border-line-2" : "border-faint/70",
                  sel ? "ring-2 ring-accent" : "", hot ? "z-10 -translate-y-0.5 bg-panel shadow-lg" : "",
                  l ? "cursor-pointer" : "cursor-default")}>
                {h && <span className={cx("absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full",
                  { up: "bg-ok", warn: "bg-warn", down: "bg-bad", none: "bg-faint", unknown: "bg-faint" }[h])} />}
                <span className={cx("tnum font-mono text-[12px] font-semibold leading-4", l ? "text-ink" : "text-faint")}>{n.port}</span>
                <span className={cx("max-w-full truncate px-1 text-[9px] uppercase leading-3 tracking-wide", n.conflict ? "text-bad" : "text-faint")}>
                  {n.conflict && !l ? "taken" : label}{n.extra ? ` +${n.extra}` : ""}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {tipNode && <MapTip n={tipNode} x={Math.min(Math.max(tipX, 150), width - 150)} taken={taken} />}
    </div>
  );
}

function MapTip({ n, x, taken }: { n: Node; x: number; taken: Set<number> }) {
  const l = n.l;
  const after = nextFree(n.port + 1, taken);
  return (
    <div className="card pop pointer-events-none absolute top-[92px] z-30 w-[280px] -translate-x-1/2 px-3 py-2.5 text-xs shadow-xl" style={{ left: x + 12 }} role="tooltip">
      {l ? <>
        <div className="flex items-center gap-2">
          <span className="tnum font-mono font-semibold text-ink">:{n.port}</span>
          <span className="truncate font-medium text-ink">{l.title}</span>
          {l.framework && <span className="ml-auto shrink-0 text-faint">{l.framework.label}</span>}
        </div>
        {l.project && <p className="mt-1 truncate text-muted">{l.project.name}{l.project.git?.branch ? <span className="text-violet-400"> · ⎇ {l.project.git.branch}</span> : null}</p>}
        <p className="mt-1 text-muted">
          {l.probe?.ok && l.probe.status ? <span className={l.probe.status >= 400 ? "text-warn" : "text-ok"}>HTTP {l.probe.status} · {l.probe.ms} ms</span> : <span>{l.probe?.error || "not checked"}</span>}
          <span className="text-faint"> · {mb(l.memMb)} · up {duration(l.uptime)}</span>
        </p>
        {l.exposure === "network" && <p className="mt-1 text-warn">Reachable from other devices on your network.</p>}
        {n.conflict && n.app && <p className="mt-1 text-bad">{n.app.name} expects this port, but it is taken.</p>}
      </> : <>
        <div className="flex items-center gap-2">
          <span className="tnum font-mono font-semibold text-ink">:{n.port}</span>
          <span className="truncate font-medium text-ink">{n.app!.name}</span>
          <span className="ml-auto shrink-0 text-faint">saved app</span>
        </div>
        <p className="mt-1 text-muted">{n.conflict ? <span className="text-bad">Not running, and another process holds this port.</span> : "Not running; this is the port it starts on."}</p>
      </>}
      {after && <p className="mt-1.5 border-t border-line pt-1.5 text-faint">Next free port after this one: <span className="tnum font-mono text-ok">:{after}</span></p>}
      {l && <p className="mt-0.5 text-faint">Click for details.</p>}
    </div>
  );
}
