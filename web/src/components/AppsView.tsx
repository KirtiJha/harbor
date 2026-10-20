import { useEffect, useMemo, useRef, useState } from "react";
import { api, type App, type ProxyRequest, type Snapshot, type Worktree } from "../api";
import type { Actions } from "../actions";
import { useLocal } from "../usePorthaven";
import { ago, clock, colorFor, cx, shortPath } from "../util";
import { Icon } from "./Icon";
import { LogView } from "./LogView";
import { Badge, Button, Dot, Field, IconButton, inputCls, Menu, Modal, Spinner, type MenuItem } from "./ui";

const STATE: Record<App["state"], { label: string; tone: "ok" | "warn" | "bad" | "muted" | "info" | "accent"; pulse?: boolean }> = {
  running: { label: "Running", tone: "ok" },
  starting: { label: "Starting", tone: "warn", pulse: true },
  external: { label: "Running outside Porthaven", tone: "info" },
  stopped: { label: "Stopped", tone: "muted" },
  exited: { label: "Exited", tone: "muted" },
  crashed: { label: "Crashed", tone: "bad" },
  sleeping: { label: "Sleeping · wakes on request", tone: "accent" },
};
const LIVE = ["running", "starting", "external"];

export function AppsView({ snap, actions, selectedId, onSelect, onEdit, onDiscover }: {
  snap: Snapshot; actions: Actions; selectedId: string | null; onSelect: (id: string) => void; onEdit: (a: Partial<App>) => void; onDiscover: () => void;
}) {
  const [filter, setFilter] = useLocal<"all" | "running" | "stopped">("porthaven.appsFilter", "all");
  const [toml, setToml] = useState(false);
  const [worktreeFor, setWorktreeFor] = useState<App | null>(null);
  const [saveWs, setSaveWs] = useState(false);
  const apps = useMemo(() => snap.apps.filter((a) => filter === "all" || (filter === "running" ? LIVE.includes(a.state) : !LIVE.includes(a.state)))
    .sort((a, b) => Number(LIVE.includes(b.state)) - Number(LIVE.includes(a.state)) || a.name.localeCompare(b.name)), [snap.apps, filter]);
  const sel = snap.apps.find((a) => a.id === selectedId) || apps[0] || null;
  const file = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!selectedId && apps[0]) onSelect(apps[0].id);
  }, [selectedId, apps, onSelect]);

  const modals = <>
    <TomlModal open={toml} onClose={() => setToml(false)} actions={actions} home={snap.me.home} />
    <WorktreeModal app={worktreeFor} onClose={() => setWorktreeFor(null)} actions={actions} home={snap.me.home} onOpened={onSelect} />
    <WorkspaceModal open={saveWs} onClose={() => setSaveWs(false)} snap={snap} actions={actions} />
  </>;

  if (snap.apps.length === 0) {
    return (
      <div className="card flex flex-1 flex-col items-center justify-center gap-3 p-10 text-center">
        <div className="rounded-2xl bg-accent-soft p-4 text-accent"><Icon name="play" size={28} /></div>
        <h2 className="text-lg font-semibold text-ink">Start your apps from one place</h2>
        <p className="max-w-md text-sm text-muted">Save the command, folder and port of each project once. Porthaven starts it with its dependencies, keeps its output, warns you when the port is taken, and stops the whole thing cleanly.</p>
        <div className="mt-2 flex gap-2">
          <Button variant="primary" icon="radar" onClick={onDiscover}>Find projects on this machine</Button>
          <Button icon="note" onClick={() => setToml(true)}>Import porthaven.toml</Button>
          <Button icon="plus" onClick={() => onEdit({})}>Add an app</Button>
        </div>
        <p className="text-xs text-faint">Tip: on the Ports tab, any running server’s menu has “Save as app”. In a terminal, <span className="font-mono">porthaven init</span> writes a porthaven.toml.</p>
        {modals}
      </div>
    );
  }

  const running = snap.apps.filter((a) => LIVE.includes(a.state)).length;
  const groups = Object.entries(apps.reduce<Record<string, App[]>>((m, a) => { (m[a.group || ""] ||= []).push(a); return m; }, {}))
    .sort(([a], [b]) => (a === "" ? 1 : b === "" ? -1 : a.localeCompare(b)));
  const claims = Object.entries(snap.summary.portClaims || {});
  const wsItems: MenuItem[] = [
    { label: "Save what is running…", icon: "plus", onClick: () => setSaveWs(true) },
    ...(snap.workspaces.length ? ["sep" as const] : []),
    ...snap.workspaces.flatMap((w) => [
      { label: `Restore “${w.name}”`, icon: "play", hint: `${w.apps.length} apps`, onClick: () => void actions.restoreWorkspace(w, false) },
      { label: `Switch to “${w.name}” (stop the rest)`, icon: "restart", onClick: () => void actions.restoreWorkspace(w, true) },
      { label: `Delete “${w.name}”`, icon: "trash", danger: true, onClick: () => void actions.deleteWorkspace(w) },
    ]),
  ];

  return (
    <div className="flex min-h-0 flex-1 gap-4">
      <div className="flex w-[390px] shrink-0 flex-col">
        <div className="mb-3 flex items-center gap-2">
          <div className="flex gap-1 rounded-xl border border-line bg-panel p-1 text-xs">
            {(["all", "running", "stopped"] as const).map((f) => (
              <button key={f} onClick={() => setFilter(f)} className={cx("rounded-lg px-2.5 py-1.5 font-medium capitalize", filter === f ? "bg-accent-soft text-accent-ink" : "text-muted hover:text-ink")}>
                {f}{f === "running" ? ` ${running}` : f === "all" ? ` ${snap.apps.length}` : ` ${snap.apps.length - running}`}
              </button>
            ))}
          </div>
          <div className="ml-auto flex gap-1">
            <Menu items={wsItems} trigger={(open) => <IconButton icon="layers" title="Workspaces: save and restore what is running" onClick={open} />} />
            <IconButton icon="radar" title="Find projects" onClick={onDiscover} />
            <Menu items={[
              { label: "Import porthaven.toml…", icon: "note", onClick: () => setToml(true) },
              ...groups.filter(([g]) => g).map(([g]) => ({ label: `Export “${g}” as porthaven.toml`, icon: "down", onClick: () => void actions.exportToml(g) })),
              "sep",
              { label: "Export apps (JSON)", icon: "down", onClick: () => void actions.exportApps() },
              { label: "Import apps (JSON)…", icon: "plus", onClick: () => file.current?.click() },
            ]} trigger={(open) => <IconButton icon="more" title="Import / export" onClick={open} />} />
            <input ref={file} type="file" accept="application/json,.json" className="hidden"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) void actions.importApps(f); e.target.value = ""; }} />
            <IconButton icon="plus" title="Add an app (n)" onClick={() => onEdit({})} />
          </div>
        </div>
        {claims.length > 0 && (
          <div className="mb-2 rounded-xl border border-warn/30 bg-warn/5 px-3 py-2 text-[11px] text-warn">
            {claims.map(([p, names]) => <p key={p}><Icon name="warn" size={11} className="mr-1 inline" /><b>:{p}</b> is expected by {names.join(" and ")}. Give one of them another port.</p>)}
          </div>
        )}
        <div className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
          {groups.map(([g, list]) => (
            <div key={g || "~"} className="space-y-2">
              {g && (
                <div className="flex items-center gap-2 px-1 pt-1">
                  <Icon name="layers" size={12} className="text-faint" />
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-faint">{g}</span>
                  <span className="h-px flex-1 bg-line" />
                  <button className="text-[11px] font-medium text-ok hover:underline" onClick={() => void actions.group(g, "start")}>Start all</button>
                  <button className="text-[11px] font-medium text-bad hover:underline" onClick={() => void actions.group(g, "stop")}>Stop all</button>
                </div>
              )}
              {list.map((a) => <AppCard key={a.id} a={a} all={snap.apps} active={sel?.id === a.id} actions={actions} home={snap.me.home}
                onClick={() => onSelect(a.id)} onEdit={() => onEdit(a)} onWorktree={() => setWorktreeFor(a)} />)}
            </div>
          ))}
        </div>
      </div>
      {sel && <AppDetail a={sel} snap={snap} actions={actions} onEdit={() => onEdit(sel)} />}
      {modals}
    </div>
  );
}

function depName(all: App[], ref: string) {
  return all.find((x) => x.id === ref || x.slugName === ref || x.name.toLowerCase() === ref.toLowerCase());
}

function AppCard({ a, all, active, actions, onClick, onEdit, onWorktree, home }: {
  a: App; all: App[]; active: boolean; actions: Actions; onClick: () => void; onEdit: () => void; onWorktree: () => void; home: string;
}) {
  const s = STATE[a.state];
  const live = LIVE.includes(a.state);
  return (
    <div onClick={onClick} className={cx("card group relative cursor-pointer overflow-hidden p-3 transition", active ? "ring-2 ring-accent/50" : "hover:border-line-2", a.worktreeOf && "ml-4")}>
      <span className="absolute inset-y-0 left-0 w-1" style={{ background: a.color || colorFor(a.cwd) }} />
      <div className="flex items-start gap-3 pl-1">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            {a.state === "sleeping" ? <Icon name="moon" size={13} className="text-violet-400" /> : <Dot tone={s.tone} pulse={s.pulse} />}
            <span className="truncate text-sm font-semibold text-ink">{a.name}</span>
            {a.ports.map((p) => <span key={p} className="tnum rounded bg-panel-2 px-1.5 font-mono text-[11px] text-ink-2">:{p}</span>)}
            {!live && a.port && <span className="tnum font-mono text-[11px] text-faint">:{a.port}</span>}
          </div>
          <div className="mt-1 truncate font-mono text-[11px] text-muted">{a.command}</div>
          <div className="mt-0.5 truncate font-mono text-[11px] text-faint">{shortPath(a.cwd, home)}</div>
          <div className="mt-1.5 flex flex-wrap gap-1">
            <Badge tone={s.tone === "muted" ? "neutral" : s.tone === "accent" ? "accent" : s.tone}>{s.label}</Badge>
            {a.branch && <Badge tone="violet" title="Runs from a git worktree">⎇ {a.branch}</Badge>}
            {(a.dependsOn || []).map((d) => {
              const dep = depName(all, d);
              return <Badge key={d} tone={dep && LIVE.includes(dep.state) ? "ok" : "neutral"} title="Starts first; this app waits for it">needs {dep?.name || d}</Badge>;
            })}
            {!!a.sleepAfter && <Badge tone="violet" title={`Stops after ${a.sleepAfter} quiet minutes; the next request wakes it`}><Icon name="moon" size={10} />{a.sleepAfter}m</Badge>}
            {a.source && <Badge title={a.source.file}>porthaven.toml</Badge>}
            {a.drift && <Badge tone="warn" title={`Saved port is ${a.port}`}>moved off :{a.port}</Badge>}
            {!live && a.conflict && <Badge tone="warn" title={`${a.conflict.title} (pid ${a.conflict.pid})`}>:{a.port} taken</Badge>}
            {a.autoRestart && <Badge tone="violet">auto-restart</Badge>}
            {a.state === "crashed" && a.run && <Badge tone="bad">exit {a.run.exitCode}</Badge>}
          </div>
        </div>
        <div className="flex flex-col items-end gap-1" onClick={(e) => e.stopPropagation()}>
          {live ? <IconButton icon="stop" title="Stop" danger onClick={() => void actions.stopApp(a)} /> :
            <IconButton icon="play" title={a.dependsOn?.length ? "Start (dependencies first)" : "Start"} className="text-ok hover:text-ok" onClick={() => void actions.startApp(a)} />}
          <Menu items={[
            { label: "Restart", icon: "restart", onClick: () => void actions.restartApp(a), disabled: !live },
            ...(a.ports[0] ? [{ label: "Open in browser", icon: "external", onClick: () => window.open(`http://localhost:${a.ports[0]}${a.openPath || "/"}`, "_blank", "noopener") }] : []),
            ...(!a.worktreeOf ? [{ label: "Run from another git worktree…", icon: "tree", onClick: onWorktree }] : []),
            { label: "Edit", icon: "edit", onClick: onEdit },
            { label: "Open folder", icon: "folder", onClick: () => void actions.reveal(a.cwd, "finder") },
            { label: "Open in editor", icon: "code", onClick: () => void actions.reveal(a.cwd, "editor") },
            { label: "Open terminal here", icon: "terminal", onClick: () => void actions.reveal(a.cwd, "terminal") },
            "sep",
            { label: "Remove from Porthaven", icon: "trash", danger: true, onClick: () => void actions.deleteApp(a), disabled: live && a.state !== "external" },
          ]} trigger={(open) => <IconButton icon="more" title="More" onClick={open} />} />
        </div>
      </div>
    </div>
  );
}

function AppDetail({ a, snap, actions, onEdit }: { a: App; snap: Snapshot; actions: Actions; onEdit: () => void }) {
  const live = LIVE.includes(a.state);
  const s = STATE[a.state];
  const [tab, setTab] = useLocal<"output" | "requests">("porthaven.appTab", "output");
  const listeners = snap.listeners.filter((l) => a.ports.includes(l.port) && (l.managed === a.id || l.appId === a.id));
  return (
    <div className="card flex min-w-0 flex-1 flex-col overflow-hidden">
      <div className="flex flex-wrap items-start gap-3 border-b border-line px-5 py-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="h-3 w-3 rounded" style={{ background: a.color || colorFor(a.cwd) }} />
            <h2 className="truncate text-lg font-semibold text-ink">{a.name}</h2>
            <Badge tone={s.tone === "muted" ? "neutral" : s.tone === "accent" ? "accent" : s.tone}><Dot tone={s.tone} pulse={s.pulse} />{s.label}</Badge>
            {a.branch && <Badge tone="violet">⎇ {a.branch}</Badge>}
          </div>
          <p className="mt-1 truncate font-mono text-xs text-muted">$ {a.run?.command || a.command}</p>
          {a.stableUrl && <p className="mt-0.5 text-[11px] text-muted">Always at <a className="font-mono text-accent-ink hover:underline" href={a.stableUrl} target="_blank" rel="noopener">{a.stableUrl}</a>
            <button className="ml-1.5 text-faint hover:text-ink" title="Copy" onClick={() => void actions.copyText(a.stableUrl!, "Copied the stable address")}><Icon name="copy" size={11} className="inline" /></button>
            {!!a.sleepAfter && <span className="ml-2 text-violet-400">· sleeps after {a.sleepAfter} quiet min, wakes on the next request</span>}</p>}
          <p className="truncate font-mono text-[11px] text-faint">{shortPath(a.cwd, snap.me.home)}{a.run && ` · started ${ago(a.run.startedAt)}`}{a.run?.pid && ` · pid ${a.run.pid}`}{a.health && ` · health ${a.health}`}</p>
          {!!a.dependsOn?.length && (
            <p className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-muted">Starts after
              {a.dependsOn.map((d) => { const dep = depName(snap.apps, d); return <span key={d} className="flex items-center gap-1 rounded-md bg-panel-2 px-1.5 py-0.5 text-ink-2"><Dot tone={dep && LIVE.includes(dep.state) ? "ok" : "muted"} />{dep?.name || d}</span>; })}
            </p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {listeners.filter((l) => l.probe?.ok).slice(0, 2).map((l) => (
            <Button key={l.port} size="sm" variant="soft" icon="external" onClick={() => window.open(`http://localhost:${l.port}${a.openPath || "/"}`, "_blank", "noopener")}>:{l.port}</Button>
          ))}
          {live ? <>
            <Button size="sm" icon="restart" onClick={() => void actions.restartApp(a)}>Restart</Button>
            <Button size="sm" variant="danger" icon="stop" onClick={() => void actions.stopApp(a)}>Stop</Button>
          </> : <Button size="sm" variant="primary" icon="play" onClick={() => void actions.startApp(a)}>{a.state === "sleeping" ? "Wake" : "Start"}{a.port ? ` on :${a.port}` : ""}</Button>}
          <IconButton icon="edit" title="Edit" onClick={onEdit} />
        </div>
      </div>
      {(a.drift || (!live && a.conflict) || a.state === "external") && (
        <div className="space-y-1 border-b border-line bg-warn/5 px-5 py-2 text-xs">
          {a.drift && <p className="text-warn"><Icon name="warn" size={12} className="mr-1 inline" />Running on :{a.ports.join(", :")}, not on its saved port :{a.port}. Something else probably had :{a.port} when it started.</p>}
          {!live && a.conflict && <p className="text-warn"><Icon name="warn" size={12} className="mr-1 inline" />:{a.port} is in use by <b>{a.conflict.title}</b> (pid {a.conflict.pid}). Starting will offer another port or to take it over.</p>}
          {a.state === "external" && <p className="text-info">Started outside Porthaven, so its output is not captured. <button className="font-semibold underline" onClick={() => void actions.restartApp(a)}>Restart it under Porthaven</button> to see logs here.</p>}
        </div>
      )}
      <div className="flex gap-1 border-b border-line px-4 pt-2">
        {(["output", "requests"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)} className={cx("relative px-3 py-2 text-xs font-medium capitalize", tab === t ? "text-ink" : "text-muted hover:text-ink")}>
            {t}{tab === t && <span className="absolute inset-x-2 -bottom-px h-0.5 rounded bg-accent" />}
          </button>
        ))}
      </div>
      <div className="flex min-h-0 flex-1 flex-col p-4">
        {tab === "output" ? <LogView key={a.id} appId={a.id} live={a.state === "running" || a.state === "starting"} /> : <Requests app={a} />}
      </div>
    </div>
  );
}

function Requests({ app }: { app: App }) {
  const [rows, setRows] = useState<ProxyRequest[]>([]);
  const [q, setQ] = useState("");
  useEffect(() => {
    let live = true;
    const load = () => api.requests(app.id).then((r) => live && setRows(r.requests)).catch(() => {});
    load();
    const t = window.setInterval(load, 1500);
    return () => { live = false; window.clearInterval(t); };
  }, [app.id]);
  const shown = [...rows].reverse().filter((r) => !q || `${r.method} ${r.path} ${r.status}`.toLowerCase().includes(q.toLowerCase()));
  const tone = (s: number | null) => (!s ? "text-faint" : s < 300 ? "text-ok" : s < 400 ? "text-info" : s < 500 ? "text-warn" : "text-bad");
  const avg = rows.length ? Math.round(rows.reduce((a, r) => a + (r.ms || 0), 0) / rows.length) : 0;
  const errors = rows.filter((r) => (r.status || 0) >= 400).length;
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-line">
      <div className="flex items-center gap-3 border-b border-line bg-panel-2/40 px-3 py-2 text-[11px] text-muted">
        <span>{rows.length} request{rows.length === 1 ? "" : "s"}</span>
        {rows.length > 0 && <><span>· {avg} ms avg</span><span className={errors ? "text-bad" : ""}>· {errors} error{errors === 1 ? "" : "s"}</span></>}
        <div className="ml-auto flex items-center gap-1.5 rounded-md bg-panel px-2 py-1">
          <Icon name="search" size={11} className="text-faint" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter" className="w-32 bg-transparent text-[11px] text-ink outline-none placeholder:text-faint" />
        </div>
      </div>
      {rows.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 p-8 text-center">
          <Icon name="globe" size={22} className="text-faint" />
          <p className="text-sm text-ink">No requests yet</p>
          <p className="max-w-sm text-xs text-muted">Porthaven records the requests that reach this app through its stable address{app.stableUrl ? <>, <a href={app.stableUrl} target="_blank" rel="noopener" className="font-mono text-accent-ink hover:underline">{app.stableUrl}</a></> : ""}.</p>
        </div>
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto font-mono text-[12px]">
          {shown.map((r, i) => (
            <div key={`${r.t}-${i}`} className="grid grid-cols-[80px_60px_1fr_56px_70px_70px] items-center gap-3 border-b border-line/60 px-3 py-1.5 hover:bg-panel-2/50">
              <span className="text-faint">{clock(r.t)}</span>
              <span className="font-semibold text-ink-2">{r.ws ? "WS" : r.method}</span>
              <span className="truncate text-ink" title={r.path}>{r.path}</span>
              <span className={cx("font-semibold", tone(r.status))}>{r.status ?? "—"}</span>
              <span className="text-right text-muted">{r.ms != null ? `${r.ms} ms` : "…"}</span>
              <span className="text-right text-faint">{r.bytes >= 1024 ? `${(r.bytes / 1024).toFixed(1)} kB` : `${r.bytes} B`}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function TomlModal({ open, onClose, actions, home }: { open: boolean; onClose: () => void; actions: Actions; home: string }) {
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (open && !path) setPath(home ? "~/" : ""); }, [open, path, home]);
  const run = async (up: boolean) => { setBusy(true); const ok = await actions.importToml(path, up); setBusy(false); if (ok) onClose(); };
  return (
    <Modal open={open} onClose={onClose} title="Import porthaven.toml" width={600}
      subtitle="A porthaven.toml in a repo lists its apps, ports, dependencies and health checks, so everyone who clones it gets the same setup."
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button onClick={() => void run(false)} busy={busy}>Import</Button>
        <Button variant="primary" icon="play" onClick={() => void run(true)} busy={busy}>Import and start</Button></>}>
      <Field label="Project folder (or the file itself)" hint="Porthaven looks for porthaven.toml there or in the folders above. In a terminal: porthaven up">
        <input autoFocus className={cx(inputCls, "font-mono text-xs")} value={path} onChange={(e) => setPath(e.target.value)} placeholder="~/code/shop" />
      </Field>
      <pre className="mt-4 overflow-x-auto rounded-xl border border-line bg-panel-2/60 p-3 font-mono text-[11px] leading-relaxed text-ink-2">{`[apps.api]
command = "uvicorn main:app --reload --port {port}"
cwd = "backend"
port = 8000
health = "/health"

[apps.web]
command = "npm run dev -- --port {port}"
cwd = "frontend"
port = 5173
depends_on = ["api"]
env = { API_URL = "{url:api}" }
sleep_after = 60`}</pre>
    </Modal>
  );
}

function WorktreeModal({ app, onClose, actions, home, onOpened }: { app: App | null; onClose: () => void; actions: Actions; home: string; onOpened: (id: string) => void }) {
  const [data, setData] = useState<{ repo: string; branch: string; worktrees: Worktree[] } | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  useEffect(() => {
    if (!app) return;
    setData(null); setErr("");
    api.worktrees(app.id).then(setData).catch((e) => setErr(e.message));
  }, [app]);
  if (!app) return null;
  return (
    <Modal open onClose={onClose} title={`Run ${app.name} from another worktree`} width={640}
      subtitle="Each worktree gets its own port and stable address (branch.app.localhost), so parallel branches and coding agents stop fighting over one port.">
      {err && <p className="text-sm text-bad">{err}</p>}
      {!data && !err && <p className="text-sm text-muted"><Spinner /> Reading worktrees…</p>}
      {data && (
        <div className="space-y-2">
          {data.worktrees.map((t) => (
            <div key={t.path} className="flex items-center gap-3 rounded-xl border border-line px-3 py-2.5">
              <Icon name="tree" size={16} className={t.current ? "text-accent" : "text-faint"} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 text-sm text-ink"><span className="font-semibold">⎇ {t.branch || "detached"}</span>{t.current && <Badge tone="accent">this app</Badge>}{t.main && <Badge>main checkout</Badge>}</div>
                <div className="truncate font-mono text-[11px] text-faint">{shortPath(t.path, home)}</div>
              </div>
              {t.current ? null : t.app ? <Button size="sm" variant="soft" onClick={() => { onOpened(t.app!.id); onClose(); }}>Open {t.app.name}</Button> :
                <Button size="sm" variant="primary" icon="play" busy={busy === t.path} onClick={async () => {
                  setBusy(t.path);
                  const r = await actions.runInWorktree(app, t.path);
                  setBusy(null);
                  if (r) { onOpened(r.app.id); onClose(); }
                }}>Run here</Button>}
            </div>
          ))}
          {data.worktrees.length < 2 && <p className="text-xs text-muted">This repository has one checkout. Add one with <span className="font-mono">git worktree add ../{data.repo}-feature -b feature</span>.</p>}
        </div>
      )}
    </Modal>
  );
}

function WorkspaceModal({ open, onClose, snap, actions }: { open: boolean; onClose: () => void; snap: Snapshot; actions: Actions }) {
  const [name, setName] = useState("");
  const running = snap.apps.filter((a) => LIVE.includes(a.state));
  const save = async () => { if (running.length && await actions.saveWorkspace(name || "Workspace")) { setName(""); onClose(); } };
  return (
    <Modal open={open} onClose={onClose} title="Save a workspace" width={480}
      subtitle="Remember which apps are running now; restore them later in one click, dependencies first."
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!running.length} onClick={save}>Save</Button></>}>
      <Field label="Name"><input autoFocus className={inputCls} value={name} onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && save()} placeholder="Shop, full stack" /></Field>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {running.length ? running.map((a) => <Badge key={a.id} tone="ok">{a.name}</Badge>) : <p className="text-xs text-muted">No saved apps are running.</p>}
      </div>
    </Modal>
  );
}

