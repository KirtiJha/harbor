import { useMemo } from "react";
import type { App, Listener, Snapshot } from "../api";
import type { Actions } from "../actions";
import { useLocal, useNow } from "../usePorthaven";
import { colorFor, cx, duration, mb, PALETTE } from "../util";
import { RANGES, useInsights, type Range } from "./ActivityView";
import { BarList, Donut, TimeChart } from "./charts";
import { Icon } from "./Icon";
import { Badge, Button, Sparkline, Spinner } from "./ui";

export function InsightsView({ snap, actions, onOpenPort, onEditApp }: {
  snap: Snapshot; actions: Actions; onOpenPort: (l: Listener) => void; onEditApp: (a: App) => void;
}) {
  const [range, setRange] = useLocal<Range>("porthaven.insightsRange", "24h");
  const { data, loading } = useInsights(range, snap.activity.length);
  const now = useNow(30000);
  const r = RANGES.find((x) => x.id === range)!;
  const start = now - r.seconds;
  const samples = data?.samples || [];
  const ts = samples.map((s) => s.ts);
  const events = data?.activity || [];
  const mine = snap.listeners.filter((l) => !["system", "app"].includes(l.kind));

  /* ---------------- KPIs */
  const first = samples[0], last = samples[samples.length - 1];
  const delta = (k: "dev" | "memMb" | "cpu" | "conns") => (first && last ? last[k] - first[k] : 0);
  const crashes = events.filter((e) => e.type === "crashed").length;
  const conflicts = events.filter((e) => e.type === "conflict").length;
  const healthVals = Object.values(data?.health || {}).filter((h) => h.avg != null);
  const avgMs = healthVals.length ? Math.round(healthVals.reduce((a, h) => a + (h.avg || 0), 0) / healthVals.length) : null;
  const okRate = healthVals.length ? healthVals.reduce((a, h) => a + h.ok, 0) / Math.max(1, healthVals.reduce((a, h) => a + h.n, 0)) : null;

  const kpis = [
    { label: "Dev ports", value: String(snap.summary.dev), d: delta("dev"), spark: samples.map((s) => s.dev), color: "var(--accent)", fmt: (v: number) => `${v > 0 ? "+" : ""}${Math.round(v)}` },
    { label: "Memory held", value: mb(snap.summary.memMb), d: delta("memMb"), spark: samples.map((s) => s.memMb), color: "var(--info)", fmt: (v: number) => `${v > 0 ? "+" : ""}${mb(Math.abs(v))}`.replace("+-", "-") },
    { label: "CPU", value: `${snap.summary.cpu}%`, d: delta("cpu"), spark: samples.map((s) => s.cpu), color: "#a78bfa", fmt: (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(1)}%` },
    { label: "Open connections", value: String(mine.reduce((a, l) => a + l.connections, 0)), d: delta("conns"), spark: samples.map((s) => s.conns), color: "#f472b6", fmt: (v: number) => `${v > 0 ? "+" : ""}${Math.round(v)}` },
    { label: "Avg response", value: avgMs != null ? `${avgMs} ms` : "—", sub: okRate != null ? `${Math.round(okRate * 1000) / 10}% of checks OK` : "", color: "var(--ok)" },
    { label: "Crashes · conflicts", value: `${crashes} · ${conflicts}`, sub: `in the last ${r.label}`, color: crashes ? "var(--bad)" : "var(--muted)" },
  ];

  /* ---------------- memory by project over time */
  const projects = useMemo(() => {
    const tot = new Map<string, number>();
    for (const s of samples) for (const [k, v] of Object.entries(s.byProject || {})) tot.set(k, (tot.get(k) || 0) + v);
    return [...tot.entries()].sort((a, b) => b[1] - a[1]).map(([k]) => k).slice(0, 8);
  }, [samples]);
  // Distinct colours by rank, shared by the chart and the donut so a project looks the same in both.
  const projColor = (name: string, i: number) => (name === "other" ? "#64748b" : PALETTE[i % PALETTE.length]);
  const memSeries = projects.map((p, i) => ({ key: p, label: p, color: projColor(p, i), values: samples.map((s) => s.byProject?.[p] || 0) }));

  /* ---------------- right now */
  const memNow = useMemo(() => {
    const m = new Map<string, number>();
    for (const l of mine) { const k = l.project?.name || l.framework?.label || l.command; m.set(k, (m.get(k) || 0) + (l.memMb || 0)); }
    const sorted = [...m.entries()].sort((a, b) => b[1] - a[1]);
    return sorted.map(([label, value], i) => {
      const inChart = projects.indexOf(label);
      return { label, value, color: inChart >= 0 ? PALETTE[inChart % PALETTE.length] : PALETTE[(projects.length + i) % PALETTE.length] };
    });
  }, [mine, projects]);
  const fwMix = useMemo(() => {
    const m = new Map<string, number>();
    for (const l of mine) { const k = l.framework?.label || "Other"; m.set(k, (m.get(k) || 0) + 1); }
    return [...m.entries()].sort((a, b) => b[1] - a[1]).map(([label, value], i) => ({ label, value, color: PALETTE[(i + 3) % PALETTE.length] }));
  }, [mine]);

  /* ---------------- leaderboards */
  const restarts = useMemo(() => {
    const m = new Map<string, { n: number; port: number }>();
    for (const e of events) if (e.type === "opened" && e.port && e.port < 32768) { const k = e.title; const v = m.get(k) || { n: 0, port: e.port }; v.n += 1; m.set(k, v); }
    return [...m.entries()].filter(([, v]) => v.n > 1).sort((a, b) => b[1].n - a[1].n).slice(0, 5);
  }, [events]);
  const contested = useMemo(() => {
    const m = new Map<number, number>();
    for (const e of events) if (e.type === "conflict" && e.port) m.set(e.port, (m.get(e.port) || 0) + 1);
    return [...m.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5);
  }, [events]);
  const longest = [...mine].sort((a, b) => (b.uptime || 0) - (a.uptime || 0)).slice(0, 5);

  /* ---------------- health */
  const health = mine.filter((l) => l.health && l.health.n > 0).map((l) => ({ l, h: data?.health?.[String(l.port)] }))
    .sort((a, b) => (a.l.health!.up / a.l.health!.n) - (b.l.health!.up / b.l.health!.n) || (b.h?.avg || 0) - (a.h?.avg || 0));

  /* ---------------- suggestions */
  const tips = useMemo(() => {
    const out: { tone: "warn" | "info" | "bad" | "ok"; icon: string; title: string; body: string; action?: { label: string; run: () => void } }[] = [];
    for (const l of snap.listeners.filter((x) => x.exposureRisk && x.exposureRisk.level !== "medium")) {
      out.push({ tone: "bad", icon: "warn", title: `:${l.port} ${l.exposureRisk!.title}`, body: `${l.exposureRisk!.why} ${l.exposureRisk!.fix}`,
        action: { label: "Review", run: () => onOpenPort(l) } });
    }
    const sleepy = snap.listeners.filter((l) => l.idleFor && l.appId).map((l) => snap.apps.find((a) => a.id === l.appId)).filter((a): a is App => !!a && !a.sleepAfter);
    for (const a of sleepy.slice(0, 2)) {
      out.push({ tone: "info", icon: "moon", title: `Let ${a.name} sleep when quiet`, body: "It has been idle for hours. With sleep on, it stops by itself and wakes on the next request to its stable address.",
        action: { label: "Turn on", run: () => onEditApp({ ...a, sleepAfter: 60 }) } });
    }
    const idle = snap.listeners.filter((l) => l.idleFor);
    if (idle.length) out.push({ tone: "warn", icon: "moon", title: `${idle.length} forgotten server${idle.length > 1 ? "s" : ""} holding ${mb(snap.summary.idleMemMb)}`,
      body: idle.map((l) => `:${l.port} ${l.title}`).join(", "), action: { label: "Stop them", run: () => void actions.killMany(idle, "app", `Stop ${idle.length} idle server${idle.length > 1 ? "s" : ""}?`) } });
    const exposed = mine.filter((l) => l.exposure === "network" && l.kind === "dev");
    if (exposed.length) out.push({ tone: "warn", icon: "network", title: `${exposed.length} dev server${exposed.length > 1 ? "s are" : " is"} reachable from your network`,
      body: `${exposed.map((l) => `:${l.port} ${l.title}`).join(", ")}. Bind to 127.0.0.1 unless you test from another device.`, action: { label: "Review", run: () => onOpenPort(exposed[0]) } });
    for (const [port, n] of contested.filter(([, n]) => n >= 2)) {
      const app = snap.apps.find((a) => a.port === port);
      out.push({ tone: "info", icon: "warn", title: `:${port} was contested ${n} times`, body: app ? `${app.name} keeps asking for it. Give it its own port, or open it by its stable name ${app.stableUrl || ""}.` : "Two projects want the same port. Give one of them another port.",
        action: app ? { label: `Edit ${app.name}`, run: () => onEditApp(app) } : undefined });
    }
    const drift = snap.apps.filter((a) => a.drift);
    if (drift.length) out.push({ tone: "info", icon: "external", title: `${drift.length} app${drift.length > 1 ? "s" : ""} running off ${drift.length > 1 ? "their" : "its"} saved port`, body: drift.map((a) => `${a.name} on :${a.ports.join(", :")} (saved :${a.port})`).join("; ") + ". Stable names keep working either way." });
    const heavy = mine.filter((l) => (l.memMb || 0) > 1024);
    if (heavy.length) out.push({ tone: "info", icon: "activity", title: `${heavy.length} server${heavy.length > 1 ? "s use" : " uses"} over 1 GB`, body: heavy.map((l) => `:${l.port} ${l.title} (${mb(l.memMb)})`).join(", "), action: { label: "Look", run: () => onOpenPort(heavy[0]) } });
    const slow = health.filter(({ h }) => h?.avg && h.avg > 800);
    if (slow.length) out.push({ tone: "info", icon: "bolt", title: `${slow.length} slow server${slow.length > 1 ? "s" : ""}`, body: slow.map(({ l, h }) => `:${l.port} averages ${h!.avg} ms`).join(", ") });
    if (crashes) out.push({ tone: "bad", icon: "warn", title: `${crashes} crash${crashes > 1 ? "es" : ""} in the last ${r.label}`, body: "Open the app in Apps to read its output around the crash, or turn on auto-restart." });
    if (!snap.listeners.some((l) => l.meta.watched)) out.push({ tone: "ok", icon: "bell", title: "Watch the ports you depend on", body: "Press w on a row and Porthaven tells you when it goes down, with a button to start it again." });
    if (!out.length) out.push({ tone: "ok", icon: "check", title: "All clear", body: "No idle, exposed, contested or crashing servers." });
    return out;
  }, [snap, mine, contested, health, crashes, actions, onOpenPort, onEditApp, r.label]);

  const historyFrom = samples.length ? samples[0].ts : now;
  // While history is shorter than the window, chart what exists instead of squeezing it against "now".
  const chartStart = samples.length > 1 ? Math.max(start, samples[0].ts - 60) : start;
  const partial = chartStart > start + 60;

  return (
    <div className="min-h-0 flex-1 space-y-4 overflow-y-auto pr-1">
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <h2 className="text-lg font-semibold text-ink">Insights</h2>
          <p className="text-xs text-muted">How your local servers behave over time{samples.length ? ` · history since ${new Date(historyFrom * 1000).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" })}` : ""}.</p>
        </div>
        {loading && <Spinner />}
        <div className="ml-auto flex rounded-lg border border-line bg-panel p-0.5 text-xs">
          {RANGES.map((x) => (
            <button key={x.id} onClick={() => setRange(x.id)} className={cx("rounded-md px-2.5 py-1 font-medium", range === x.id ? "bg-accent-soft text-accent-ink" : "text-muted hover:text-ink")}>{x.id}</button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-6 gap-3">
        {kpis.map((k) => (
          <div key={k.label} className="card relative overflow-hidden px-4 py-3">
            <div className="text-[11px] text-muted">{k.label}</div>
            <div className="tnum mt-1 text-2xl font-semibold text-ink">{k.value}</div>
            {"spark" in k && k.spark ? (
              <div className="mt-1 flex items-end justify-between gap-2">
                <span className={cx("tnum text-[11px]", !k.d ? "text-faint" : "text-muted")}>{k.spark.length > 1 ? `${k.fmt!(k.d!)} in ${range}` : "collecting…"}</span>
                <Sparkline values={k.spark} width={70} height={22} color={k.color} />
              </div>
            ) : <div className="mt-1 text-[11px] text-faint">{k.sub}</div>}
          </div>
        ))}
      </div>

      <div className="grid grid-cols-[1.6fr_1fr] gap-4">
        <section className="card p-4">
          <div className="mb-2 flex items-baseline gap-2"><h3 className="text-sm font-semibold text-ink">Memory by project</h3><span className="text-xs text-muted">stacked, MB</span>
            {partial && <span className="ml-auto text-[11px] text-faint">history since {new Date(chartStart * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}; fills up as Porthaven runs</span>}</div>
          <TimeChart ts={ts} series={memSeries} stacked start={chartStart} end={now} height={220} format={(v) => mb(v)} />
          <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">{memSeries.map((s) => <span key={s.key} className="flex items-center gap-1.5 text-[11px] text-muted"><span className="h-2 w-2 rounded-sm" style={{ background: s.color }} />{s.label}</span>)}</div>
        </section>
        <section className="card p-4">
          <h3 className="mb-3 text-sm font-semibold text-ink">Right now</h3>
          <Donut items={memNow} center={mb(snap.summary.memMb)} sub="memory" />
          <div className="mt-4 border-t border-line pt-3">
            <p className="mb-2 text-[11px] font-medium text-muted">Frameworks</p>
            <div className="flex h-2.5 overflow-hidden rounded-full">{fwMix.map((f) => <span key={f.label} title={`${f.label}: ${f.value}`} style={{ width: `${(f.value / Math.max(1, mine.length)) * 100}%`, background: f.color }} />)}</div>
            <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">{fwMix.map((f) => <span key={f.label} className="flex items-center gap-1.5 text-[11px] text-muted"><span className="h-2 w-2 rounded-sm" style={{ background: f.color }} />{f.label} <b className="text-ink-2">{f.value}</b></span>)}</div>
          </div>
        </section>
      </div>

      <div className="grid grid-cols-[1.6fr_1fr] gap-4">
        <section className="card p-4">
          <div className="mb-2 flex items-baseline gap-2"><h3 className="text-sm font-semibold text-ink">Ports over time</h3><span className="text-xs text-muted">listening, idle and network-exposed</span></div>
          <TimeChart ts={ts} start={chartStart} end={now} height={170} format={(v) => String(Math.round(v))}
            series={[{ key: "dev", label: "Dev ports", color: "#2dd4bf", values: samples.map((s) => s.dev) },
              { key: "idle", label: "Idle", color: "#a78bfa", values: samples.map((s) => s.idle) },
              { key: "exposed", label: "On network", color: "#fbbf24", values: samples.map((s) => s.exposed) }]} />
          <div className="mt-2 flex gap-3">{[["Dev ports", "#2dd4bf"], ["Idle", "#a78bfa"], ["On network (incl. system)", "#fbbf24"]].map(([l, c]) => (
            <span key={l} className="flex items-center gap-1.5 text-[11px] text-muted"><span className="h-0.5 w-3 rounded" style={{ background: c }} />{l}</span>))}</div>
        </section>
        <section className="card p-4">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-ink"><Icon name="sparkle" size={14} className="text-accent" />Suggestions</h3>
          <ul className="space-y-2">
            {tips.map((t, i) => (
              <li key={i} className={cx("rounded-xl border px-3 py-2.5",
                t.tone === "warn" ? "border-warn/25 bg-warn/5" : t.tone === "bad" ? "border-bad/25 bg-bad/5" : t.tone === "ok" ? "border-ok/20 bg-ok/5" : "border-info/20 bg-info/5")}>
                <div className="flex items-start gap-2">
                  <Icon name={t.icon} size={14} className={cx("mt-0.5 shrink-0", t.tone === "warn" ? "text-warn" : t.tone === "bad" ? "text-bad" : t.tone === "ok" ? "text-ok" : "text-info")} />
                  <div className="min-w-0 flex-1">
                    <div className="text-xs font-semibold text-ink">{t.title}</div>
                    <div className="mt-0.5 text-[11px] leading-relaxed text-muted">{t.body}</div>
                  </div>
                  {t.action && <Button size="sm" variant="outline" onClick={t.action.run}>{t.action.label}</Button>}
                </div>
              </li>
            ))}
          </ul>
        </section>
      </div>

      <section className="card p-4">
        <div className="mb-3 flex items-baseline gap-2"><h3 className="text-sm font-semibold text-ink">Health</h3><span className="text-xs text-muted">from Porthaven's HTTP checks while it has been running</span></div>
        {health.length === 0 ? <p className="py-4 text-center text-xs text-muted">No HTTP checks yet.</p> : (
          <div className="overflow-hidden rounded-xl border border-line">
            <div className="grid grid-cols-[80px_1.4fr_120px_90px_90px_1fr_80px] gap-3 bg-panel-2/60 px-4 py-2 text-[11px] font-medium uppercase tracking-wide text-faint">
              <span>Port</span><span>Server</span><span>Checks OK</span><span>Avg</span><span>p95</span><span>Response time</span><span>Status</span>
            </div>
            {health.map(({ l, h }) => {
              const rate = l.health!.up / l.health!.n;
              return (
                <button key={l.id} onClick={() => onOpenPort(l)} className="grid w-full grid-cols-[80px_1.4fr_120px_90px_90px_1fr_80px] items-center gap-3 border-t border-line px-4 py-2 text-left text-xs hover:bg-panel-2/50">
                  <span className="tnum font-mono font-semibold text-ink">:{l.port}</span>
                  <span className="truncate text-ink-2">{l.title}</span>
                  <span className="flex items-center gap-2">
                    <span className="h-1.5 w-14 overflow-hidden rounded-full bg-panel-2"><span className="block h-full rounded-full" style={{ width: `${rate * 100}%`, background: rate > 0.98 ? "var(--ok)" : rate > 0.9 ? "var(--warn)" : "var(--bad)" }} /></span>
                    <span className="tnum text-muted">{Math.round(rate * 100)}%</span>
                  </span>
                  <span className="tnum text-ink-2">{h?.avg != null ? `${h.avg} ms` : "—"}</span>
                  <span className="tnum text-muted">{h?.p95 != null ? `${h.p95} ms` : "—"}</span>
                  <Sparkline values={l.health!.ms.map((x) => x || 0)} width={160} height={20} color="var(--info)" />
                  <span>{l.probe?.status ? <Badge tone={l.probe.status < 400 ? "ok" : l.probe.status < 500 ? "warn" : "bad"}>{l.probe.status}</Badge> : <Badge tone="bad">down</Badge>}</span>
                </button>
              );
            })}
          </div>
        )}
      </section>

      <div className="grid grid-cols-3 gap-4">
        <section className="card p-4">
          <h3 className="mb-3 text-sm font-semibold text-ink">Running longest</h3>
          <BarList items={longest.map((l) => ({ key: l.id, label: `:${l.port} ${l.title}`, value: l.uptime || 0, color: colorFor(l.project?.name || l.title) }))}
            format={(v) => duration(v)} onClick={(k) => { const l = mine.find((x) => x.id === k); if (l) onOpenPort(l); }} />
        </section>
        <section className="card p-4">
          <h3 className="mb-3 text-sm font-semibold text-ink">Most restarted <span className="font-normal text-muted">· {range}</span></h3>
          {restarts.length ? <BarList items={restarts.map(([t, v]) => ({ label: t, sub: `:${v.port}`, value: v.n - 1, color: "#60a5fa" }))} format={(v) => `${v}×`} />
            : <p className="py-4 text-center text-xs text-muted">Nothing restarted in this window.</p>}
        </section>
        <section className="card p-4">
          <h3 className="mb-3 text-sm font-semibold text-ink">Most contested ports <span className="font-normal text-muted">· {range}</span></h3>
          {contested.length ? <BarList items={contested.map(([p, n]) => ({ label: `:${p}`, value: n, color: "#fbbf24" }))} format={(v) => `${v}×`} />
            : <p className="py-4 text-center text-xs text-muted">No port conflicts in this window.</p>}
        </section>
      </div>
    </div>
  );
}
