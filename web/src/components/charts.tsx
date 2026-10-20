import { useMemo, useRef, useState, type ReactNode } from "react";
import { cx } from "../util";

/* Small, dependency-free SVG charts with hover read-outs. Every chart sizes to its container width. */

function useWidth(initial = 600) {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(initial);
  const obs = useRef<ResizeObserver | null>(null);
  const set = (el: HTMLDivElement | null) => {
    (ref as React.MutableRefObject<HTMLDivElement | null>).current = el;
    obs.current?.disconnect();
    if (el) {
      obs.current = new ResizeObserver(([e]) => setW(Math.max(120, Math.floor(e.contentRect.width))));
      obs.current.observe(el);
    }
  };
  return [set, w] as const;
}

export function timeLabel(ts: number, span: number) {
  const d = new Date(ts * 1000);
  if (span > 2 * 86400) return d.toLocaleDateString([], { weekday: "short", day: "numeric" }) + (span < 4 * 86400 ? " " + d.toLocaleTimeString([], { hour: "2-digit" }) : "");
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function niceMax(v: number) {
  if (v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  const n = v / p;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p;
}

export type Series = { key: string; label: string; color: string; values: number[] };

/** Line or stacked-area chart over time. */
export function TimeChart({ ts, series, height = 180, stacked = false, start, end, unit = "", format }: {
  ts: number[]; series: Series[]; height?: number; stacked?: boolean; start: number; end: number; unit?: string; format?: (v: number) => string;
}) {
  const [ref, w] = useWidth();
  const [hover, setHover] = useState<number | null>(null);
  const pad = { l: 56, r: 10, t: 10, b: 22 };
  const iw = w - pad.l - pad.r, ih = height - pad.t - pad.b;
  const fmt = format || ((v: number) => `${Math.round(v * 10) / 10}${unit}`);
  const stacks = useMemo(() => {
    const acc = ts.map(() => 0);
    return series.map((s) => {
      const lo = [...acc];
      const hi = s.values.map((v, i) => (stacked ? (acc[i] += v || 0) : v || 0));
      return { s, lo: stacked ? lo : ts.map(() => 0), hi };
    });
  }, [ts, series, stacked]);
  const max = niceMax(Math.max(1, ...stacks.flatMap((x) => x.hi)));
  const x = (t: number) => pad.l + ((t - start) / Math.max(1, end - start)) * iw;
  const y = (v: number) => pad.t + ih - (v / max) * ih;
  const ticks = 5;
  const empty = ts.length < 2;

  return (
    <div ref={ref} className="relative select-none" onMouseLeave={() => setHover(null)}>
      <svg width={w} height={height}
        onMouseMove={(e) => {
          if (empty) return;
          const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
          const t = start + ((e.clientX - r.left - pad.l) / iw) * (end - start);
          let best = 0;
          ts.forEach((v, i) => { if (Math.abs(v - t) < Math.abs(ts[best] - t)) best = i; });
          setHover(best);
        }}>
        {[0, 0.25, 0.5, 0.75, 1].map((f) => (
          <g key={f}>
            <line x1={pad.l} x2={w - pad.r} y1={y(max * f)} y2={y(max * f)} stroke="var(--line)" strokeDasharray={f ? "3 4" : undefined} />
            <text x={pad.l - 6} y={y(max * f) + 3} textAnchor="end" className="fill-[var(--faint)] text-[10px]">{fmt(max * f)}</text>
          </g>
        ))}
        {Array.from({ length: ticks }, (_, i) => start + ((end - start) * (i + 0.5)) / ticks).map((t) => (
          <text key={t} x={x(t)} y={height - 6} textAnchor="middle" className="fill-[var(--faint)] text-[10px]">{timeLabel(t, end - start)}</text>
        ))}
        {!empty && stacks.map(({ s, lo, hi }) => {
          const top = hi.map((v, i) => `${i ? "L" : "M"}${x(ts[i]).toFixed(1)},${y(v).toFixed(1)}`).join("");
          const bottom = lo.map((v, i) => `L${x(ts[i]).toFixed(1)},${y(v).toFixed(1)}`).reverse().join("");
          return (
            <g key={s.key}>
              <path d={`${top}${bottom}Z`} fill={s.color} opacity={stacked ? 0.55 : 0.12} />
              <path d={top} fill="none" stroke={s.color} strokeWidth={1.6} strokeLinejoin="round" />
            </g>
          );
        })}
        {hover != null && !empty && (
          <g>
            <line x1={x(ts[hover])} x2={x(ts[hover])} y1={pad.t} y2={pad.t + ih} stroke="var(--muted)" strokeDasharray="2 3" />
            {stacks.map(({ s, hi }) => <circle key={s.key} cx={x(ts[hover])} cy={y(hi[hover])} r={3} fill={s.color} stroke="var(--panel)" strokeWidth={1.5} />)}
          </g>
        )}
      </svg>
      {empty && <div className="absolute inset-0 flex items-center justify-center text-xs text-muted">Collecting history: Porthaven records a sample every minute.</div>}
      {hover != null && !empty && (
        <Tip x={x(ts[hover])} w={w}>
          <div className="mb-1 text-[11px] text-faint">{new Date(ts[hover] * 1000).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" })}</div>
          {[...series].reverse().map((s) => (
            <div key={s.key} className="flex items-center gap-2 text-xs">
              <span className="h-2 w-2 rounded-sm" style={{ background: s.color }} />
              <span className="max-w-[160px] truncate text-ink-2">{s.label}</span>
              <span className="tnum ml-auto pl-3 font-medium text-ink">{fmt(s.values[hover] || 0)}</span>
            </div>
          ))}
        </Tip>
      )}
    </div>
  );
}

function Tip({ x, w, children, top = 8 }: { x: number; w: number; children: ReactNode; top?: number }) {
  const left = x > w * 0.6;
  return (
    <div className="card pointer-events-none absolute z-10 min-w-[160px] px-3 py-2" style={{ top, ...(left ? { right: w - x + 12 } : { left: x + 12 }) }}>
      {children}
    </div>
  );
}

/** Stacked bars over time buckets. */
export function StackedBars({ buckets, keys, colors, labels, height = 150, start, end }: {
  buckets: { t: number; counts: Record<string, number> }[]; keys: string[]; colors: Record<string, string>; labels: Record<string, string>;
  height?: number; start: number; end: number;
}) {
  const [ref, w] = useWidth();
  const [hover, setHover] = useState<number | null>(null);
  const pad = { l: 28, r: 6, t: 8, b: 20 };
  const iw = w - pad.l - pad.r, ih = height - pad.t - pad.b;
  const totals = buckets.map((b) => keys.reduce((a, k) => a + (b.counts[k] || 0), 0));
  const max = niceMax(Math.max(1, ...totals));
  const bw = iw / Math.max(1, buckets.length);
  return (
    <div ref={ref} className="relative select-none" onMouseLeave={() => setHover(null)}>
      <svg width={w} height={height}>
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line x1={pad.l} x2={w - pad.r} y1={pad.t + ih - f * ih} y2={pad.t + ih - f * ih} stroke="var(--line)" strokeDasharray={f ? "3 4" : undefined} />
            <text x={pad.l - 5} y={pad.t + ih - f * ih + 3} textAnchor="end" className="fill-[var(--faint)] text-[10px]">{Math.round(max * f)}</text>
          </g>
        ))}
        {buckets.map((b, i) => {
          let acc = 0;
          return (
            <g key={b.t} onMouseEnter={() => setHover(i)}>
              <rect x={pad.l + i * bw} y={pad.t} width={bw} height={ih} fill="transparent" />
              {keys.map((k) => {
                const v = b.counts[k] || 0;
                if (!v) return null;
                const hgt = (v / max) * ih;
                acc += hgt;
                return <rect key={k} x={pad.l + i * bw + bw * 0.14} y={pad.t + ih - acc} width={bw * 0.72} height={Math.max(1, hgt - 1)} rx={1.5}
                  fill={colors[k]} opacity={hover == null || hover === i ? 0.95 : 0.45} />;
              })}
            </g>
          );
        })}
        {[0, 0.5, 1].map((f) => (
          <text key={f} x={pad.l + f * iw} y={height - 5} textAnchor={f === 0 ? "start" : f === 1 ? "end" : "middle"} className="fill-[var(--faint)] text-[10px]">
            {timeLabel(start + f * (end - start), end - start)}
          </text>
        ))}
      </svg>
      {hover != null && totals[hover] > 0 && (
        <Tip x={pad.l + hover * bw + bw / 2} w={w}>
          <div className="mb-1 text-[11px] text-faint">{timeLabel(buckets[hover].t, end - start)} · {totals[hover]} event{totals[hover] > 1 ? "s" : ""}</div>
          {keys.filter((k) => buckets[hover].counts[k]).map((k) => (
            <div key={k} className="flex items-center gap-2 text-xs">
              <span className="h-2 w-2 rounded-sm" style={{ background: colors[k] }} />
              <span className="text-ink-2">{labels[k]}</span>
              <span className="tnum ml-auto pl-3 font-medium text-ink">{buckets[hover].counts[k]}</span>
            </div>
          ))}
        </Tip>
      )}
    </div>
  );
}

/** Donut with a centre label and a hoverable legend. */
export function Donut({ items, size = 150, center, sub }: { items: { label: string; value: number; color: string }[]; size?: number; center: ReactNode; sub?: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const total = items.reduce((a, i) => a + i.value, 0) || 1;
  const r = size / 2 - 10, c = 2 * Math.PI * r;
  let off = 0;
  return (
    <div className="flex items-center gap-5">
      <div className="relative shrink-0" style={{ width: size, height: size }}>
        <svg width={size} height={size} className="-rotate-90">
          <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--line)" strokeWidth={14} />
          {items.map((it, i) => {
            const len = (it.value / total) * c;
            const el = (
              <circle key={it.label} cx={size / 2} cy={size / 2} r={r} fill="none" stroke={it.color} strokeWidth={hover === i ? 18 : 14}
                strokeDasharray={`${Math.max(0, len - 2)} ${c}`} strokeDashoffset={-off} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}
                className="cursor-default transition-all" />
            );
            off += len;
            return el;
          })}
        </svg>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center">
          <div className="tnum text-lg font-semibold text-ink">{hover != null ? `${Math.round((items[hover].value / total) * 100)}%` : center}</div>
          <div className="max-w-[90px] truncate text-[10px] text-muted">{hover != null ? items[hover].label : sub}</div>
        </div>
      </div>
      <ul className="min-w-0 flex-1 space-y-1">
        {items.slice(0, 7).map((it, i) => (
          <li key={it.label} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}
            className={cx("flex items-center gap-2 rounded px-1 text-xs", hover === i && "bg-panel-2")}>
            <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: it.color }} />
            <span className="truncate text-ink-2">{it.label}</span>
            <span className="tnum ml-auto text-muted">{Math.round((it.value / total) * 100)}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Weekday x hour heatmap. */
export function Heatmap({ cells, color = "45 212 191" }: { cells: number[][]; color?: string }) {
  const [hover, setHover] = useState<[number, number] | null>(null);
  const max = Math.max(1, ...cells.flat());
  const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  return (
    <div className="relative">
      <div className="grid gap-[3px]" style={{ gridTemplateColumns: "28px repeat(24, minmax(0, 1fr))" }}>
        {cells.map((row, d) => (
          <div key={d} className="contents">
            <span className="pr-1 text-right text-[10px] leading-[14px] text-faint">{days[d]}</span>
            {row.map((v, h) => (
              <span key={h} onMouseEnter={() => setHover([d, h])} onMouseLeave={() => setHover(null)}
                className={cx("h-[14px] rounded-[3px] transition", hover && hover[0] === d && hover[1] === h && "ring-1 ring-ink")}
                style={{ background: v ? `rgb(${color} / ${0.15 + 0.85 * (v / max)})` : "var(--panel-2)" }} />
            ))}
          </div>
        ))}
        <span />
        {Array.from({ length: 24 }, (_, h) => <span key={h} className="text-center text-[9px] text-faint">{h % 6 === 0 ? h : ""}</span>)}
      </div>
      <p className="mt-2 h-4 text-[11px] text-muted">
        {hover ? <>{days[hover[0]]} {String(hover[1]).padStart(2, "0")}:00 · <b className="text-ink">{cells[hover[0]][hover[1]]}</b> event{cells[hover[0]][hover[1]] === 1 ? "" : "s"}</> : "Hover a square: when your servers start, stop and crash."}
      </p>
    </div>
  );
}

/** Horizontal bars with labels. */
export function BarList({ items, format, onClick }: { items: { label: string; value: number; color?: string; sub?: string; key?: string }[]; format: (v: number) => string; onClick?: (k: string) => void }) {
  const max = Math.max(1, ...items.map((i) => i.value));
  return (
    <ul className="space-y-2">
      {items.map((it) => (
        <li key={it.key || it.label} onClick={() => onClick?.(it.key || it.label)} className={cx("group", onClick && "cursor-pointer")}>
          <div className="mb-1 flex items-baseline gap-2 text-xs">
            <span className="truncate text-ink-2 group-hover:text-ink">{it.label}</span>
            {it.sub && <span className="truncate text-[11px] text-faint">{it.sub}</span>}
            <span className="tnum ml-auto shrink-0 font-medium text-ink">{format(it.value)}</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-panel-2">
            <div className="h-full rounded-full transition-all duration-700" style={{ width: `${(it.value / max) * 100}%`, background: it.color || "var(--accent)" }} />
          </div>
        </li>
      ))}
    </ul>
  );
}
