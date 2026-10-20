import { useEffect, useMemo, useRef, useState } from "react";
import type { Snapshot } from "../api";
import type { Actions } from "../actions";
import { cx } from "../util";
import { Icon } from "./Icon";
import { Kbd, Modal, Toggle } from "./ui";
import { api, type Settings } from "../api";

export type Command = { id: string; label: string; sub?: string; icon: string; group: string; run: () => void; keywords?: string };

export function Palette({ open, onClose, snap, actions, nav }: {
  open: boolean; onClose: () => void; snap: Snapshot; actions: Actions;
  nav: { go: (tab: "ports" | "apps" | "activity" | "insights") => void; select: (id: string) => void; app: (id: string) => void; newApp: () => void; discover: () => void; theme: () => void; settings: () => void; help: () => void };
}) {
  const [q, setQ] = useState("");
  const [i, setI] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { if (open) { setQ(""); setI(0); } }, [open]);

  const commands = useMemo<Command[]>(() => {
    const c: Command[] = [];
    const n = Number(q.trim().replace(/^:/, ""));
    if (n > 0 && n < 65536) {
      const l = snap.listeners.find((x) => x.port === n);
      if (l) {
        if (l.probe?.ok) c.push({ id: `open-n`, label: `Open localhost:${n}`, sub: l.title, icon: "external", group: "Port", run: () => actions.open(l) });
        if (l.risk !== "self" && l.risk !== "foreign") c.push({ id: `kill-n`, label: `Stop what is on :${n}`, sub: l.display, icon: "stop", group: "Port", run: () => void actions.kill(l, "process") });
      } else c.push({ id: "free-n", label: `:${n} is free`, sub: "nothing is listening there", icon: "check", group: "Port", run: () => {} });
    }
    for (const l of snap.listeners) {
      if ((l.kind === "system" || l.kind === "app") && !q) continue;
      c.push({ id: `go-${l.id}`, label: `:${l.port}  ${l.title}`, sub: l.project?.name || l.display, icon: l.probe?.ok ? "globe" : "bolt", group: "Ports",
        run: () => { nav.go("ports"); nav.select(l.id); }, keywords: [l.display, l.cwd, l.framework?.label, l.meta.note].join(" ") });
      if (l.probe?.ok) c.push({ id: `open-${l.id}`, label: `Open :${l.port} in browser`, sub: l.title, icon: "external", group: "Open", run: () => actions.open(l), keywords: l.title });
    }
    for (const a of snap.apps) {
      const live = ["running", "starting", "external"].includes(a.state);
      c.push({ id: `app-${a.id}`, label: `${live ? "Stop" : "Start"} ${a.name}`, sub: a.command, icon: live ? "stop" : "play", group: "Apps",
        run: () => void (live ? actions.stopApp(a) : actions.startApp(a)) });
      c.push({ id: `logs-${a.id}`, label: `Show output of ${a.name}`, sub: a.cwd, icon: "terminal", group: "Apps", run: () => { nav.go("apps"); nav.app(a.id); } });
      if (live) c.push({ id: `restart-${a.id}`, label: `Restart ${a.name}`, icon: "restart", group: "Apps", run: () => void actions.restartApp(a) });
    }
    c.push(
      { id: "nav-ports", label: "Go to Ports", icon: "layers", group: "Go", run: () => nav.go("ports") },
      { id: "nav-apps", label: "Go to Apps", icon: "play", group: "Go", run: () => nav.go("apps") },
      { id: "nav-activity", label: "Go to Activity", icon: "activity", group: "Go", run: () => nav.go("activity") },
      { id: "nav-insights", label: "Go to Insights", icon: "sparkle", group: "Go", run: () => nav.go("insights") },
      { id: "new-app", label: "Add an app", icon: "plus", group: "Porthaven", run: nav.newApp },
      { id: "discover", label: "Find projects on this machine", icon: "radar", group: "Porthaven", run: nav.discover },
      { id: "refresh", label: "Scan now", icon: "refresh", group: "Porthaven", run: () => void api.refresh() },
      { id: "theme", label: "Toggle light / dark", icon: "sun", group: "Porthaven", run: nav.theme },
      { id: "settings", label: "Settings", icon: "settings", group: "Porthaven", run: nav.settings },
      { id: "help", label: "Keyboard shortcuts", icon: "keyboard", group: "Porthaven", run: nav.help },
    );
    return c;
  }, [snap, q, actions, nav]);

  const shown = useMemo(() => {
    const words = q.toLowerCase().replace(/^:/, "").trim();
    if (!words) return commands.filter((c) => c.group !== "Open").slice(0, 60);
    return commands.filter((c) => c.group === "Port" || `${c.label} ${c.sub || ""} ${c.keywords || ""}`.toLowerCase().includes(words)).slice(0, 60);
  }, [commands, q]);

  useEffect(() => setI(0), [q]);
  if (!open) return null;
  const run = (c: Command | undefined) => { if (!c) return; onClose(); c.run(); };
  let lastGroup = "";

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 p-4 pt-[12vh] backdrop-blur-sm" onMouseDown={onClose}>
      <div className="card pop w-full max-w-[620px] overflow-hidden" onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-3 border-b border-line px-4">
          <Icon name="search" size={18} className="text-faint" />
          <input ref={input} autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Type a port, an app, or a command…"
            className="h-14 flex-1 bg-transparent text-[15px] text-ink outline-none placeholder:text-faint"
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") { e.preventDefault(); setI((x) => Math.min(shown.length - 1, x + 1)); }
              else if (e.key === "ArrowUp") { e.preventDefault(); setI((x) => Math.max(0, x - 1)); }
              else if (e.key === "Enter") run(shown[i]);
              else if (e.key === "Escape") onClose();
            }} />
          <Kbd>esc</Kbd>
        </div>
        <div className="max-h-[50vh] overflow-y-auto p-1.5">
          {shown.length === 0 && <p className="p-6 text-center text-sm text-muted">No matches.</p>}
          {shown.map((c, k) => {
            const head = c.group !== lastGroup ? (lastGroup = c.group) : null;
            return (
              <div key={c.id}>
                {head && <div className="px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-faint">{head}</div>}
                <button onMouseEnter={() => setI(k)} onClick={() => run(c)}
                  className={cx("flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left", k === i ? "bg-accent-soft" : "")}>
                  <Icon name={c.icon} size={15} className={k === i ? "text-accent" : "text-muted"} />
                  <span className="truncate text-sm text-ink">{c.label}</span>
                  {c.sub && <span className="ml-auto truncate pl-4 font-mono text-[11px] text-faint">{c.sub}</span>}
                </button>
              </div>
            );
          })}
        </div>
        <div className="flex items-center gap-3 border-t border-line px-4 py-2 text-[11px] text-faint">
          <span><Kbd>↑↓</Kbd> move</span><span><Kbd>↵</Kbd> run</span><span>Type a number to jump to a port</span>
        </div>
      </div>
    </div>
  );
}

export function Help({ open, onClose }: { open: boolean; onClose: () => void }) {
  const rows: [string, string][] = [
    ["⌘K / Ctrl K", "Command palette"], ["/", "Search ports"], ["1 · 2 · 3 · 4", "Ports · Apps · Activity · Insights"], ["j / k  or  ↑ / ↓", "Move through ports"],
    ["Enter", "Details of the port"], ["o", "Open in browser"], ["c", "Copy URL"], ["p", "Pin to top"], ["w", "Watch (notify when it goes down)"],
    ["x", "Stop the process"], ["Space", "Select for bulk stop"], ["⇧X", "Stop the whole app"], ["n", "Add an app"], ["t", "Light / dark"], ["Esc", "Close"], ["?", "This list"],
  ];
  return (
    <Modal open={open} onClose={onClose} title="Keyboard shortcuts" width={460}>
      <div className="grid grid-cols-[150px_1fr] gap-y-2 text-sm">
        {rows.map(([k, v]) => <div key={k} className="contents"><span className="font-mono text-xs text-accent-ink">{k}</span><span className="text-ink-2">{v}</span></div>)}
      </div>
    </Modal>
  );
}

export function SettingsModal({ open, onClose, settings, onTheme, theme }: { open: boolean; onClose: () => void; settings: Settings; onTheme: (t: string) => void; theme: string }) {
  const set = (s: Partial<Settings>) => void api.settings(s);
  const [perm, setPerm] = useState(typeof Notification !== "undefined" ? Notification.permission : "denied");
  return (
    <Modal open={open} onClose={onClose} title="Settings" width={520}>
      <div className="space-y-5 text-sm">
        <Row label="Theme">
          <div className="flex gap-1 rounded-lg border border-line p-0.5 text-xs">
            {["dark", "light", "system"].map((t) => <button key={t} onClick={() => onTheme(t)} className={cx("rounded-md px-2.5 py-1 capitalize", theme === t ? "bg-accent-soft text-accent-ink" : "text-muted")}>{t}</button>)}
          </div>
        </Row>
        <Row label="Scan every" hint="How often Porthaven looks for ports while this page is open.">
          <select className="rounded-lg border border-line-2 bg-panel-2 px-2 py-1 text-xs" value={settings.scanInterval} onChange={(e) => set({ scanInterval: Number(e.target.value) })}>
            {[1, 2, 3, 5, 10].map((s) => <option key={s} value={s}>{s} s</option>)}
          </select>
        </Row>
        <Row label="Check HTTP every" hint="Porthaven asks each server for its page title and status.">
          <select className="rounded-lg border border-line-2 bg-panel-2 px-2 py-1 text-xs" value={settings.probeInterval} onChange={(e) => set({ probeInterval: Number(e.target.value) })}>
            {[5, 15, 30, 60].map((s) => <option key={s} value={s}>{s} s</option>)}
          </select>
        </Row>
        <Row label="Grace before forcing" hint="Seconds between asking a process to stop (SIGTERM) and forcing it (SIGKILL).">
          <select className="rounded-lg border border-line-2 bg-panel-2 px-2 py-1 text-xs" value={settings.graceSeconds} onChange={(e) => set({ graceSeconds: Number(e.target.value) })}>
            {[1, 2, 4, 8, 15].map((s) => <option key={s} value={s}>{s} s</option>)}
          </select>
        </Row>
        <Row label="Call a server idle after" hint="No connections and no CPU for this long puts it under Forgotten servers.">
          <select className="rounded-lg border border-line-2 bg-panel-2 px-2 py-1 text-xs" value={settings.idleHours} onChange={(e) => set({ idleHours: Number(e.target.value) })}>
            {[1, 2, 4, 8, 24, 72].map((s) => <option key={s} value={s}>{s} h</option>)}
          </select>
        </Row>
        <Row label="Check desktop apps too" hint="Also send HTTP checks to ports of desktop apps and system services."><Toggle checked={settings.probeApps} onChange={(b) => set({ probeApps: b })} /></Row>
        <Row label="Desktop notifications" hint="For watched ports going down and apps crashing.">
          {perm === "granted" ? <Toggle checked={settings.notify} onChange={(b) => set({ notify: b })} /> :
            <button className="text-xs font-semibold text-accent hover:underline" onClick={() => void Notification.requestPermission().then(setPerm)}>{perm === "denied" ? "Blocked in browser settings" : "Allow notifications"}</button>}
        </Row>
        <p className="border-t border-line pt-3 text-[11px] text-faint">Saved in ~/.porthaven/state.json. Porthaven listens on 127.0.0.1 only, and every change needs this page’s session token.</p>
      </div>
    </Modal>
  );
}

function Row({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div><div className="font-medium text-ink">{label}</div>{hint && <div className="text-xs text-muted">{hint}</div>}</div>
      {children}
    </div>
  );
}

