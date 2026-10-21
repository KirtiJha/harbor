import { useState } from "react";
import { api, type Activity, type DriftFinding, type Listener, type Snapshot } from "../api";
import { useNow } from "../usePorthaven";
import type { Actions } from "../actions";
import { ago, clock, cx, duration, mb } from "../util";
import { Icon } from "./Icon";
import { Badge, Button, Dot, inputCls, Spinner } from "./ui";

export function Stats({ snap }: { snap: Snapshot }) {
  const s = snap.summary;
  const items: { label: string; value: string | number; sub?: string; tone?: string; icon: string }[] = [
    { label: "Your ports", value: s.dev, sub: `${s.listening} incl. system`, icon: "layers" },
    { label: "Projects", value: s.projects, sub: `${snap.apps.length} saved app${snap.apps.length === 1 ? "" : "s"}`, icon: "folder" },
    { label: "On network", value: s.exposed, sub: s.exposed ? "reachable by others" : "all local", tone: s.exposed ? "text-warn" : undefined, icon: "network" },
    { label: "CPU · memory", value: `${s.cpu}%`, sub: mb(s.memMb), icon: "activity" },
  ];
  return (
    <div className="grid grid-cols-2 gap-2">
      {items.map((i) => (
        <div key={i.label} className="card px-3 py-2.5">
          <div className="flex items-center gap-1.5 text-[11px] text-muted"><Icon name={i.icon} size={12} />{i.label}</div>
          <div className={cx("tnum mt-0.5 text-xl font-semibold text-ink", i.tone)}>{i.value}</div>
          {i.sub && <div className="truncate text-[11px] text-faint">{i.sub}</div>}
        </div>
      ))}
    </div>
  );
}

export function PortTools({ onSelect }: { onSelect: (l: Listener) => void }) {
  const [q, setQ] = useState("");
  const [res, setRes] = useState<{ port: number; free: boolean; listeners: Listener[]; hint: string | null; next: number[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [freeFrom, setFreeFrom] = useState("3000");
  const [free, setFree] = useState<number[] | null>(null);

  const check = async (e?: React.FormEvent) => {
    e?.preventDefault();
    const n = Number(q);
    if (!n) return;
    setBusy(true);
    try { setRes(await api.checkPort(n)); } finally { setBusy(false); }
  };
  const findFree = async (from = Number(freeFrom)) => setFree((await api.free(from, 6)).ports);

  return (
    <div className="card p-3">
      <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-ink-2"><Icon name="search" size={13} />Is this port free?</h3>
      <form onSubmit={check} className="flex gap-1.5">
        <input className={cx(inputCls, "h-8 py-1 font-mono")} inputMode="numeric" placeholder="5173" value={q} onChange={(e) => { setQ(e.target.value.replace(/\D/g, "")); setRes(null); }} />
        <Button size="sm" type="submit" busy={busy} className="h-8">Check</Button>
      </form>
      {res && (
        <div className="pop mt-2 rounded-lg bg-panel-2/60 p-2 text-xs">
          {res.free ? <p className="flex items-center gap-1.5 text-ok"><Icon name="check" size={13} />:{res.port} is free{res.hint ? <span className="text-faint"> · usually {res.hint}</span> : ""}</p> : (
            <div className="space-y-1">
              {res.listeners.length ? res.listeners.map((l) => (
                <button key={l.id} onClick={() => onSelect(l)} className="flex w-full items-center gap-2 text-left text-ink-2 hover:text-ink">
                  <Dot tone="bad" /><span className="truncate"><b>:{l.port}</b> {l.title} <span className="text-faint">pid {l.pid}</span></span>
                </button>
              )) : <p className="text-warn">:{res.port} cannot be bound (another user or a reserved port).</p>}
              {res.next.length > 0 && <p className="text-faint">Free nearby: {res.next.map((p) => <span key={p} className="mx-0.5 font-mono text-ink-2">{p}</span>)}</p>}
            </div>
          )}
        </div>
      )}
      <h3 className="mb-2 mt-4 flex items-center gap-1.5 text-xs font-semibold text-ink-2"><Icon name="sparkle" size={13} />Find free ports</h3>
      <div className="flex flex-wrap gap-1">
        {[3000, 5173, 8000, 8080, 9000].map((p) => (
          <button key={p} onClick={() => { setFreeFrom(String(p)); void findFree(p); }} className="rounded-md border border-line px-1.5 py-0.5 font-mono text-[11px] text-muted hover:border-accent hover:text-accent">{p}+</button>
        ))}
      </div>
      {free && (
        <div className="pop mt-2 flex flex-wrap gap-1">
          {free.map((p) => (
            <button key={p} title="Copy" onClick={() => void navigator.clipboard.writeText(String(p))} className="rounded-md bg-ok/10 px-2 py-0.5 font-mono text-xs text-ok hover:bg-ok/20">{p}</button>
          ))}
          <span className="text-[11px] text-faint">click to copy</span>
        </div>
      )}
    </div>
  );
}

export function WatchList({ snap, onSelect }: { snap: Snapshot; onSelect: (l: Listener) => void }) {
  const watched = snap.listeners.filter((l) => l.meta.watched);
  const down = snap.summary.watchedDown;
  if (!watched.length && !down.length) return null;
  return (
    <div className="card p-3">
      <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-ink-2"><Icon name="bell" size={13} />Watching</h3>
      <div className="space-y-1">
        {watched.map((l) => (
          <button key={l.id} onClick={() => onSelect(l)} className="flex w-full items-center gap-2 rounded-md px-1 py-0.5 text-left text-xs hover:bg-panel-2">
            <Dot tone="ok" /><span className="tnum font-mono font-semibold text-ink">:{l.port}</span><span className="truncate text-muted">{l.title}</span>
          </button>
        ))}
        {down.map((p) => (
          <div key={p} className="flex items-center gap-2 px-1 py-0.5 text-xs">
            <Dot tone="bad" pulse /><span className="tnum font-mono font-semibold text-ink">:{p}</span><span className="text-bad">down</span>
            <button className="ml-auto text-[11px] text-faint hover:text-ink" onClick={() => void api.updatePort(p, { ...(snap.listeners.find((l) => l.port === p)?.meta || {}), watched: false })}>unwatch</button>
          </div>
        ))}
      </div>
    </div>
  );
}

const EV: Record<Activity["type"], { icon: string; tone: string; verb: string }> = {
  opened: { icon: "play", tone: "text-ok", verb: "started listening on" },
  closed: { icon: "stop", tone: "text-muted", verb: "stopped listening on" },
  killed: { icon: "stop", tone: "text-bad", verb: "stopped from Porthaven" },
  started: { icon: "play", tone: "text-accent", verb: "launched by Porthaven" },
  ready: { icon: "check", tone: "text-ok", verb: "is ready on" },
  stopped: { icon: "stop", tone: "text-muted", verb: "stopped" },
  exited: { icon: "stop", tone: "text-muted", verb: "exited" },
  crashed: { icon: "warn", tone: "text-bad", verb: "crashed" },
  conflict: { icon: "warn", tone: "text-warn", verb: "could not get" },
  slept: { icon: "moon", tone: "text-violet-400", verb: "went to sleep on" },
  woke: { icon: "bolt", tone: "text-violet-300", verb: "woke up on" },
  exposed: { icon: "warn", tone: "text-bad", verb: "is dangerously exposed on" },
  leak: { icon: "trend", tone: "text-warn", verb: "keeps growing in memory on" },
  "agent-ended": { icon: "robot", tone: "text-warn", verb: "" },
  shared: { icon: "share", tone: "text-accent", verb: "is shared from" },
  unshared: { icon: "share", tone: "text-muted", verb: "is no longer shared from" },
  fixed: { icon: "wrench", tone: "text-ok", verb: "now points at" },
};

export function ActivityFeed({ items, compact, onClear }: { items: Activity[]; compact?: boolean; onClear?: () => void }) {
  const now = useNow(5000);
  const [kind, setKind] = useState<"all" | "problems">("all");
  const list = [...items].reverse().filter((e) => kind === "all" || e.level !== "info").slice(0, compact ? 8 : 400);
  return (
    <div className={cx(!compact && "card flex min-h-0 flex-1 flex-col overflow-hidden")}>
      {!compact && (
        <div className="flex items-center gap-2 border-b border-line px-4 py-3">
          <h2 className="text-sm font-semibold text-ink">Activity</h2>
          <span className="text-xs text-muted">ports opening and closing, apps starting, stopping and crashing</span>
          <div className="ml-auto flex gap-1 rounded-lg border border-line p-0.5 text-xs">
            {(["all", "problems"] as const).map((k) => <button key={k} onClick={() => setKind(k)} className={cx("rounded-md px-2 py-1 capitalize", kind === k ? "bg-panel-2 text-ink" : "text-muted")}>{k}</button>)}
          </div>
          {onClear && <Button size="sm" variant="ghost" icon="trash" onClick={onClear}>Clear</Button>}
        </div>
      )}
      <ol className={cx(!compact && "min-h-0 flex-1 overflow-y-auto px-4 py-2")}>
        {list.length === 0 && <li className="py-6 text-center text-xs text-muted">Nothing yet. Start or stop a server and it shows up here.</li>}
        {list.map((e) => {
          const ev = EV[e.type] || EV.opened;
          return (
            <li key={e.id} className={cx("flex items-start gap-2.5 py-1.5", !compact && "border-b border-line/50 last:border-0")}>
              <span className={cx("mt-0.5", ev.tone)}><Icon name={ev.icon} size={13} /></span>
              <div className="min-w-0 flex-1 text-xs">
                <span className="font-medium text-ink">{e.title}</span>{" "}
                <span className="text-muted">{ev.verb}</span>
                {e.port ? <span className="tnum ml-1 font-mono text-ink-2">:{e.port}</span> : null}
                {e.detail && <span className="ml-1 text-faint">· {e.detail}</span>}
                {!compact && e.project && e.project !== e.title && <Badge className="ml-2">{e.project}</Badge>}
              </div>
              <time className="tnum shrink-0 text-[11px] text-faint" title={new Date(e.ts * 1000).toLocaleString()}>{compact ? ago(e.ts, now) : clock(e.ts)}</time>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

export function ScanStatus({ snap, conn }: { snap: Snapshot | null; conn: string }) {
  const now = useNow(1000);
  const [busy, setBusy] = useState(false);
  const age = snap ? now - snap.scannedAt : 0;
  return (
    <button onClick={async () => { setBusy(true); await api.refresh().catch(() => {}); setBusy(false); }} title="Scan now"
      className="flex items-center gap-2 rounded-lg px-2 py-1 text-[11px] text-muted hover:bg-panel-2">
      {busy ? <Spinner size={10} /> : <Dot tone={conn === "live" && age < 15 ? "ok" : conn === "lost" ? "bad" : "warn"} pulse={conn === "live"} />}
      {conn === "lost" ? "Porthaven not reachable, retrying…" : conn === "connecting" ? "connecting…" : <>live · {snap?.scanMs ?? "–"} ms scan</>}
    </button>
  );
}

export function CleanUp({ snap, actions, onSelect }: { snap: Snapshot; actions: Actions; onSelect: (l: Listener) => void }) {
  const idle = snap.listeners.filter((l) => l.idleFor).sort((a, b) => (b.memMb || 0) - (a.memMb || 0));
  if (!idle.length) return null;
  return (
    <div className="card overflow-hidden">
      <div className="bg-gradient-to-r from-violet-500/15 to-transparent px-3 pb-2 pt-3">
        <h3 className="flex items-center gap-1.5 text-xs font-semibold text-ink-2"><Icon name="moon" size={13} className="text-violet-400" />Forgotten servers</h3>
        <p className="mt-0.5 text-[11px] text-muted">{idle.length} dev server{idle.length > 1 ? "s" : ""} unused for {snap.settings.idleHours}h+, holding {mb(snap.summary.idleMemMb)}.</p>
      </div>
      <div className="space-y-0.5 px-2 py-1.5">
        {idle.slice(0, 5).map((l) => (
          <button key={l.id} onClick={() => onSelect(l)} className="flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left text-xs hover:bg-panel-2">
            <span className="tnum font-mono font-semibold text-ink">:{l.port}</span>
            <span className="truncate text-muted">{l.title}</span>
            <span className="ml-auto shrink-0 text-[11px] text-faint">{duration(l.idleFor)}</span>
          </button>
        ))}
      </div>
      <div className="border-t border-line px-3 py-2">
        <Button size="sm" variant="soft" icon="stop" className="w-full" onClick={() => void actions.killMany(idle, "app", `Stop ${idle.length} forgotten server${idle.length > 1 ? "s" : ""}?`)}>
          Stop all idle · free {mb(snap.summary.idleMemMb)}
        </Button>
      </div>
    </div>
  );
}

export function AgentLeftovers({ snap, actions, onSelect }: { snap: Snapshot; actions: Actions; onSelect: (l: Listener) => void }) {
  const left = snap.listeners.filter((l) => l.agent && !l.agent.alive && l.risk !== "self");
  const [busy, setBusy] = useState(false);
  if (!left.length) return null;
  const sessions = [...new Set(left.map((l) => l.agent!.label))];
  const stop = async () => {
    setBusy(true);
    try {
      const r = await api.stopAgentServers();
      actions.toast(`Stopped ${r.stopped} server${r.stopped === 1 ? "" : "s"} left by coding agents.`, "ok");
    } catch (e) { actions.fail(e); } finally { setBusy(false); }
  };
  return (
    <div className="card overflow-hidden">
      <div className="bg-gradient-to-r from-amber-500/15 to-transparent px-3 pb-2 pt-3">
        <h3 className="flex items-center gap-1.5 text-xs font-semibold text-ink-2"><Icon name="robot" size={13} className="text-warn" />Left by coding agents</h3>
        <p className="mt-0.5 text-[11px] text-muted">{left.length} server{left.length > 1 ? "s" : ""} from {sessions.join(", ")} session{sessions.length > 1 ? "s" : ""} that ended, holding {mb(snap.summary.agentLeftoverMemMb)}.</p>
      </div>
      <div className="space-y-0.5 px-2 py-1.5">
        {left.slice(0, 6).map((l) => (
          <button key={l.id} onClick={() => onSelect(l)} className="flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left text-xs hover:bg-panel-2">
            <span className="tnum font-mono font-semibold text-ink">:{l.port}</span>
            <span className="truncate text-muted">{l.title}</span>
            <span className="ml-auto shrink-0 text-[11px] text-faint">{l.agent!.endedAt ? `ended ${ago(l.agent!.endedAt)}` : l.agent!.label}</span>
          </button>
        ))}
      </div>
      <div className="border-t border-line px-3 py-2">
        <Button size="sm" variant="soft" icon="stop" className="w-full" busy={busy} onClick={() => void stop()}>Stop all · free {mb(snap.summary.agentLeftoverMemMb)}</Button>
        {snap.settings.agentCleanup !== "stop" && <p className="mt-1.5 text-[10.5px] text-faint">Settings can stop them on their own once a session has been over for a while.</p>}
      </div>
    </div>
  );
}

export function DriftCard({ snap, actions, onAll }: { snap: Snapshot; actions: Actions; onAll?: () => void }) {
  const found = snap.drift.findings.filter((f) => f.level === "warn");
  if (!found.length) return null;
  return (
    <div className="card overflow-hidden">
      <div className="bg-gradient-to-r from-amber-500/15 to-transparent px-3 pb-2 pt-3">
        <h3 className="flex items-center gap-1.5 text-xs font-semibold text-ink-2"><Icon name="wrench" size={13} className="text-warn" />Pointing at the wrong port</h3>
        <p className="mt-0.5 text-[11px] text-muted">Config files that still name a port the service has moved away from.</p>
      </div>
      <div className="space-y-2 px-3 py-2.5">
        {found.slice(0, 3).map((f) => <DriftItem key={f.id} f={f} actions={actions} />)}
        {found.length > 3 && onAll && <button className="text-[11px] text-accent hover:underline" onClick={onAll}>All {found.length}</button>}
      </div>
    </div>
  );
}

export function DriftItem({ f, actions }: { f: DriftFinding; actions: Actions }) {
  const [busy, setBusy] = useState(false);
  const fix = async () => {
    setBusy(true);
    try {
      const r = await api.driftFix(f.id);
      actions.toast(<>Changed {f.rel} line {f.line}: <span className="font-mono">{r.text}</span></>, "ok");
    } catch (e) { actions.fail(e); } finally { setBusy(false); }
  };
  return (
    <div className="text-xs">
      <p className="text-ink">{f.title}</p>
      <p className="mt-0.5 truncate font-mono text-[10.5px] text-muted" title={`${f.file}:${f.line}  ${f.text}`}>{f.rel}:{f.line} · {f.text}</p>
      <div className="mt-1.5 flex gap-1.5">
        {f.fix && <Button size="sm" variant="soft" icon="wrench" busy={busy} onClick={() => void fix()}>Use :{f.fix.port}</Button>}
        <Button size="sm" variant="ghost" icon="code" onClick={() => void actions.reveal(f.projectRoot, "editor")}>Open</Button>
        <Button size="sm" variant="ghost" onClick={() => void api.driftDismiss(f.id).catch(actions.fail)}>Ignore</Button>
      </div>
    </div>
  );
}

export function LeaksCard({ snap, actions, onSelect }: { snap: Snapshot; actions: Actions; onSelect: (l: Listener) => void }) {
  const rows = snap.listeners.filter((l) => l.leak);
  if (!rows.length) return null;
  return (
    <div className="card overflow-hidden">
      <div className="bg-gradient-to-r from-rose-500/15 to-transparent px-3 pb-2 pt-3">
        <h3 className="flex items-center gap-1.5 text-xs font-semibold text-ink-2"><Icon name="trend" size={13} className="text-bad" />Memory keeps growing</h3>
        <p className="mt-0.5 text-[11px] text-muted">A leak, or a watcher piling up modules. A restart usually gives it back.</p>
      </div>
      <div className="space-y-1 px-2 py-1.5">
        {rows.map((l) => (
          <div key={l.id} className="flex items-center gap-2 rounded-md px-1.5 py-1 text-xs hover:bg-panel-2">
            <button onClick={() => onSelect(l)} className="flex min-w-0 flex-1 items-center gap-2 text-left">
              <span className="tnum font-mono font-semibold text-ink">:{l.port}</span>
              <span className="truncate text-muted">{l.title}</span>
              <span className="ml-auto shrink-0 text-[11px] text-bad">+{mb(l.leak!.growthMb)} in {duration(l.leak!.minutes * 60)}</span>
            </button>
            <button className="shrink-0 rounded-md px-1.5 text-[11px] font-medium text-accent hover:bg-accent-soft" title="Restart it"
              onClick={() => { const app = l.managed ? snap.apps.find((a) => a.id === l.managed) : null; void (app ? actions.restartApp(app) : actions.restart(l)); }}>Restart</button>
          </div>
        ))}
      </div>
    </div>
  );
}
