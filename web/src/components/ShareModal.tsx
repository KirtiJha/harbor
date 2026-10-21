import qrcode from "qrcode-generator";
import { useMemo, useState } from "react";
import { api, type Listener, type Share, type Snapshot } from "../api";
import type { Actions } from "../actions";
import { useNow } from "../usePorthaven";
import { cx, duration } from "../util";
import { Icon } from "./Icon";
import { Badge, Button, Modal } from "./ui";

export function Qr({ text, size = 176 }: { text: string; size?: number }) {
  const svg = useMemo(() => {
    const q = qrcode(0, "M");
    q.addData(text);
    q.make();
    return q.createSvgTag({ cellSize: 4, margin: 2, scalable: true });
  }, [text]);
  return <div className="rounded-xl bg-white p-2 [&_svg]:h-full [&_svg]:w-full" style={{ width: size, height: size }} dangerouslySetInnerHTML={{ __html: svg }} />;
}

const DURATIONS: [number, string][] = [[15, "15 minutes"], [60, "1 hour"], [240, "4 hours"], [480, "8 hours"]];

/** Share one dev server for a while: on this network (phone, tablet, a colleague's laptop) or publicly. */
export function ShareModal({ l, snap, actions, onClose }: { l: Listener | null; snap: Snapshot; actions: Actions; onClose: () => void }) {
  const [picked, setMode] = useState<"lan" | "public" | null>(null);
  const [minutes, setMinutes] = useState(60);
  const [busy, setBusy] = useState(false);
  if (!l) return null;
  const shares = snap.shares.filter((s) => s.port === l.port);
  const tunnels = snap.me.tunnels || [];
  const canLan = !!snap.me.lanIp && !shares.some((s) => s.mode === "lan");
  const canPublic = tunnels.length > 0 && !shares.some((s) => s.mode === "public");
  const mode = picked && (picked === "lan" ? canLan : canPublic) ? picked : canLan ? "lan" : "public";
  const start = async () => {
    setBusy(true);
    try {
      await api.share(l.port, mode, minutes);
      actions.toast(<>Sharing <b>:{l.port}</b> {mode === "lan" ? "on your network" : "publicly"}.</>, "ok");
    } catch (e) { actions.fail(e); } finally { setBusy(false); }
  };
  return (
    <Modal open onClose={onClose} title={`Share :${l.port} ${l.title}`} width={620}
      subtitle="The app stays on 127.0.0.1. Porthaven opens a separate door for the link, lets in only visitors who have the link, and closes it when time is up.">
      <div className="space-y-4">
        {shares.map((s) => <ShareCard key={s.id} s={s} actions={actions} />)}
        {(canLan || canPublic) && (
          <div className="rounded-xl border border-line p-4">
            <div className="grid grid-cols-2 gap-2">
              <ModeButton on={mode === "lan"} onClick={() => setMode("lan")} icon="network" title="On this network"
                sub={snap.me.lanIp ? `Phones and laptops on the same Wi-Fi · ${snap.me.lanIp}` : "Not connected to a local network"} disabled={!canLan} />
              <ModeButton on={mode === "public"} onClick={() => setMode("public")} icon="globe" title="Public link"
                sub={tunnels.length ? `Through ${tunnels[0]}; anyone with the link` : "Install cloudflared or ngrok to use this"} disabled={!canPublic} />
            </div>
            <div className="mt-3 flex items-center gap-2">
              <span className="text-xs text-muted">For</span>
              <select value={minutes} onChange={(e) => setMinutes(Number(e.target.value))} className="h-8 rounded-lg border border-line bg-panel px-2 text-xs text-ink-2">
                {DURATIONS.map(([m, label]) => <option key={m} value={m}>{label}</option>)}
              </select>
              <Button variant="primary" icon="share" className="ml-auto" busy={busy} onClick={() => void start()}
                disabled={mode === "lan" ? !canLan : !canPublic}>
                Start sharing
              </Button>
            </div>
            {mode === "public" && <p className="mt-2 text-[11px] text-warn">A public link reaches the internet. Share it only with people you trust, and stop it when you are done.</p>}
            {!tunnels.length && mode === "public" && <p className="mt-1 text-[11px] text-muted">Install one: <span className="font-mono">brew install cloudflared</span> (or ngrok), then reopen this.</p>}
          </div>
        )}
        <p className="text-[11px] text-faint">Porthaven refuses to share debuggers, notebooks, databases and debug pages. In a terminal: <span className="font-mono">porthaven share {l.port}</span></p>
      </div>
    </Modal>
  );
}

function ModeButton({ on, onClick, icon, title, sub, disabled }: { on: boolean; onClick: () => void; icon: string; title: string; sub: string; disabled?: boolean }) {
  return (
    <button disabled={disabled} onClick={onClick} className={cx("rounded-xl border p-3 text-left transition disabled:opacity-40",
      on ? "border-accent bg-accent-soft" : "border-line hover:border-line-2")}>
      <div className={cx("flex items-center gap-2 text-sm font-semibold", on ? "text-accent-ink" : "text-ink")}><Icon name={icon} size={15} />{title}</div>
      <p className="mt-0.5 text-[11px] text-muted">{sub}</p>
    </button>
  );
}

export function ShareCard({ s, actions, compact }: { s: Share; actions: Actions; compact?: boolean }) {
  const now = useNow(1000);
  const left = Math.max(0, s.expiresAt - now);
  const stop = async () => { try { await api.unshare(s.id); actions.toast(`Stopped sharing :${s.port}.`, "ok"); } catch (e) { actions.fail(e); } };
  return (
    <div className={cx("flex gap-4 rounded-xl border p-3", s.mode === "public" ? "border-warn/40 bg-warn/5" : "border-accent/30 bg-accent-soft/40")}>
      {s.url && !compact && <Qr text={s.url} size={150} />}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <Badge tone={s.mode === "public" ? "warn" : "accent"}><Icon name={s.mode === "public" ? "globe" : "network"} size={11} />{s.mode === "public" ? `Public via ${s.tunnel}` : "On your network"}</Badge>
          <span className="text-[11px] text-muted">ends in {duration(left)}</span>
        </div>
        {s.url ? (
          <div className="mt-2 flex items-center gap-1.5">
            <a href={s.url} target="_blank" rel="noopener" className="truncate font-mono text-xs text-accent-ink hover:underline">{s.url}</a>
            <button className="shrink-0 rounded-md bg-panel px-1.5 py-0.5 text-[10px] text-muted hover:text-ink" onClick={() => void actions.copyText(s.url!, "Copied the link")}>copy</button>
          </div>
        ) : <p className="mt-2 text-xs text-muted">Waiting for the tunnel…</p>}
        <p className="mt-1.5 text-[11px] text-muted">{s.requests} request{s.requests === 1 ? "" : "s"} so far{!compact && s.mode === "lan" ? " · scan the code with your phone's camera" : ""}</p>
        <Button size="sm" variant="outline" icon="stop" className="mt-2 text-bad" onClick={() => void stop()}>Stop sharing</Button>
      </div>
    </div>
  );
}
