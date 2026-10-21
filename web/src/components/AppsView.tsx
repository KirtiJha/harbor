import { useEffect, useMemo, useRef, useState } from "react";
import { api, type App, type Body, type ProxyRequest, type RequestDetail, type Snapshot, type Worktree } from "../api";
import type { Actions } from "../actions";
import { useLocal } from "../usePorthaven";
import { ago, clock, colorFor, cx, shortPath, url } from "../util";
import { Icon } from "./Icon";
import { LogView } from "./LogView";
import { DriftItem } from "./Side";
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
            {a.compose && <Badge tone="info" title={`${a.compose.file} · service ${a.compose.service}`}><Icon name="docker" size={10} />compose{a.container?.health ? ` · ${a.container.health}` : ""}</Badge>}
            {!!a.errors && <Badge tone="bad" title={a.lastError || ""}>{a.errors} error{a.errors > 1 ? "s" : ""} · 10 min</Badge>}
            {a.run?.agent && <Badge tone="warn" title={`Started for ${a.run.agent.label} (pid ${a.run.agent.pid})`}><Icon name="robot" size={10} />{a.run.agent.label}</Badge>}
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
            {a.stableHttpsUrl && <> · <a className="font-mono text-accent-ink hover:underline" href={a.stableHttpsUrl} target="_blank" rel="noopener"><Icon name="lock" size={10} className="mr-0.5 inline" />{a.stableHttpsUrl}</a></>}
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
            <Button key={l.port} size="sm" variant="soft" icon="external" onClick={() => window.open(url(l, a.openPath || "/"), "_blank", "noopener")}>:{l.port}</Button>
          ))}
          {live ? <>
            <Button size="sm" icon="restart" onClick={() => void actions.restartApp(a)}>Restart</Button>
            <Button size="sm" variant="danger" icon="stop" onClick={() => void actions.stopApp(a)}>Stop</Button>
          </> : <Button size="sm" variant="primary" icon="play" onClick={() => void actions.startApp(a)}>{a.state === "sleeping" ? "Wake" : "Start"}{a.port ? ` on :${a.port}` : ""}</Button>}
          <IconButton icon="edit" title="Edit" onClick={onEdit} />
        </div>
      </div>
      {snap.drift.findings.some((f) => f.appId === a.id && f.level === "warn") && (
        <div className="space-y-2 border-b border-line bg-warn/5 px-5 py-2.5">
          {snap.drift.findings.filter((f) => f.appId === a.id && f.level === "warn").map((f) => <DriftItem key={f.id} f={f} actions={actions} />)}
        </div>
      )}
      {(a.drift || (!live && a.conflict) || a.state === "external") && (
        <div className="space-y-1 border-b border-line bg-warn/5 px-5 py-2 text-xs">
          {a.drift && <p className="text-warn"><Icon name="warn" size={12} className="mr-1 inline" />Running on :{a.ports.join(", :")}, not on its saved port :{a.port}. Something else probably had :{a.port} when it started.</p>}
          {!live && a.conflict && <p className="text-warn"><Icon name="warn" size={12} className="mr-1 inline" />:{a.port} is in use by <b>{a.conflict.title}</b> (pid {a.conflict.pid}). Starting will offer another port or to take it over.</p>}
          {a.state === "external" && !a.container && <p className="text-info">Started outside Porthaven, so its output is not captured. <button className="font-semibold underline" onClick={() => void actions.restartApp(a)}>Restart it under Porthaven</button> to see logs here.</p>}
          {a.state === "external" && a.container && <p className="text-info">Its container <b>{a.container.name}</b> was started with docker compose outside Porthaven ({a.container.status}). Stop and start it here to see its output.</p>}
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
        {tab === "output" ? <LogView key={a.id} appId={a.id} live={a.state === "running" || a.state === "starting"} /> : <Requests app={a} actions={actions} />}
      </div>
    </div>
  );
}

function Requests({ app, actions }: { app: App; actions: Actions }) {
  const [rows, setRows] = useState<ProxyRequest[]>([]);
  const [q, setQ] = useState("");
  const [sel, setSel] = useState<number | null>(null);
  useEffect(() => {
    let live = true;
    const load = () => api.requests(app.id).then((r) => live && setRows(r.requests)).catch(() => {});
    load();
    const t = window.setInterval(load, 1500);
    return () => { live = false; window.clearInterval(t); };
  }, [app.id]);
  useEffect(() => setSel(null), [app.id]);
  const shown = [...rows].reverse().filter((r) => !q || `${r.method} ${r.path} ${r.status}`.toLowerCase().includes(q.toLowerCase()));
  const tone = (s: number | null) => (!s ? "text-faint" : s < 300 ? "text-ok" : s < 400 ? "text-info" : s < 500 ? "text-warn" : "text-bad");
  const avg = rows.length ? Math.round(rows.reduce((a, r) => a + (r.ms || 0), 0) / rows.length) : 0;
  const errors = rows.filter((r) => (r.status || 0) >= 400).length;
  const exportHar = async () => {
    try {
      const har = await api.har(app.id);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([JSON.stringify(har, null, 2)], { type: "application/json" }));
      a.download = `${app.slugName || "app"}-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.har`;
      a.click();
      URL.revokeObjectURL(a.href);
      actions.toast("Saved a HAR file. It holds cookies and auth headers, so share it with care.", "ok");
    } catch (e) { actions.fail(e); }
  };
  return (
    <div className="flex min-h-0 flex-1 gap-3">
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-xl border border-line">
        <div className="flex items-center gap-3 border-b border-line bg-panel-2/40 px-3 py-2 text-[11px] text-muted">
          <span>{rows.length} request{rows.length === 1 ? "" : "s"}</span>
          {rows.length > 0 && <><span>· {avg} ms avg</span><span className={errors ? "text-bad" : ""}>· {errors} error{errors === 1 ? "" : "s"}</span></>}
          <div className="ml-auto flex items-center gap-1.5 rounded-md bg-panel px-2 py-1">
            <Icon name="search" size={11} className="text-faint" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter" className="w-28 bg-transparent text-[11px] text-ink outline-none placeholder:text-faint" />
          </div>
          {rows.length > 0 && <button onClick={() => void exportHar()} className="flex items-center gap-1 rounded-md px-1.5 py-1 hover:bg-panel hover:text-ink" title="Save every request as a HAR file (opens in browser dev tools)"><Icon name="down" size={12} />HAR</button>}
        </div>
        {rows.length === 0 ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 p-8 text-center">
            <Icon name="globe" size={22} className="text-faint" />
            <p className="text-sm text-ink">No requests yet</p>
            <p className="max-w-sm text-xs text-muted">Porthaven records the requests that reach this app through its stable address{app.stableUrl ? <>, <a href={app.stableUrl} target="_blank" rel="noopener" className="font-mono text-accent-ink hover:underline">{app.stableUrl}</a></> : ""}. Click one to see its headers and body, replay it, or copy it as curl.</p>
          </div>
        ) : (
          <div className="min-h-0 flex-1 overflow-y-auto font-mono text-[12px]">
            {shown.map((r) => (
              <button key={r.id} onClick={() => setSel(r.id === sel ? null : r.id)}
                className={cx("grid w-full grid-cols-[72px_52px_1fr_44px_62px] items-center gap-2.5 border-b border-line/60 px-3 py-1.5 text-left", sel === r.id ? "bg-accent-soft" : "hover:bg-panel-2/50")}>
                <span className="text-faint">{clock(r.t)}</span>
                <span className="font-semibold text-ink-2">{r.ws ? "WS" : r.method}</span>
                <span className="truncate text-ink" title={r.path}>{r.replay && <Icon name="restart" size={10} className="mr-1 inline text-accent" />}{r.path}</span>
                <span className={cx("font-semibold", tone(r.status))}>{r.status ?? "—"}</span>
                <span className="text-right text-muted">{r.ms != null ? `${r.ms} ms` : "…"}</span>
              </button>
            ))}
          </div>
        )}
      </div>
      {sel != null && <RequestPane app={app} rid={sel} actions={actions} onClose={() => setSel(null)} onReplayed={(id) => setSel(id)} />}
    </div>
  );
}

const HIDE_IN_CURL = new Set(["host", "content-length", "connection", "accept-encoding", "x-forwarded-host", "x-forwarded-proto"]);

function curlOf(d: RequestDetail) {
  const q = (s: string) => `'${s.replace(/'/g, "'\\''")}'`;
  const host = d.requestHeaders.find(([k]) => k.toLowerCase() === "host")?.[1] || `localhost:${d.port}`;
  const parts = [`curl${d.method !== "GET" ? ` -X ${d.method}` : ""} ${q(`http://${host}${d.path}`)}`];
  for (const [k, v] of d.requestHeaders) if (!HIDE_IN_CURL.has(k.toLowerCase())) parts.push(`-H ${q(`${k}: ${v}`)}`);
  if (d.requestHeaders.some(([k]) => k.toLowerCase() === "accept-encoding")) parts.push("--compressed");
  if (d.requestBody.text) parts.push(`--data-raw ${q(d.requestBody.text)}`);
  return parts.join(" \\\n  ");
}

function RequestPane({ app, rid, actions, onClose, onReplayed }: { app: App; rid: number; actions: Actions; onClose: () => void; onReplayed: (id: number) => void }) {
  const [d, setD] = useState<RequestDetail | null>(null);
  const [err, setErr] = useState("");
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState({ method: "", path: "", headers: "", body: "" });
  useEffect(() => {
    let live = true;
    setD(null); setErr(""); setEditing(false);
    api.requestDetail(app.id, rid).then((x) => { if (live) { setD(x); setDraft({ method: x.method, path: x.path, headers: x.requestHeaders.map(([k, v]) => `${k}: ${v}`).join("\n"), body: x.requestBody.text || "" }); } })
      .catch((e) => live && setErr(e.message));
    return () => { live = false; };
  }, [app.id, rid]);
  const replay = async (edited: boolean) => {
    setBusy(true);
    try {
      const edits = edited ? { method: draft.method, path: draft.path, body: draft.body,
        headers: draft.headers.split("\n").map((l) => l.trim()).filter((l) => l.includes(":")).map((l) => [l.slice(0, l.indexOf(":")).trim(), l.slice(l.indexOf(":") + 1).trim()] as [string, string]) } : {};
      const r = await api.replay(app.id, rid, edits);
      actions.toast(<>Replayed: <b>{r.status}</b> in {r.ms} ms</>, (r.status || 0) < 400 ? "ok" : "warn");
      onReplayed(r.id);
    } catch (e) { actions.fail(e); } finally { setBusy(false); }
  };
  return (
    <div className="flex w-[440px] shrink-0 flex-col overflow-hidden rounded-xl border border-line">
      <div className="flex items-center gap-2 border-b border-line bg-panel-2/40 px-3 py-2">
        <span className="truncate font-mono text-xs font-semibold text-ink">{d ? `${d.method} ${d.path}` : "…"}</span>
        <IconButton icon="close" title="Close" size={14} className="ml-auto h-7 w-7" onClick={onClose} />
      </div>
      {err && <p className="p-4 text-xs text-bad">{err}</p>}
      {!d && !err && <p className="p-4 text-xs text-muted"><Spinner size={10} /> Loading…</p>}
      {d && (
        <>
          <div className="flex flex-wrap gap-1.5 border-b border-line px-3 py-2">
            <Button size="sm" variant="primary" icon="restart" busy={busy && !editing} disabled={d.ws} onClick={() => void replay(false)}>Replay</Button>
            <Button size="sm" variant={editing ? "soft" : "outline"} icon="edit" disabled={d.ws} onClick={() => setEditing(!editing)}>Edit and replay</Button>
            <Button size="sm" variant="ghost" icon="copy" onClick={() => void actions.copyText(curlOf(d), "Copied as curl")}>curl</Button>
          </div>
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-3 py-3 text-xs">
            {editing ? (
              <div className="space-y-2">
                <div className="flex gap-2">
                  <select value={draft.method} onChange={(e) => setDraft({ ...draft, method: e.target.value })} className="rounded-lg border border-line-2 bg-panel-2 px-2 font-mono text-xs">
                    {["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"].map((m) => <option key={m}>{m}</option>)}
                  </select>
                  <input className={cx(inputCls, "font-mono text-xs")} value={draft.path} onChange={(e) => setDraft({ ...draft, path: e.target.value })} />
                </div>
                <textarea className={cx(inputCls, "min-h-[110px] font-mono text-[11px]")} value={draft.headers} onChange={(e) => setDraft({ ...draft, headers: e.target.value })} />
                <textarea className={cx(inputCls, "min-h-[90px] font-mono text-[11px]")} placeholder="Body" value={draft.body} onChange={(e) => setDraft({ ...draft, body: e.target.value })} />
                <Button size="sm" variant="primary" icon="play" busy={busy} onClick={() => void replay(true)}>Send</Button>
              </div>
            ) : null}
            <div>
              <div className="mb-1 flex items-center gap-2"><span className="font-semibold text-ink">Response</span>
                <Badge tone={(d.status || 0) < 300 ? "ok" : (d.status || 0) < 400 ? "info" : (d.status || 0) < 500 ? "warn" : "bad"}>{d.status ?? "—"} {d.reason}</Badge>
                <span className="text-faint">{d.ms} ms{d.replay ? " · replay" : ""}</span></div>
              <Headers rows={d.responseHeaders} />
              <BodyView b={d.responseBody} />
            </div>
            <div>
              <div className="mb-1 font-semibold text-ink">Request</div>
              <Headers rows={d.requestHeaders} />
              {d.requestBody.size > 0 && <BodyView b={d.requestBody} />}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function Headers({ rows }: { rows: [string, string][] }) {
  if (!rows.length) return null;
  return (
    <div className="mb-2 rounded-lg border border-line bg-panel-2/40 p-2 font-mono text-[10.5px] leading-relaxed">
      {rows.map(([k, v], i) => <div key={i} className="break-all"><span className="text-muted">{k}:</span> <span className="text-ink-2">{/^(authorization|cookie|set-cookie)$/i.test(k) ? <Secret v={v} /> : v}</span></div>)}
    </div>
  );
}

function Secret({ v }: { v: string }) {
  const [show, setShow] = useState(false);
  return show ? <>{v}</> : <button className="text-faint underline decoration-dotted" onClick={() => setShow(true)}>hidden · show</button>;
}

function BodyView({ b }: { b: Body }) {
  const pretty = useMemo(() => {
    if (!b.text) return null;
    try { return JSON.stringify(JSON.parse(b.text), null, 2); } catch { return b.text; }
  }, [b.text]);
  if (!b.size) return <p className="text-faint">No body.</p>;
  return (
    <div>
      <pre className="max-h-72 overflow-auto rounded-lg border border-line bg-[#05070c] p-2 font-mono text-[10.5px] leading-relaxed text-slate-300">{pretty ?? `${b.size} bytes of binary data${b.note ? ` (${b.note})` : ""}`}</pre>
      {(b.truncated || b.note) && <p className="mt-1 text-[10.5px] text-faint">{b.truncated ? "Only the first 32 kB is kept. " : ""}{b.note && pretty ? b.note : ""}</p>}
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

