import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type Activity, type App as AppT } from "./api";
import { useActions } from "./actions";
import { AppEditor, DiscoverModal } from "./components/AppEditor";
import { AppsView } from "./components/AppsView";
import { Drawer } from "./components/Drawer";
import { Icon } from "./components/Icon";
import { Help, Palette, SettingsModal } from "./components/Palette";
import { PortsView } from "./components/PortsView";
import { ActivityFeed, CleanUp, PortTools, ScanStatus, Stats, WatchList } from "./components/Side";
import { IconButton, Kbd, Spinner, useUi } from "./components/ui";
import { useHarbor, useLocal } from "./useHarbor";
import { cx } from "./util";

type Tab = "ports" | "apps" | "activity";

export default function App() {
  const { toast } = useUi();
  const [tab, setTab] = useLocal<Tab>("harbor.tab", "ports");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [appSel, setAppSel] = useLocal<string | null>("harbor.app", null);
  const [editing, setEditing] = useState<Partial<AppT> | null>(null);
  const [discover, setDiscover] = useState(false);
  const [palette, setPalette] = useState(false);
  const [help, setHelp] = useState(false);
  const [settings, setSettings] = useState(false);
  const [theme, setTheme] = useLocal("harbor.theme", "dark");
  const [flash, setFlash] = useState<Set<string>>(new Set());
  const search = useRef<HTMLInputElement>(null);
  const settingsRef = useRef<{ notify: boolean }>({ notify: true });

  const onEvents = useCallback((events: Activity[]) => {
    const opened = events.filter((e) => e.type === "opened").map((e) => `${e.pid}:${e.port}`);
    if (opened.length) {
      setFlash(new Set(opened));
      window.setTimeout(() => setFlash(new Set()), 1700);
    }
    for (const e of events) {
      const important = e.notify || e.type === "crashed" || e.type === "ready";
      if (!important) continue;
      const text = e.type === "ready" ? `${e.title} is ready on :${e.port}` : e.type === "crashed" ? `${e.title} crashed (${e.detail})` :
        e.type === "closed" ? `:${e.port} ${e.title} went down` : `:${e.port} ${e.title} is back`;
      toast(text, e.type === "crashed" || e.type === "closed" ? "bad" : "ok",
        e.type === "ready" && e.port ? { label: "Open", onClick: () => window.open(`http://localhost:${e.port}/`, "_blank", "noopener") } : undefined);
      if (settingsRef.current.notify && typeof Notification !== "undefined" && Notification.permission === "granted" && document.hidden) {
        new Notification("Harbor", { body: text, tag: e.id });
      }
    }
  }, [toast]);

  const { snap, conn } = useHarbor(onEvents);
  if (snap) settingsRef.current.notify = snap.settings.notify;
  const actions = useActions(setEditing);

  useEffect(() => {
    const t = theme === "system" ? (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark") : theme;
    document.documentElement.classList.toggle("dark", t === "dark");
  }, [theme]);

  useEffect(() => {
    if (!snap) return;
    const down = snap.summary.watchedDown.length;
    const running = snap.summary.dev;
    document.title = `${down ? `⚠ ${down} down · ` : ""}Harbor · ${running} port${running === 1 ? "" : "s"}`;
  }, [snap]);

  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement).closest("input,textarea,select");
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette((p) => !p); return; }
      if (typing || e.metaKey || e.ctrlKey || e.altKey || document.querySelector("[role=dialog]")) {
        if (e.key === "Escape" && typing === search.current) { setQuery(""); search.current?.blur(); }
        return;
      }
      if (e.key === "/") { e.preventDefault(); setTab("ports"); search.current?.focus(); }
      else if (e.key === "1") setTab("ports");
      else if (e.key === "2") setTab("apps");
      else if (e.key === "3") setTab("activity");
      else if (e.key === "?") { e.preventDefault(); setHelp(true); }
      else if (e.key === "n") { e.preventDefault(); setEditing({}); }
      else if (e.key === "t") setTheme((t) => (t === "dark" ? "light" : "dark"));
      else if (e.key === "Escape") setSelected(null);
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [setTab, setTheme]);

  const nav = useMemo(() => ({
    go: (t: Tab) => setTab(t), select: (id: string) => setSelected(id), app: (id: string) => setAppSel(id), newApp: () => setEditing({}),
    discover: () => setDiscover(true), theme: () => setTheme((t) => (t === "dark" ? "light" : "dark")), settings: () => setSettings(true), help: () => setHelp(true),
  }), [setTab, setAppSel, setTheme]);

  const sel = snap?.listeners.find((l) => l.id === selected) || null;
  useEffect(() => {
    if (selected && snap && !sel) setSelected(null);
  }, [selected, snap, sel]);

  if (!snap) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-muted">
        <Logo size={40} />
        <p className="flex items-center gap-2 text-sm">{conn === "lost" ? "Harbor is not reachable. Start it with `python3 -m harbor`." : <><Spinner /> Looking at your ports…</>}</p>
      </div>
    );
  }

  const appsRunning = snap.apps.filter((a) => ["running", "starting", "external"].includes(a.state)).length;
  const problems = snap.activity.filter((a) => a.level !== "info" && Date.now() / 1000 - a.ts < 3600).length;

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-4 border-b border-line bg-panel/70 px-5 py-2.5 backdrop-blur">
        <div className="flex items-center gap-2.5">
          <Logo size={28} />
          <div className="leading-tight">
            <div className="text-[15px] font-bold tracking-tight text-ink">Harbor</div>
            <div className="text-[10px] text-faint">every port on this Mac</div>
          </div>
        </div>
        <nav className="ml-4 flex gap-1">
          {([["ports", "Ports", snap.summary.dev, "layers"], ["apps", "Apps", appsRunning ? `${appsRunning}/${snap.apps.length}` : snap.apps.length, "play"], ["activity", "Activity", problems || null, "activity"]] as const).map(([id, label, count, icon], i) => (
            <button key={id} onClick={() => setTab(id)} title={`${label} (${i + 1})`}
              className={cx("relative flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium transition", tab === id ? "bg-panel-2 text-ink" : "text-muted hover:text-ink")}>
              <Icon name={icon} size={15} />{label}
              {count != null && count !== 0 && <span className={cx("tnum rounded-md px-1.5 text-[11px]", id === "activity" ? "bg-bad/15 text-bad" : tab === id ? "bg-accent-soft text-accent-ink" : "bg-panel-2 text-muted")}>{count}</span>}
              {tab === id && <span className="absolute inset-x-3 -bottom-[11px] h-0.5 rounded-full bg-accent" />}
            </button>
          ))}
        </nav>
        <div className="relative ml-auto w-full max-w-sm">
          <Icon name="search" size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
          <input ref={search} value={query} onChange={(e) => { setQuery(e.target.value); if (tab !== "ports") setTab("ports"); }}
            placeholder="Search port, project, command, note…" className="h-9 w-full rounded-lg border border-line bg-panel-2/60 pl-9 pr-16 text-sm text-ink outline-none placeholder:text-faint focus:border-accent focus:ring-2 focus:ring-accent/20" />
          <span className="pointer-events-none absolute right-2 top-1/2 flex -translate-y-1/2 gap-1">{query ? null : <Kbd>/</Kbd>}</span>
          {query && <button className="absolute right-2 top-1/2 -translate-y-1/2 text-faint hover:text-ink" onClick={() => setQuery("")}><Icon name="close" size={14} /></button>}
        </div>
        <ScanStatus snap={snap} conn={conn} />
        <div className="flex items-center gap-0.5">
          <button onClick={() => setPalette(true)} className="flex h-8 items-center gap-1.5 rounded-lg border border-line px-2 text-xs text-muted hover:text-ink" title="Command palette">
            <Icon name="bolt" size={13} /><Kbd>⌘K</Kbd>
          </button>
          <IconButton icon={document.documentElement.classList.contains("dark") ? "sun" : "moon"} title="Light / dark (t)" onClick={() => setTheme(theme === "dark" ? "light" : "dark")} />
          <IconButton icon="keyboard" title="Shortcuts (?)" onClick={() => setHelp(true)} />
          <a href="/welcome" target="_blank" rel="noopener" title="About Harbor" className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-muted hover:bg-panel-2 hover:text-ink"><Icon name="sparkle" size={16} /></a>
          <IconButton icon="settings" title="Settings" onClick={() => setSettings(true)} />
        </div>
      </header>

      {(snap.error || conn === "lost") && (
        <div className="flex items-center gap-2 border-b border-bad/30 bg-bad/10 px-5 py-2 text-sm text-bad">
          <Icon name="warn" size={15} />{conn === "lost" ? "Lost the connection to Harbor. Retrying…" : snap.error}
        </div>
      )}
      {snap.summary.watchedDown.length > 0 && (
        <div className="flex items-center gap-2 border-b border-warn/30 bg-warn/10 px-5 py-2 text-sm text-warn">
          <Icon name="bell" size={15} />Watched port{snap.summary.watchedDown.length > 1 ? "s" : ""} down: {snap.summary.watchedDown.map((p) => <span key={p} className="font-mono font-semibold">:{p}</span>)}
          {snap.apps.filter((a) => a.port && snap.summary.watchedDown.includes(a.port) && !["running", "starting"].includes(a.state)).map((a) => (
            <button key={a.id} onClick={() => void actions.startApp(a)} className="ml-2 rounded-md bg-warn/20 px-2 py-0.5 text-xs font-semibold hover:bg-warn/30">Start {a.name}</button>
          ))}
        </div>
      )}

      <main className="flex min-h-0 flex-1 gap-4 p-4">
        {tab === "ports" && <>
          <PortsView snap={snap} query={query} actions={actions} selected={selected} onSelect={setSelected} flash={flash} />
          {sel ? <Drawer key={sel.id} l={sel} snap={snap} actions={actions} onClose={() => setSelected(null)} onOpenApp={(id) => { setAppSel(id); setTab("apps"); }} /> : (
            <aside className="flex w-[300px] shrink-0 flex-col gap-3 overflow-y-auto">
              <Stats snap={snap} />
              <CleanUp snap={snap} actions={actions} onSelect={(l) => setSelected(l.id)} />
              <WatchList snap={snap} onSelect={(l) => setSelected(l.id)} />
              <PortTools onSelect={(l) => setSelected(l.id)} />
              <div className="card p-3">
                <div className="mb-1 flex items-center justify-between">
                  <h3 className="flex items-center gap-1.5 text-xs font-semibold text-ink-2"><Icon name="activity" size={13} />Recent</h3>
                  <button className="text-[11px] text-accent hover:underline" onClick={() => setTab("activity")}>All activity</button>
                </div>
                <ActivityFeed items={snap.activity} compact />
              </div>
              <p className="px-1 text-[11px] leading-relaxed text-faint">Press <Kbd>?</Kbd> for shortcuts, <Kbd>⌘K</Kbd> to jump anywhere. Click a row for details.</p>
            </aside>
          )}
        </>}
        {tab === "apps" && <AppsView snap={snap} actions={actions} selectedId={appSel} onSelect={setAppSel} onEdit={setEditing} onDiscover={() => setDiscover(true)} />}
        {tab === "activity" && <ActivityFeed items={snap.activity} onClear={() => void api.clearActivity()} />}
      </main>

      <AppEditor app={editing} groups={[...new Set(snap.apps.map((a) => a.group).filter(Boolean) as string[])]} harborPort={snap.me.port} onClose={() => setEditing(null)} onStart={(a) => { setTab("apps"); setAppSel(a.id); void actions.startApp(a); }} />
      <DiscoverModal open={discover} onClose={() => setDiscover(false)} home={snap.me.home} onPick={(a) => { setDiscover(false); setEditing(a); }} />
      <Palette open={palette} onClose={() => setPalette(false)} snap={snap} actions={actions} nav={nav} />
      <Help open={help} onClose={() => setHelp(false)} />
      <SettingsModal open={settings} onClose={() => setSettings(false)} settings={snap.settings} theme={theme} onTheme={setTheme} />
    </div>
  );
}

function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <defs><linearGradient id="hg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#2dd4bf" /><stop offset="1" stopColor="#0e7490" /></linearGradient></defs>
      <rect width="32" height="32" rx="9" fill="url(#hg)" />
      <path d="M16 8v15M11.5 11.5h9M8.5 17.5c0 4.5 3.4 7 7.5 7s7.5-2.5 7.5-7" fill="none" stroke="#ecfeff" strokeWidth="2.4" strokeLinecap="round" />
      <circle cx="16" cy="7.5" r="2" fill="none" stroke="#ecfeff" strokeWidth="1.8" />
    </svg>
  );
}
