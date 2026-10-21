import { useMemo, useState } from "react";
import type { MapEdge, MapNode, Snapshot } from "../api";
import { useLocal, useNow } from "../usePorthaven";
import { ago, colorFor, cx, mb } from "../util";
import { Icon } from "./Icon";
import { Badge, Toggle } from "./ui";

const NODE_W = 196, NODE_H = 58, COL = 310, ROW = 82, PAD = 28;

type Placed = MapNode & { x: number; y: number; layer: number };

/** Columns from left to right: clients (browsers, tools), then each service after the ones that call it. */
function layout(nodes: MapNode[], edges: MapEdge[]) {
  const ids = new Set(nodes.map((n) => n.id));
  const es = edges.filter((e) => ids.has(e.from) && ids.has(e.to) && e.from !== e.to);
  const into = new Map<string, string[]>();
  for (const e of es) into.set(e.to, [...(into.get(e.to) || []), e.from]);
  const layer = new Map<string, number>();
  const depth = (id: string, stack: Set<string>): number => {
    if (layer.has(id)) return layer.get(id)!;
    const n = nodes.find((x) => x.id === id)!;
    if (n.client) { layer.set(id, 0); return 0; }
    if (stack.has(id)) return 1;   // a cycle: stop climbing
    stack.add(id);
    const ins = (into.get(id) || []).map((s) => depth(s, stack));
    stack.delete(id);
    const d = ins.length ? Math.max(...ins) + 1 : 1;
    layer.set(id, d);
    return d;
  };
  const linked = new Set(es.flatMap((e) => [e.from, e.to]));
  const connected = nodes.filter((n) => linked.has(n.id));
  const alone = nodes.filter((n) => !linked.has(n.id) && !n.client && !n.self);
  connected.forEach((n) => depth(n.id, new Set()));
  const hasClients = connected.some((n) => n.client);
  const cols = new Map<number, MapNode[]>();
  for (const n of connected) {
    const l = (layer.get(n.id) ?? 1) - (hasClients ? 0 : 1);
    cols.set(l, [...(cols.get(l) || []), n]);
  }
  const placed = new Map<string, Placed>();
  const order = [...cols.keys()].sort((a, b) => a - b);
  for (const l of order) {
    const list = cols.get(l)!;
    // order each column by where its callers sit, so lines cross less
    const at = (n: MapNode) => {
      const ys = (into.get(n.id) || []).map((s) => placed.get(s)?.y).filter((y): y is number => y != null);
      return ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : Number.MAX_SAFE_INTEGER;
    };
    list.sort((a, b) => at(a) - at(b) || a.title.localeCompare(b.title));
    list.forEach((n, i) => placed.set(n.id, { ...n, layer: l, x: PAD + l * COL, y: PAD + i * ROW }));
  }
  const height = Math.max(...[...cols.values()].map((c) => c.length), 1) * ROW + PAD;
  const width = (Math.max(...order, 0) + 1) * COL + PAD;
  return { placed, edges: es, alone, width, height };
}

const EDGE: Record<MapEdge["state"], { label: string; cls: string }> = {
  active: { label: "talking now", cls: "stroke-accent" },
  idle: { label: "quiet now", cls: "stroke-[var(--line-2)]" },
  broken: { label: "broken", cls: "stroke-bad" },
  declared: { label: "declared, no traffic yet", cls: "stroke-[var(--faint)]" },
};

export function MapView({ snap, onOpenPort, onOpenApp }: { snap: Snapshot; onOpenPort: (port: number) => void; onOpenApp: (id: string) => void }) {
  const [clients, setClients] = useLocal("porthaven.mapClients", true);
  const [hover, setHover] = useState<string | null>(null);
  const now = useNow(5000);
  const nodes = useMemo(() => snap.map.nodes.filter((n) => clients || !n.client), [snap.map.nodes, clients]);
  const edges = useMemo(() => snap.map.edges.filter((e) => nodes.some((n) => n.id === e.from) && nodes.some((n) => n.id === e.to)), [snap.map.edges, nodes]);
  const { placed, alone, width, height } = useMemo(() => layout(nodes, edges), [nodes, edges]);
  const byId = new Map(snap.map.nodes.map((n) => [n.id, n]));
  const counts = { active: 0, idle: 0, broken: 0, declared: 0 } as Record<MapEdge["state"], number>;
  for (const e of edges) counts[e.state]++;
  const near = hover ? new Set(edges.filter((e) => e.from === hover || e.to === hover).flatMap((e) => [e.from, e.to])) : null;
  const open = (n: MapNode) => (n.appId && !n.ports.length ? onOpenApp(n.appId) : n.ports[0] ? onOpenPort(n.ports[0]) : n.appId && onOpenApp(n.appId));

  return (
    <div className="flex min-h-0 flex-1 gap-4">
      <div className="card flex min-w-0 flex-1 flex-col overflow-hidden">
        <div className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3">
          <h2 className="text-sm font-semibold text-ink">Service map</h2>
          <span className="text-xs text-muted">which local services talk to which, from live connections</span>
          <div className="ml-auto flex items-center gap-3 text-[11px] text-muted">
            <Legend cls="bg-accent" label={`talking ${counts.active}`} anim />
            <Legend cls="bg-[var(--line-2)]" label={`quiet ${counts.idle}`} />
            <Legend cls="bg-bad" label={`broken ${counts.broken}`} dashed />
            <Legend cls="bg-[var(--faint)]" label={`declared ${counts.declared}`} dashed />
            <Toggle checked={clients} onChange={setClients} label={<span className="text-[11px]">Browsers and tools</span>} />
          </div>
        </div>
        <div className="relative min-h-0 flex-1 overflow-auto">
          {placed.size === 0 ? (
            <div className="flex h-full flex-col items-center justify-center gap-2 p-10 text-center">
              <div className="rounded-2xl bg-accent-soft p-4 text-accent"><Icon name="map" size={26} /></div>
              <p className="text-sm font-medium text-ink">No connections between local services yet</p>
              <p className="max-w-md text-xs text-muted">When one of your servers connects to another (a frontend calling its API, an API using Postgres or Redis), the link shows up here and lights up while it carries traffic. Dependencies you set on saved apps are drawn too.</p>
            </div>
          ) : (
            <svg width={width} height={height} className="block">
              <defs>
                <marker id="ph-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                  <path d="M0 0L10 5L0 10z" className="fill-[var(--faint)]" />
                </marker>
              </defs>
              {edges.map((e) => {
                const a = placed.get(e.from), b = placed.get(e.to);
                if (!a || !b) return null;
                const x1 = a.x + NODE_W, y1 = a.y + NODE_H / 2, x2 = b.x, y2 = b.y + NODE_H / 2;
                const back = x2 <= x1;
                const d = back
                  ? `M${x1},${y1} C${x1 + 60},${y1} ${x1 + 60},${Math.max(y1, y2) + ROW / 1.4} ${(x1 + x2) / 2},${Math.max(y1, y2) + ROW / 1.4} S${x2 - 60},${y2} ${x2},${y2}`
                  : `M${x1},${y1} C${x1 + (x2 - x1) / 2},${y1} ${x1 + (x2 - x1) / 2},${y2} ${x2},${y2}`;
                const dim = near && !(near.has(e.from) && near.has(e.to));
                const mx = (x1 + x2) / 2, my = back ? Math.max(y1, y2) + ROW / 1.4 : (y1 + y2) / 2;
                return (
                  <g key={e.id} className={cx("transition-opacity", dim && "opacity-15")}>
                    <path d={d} fill="none" strokeWidth={e.state === "active" ? 2.2 : 1.5} markerEnd="url(#ph-arrow)"
                      className={cx(EDGE[e.state].cls, e.state === "active" && "ph-flow", (e.state === "broken" || e.state === "declared") && "[stroke-dasharray:5_5]")} />
                    {(e.state === "active" || e.state === "broken") && (
                      <g transform={`translate(${mx},${my})`}>
                        <rect x={-34} y={-9} width={68} height={18} rx={9} className="fill-panel" />
                        <rect x={-34} y={-9} width={68} height={18} rx={9} className={e.state === "broken" ? "fill-bad/15 stroke-bad/40" : "fill-panel stroke-[var(--line)]"} />
                        <text textAnchor="middle" y={4} className={cx("text-[10px] font-medium", e.state === "broken" ? "fill-bad" : "fill-[var(--muted)]")}>
                          {e.state === "broken" ? "✕ broken" : `${e.count} conn`}{e.port && e.state !== "broken" ? ` :${e.port}` : ""}
                        </text>
                      </g>
                    )}
                    <title>{`${byId.get(e.from)?.title} → ${byId.get(e.to)?.title}${e.port ? ` :${e.port}` : ""}: ${EDGE[e.state].label}${e.last ? ` (last seen ${ago(e.last, now)})` : ""}`}</title>
                  </g>
                );
              })}
              {[...placed.values()].map((n) => {
                const color = n.client ? "var(--info)" : colorFor(n.project || n.title);
                const dim = near && !near.has(n.id);
                return (
                  <g key={n.id} transform={`translate(${n.x},${n.y})`} className={cx("cursor-pointer transition-opacity", dim && "opacity-30")}
                    onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)} onClick={() => !n.client && open(n)}>
                    <rect width={NODE_W} height={NODE_H} rx={12} className={cx("fill-panel", n.gone || n.stopped ? "stroke-[var(--line-2)] [stroke-dasharray:4_4]" : "stroke-[var(--line)]",
                      hover === n.id && "stroke-accent")} strokeWidth={1.2} />
                    <rect x={0} y={10} width={3} height={NODE_H - 20} rx={1.5} style={{ fill: color }} />
                    <foreignObject x={12} y={6} width={NODE_W - 20} height={NODE_H - 10}>
                      <div className="flex h-full flex-col justify-center leading-tight">
                        <div className="flex items-center gap-1.5">
                          {n.client && <Icon name="globe" size={12} className="shrink-0 text-info" />}
                          <span className={cx("truncate text-[12.5px] font-semibold", n.gone || n.stopped ? "text-faint" : "text-ink")}>{n.title}</span>
                        </div>
                        <div className="mt-0.5 flex items-center gap-1.5 truncate text-[10.5px] text-muted">
                          {n.ports.slice(0, 3).map((p) => <span key={p} className="font-mono text-ink-2">:{p}</span>)}
                          {n.client ? <span>client</span> : n.gone ? <span className="text-bad">gone</span> : n.stopped ? <span>not running</span> :
                            <>{n.framework && <span className="truncate">{n.framework}</span>}{n.memMb ? <span className="text-faint">{mb(n.memMb)}</span> : null}</>}
                        </div>
                      </div>
                    </foreignObject>
                  </g>
                );
              })}
            </svg>
          )}
        </div>
        {alone.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 border-t border-line px-4 py-2.5 text-[11px] text-muted">
            <span className="mr-1">Not talking to another local service:</span>
            {alone.map((n) => (
              <button key={n.id} onClick={() => open(n)} className="rounded-md border border-line px-1.5 py-0.5 text-ink-2 hover:border-accent hover:text-ink">
                {n.title}{n.ports[0] ? <span className="ml-1 font-mono text-faint">:{n.ports[0]}</span> : null}
              </button>
            ))}
          </div>
        )}
      </div>
      <aside className="card flex w-[300px] shrink-0 flex-col overflow-hidden">
        <div className="border-b border-line px-4 py-3">
          <h3 className="text-xs font-semibold text-ink-2">Links</h3>
          <p className="mt-0.5 text-[11px] text-muted">Quiet links stay for 30 minutes after their last connection.</p>
        </div>
        <ol className="min-h-0 flex-1 space-y-1 overflow-y-auto p-2">
          {edges.length === 0 && <li className="p-4 text-center text-xs text-muted">No links yet.</li>}
          {[...edges].sort((a, b) => Number(b.state === "broken") - Number(a.state === "broken") || Number(b.state === "active") - Number(a.state === "active")).map((e) => (
            <li key={e.id} onMouseEnter={() => setHover(e.to)} onMouseLeave={() => setHover(null)}
              className={cx("rounded-lg border px-2.5 py-2 text-xs", e.state === "broken" ? "border-bad/30 bg-bad/5" : "border-line")}>
              <div className="flex items-center gap-1.5 text-ink">
                <span className="truncate font-medium">{byId.get(e.from)?.title}</span>
                <Icon name="chevron" size={11} className="shrink-0 text-faint" />
                <span className="truncate font-medium">{byId.get(e.to)?.title}</span>
                {e.port && <span className="ml-auto shrink-0 font-mono text-[10px] text-faint">:{e.port}</span>}
              </div>
              <div className="mt-1 flex items-center gap-1.5">
                <Badge tone={e.state === "active" ? "accent" : e.state === "broken" ? "bad" : "neutral"}>{EDGE[e.state].label}</Badge>
                {e.state === "active" && <span className="text-[11px] text-muted">{e.count} open</span>}
                {e.state === "broken" && <span className="text-[11px] text-bad">{e.declared && !e.last ? "needs it, but it is not running" : "the server went away"}</span>}
                {e.state === "idle" && e.last && <span className="text-[11px] text-faint">last {ago(e.last, now)}</span>}
              </div>
            </li>
          ))}
        </ol>
      </aside>
    </div>
  );
}

function Legend({ cls, label, dashed, anim }: { cls: string; label: string; dashed?: boolean; anim?: boolean }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={cx("inline-block h-0.5 w-5 rounded", cls, dashed && "opacity-70 [mask:repeating-linear-gradient(90deg,#000_0_4px,transparent_4px_7px)]", anim && "pulse")} />
      {label}
    </span>
  );
}
