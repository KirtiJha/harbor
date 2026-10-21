import { useEffect, useState, type ReactNode } from "react";
import { api, type Interval, type Listener, type ProcessDetail, type Snapshot } from "../api";
import type { Actions } from "../actions";
import { ago, cx, duration, health, KIND_LABEL, mb, shortPath } from "../util";
import { Icon } from "./Icon";
import { ShareCard, ShareModal } from "./ShareModal";
import { Badge, Button, Dot, IconButton, inputCls, Sparkline, Spinner } from "./ui";

export function Drawer({ l, snap, actions, onClose, onOpenApp }: { l: Listener; snap: Snapshot; actions: Actions; onClose: () => void; onOpenApp: (id: string) => void }) {
  const [detail, setDetail] = useState<ProcessDetail | null>(null);
  const [label, setLabel] = useState(l.meta.label || "");
  const [note, setNote] = useState(l.meta.note || "");
  const [checking, setChecking] = useState(false);
  const [sharing, setSharing] = useState(false);
  const locked = l.risk === "self" || l.risk === "foreign";
  const shareable = !l.risk && ["dev", "service", "other"].includes(l.kind) && !!l.probe?.ok && !l.shareRelay;
  const h = health(l);
  const home = snap.me.home;

  useEffect(() => {
    setLabel(l.meta.label || "");
    setNote(l.meta.note || "");
  }, [l.port, l.meta.label, l.meta.note]);

  useEffect(() => {
    let live = true;
    api.process(l.pid).then((d) => live && setDetail(d)).catch(() => live && setDetail(null));
    return () => { live = false; };
  }, [l.pid, l.root?.count]);

  const saveMeta = () => {
    if ((label || "") !== (l.meta.label || "") || (note || "") !== (l.meta.note || "")) void actions.meta(l, { label, note });
  };

  const app = l.appId ? snap.apps.find((a) => a.id === l.appId) : null;

  return (
    <aside className="card slide-in flex h-full w-[440px] shrink-0 flex-col overflow-hidden">
      <div className="border-b border-line px-5 pb-4 pt-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <Dot tone={h === "up" ? "ok" : h === "warn" ? "warn" : h === "down" ? "bad" : "muted"} />
              <span className="tnum font-mono text-2xl font-semibold text-ink">:{l.port}</span>
              <Badge>{KIND_LABEL[l.kind]}</Badge>
              {l.framework && <Badge tone="accent">{l.framework.label}</Badge>}
            </div>
            <h2 className="mt-1 truncate text-[15px] font-semibold text-ink">{l.title}</h2>
            {l.project && <p className="truncate text-xs text-muted">{l.project.repo && l.project.repo !== l.project.name ? `${l.project.repo} › ` : ""}{l.project.name}
              {l.project.git?.branch && <span className="ml-2 text-violet-400">⎇ {l.project.git.branch}{l.project.git.worktree ? " (worktree)" : ""}</span>}</p>}
          </div>
          <IconButton icon="close" title="Close (Esc)" onClick={onClose} />
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {l.probe?.ok && <Button size="sm" variant="primary" icon="external" onClick={() => actions.open(l)}>Open</Button>}
          <Button size="sm" icon="copy" onClick={() => void actions.copyUrl(l)}>Copy URL</Button>
          <Button size="sm" icon="pin" variant={l.meta.pinned ? "soft" : "outline"} onClick={() => void actions.meta(l, { pinned: !l.meta.pinned })}>{l.meta.pinned ? "Pinned" : "Pin"}</Button>
          <Button size="sm" icon="bell" variant={l.meta.watched ? "soft" : "outline"} onClick={() => void actions.meta(l, { watched: !l.meta.watched })}
            title="Notify me when this port goes down or comes back">{l.meta.watched ? "Watching" : "Watch"}</Button>
          {shareable && <Button size="sm" icon="share" variant={l.shares.length ? "soft" : "outline"} onClick={() => setSharing(true)}
            title="A link (and QR code) for your phone, or a public link">{l.shares.length ? "Shared" : "Share"}</Button>}
        </div>
      </div>
      {sharing && <ShareModal l={l} snap={snap} actions={actions} onClose={() => setSharing(false)} />}

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-5 py-4">
        {l.shares.map((x) => <ShareCard key={x.id} s={x} actions={actions} compact />)}
        {l.shareRelay && <p className="rounded-xl border border-accent/30 bg-accent-soft/40 px-4 py-3 text-xs text-ink-2">Porthaven's own relay for a shared link. It closes when the share ends.</p>}
        {l.leak && (
          <div className="rounded-xl border border-bad/30 bg-bad/5 px-4 py-3">
            <div className="flex items-center gap-2 text-sm font-semibold text-bad"><Icon name="trend" size={15} />Memory keeps growing</div>
            <p className="mt-1 text-xs text-ink-2">From {mb(l.leak.fromMb)} to {mb(l.leak.toMb)} in {duration(l.leak.minutes * 60)} (about {mb(l.leak.perHour)} an hour), and still rising.</p>
            <p className="mt-1.5 text-xs text-muted">Usually a leak or a file watcher piling up modules. A restart gives the memory back.</p>
            <Button size="sm" variant="soft" icon="restart" className="mt-2" onClick={() => { const a = l.managed ? snap.apps.find((x) => x.id === l.managed) : null; void (a ? actions.restartApp(a) : actions.restart(l)); }}>Restart it</Button>
          </div>
        )}
        {l.twins && (
          <div className="rounded-xl border border-warn/40 bg-warn/5 px-4 py-3">
            <div className="flex items-center gap-2 text-sm font-semibold text-warn"><Icon name="warn" size={15} />Two servers on :{l.port}</div>
            <p className="mt-1 text-xs text-ink-2">This one listens on <span className="font-mono">{l.addresses.join(", ")}</span>; {l.twins.others.map((o) => <span key={o.pid}><b>{o.title}</b> (pid {o.pid}, up {duration(o.uptime)}) on <span className="font-mono">{o.addresses.join(", ")}</span></span>)} also does. IPv4 and IPv6 are separate sockets, so even <span className="font-mono">--strictPort</span> lets both start.</p>
            <p className="mt-1.5 text-xs text-muted"><span className="font-mono">localhost:{l.port}</span> reaches either one, depending on the browser or tool. {l.twins.older ? "This is the older one; it is probably left over." : "The other one is older and probably left over."}</p>
            {l.twins.older && !locked && <Button size="sm" variant="soft" icon="stop" className="mt-2" onClick={() => void actions.kill(l, "app")}>Stop this older one</Button>}
          </div>
        )}
        {l.agent && (
          <div className={cx("rounded-xl border px-4 py-3", l.agent.alive ? "border-line" : "border-warn/40 bg-warn/5")}>
            <div className={cx("flex items-center gap-2 text-sm font-semibold", l.agent.alive ? "text-ink" : "text-warn")}><Icon name="robot" size={15} />Started by {l.agent.label}</div>
            <p className="mt-1 text-xs text-muted">{l.agent.alive ? <>That session (pid {l.agent.pid}) is still running.</> :
              <>That session ended {l.agent.endedAt ? ago(l.agent.endedAt) : ""} and left this server running. Stop it if nobody needs it.</>}</p>
          </div>
        )}
        {l.exposureRisk && (
          <div className={cx("rounded-xl border px-4 py-3", l.exposureRisk.level === "medium" ? "border-warn/30 bg-warn/5" : "border-bad/40 bg-bad/10")}>
            <div className={cx("flex items-center gap-2 text-sm font-semibold", l.exposureRisk.level === "medium" ? "text-warn" : "text-bad")}>
              <Icon name="warn" size={15} />{l.exposureRisk.title}<span className="ml-auto rounded-md bg-black/20 px-1.5 text-[10px] uppercase tracking-wide">{l.exposureRisk.level}</span>
            </div>
            <p className="mt-1 text-xs text-ink-2">{l.exposureRisk.why}</p>
            <p className="mt-1.5 text-xs text-muted"><b className="text-ink-2">Fix:</b> {l.exposureRisk.fix}</p>
          </div>
        )}
        <Section title="HTTP" icon="globe" right={
          <button className="text-[11px] font-medium text-accent hover:underline disabled:opacity-50" disabled={checking}
            onClick={async () => { setChecking(true); await actions.probe(l); setChecking(false); }}>{checking ? <Spinner size={10} /> : "Check again"}</button>}>
          {l.probe ? (l.probe.ok ? (
            <dl className="grid grid-cols-[96px_1fr] gap-y-1.5 text-xs">
              <dt className="text-muted">Status</dt><dd><Badge tone={(l.probe.status || 0) < 400 ? "ok" : (l.probe.status || 0) < 500 ? "warn" : "bad"}>{l.probe.status} {l.probe.reason}</Badge> <span className="text-faint">in {l.probe.ms} ms</span></dd>
              {l.probe.title && <><dt className="text-muted">Page title</dt><dd className="text-ink">{l.probe.title}</dd></>}
              {l.probe.contentType && <><dt className="text-muted">Content</dt><dd className="font-mono text-ink-2">{l.probe.contentType}</dd></>}
              {l.probe.server && <><dt className="text-muted">Server</dt><dd className="font-mono text-ink-2">{l.probe.server}</dd></>}
              {l.probe.poweredBy && <><dt className="text-muted">Powered by</dt><dd className="font-mono text-ink-2">{l.probe.poweredBy}</dd></>}
              {l.probe.location && <><dt className="text-muted">Redirects to</dt><dd className="break-all font-mono text-ink-2">{l.probe.location}</dd></>}
              <dt className="text-muted">Checked</dt><dd className="text-faint">{ago(l.probe.checkedAt)}</dd>
              {l.health && l.health.n > 1 && <><dt className="text-muted">Response</dt>
                <dd className="flex items-center gap-2">
                  <Sparkline values={l.health.ms.map((x) => x || 0)} width={120} height={22} color="var(--info)" />
                  <span className="text-faint">{Math.round(l.health.ms.reduce<number>((a, b) => a + (b || 0), 0) / l.health.n)} ms avg · {l.health.up}/{l.health.n} ok</span>
                </dd></>}
            </dl>
          ) : <p className="text-xs text-muted">No HTTP answer: <span className="text-ink-2">{l.probe.error}</span>. It may speak another protocol (a database, a debugger, a socket server).</p>)
            : <p className="text-xs text-muted">{l.kind === "database" ? "Databases are not checked over HTTP." : l.kind === "system" || l.kind === "app" ? "System services and desktop apps are not checked (turn it on in Settings)." : "Checking…"}</p>}
        </Section>

        {(l.stableUrl || l.lanUrl) && (
          <Section title="Other addresses" icon="external">
            <div className="space-y-1.5">
              {l.stableUrl && <UrlRow label="Stable name" hint="Always reaches this app, whatever port it is on" url={l.stableUrl} actions={actions} />}
              {l.stableHttpsUrl && <UrlRow label="Stable name, HTTPS" hint="With a certificate from Porthaven's local CA" url={l.stableHttpsUrl} actions={actions} />}
              {l.lanUrl && <UrlRow label="From your phone" hint="Same Wi-Fi network" url={l.lanUrl} actions={actions} />}
            </div>
          </Section>
        )}

        <Section title="Process" icon="bolt">
          <dl className="grid grid-cols-[96px_1fr] gap-y-1.5 text-xs">
            <dt className="text-muted">PID</dt><dd className="tnum font-mono text-ink">{l.pid} <span className="text-faint">· {l.user}</span></dd>
            <dt className="text-muted">Up for</dt><dd className="text-ink-2">{duration(l.uptime)}</dd>
            <dt className="text-muted">CPU</dt><dd className="flex items-center gap-2"><Sparkline values={l.spark.cpu} width={120} height={22} /><span className="tnum text-ink-2">{l.cpu?.toFixed(1)}%</span></dd>
            <dt className="text-muted">Memory</dt><dd className="flex items-center gap-2"><Sparkline values={l.spark.mem} width={120} height={22} color="var(--info)" /><span className="tnum text-ink-2">{mb(l.memMb)}</span></dd>
            <dt className="text-muted">Connections</dt><dd className="tnum text-ink-2">{l.connections} open</dd>
            <dt className="text-muted">Command</dt>
            <dd className="group relative">
              <code className="block max-h-32 overflow-auto break-all rounded-md bg-panel-2 px-2 py-1.5 font-mono text-[11px] leading-relaxed text-ink-2">{l.args}</code>
              <button onClick={() => void actions.copyText(l.args, "Copied the command")} className="absolute right-1 top-1 rounded bg-panel px-1.5 text-[10px] text-muted opacity-0 transition group-hover:opacity-100">copy</button>
            </dd>
            {l.cwd && <><dt className="text-muted">Folder</dt>
              <dd>
                <div className="break-all font-mono text-[11px] text-ink-2">{shortPath(l.cwd, home)}</div>
                <div className="mt-1 flex gap-1">
                  <Button size="sm" variant="ghost" icon="folder" onClick={() => void actions.reveal(l.project?.root || l.cwd, "finder")}>Finder</Button>
                  <Button size="sm" variant="ghost" icon="code" onClick={() => void actions.reveal(l.project?.root || l.cwd, "editor")}>Editor</Button>
                  <Button size="sm" variant="ghost" icon="terminal" onClick={() => void actions.reveal(l.project?.root || l.cwd, "terminal")}>Terminal</Button>
                </div>
              </dd></>}
          </dl>
          {l.workers && l.workers.length > 0 && (
            <div className="mt-2 rounded-lg border border-line px-3 py-2 text-xs">
              <p className="mb-1 text-muted">Shares the socket with {l.workers.length} worker{l.workers.length > 1 ? "s" : ""}:</p>
              {l.workers.map((w) => <div key={w.pid} className="flex justify-between gap-2 font-mono text-[11px] text-ink-2"><span className="truncate">{w.pid} {w.display}</span><span className="text-faint">{mb(w.memMb)}</span></div>)}
            </div>
          )}
        </Section>

        <Section title="App" icon="tree">
          {detail ? <Tree d={detail} pid={l.pid} /> : <p className="text-xs text-muted"><Spinner size={10} /> Reading the process tree…</p>}
          {l.root && <p className="mt-2 text-[11px] text-muted">“Stop whole app” stops <span className="font-mono text-ink-2">{l.root.display.slice(0, 60)}</span> and its {l.root.count - 1} child process{l.root.count > 2 ? "es" : ""}.</p>}
          {app && <button onClick={() => onOpenApp(app.id)} className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline">Saved as “{app.name}” in Apps <Icon name="chevron" size={12} /></button>}
        </Section>

        <Section title="Network" icon="network">
          <div className="flex flex-wrap gap-1.5">{l.addresses.map((a) => <Badge key={a} tone={["*", "0.0.0.0", "::"].includes(a) ? "warn" : "neutral"}><span className="font-mono">{a === "*" ? "all interfaces" : a}</span></Badge>)}</div>
          <p className="mt-2 text-xs text-muted">{l.exposure === "network" ? <><span className="text-warn">Reachable from other devices on your network.</span> Dev servers usually only need 127.0.0.1 (for Vite, drop <span className="font-mono">--host</span>).</> : "Only this computer can reach it."}</p>
          {l.docker && <p className="mt-2 text-xs text-ink-2"><Icon name="docker" size={12} className="mr-1 inline" />Docker container <b>{l.docker.name}</b> · {l.docker.image} · <span className="font-mono">{l.docker.mapping}</span></p>}
          {l.hint && <p className="mt-1 text-[11px] text-faint">Port {l.port} is usually {l.hint}.</p>}
        </Section>

        <History port={l.port} snap={snap} />

        <Section title="Your notes" icon="note">
          <div className="space-y-2">
            <input className={inputCls} placeholder={`Name for :${l.port} (shown instead of “${l.title}”)`} value={label} onChange={(e) => setLabel(e.target.value)} onBlur={saveMeta}
              onKeyDown={(e) => e.key === "Enter" && (e.currentTarget as HTMLInputElement).blur()} />
            <textarea className={cx(inputCls, "min-h-[64px] resize-y")} placeholder="Notes: what it is, credentials hint, who owns it…" value={note} onChange={(e) => setNote(e.target.value)} onBlur={saveMeta} />
            <p className="text-[11px] text-faint">Saved for port {l.port}, so they stay when the app restarts.</p>
          </div>
        </Section>
      </div>

      <div className="space-y-2 border-t border-line bg-panel-2/40 px-5 py-3">
        {locked ? (
          <p className="flex items-center gap-2 text-xs text-muted"><Icon name="lock" size={14} />{l.risk === "self" ? "This is Porthaven itself. Stop it with Ctrl-C in its terminal." : "Owned by another user. Porthaven never uses sudo."}</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            <Button variant="danger" size="sm" icon="stop" onClick={() => void actions.kill(l, "process")}>Stop process</Button>
            {l.root && <Button variant="outline" size="sm" icon="stop" className="text-bad" onClick={() => void actions.kill(l, "app")}>Stop whole app ({l.root.count})</Button>}
            {l.cwd && !l.managed && <Button variant="outline" size="sm" icon="restart" onClick={() => void actions.restart(l)}>Restart</Button>}
            {l.cwd && !l.appId && <Button variant="ghost" size="sm" icon="plus" onClick={() => void actions.saveApp(l)}>Save as app</Button>}
            {l.docker && <Button variant="outline" size="sm" icon="docker" onClick={() => void api.dockerStop(l.docker!.id).then(() => actions.toast(`Stopped container ${l.docker!.name}`, "ok")).catch(actions.fail)}>docker stop</Button>}
          </div>
        )}
      </div>
    </aside>
  );
}

function Section({ title, icon, children, right }: { title: string; icon: string; children: ReactNode; right?: ReactNode }) {
  return (
    <section>
      <div className="mb-2 flex items-center gap-2">
        <Icon name={icon} size={13} className="text-faint" />
        <h3 className="text-[11px] font-semibold uppercase tracking-wider text-faint">{title}</h3>
        <span className="h-px flex-1 bg-line" />
        {right}
      </div>
      {children}
    </section>
  );
}

function Tree({ d, pid }: { d: ProcessDetail; pid: number }) {
  const anc = [...d.ancestors].reverse().slice(-4);
  const rootPid = d.root?.pid;
  const nodes = d.root ? [d.root, ...d.tree] : [d.process];
  const depth = new Map<number, number>();
  for (const n of nodes) depth.set(n.pid, n.pid === rootPid ? 0 : (depth.get(n.ppid) ?? 0) + 1);
  return (
    <div className="rounded-lg border border-line bg-panel-2/40 p-2 font-mono text-[11px]">
      {anc.filter((a) => !nodes.some((n) => n.pid === a.pid)).map((a) => (
        <div key={a.pid} className="truncate px-1 py-0.5 text-faint" title={a.args}>{a.pid} {a.display}</div>
      ))}
      {nodes.map((n) => (
        <div key={n.pid} title={n.args}
          className={cx("flex items-center gap-2 rounded px-1 py-0.5", n.pid === pid ? "bg-accent-soft text-accent-ink" : "text-ink-2")}
          style={{ paddingLeft: 4 + (depth.get(n.pid) || 0) * 14 }}>
          <span className="text-faint">{(depth.get(n.pid) || 0) > 0 ? "└" : "●"}</span>
          <span className="tnum shrink-0">{n.pid}</span>
          <span className="truncate">{n.display}</span>
          {n.ports.length > 0 && <span className="ml-auto shrink-0 rounded bg-panel px-1 text-accent">:{n.ports.join(", :")}</span>}
        </div>
      ))}
    </div>
  );
}

function UrlRow({ label, hint, url, actions }: { label: string; hint: string; url: string; actions: Actions }) {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-line px-2.5 py-1.5">
      <div className="min-w-0 flex-1">
        <div className="text-[11px] text-muted">{label} <span className="text-faint">· {hint}</span></div>
        <a href={url} target="_blank" rel="noopener" className="block truncate font-mono text-xs text-accent-ink hover:underline">{url}</a>
      </div>
      <IconButton icon="copy" title="Copy" onClick={() => void actions.copyText(url, "Copied")} size={14} className="h-7 w-7" />
    </div>
  );
}

function History({ port, snap }: { port: number; snap: Snapshot }) {
  const [rows, setRows] = useState<Interval[] | null>(null);
  const [at, setAt] = useState("");
  const [found, setFound] = useState<{ at: number | null; intervals: Interval[] } | null>(null);
  const [err, setErr] = useState("");
  const opened = snap.activity.filter((a) => a.port === port).length;
  useEffect(() => {
    let live = true;
    api.history(port).then((r) => live && setRows(r.intervals)).catch(() => live && setRows([]));
    return () => { live = false; };
  }, [port, opened]);
  const ask = async () => {
    if (!at.trim()) { setFound(null); return; }
    try { const r = await api.history(port, at); setFound(r); setErr(""); } catch (e) { setErr(e instanceof Error ? e.message : String(e)); setFound(null); }
  };
  const list = found ? found.intervals : (rows || []).slice(0, 8);
  return (
    <Section title={`History of :${port}`} icon="activity">
      <form className="mb-2 flex gap-1.5" onSubmit={(e) => { e.preventDefault(); void ask(); }}>
        <input className={cx(inputCls, "h-8 py-1 text-xs")} value={at} onChange={(e) => { setAt(e.target.value); if (!e.target.value) setFound(null); }}
          placeholder="What was here at… (yesterday 3pm, 2h ago, 14:30)" />
        <Button size="sm" type="submit" className="h-8">Look</Button>
      </form>
      {err && <p className="mb-1 text-[11px] text-bad">{err}</p>}
      {found && <p className="mb-1 text-[11px] text-muted">At {found.at ? new Date(found.at * 1000).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" }) : "that time"}: {found.intervals.length ? "" : "nothing was listening."}</p>}
      {rows === null ? <p className="text-xs text-muted"><Spinner size={10} /> Reading history…</p> : list.length === 0 && !found ? <p className="text-xs text-muted">Nothing recorded yet. Porthaven keeps 30 days.</p> : (
        <ol className="space-y-1 text-xs">
          {list.map((iv) => (
            <li key={`${iv.pid}-${iv.start}`} className="flex items-center gap-2">
              <Dot tone={iv.end ? "muted" : "ok"} />
              <span className="truncate text-ink-2" title={iv.command}>{iv.title || iv.command || `pid ${iv.pid}`}{iv.project && iv.project !== iv.title ? <span className="text-faint"> · {iv.project}</span> : null}</span>
              <span className="ml-auto shrink-0 text-[11px] text-faint" title={`${new Date(iv.start * 1000).toLocaleString()} → ${iv.end ? new Date(iv.end * 1000).toLocaleString() : "now"}`}>
                {iv.end ? `${span(iv.start)} → ${span(iv.end)}` : `since ${span(iv.start)}`}
              </span>
            </li>
          ))}
        </ol>
      )}
    </Section>
  );
}

function span(ts: number) {
  const d = new Date(ts * 1000);
  const today = new Date().toDateString() === d.toDateString();
  return today ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : d.toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" });
}
