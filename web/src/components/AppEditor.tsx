import { useEffect, useState } from "react";
import { api, type App, type Discovered } from "../api";
import { useUi } from "./ui";
import { Badge, Button, Field, inputCls, Modal, Spinner, Toggle } from "./ui";
import { Icon } from "./Icon";
import { cx, shortPath } from "../util";

export function AppEditor({ app, onClose, onStart, groups = [], porthavenPort }: { app: Partial<App> | null; onClose: () => void; onStart: (a: App) => void; groups?: string[]; porthavenPort?: number }) {
  const { toast } = useUi();
  const [v, setV] = useState<Partial<App>>({});
  const [envText, setEnvText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [free, setFree] = useState<number[]>([]);

  useEffect(() => {
    if (!app) return;
    setV({ openPath: "/", ...app });
    setEnvText(Object.entries(app.env || {}).map(([k, val]) => `${k}=${val}`).join("\n"));
    setErr("");
  }, [app]);

  useEffect(() => {
    if (!app || !v.port) { setFree([]); return; }
    const t = window.setTimeout(() => api.checkPort(Number(v.port)).then((r) => setFree(r.free ? [] : r.next)).catch(() => {}), 250);
    return () => window.clearTimeout(t);
  }, [v.port, app]);

  if (!app) return null;
  const editing = !!app.id;

  const save = async (start = false) => {
    setBusy(true);
    setErr("");
    const env = Object.fromEntries(envText.split("\n").map((l) => l.trim()).filter((l) => l && !l.startsWith("#") && l.includes("=")).map((l) => [l.slice(0, l.indexOf("=")).trim(), l.slice(l.indexOf("=") + 1).trim()]));
    const body = { name: v.name, cwd: v.cwd, command: v.command, port: v.port || null, openPath: v.openPath || "/", env, autoRestart: !!v.autoRestart,
      color: v.color || "", group: (v.group || "").trim(), slug: (v.slug || "").trim().toLowerCase() };
    try {
      const saved = editing ? await api.updateApp(app.id!, body) : await api.createApp(body);
      toast(<>{editing ? "Saved" : "Added"} <b>{saved.name}</b>.</>, "ok");
      onClose();
      if (start) onStart(saved);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const set = (k: keyof App) => (e: React.ChangeEvent<HTMLInputElement>) => setV({ ...v, [k]: k === "port" ? (e.target.value ? Number(e.target.value) : null) : e.target.value });

  return (
    <Modal open onClose={onClose} title={editing ? `Edit ${app.name}` : "Add an app"} width={620}
      subtitle="Porthaven runs the command in the folder with your shell, sets PORT, and replaces {port} in the command."
      footer={<>
        {err && <span className="mr-auto max-w-[60%] text-xs text-bad">{err}</span>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        {!editing && <Button onClick={() => void save(false)} busy={busy}>Save</Button>}
        <Button variant="primary" onClick={() => void save(!editing)} busy={busy} icon={editing ? "check" : "play"}>{editing ? "Save" : "Save and start"}</Button>
      </>}>
      <form className="grid grid-cols-2 gap-4" onSubmit={(e) => { e.preventDefault(); void save(!editing); }}>
        <Field label="Name"><input autoFocus className={inputCls} value={v.name || ""} onChange={set("name")} placeholder="Shop web" /></Field>
        <Field label="Port" hint={free.length ? <span className="text-warn">In use now. Free: {free.map((p) => <button type="button" key={p} className="mx-0.5 font-mono underline" onClick={() => setV({ ...v, port: p })}>{p}</button>)}</span> : "Expected port; leave empty if it picks its own."}>
          <input className={cx(inputCls, "font-mono")} type="number" min={1} max={65535} value={v.port ?? ""} onChange={set("port")} placeholder="5173" />
        </Field>
        <div className="col-span-2"><Field label="Folder"><input className={cx(inputCls, "font-mono text-xs")} value={v.cwd || ""} onChange={set("cwd")} placeholder="~/projects/my-app" /></Field></div>
        <div className="col-span-2"><Field label="Command" hint={<>e.g. <span className="font-mono">npm run dev -- --port {"{port}"} --strictPort</span>, <span className="font-mono">make dev</span>, <span className="font-mono">uvicorn app:app --reload --port {"{port}"}</span></>}>
          <input className={cx(inputCls, "font-mono text-xs")} value={v.command || ""} onChange={set("command")} placeholder="npm run dev" />
        </Field></div>
        <Field label="Group" hint="Apps in a group start and stop together (e.g. backend + frontend).">
          <input className={inputCls} list="porthaven-groups" value={v.group || ""} onChange={set("group")} placeholder="Shop" />
          <datalist id="porthaven-groups">{groups.map((g) => <option key={g} value={g} />)}</datalist>
        </Field>
        <Field label="Short name" hint={<>Stable address: <span className="font-mono">http://{(v.slug || slug(v.name || "app"))}.localhost:{porthavenPort || 7475}</span></>}>
          <input className={cx(inputCls, "font-mono text-xs")} value={v.slug || ""} onChange={set("slug")} placeholder={slug(v.name || "my-app")} />
        </Field>
        <Field label="Open path" hint="Where “Open” goes, e.g. /docs"><input className={cx(inputCls, "font-mono text-xs")} value={v.openPath || ""} onChange={set("openPath")} /></Field>
        <Field label="Colour"><div className="flex gap-1.5 pt-1">{["", "#2dd4bf", "#60a5fa", "#a78bfa", "#f472b6", "#fbbf24", "#34d399", "#fb923c", "#f87171"].map((c) => (
          <button type="button" key={c || "auto"} onClick={() => setV({ ...v, color: c })} title={c || "automatic"}
            className={cx("h-6 w-6 rounded-md border", (v.color || "") === c ? "ring-2 ring-accent ring-offset-2 ring-offset-panel" : "border-line-2")}
            style={{ background: c || "conic-gradient(#2dd4bf,#60a5fa,#a78bfa,#f472b6,#fbbf24,#2dd4bf)" }} />))}</div></Field>
        <div className="col-span-2"><Field label="Environment" hint="One NAME=value per line. Kept in ~/.porthaven/state.json, so do not put secrets here; let the app read its own .env.">
          <textarea className={cx(inputCls, "min-h-[70px] font-mono text-xs")} value={envText} onChange={(e) => setEnvText(e.target.value)} placeholder={"NODE_ENV=development\nDEBUG=1"} />
        </Field></div>
        <div className="col-span-2"><Toggle checked={!!v.autoRestart} onChange={(b) => setV({ ...v, autoRestart: b })} label={<span>Restart automatically if it crashes <span className="text-faint">(up to 3 times in 2 minutes)</span></span>} /></div>
        <button type="submit" className="hidden" />
      </form>
    </Modal>
  );
}

export function DiscoverModal({ open, onClose, home, onPick }: { open: boolean; onClose: () => void; home: string; onPick: (a: Partial<App>) => void }) {
  const [folder, setFolder] = useState("~");
  const [depth, setDepth] = useState(3);
  const [res, setRes] = useState<{ root: string; items: Discovered[]; truncated: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const { toast } = useUi();

  const scan = async () => {
    setBusy(true);
    setErr("");
    try {
      setRes(await api.discover(folder, depth));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => { if (open && !res) void scan(); }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const add = async (d: Discovered) => {
    try {
      const a = await api.createApp({ name: d.script === "dev" || d.script === "start" ? d.name : `${d.name} · ${d.script}`, cwd: d.cwd, command: d.command, port: d.port });
      toast(<>Added <b>{a.name}</b>.</>, "ok");
      setRes((r) => r && { ...r, items: r.items.map((x) => x === d ? { ...x, saved: true } : x) });
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "bad");
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Find projects" width={760} subtitle="Looks for package.json scripts, Makefile targets, Django/FastAPI/Flask/Streamlit apps and Docker Compose files.">
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); void scan(); }}>
        <input className={cx(inputCls, "font-mono text-xs")} value={folder} onChange={(e) => setFolder(e.target.value)} />
        <select className={cx(inputCls, "w-32")} value={depth} onChange={(e) => setDepth(Number(e.target.value))}>
          {[1, 2, 3, 4, 5].map((d) => <option key={d} value={d}>{d} level{d > 1 ? "s" : ""} deep</option>)}
        </select>
        <Button type="submit" variant="primary" icon="radar" busy={busy}>Scan</Button>
      </form>
      {err && <p className="mt-3 text-xs text-bad">{err}</p>}
      <div className="mt-4 max-h-[55vh] overflow-y-auto rounded-xl border border-line">
        {busy && !res && <p className="p-6 text-center text-sm text-muted"><Spinner /> Scanning…</p>}
        {res && res.items.length === 0 && <p className="p-6 text-center text-sm text-muted">No runnable projects found in {shortPath(res.root, home)}.</p>}
        {res?.items.map((d, i) => (
          <div key={i} className="flex items-center gap-3 border-b border-line px-4 py-2.5 last:border-0">
            <Badge tone={d.type === "node" ? "ok" : d.type === "python" ? "info" : d.type === "docker" ? "violet" : "neutral"}>{d.type}</Badge>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2"><span className="truncate text-sm font-medium text-ink">{d.name}</span><span className="font-mono text-xs text-accent-ink">{d.command}</span>{d.port && <span className="font-mono text-[11px] text-faint">:{d.port}</span>}</div>
              <div className="truncate font-mono text-[11px] text-faint">{shortPath(d.cwd, home)} · {d.detail}</div>
            </div>
            {d.saved ? <span className="flex items-center gap-1 text-xs text-ok"><Icon name="check" size={13} />Added</span> : <>
              <Button size="sm" variant="ghost" onClick={() => onPick({ name: d.name, cwd: d.cwd, command: d.command, port: d.port })}>Edit first</Button>
              <Button size="sm" variant="soft" icon="plus" onClick={() => void add(d)}>Add</Button>
            </>}
          </div>
        ))}
      </div>
      {res?.truncated && <p className="mt-2 text-xs text-muted">Showing the first 200. Pick a narrower folder to see the rest.</p>}
    </Modal>
  );
}

function slug(s: string) {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40) || "app";
}
