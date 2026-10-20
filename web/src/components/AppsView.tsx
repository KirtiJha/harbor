import { useEffect, useMemo, useRef } from "react";
import type { App, Snapshot } from "../api";
import type { Actions } from "../actions";
import { useLocal } from "../useHarbor";
import { ago, colorFor, cx, shortPath } from "../util";
import { Icon } from "./Icon";
import { LogView } from "./LogView";
import { Badge, Button, Dot, IconButton, Menu } from "./ui";

const STATE: Record<App["state"], { label: string; tone: "ok" | "warn" | "bad" | "muted" | "info" | "accent"; pulse?: boolean }> = {
  running: { label: "Running", tone: "ok" },
  starting: { label: "Starting", tone: "warn", pulse: true },
  external: { label: "Running outside Harbor", tone: "info" },
  stopped: { label: "Stopped", tone: "muted" },
  exited: { label: "Exited", tone: "muted" },
  crashed: { label: "Crashed", tone: "bad" },
};

export function AppsView({ snap, actions, selectedId, onSelect, onEdit, onDiscover }: {
  snap: Snapshot; actions: Actions; selectedId: string | null; onSelect: (id: string) => void; onEdit: (a: Partial<App>) => void; onDiscover: () => void;
}) {
  const [filter, setFilter] = useLocal<"all" | "running" | "stopped">("harbor.appsFilter", "all");
  const apps = useMemo(() => {
    const live = (a: App) => ["running", "starting", "external"].includes(a.state);
    return snap.apps.filter((a) => filter === "all" || (filter === "running" ? live(a) : !live(a)))
      .sort((a, b) => Number(["running", "starting", "external"].includes(b.state)) - Number(["running", "starting", "external"].includes(a.state)) || a.name.localeCompare(b.name));
  }, [snap.apps, filter]);
  const sel = snap.apps.find((a) => a.id === selectedId) || apps[0] || null;
  const file = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!selectedId && apps[0]) onSelect(apps[0].id);
  }, [selectedId, apps, onSelect]);

  if (snap.apps.length === 0) {
    return (
      <div className="card flex flex-1 flex-col items-center justify-center gap-3 p-10 text-center">
        <div className="rounded-2xl bg-accent-soft p-4 text-accent"><Icon name="play" size={28} /></div>
        <h2 className="text-lg font-semibold text-ink">Start your apps from one place</h2>
        <p className="max-w-md text-sm text-muted">Save the command, folder and port of each project once. Harbor starts it, keeps its output, warns you when the port is taken, and stops the whole thing cleanly.</p>
        <div className="mt-2 flex gap-2">
          <Button variant="primary" icon="radar" onClick={onDiscover}>Find projects on this machine</Button>
          <Button icon="plus" onClick={() => onEdit({})}>Add an app</Button>
        </div>
        <p className="text-xs text-faint">Tip: on the Ports tab, any running server’s menu has “Save as app”.</p>
      </div>
    );
  }

  const running = snap.apps.filter((a) => ["running", "starting", "external"].includes(a.state)).length;
  const groups = Object.entries(apps.reduce<Record<string, App[]>>((m, a) => { (m[a.group || ""] ||= []).push(a); return m; }, {}))
    .sort(([a], [b]) => (a === "" ? 1 : b === "" ? -1 : a.localeCompare(b)));

  return (
    <div className="flex min-h-0 flex-1 gap-4">
      <div className="flex w-[380px] shrink-0 flex-col">
        <div className="mb-3 flex items-center gap-2">
          <div className="flex gap-1 rounded-xl border border-line bg-panel p-1 text-xs">
            {(["all", "running", "stopped"] as const).map((f) => (
              <button key={f} onClick={() => setFilter(f)} className={cx("rounded-lg px-2.5 py-1.5 font-medium capitalize", filter === f ? "bg-accent-soft text-accent-ink" : "text-muted hover:text-ink")}>
                {f}{f === "running" ? ` ${running}` : f === "all" ? ` ${snap.apps.length}` : ` ${snap.apps.length - running}`}
              </button>
            ))}
          </div>
          <div className="ml-auto flex gap-1">
            <IconButton icon="radar" title="Find projects" onClick={onDiscover} />
            <Menu items={[
              { label: "Export apps (JSON)", icon: "down", onClick: () => void actions.exportApps() },
              { label: "Import apps…", icon: "plus", onClick: () => file.current?.click() },
            ]} trigger={(open) => <IconButton icon="more" title="Export / import" onClick={open} />} />
            <input ref={file} type="file" accept="application/json,.json" className="hidden"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) void actions.importApps(f); e.target.value = ""; }} />
            <IconButton icon="plus" title="Add an app (n)" onClick={() => onEdit({})} />
          </div>
        </div>
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
              {list.map((a) => <AppCard key={a.id} a={a} active={sel?.id === a.id} actions={actions} home={snap.me.home} onClick={() => onSelect(a.id)} onEdit={() => onEdit(a)} />)}
            </div>
          ))}
        </div>
      </div>
      {sel && <AppDetail a={sel} snap={snap} actions={actions} onEdit={() => onEdit(sel)} />}
    </div>
  );
}

function AppCard({ a, active, actions, onClick, onEdit, home }: { a: App; active: boolean; actions: Actions; onClick: () => void; onEdit: () => void; home: string }) {
  const s = STATE[a.state];
  const live = ["running", "starting", "external"].includes(a.state);
  return (
    <div onClick={onClick} className={cx("card group relative cursor-pointer overflow-hidden p-3 transition", active ? "ring-2 ring-accent/50" : "hover:border-line-2")}>
      <span className="absolute inset-y-0 left-0 w-1" style={{ background: a.color || colorFor(a.cwd) }} />
      <div className="flex items-start gap-3 pl-1">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <Dot tone={s.tone} pulse={s.pulse} />
            <span className="truncate text-sm font-semibold text-ink">{a.name}</span>
            {a.ports.map((p) => <span key={p} className="tnum rounded bg-panel-2 px-1.5 font-mono text-[11px] text-ink-2">:{p}</span>)}
            {!live && a.port && <span className="tnum font-mono text-[11px] text-faint">:{a.port}</span>}
          </div>
          <div className="mt-1 truncate font-mono text-[11px] text-muted">{a.command}</div>
          <div className="mt-0.5 truncate font-mono text-[11px] text-faint">{shortPath(a.cwd, home)}</div>
          <div className="mt-1.5 flex flex-wrap gap-1">
            <Badge tone={s.tone === "muted" ? "neutral" : s.tone === "accent" ? "accent" : s.tone}>{s.label}</Badge>
            {a.drift && <Badge tone="warn" title={`Saved port is ${a.port}`}>moved off :{a.port}</Badge>}
            {!live && a.conflict && <Badge tone="warn" title={`${a.conflict.title} (pid ${a.conflict.pid})`}>:{a.port} taken</Badge>}
            {a.autoRestart && <Badge tone="violet">auto-restart</Badge>}
            {a.state === "crashed" && a.run && <Badge tone="bad">exit {a.run.exitCode}</Badge>}
          </div>
        </div>
        <div className="flex flex-col items-end gap-1" onClick={(e) => e.stopPropagation()}>
          {live ? <IconButton icon="stop" title="Stop" danger onClick={() => void actions.stopApp(a)} /> :
            <IconButton icon="play" title="Start" className="text-ok hover:text-ok" onClick={() => void actions.startApp(a)} />}
          <Menu items={[
            { label: "Restart", icon: "restart", onClick: () => void actions.restartApp(a), disabled: !live },
            ...(a.ports[0] ? [{ label: "Open in browser", icon: "external", onClick: () => window.open(`http://localhost:${a.ports[0]}${a.openPath || "/"}`, "_blank", "noopener") }] : []),
            { label: "Edit", icon: "edit", onClick: onEdit },
            { label: "Open folder", icon: "folder", onClick: () => void actions.reveal(a.cwd, "finder") },
            { label: "Open in editor", icon: "code", onClick: () => void actions.reveal(a.cwd, "editor") },
            { label: "Open terminal here", icon: "terminal", onClick: () => void actions.reveal(a.cwd, "terminal") },
            "sep",
            { label: "Remove from Harbor", icon: "trash", danger: true, onClick: () => void actions.deleteApp(a), disabled: live && a.state !== "external" },
          ]} trigger={(open) => <IconButton icon="more" title="More" onClick={open} />} />
        </div>
      </div>
    </div>
  );
}

function AppDetail({ a, snap, actions, onEdit }: { a: App; snap: Snapshot; actions: Actions; onEdit: () => void }) {
  const live = ["running", "starting", "external"].includes(a.state);
  const s = STATE[a.state];
  const listeners = snap.listeners.filter((l) => a.ports.includes(l.port) && (l.managed === a.id || l.appId === a.id));
  return (
    <div className="card flex min-w-0 flex-1 flex-col overflow-hidden">
      <div className="flex flex-wrap items-start gap-3 border-b border-line px-5 py-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="h-3 w-3 rounded" style={{ background: a.color || colorFor(a.cwd) }} />
            <h2 className="truncate text-lg font-semibold text-ink">{a.name}</h2>
            <Badge tone={s.tone === "muted" ? "neutral" : s.tone === "accent" ? "accent" : s.tone}><Dot tone={s.tone} pulse={s.pulse} />{s.label}</Badge>
          </div>
          <p className="mt-1 truncate font-mono text-xs text-muted">$ {a.run?.command || a.command}</p>
          {a.stableUrl && <p className="mt-0.5 text-[11px] text-muted">Always at <a className="font-mono text-accent-ink hover:underline" href={a.stableUrl} target="_blank" rel="noopener">{a.stableUrl}</a>
            <button className="ml-1.5 text-faint hover:text-ink" title="Copy" onClick={() => void actions.copyText(a.stableUrl!, "Copied the stable address")}><Icon name="copy" size={11} className="inline" /></button></p>}
          <p className="truncate font-mono text-[11px] text-faint">{shortPath(a.cwd, snap.me.home)}{a.run && ` · started ${ago(a.run.startedAt)}`}{a.run?.pid && ` · pid ${a.run.pid}`}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {listeners.filter((l) => l.probe?.ok).slice(0, 2).map((l) => (
            <Button key={l.port} size="sm" variant="soft" icon="external" onClick={() => window.open(`http://localhost:${l.port}${a.openPath || "/"}`, "_blank", "noopener")}>:{l.port}</Button>
          ))}
          {live ? <>
            <Button size="sm" icon="restart" onClick={() => void actions.restartApp(a)}>Restart</Button>
            <Button size="sm" variant="danger" icon="stop" onClick={() => void actions.stopApp(a)}>Stop</Button>
          </> : <Button size="sm" variant="primary" icon="play" onClick={() => void actions.startApp(a)}>Start{a.port ? ` on :${a.port}` : ""}</Button>}
          <IconButton icon="edit" title="Edit" onClick={onEdit} />
        </div>
      </div>
      {(a.drift || (!live && a.conflict) || a.state === "external") && (
        <div className="space-y-1 border-b border-line bg-warn/5 px-5 py-2 text-xs">
          {a.drift && <p className="text-warn"><Icon name="warn" size={12} className="mr-1 inline" />Running on :{a.ports.join(", :")}, not on its saved port :{a.port}. Something else probably had :{a.port} when it started.</p>}
          {!live && a.conflict && <p className="text-warn"><Icon name="warn" size={12} className="mr-1 inline" />:{a.port} is in use by <b>{a.conflict.title}</b> (pid {a.conflict.pid}). Starting will offer another port or to take it over.</p>}
          {a.state === "external" && <p className="text-info">Started outside Harbor, so its output is not captured. <button className="font-semibold underline" onClick={() => void actions.restartApp(a)}>Restart it under Harbor</button> to see logs here.</p>}
        </div>
      )}
      <div className="flex min-h-0 flex-1 flex-col p-4">
        <LogView key={a.id} appId={a.id} live={a.state === "running" || a.state === "starting"} />
      </div>
    </div>
  );
}
