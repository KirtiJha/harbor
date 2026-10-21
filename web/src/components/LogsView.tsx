import { useEffect, useMemo, useRef, useState } from "react";
import { api, type LogMatch, type Snapshot } from "../api";
import { useLocal } from "../usePorthaven";
import { clock, colorFor, cx } from "../util";
import { Icon } from "./Icon";
import { Badge, Spinner } from "./ui";

type Result = Awaited<ReturnType<typeof api.searchLogs>>;
const WINDOWS: [string, number][] = [["10 min", 600], ["1 hour", 3600], ["24 hours", 86400], ["all kept", 0]];

/** One search box over the output of every saved app, with the errors of the last ten minutes on top. */
export function LogsView({ snap, onOpenApp }: { snap: Snapshot; onOpenApp: (id: string) => void }) {
  const [q, setQ] = useState("");
  const [errors, setErrors] = useLocal("porthaven.logsErrors", false);
  const [regex, setRegex] = useLocal("porthaven.logsRegex", false);
  const [within, setWithin] = useLocal("porthaven.logsWithin", 0);
  const [only, setOnly] = useState<string[]>([]);
  const [res, setRes] = useState<Result | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [tick, setTick] = useState(0);
  const box = useRef<HTMLInputElement>(null);
  // focus after the key that opened this tab (4) has been typed, so it does not land in the search
  useEffect(() => { const t = window.setTimeout(() => box.current?.focus(), 0); return () => window.clearTimeout(t); }, []);

  useEffect(() => {
    let live = true;
    const t = window.setTimeout(() => {
      setBusy(true);
      api.searchLogs({ q, apps: only, regex, errors, since: within ? Date.now() / 1000 - within : undefined, limit: 600 })
        .then((r) => { if (live) { setRes(r); setErr(""); } })
        .catch((e) => live && setErr(e.message))
        .finally(() => live && setBusy(false));
    }, 220);
    return () => { live = false; window.clearTimeout(t); };
  }, [q, only, regex, errors, within, tick]);

  useEffect(() => {   // keep the results fresh while apps write output
    const t = window.setInterval(() => setTick((x) => x + 1), 5000);
    return () => window.clearInterval(t);
  }, []);

  const apps = snap.apps.filter((a) => a.logLines || a.logFile);
  const hl = useMemo(() => {
    if (!q) return null;
    try { return new RegExp(regex ? q : q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi"); } catch { return null; }
  }, [q, regex]);

  return (
    <div className="flex min-h-0 flex-1 gap-4">
      <div className="card flex min-w-0 flex-1 flex-col overflow-hidden">
        <div className="space-y-2.5 border-b border-line px-4 py-3">
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <Icon name="search" size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
              <input ref={box} value={q} onChange={(e) => setQ(e.target.value)} placeholder={regex ? "Regular expression, e.g. timeout|ECONNREFUSED" : "Search every app's output…"}
                className="h-10 w-full rounded-lg border border-line bg-panel-2/60 pl-9 pr-3 font-mono text-sm text-ink outline-none placeholder:font-sans placeholder:text-faint focus:border-accent focus:ring-2 focus:ring-accent/20" />
            </div>
            <Chip on={errors} onClick={() => setErrors(!errors)} icon="warn" tone="bad">Errors only</Chip>
            <Chip on={regex} onClick={() => setRegex(!regex)} icon="code">Regex</Chip>
            <select value={within} onChange={(e) => setWithin(Number(e.target.value))} className="h-8 rounded-lg border border-line bg-panel px-2 text-xs text-ink-2">
              {WINDOWS.map(([l, s]) => <option key={s} value={s}>{s ? `Last ${l}` : "Everything kept"}</option>)}
            </select>
          </div>
          {apps.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
              <span className="text-faint">Apps:</span>
              {apps.map((a) => {
                const on = only.includes(a.id);
                return (
                  <button key={a.id} onClick={() => setOnly(on ? only.filter((x) => x !== a.id) : [...only, a.id])}
                    className={cx("flex items-center gap-1.5 rounded-md border px-2 py-0.5 transition", on ? "border-accent bg-accent-soft text-accent-ink" : "border-line text-muted hover:text-ink")}>
                    <span className="h-2 w-2 rounded-full" style={{ background: a.color || colorFor(a.cwd) }} />{a.name}
                    {res && res.counts[a.id] ? <span className="tnum text-faint">{res.counts[a.id]}</span> : null}
                  </button>
                );
              })}
              {only.length > 0 && <button className="text-faint hover:text-ink" onClick={() => setOnly([])}>all</button>}
            </div>
          )}
        </div>
        <div className="min-h-0 flex-1 overflow-auto bg-[#05070c] px-3 py-2 font-mono text-[11.5px] leading-[1.6] text-slate-300">
          {err && <p className="py-6 text-center text-red-300">{err}</p>}
          {!err && res && res.matches.length === 0 && (
            <p className="py-10 text-center text-slate-500">{apps.length ? (q || errors ? "No lines match." : "No output yet.") : "Output is kept for apps Porthaven runs. Start a saved app and its output becomes searchable here."}</p>
          )}
          {!res && !err && <p className="py-10 text-center text-slate-500"><Spinner /> Searching…</p>}
          {res?.matches.map((m) => <Line key={`${m.appId}-${m.seq}-${m.t}`} m={m} color={snap.apps.find((a) => a.id === m.appId)?.color || colorFor(snap.apps.find((a) => a.id === m.appId)?.cwd || m.app)} hl={hl} onOpen={() => onOpenApp(m.appId)} />)}
        </div>
        <div className="flex items-center gap-2 border-t border-line px-4 py-2 text-[11px] text-muted">
          {busy && <Spinner size={10} />}
          {res && <span>{res.total} line{res.total === 1 ? "" : "s"}{res.truncated ? ` · showing the newest ${res.matches.length}` : ""}</span>}
          <span className="ml-auto">Newest first. Porthaven keeps the last 4,000 lines of each running app in memory and its log file in ~/.porthaven/logs.</span>
        </div>
      </div>
      <aside className="flex w-[290px] shrink-0 flex-col gap-3">
        <div className="card p-3">
          <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-ink-2"><Icon name="warn" size={13} className="text-bad" />Errors in the last 10 minutes</h3>
          {!res?.recentErrors.length ? <p className="text-xs text-muted">None. Lines that look like errors (exceptions, stack traces, 5xx answers, npm ERR!) show up here as apps write them.</p> : (
            <div className="space-y-1.5">
              {res.recentErrors.sort((a, b) => b.n - a.n).map((r) => (
                <button key={r.appId} onClick={() => { setOnly([r.appId]); setErrors(true); }} className="block w-full rounded-lg border border-bad/25 bg-bad/5 px-2.5 py-2 text-left hover:border-bad/50">
                  <div className="flex items-center gap-2 text-xs"><span className="font-semibold text-ink">{r.app}</span><Badge tone="bad" className="ml-auto">{r.n}</Badge></div>
                  <p className="mt-1 truncate font-mono text-[10.5px] text-muted" title={r.last}>{r.last}</p>
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="card p-3 text-[11px] leading-relaxed text-muted">
          <h3 className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-ink-2"><Icon name="terminal" size={13} />From a terminal</h3>
          <p><span className="font-mono text-ink-2">porthaven logs timeout --errors</span> searches the same output; coding agents use the <span className="font-mono text-ink-2">search_logs</span> tool.</p>
        </div>
      </aside>
    </div>
  );
}

function Chip({ on, onClick, icon, tone, children }: { on: boolean; onClick: () => void; icon: string; tone?: "bad"; children: React.ReactNode }) {
  return (
    <button onClick={onClick} className={cx("flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-xs font-medium transition",
      on ? (tone === "bad" ? "border-bad/40 bg-bad/10 text-bad" : "border-accent bg-accent-soft text-accent-ink") : "border-line text-muted hover:text-ink")}>
      <Icon name={icon} size={13} />{children}
    </button>
  );
}

function Line({ m, color, hl, onOpen }: { m: LogMatch; color: string; hl: RegExp | null; onOpen: () => void }) {
  const parts = useMemo(() => {
    if (!hl) return [m.text];
    const out: (string | { h: string })[] = [];
    let last = 0;
    for (const x of m.text.matchAll(hl)) {
      if (x.index === undefined || !x[0]) continue;
      out.push(m.text.slice(last, x.index), { h: x[0] });
      last = x.index + x[0].length;
    }
    out.push(m.text.slice(last));
    return out;
  }, [m.text, hl]);
  return (
    <div className={cx("group flex gap-3 rounded px-1 hover:bg-white/[0.03]", m.error && "bg-red-500/[0.07]")}>
      <span className="w-[62px] shrink-0 text-slate-600" title={m.approx ? "time of the run this line belongs to" : undefined}>{m.t ? (m.approx ? "~" : "") + clock(m.t).slice(0, 8) : ""}</span>
      <button onClick={onOpen} className="flex w-[120px] shrink-0 items-center gap-1.5 truncate text-left text-slate-400 hover:text-teal-300" title="Open this app's output">
        <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: color }} /><span className="truncate">{m.app}</span>
      </button>
      <span className={cx("min-w-0 flex-1 whitespace-pre-wrap break-all", m.error && "text-red-200")}>
        {parts.map((p, i) => typeof p === "string" ? p : <mark key={i} className="rounded bg-amber-300/25 px-0.5 text-amber-100">{p.h}</mark>)}
      </span>
    </div>
  );
}
