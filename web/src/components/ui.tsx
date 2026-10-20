import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { cx } from "../util";
import { Icon } from "./Icon";

type BtnProps = {
  children?: ReactNode; onClick?: (e: React.MouseEvent) => void; variant?: "primary" | "ghost" | "danger" | "soft" | "outline";
  size?: "sm" | "md"; icon?: string; title?: string; disabled?: boolean; className?: string; type?: "button" | "submit"; busy?: boolean;
};

export function Button({ children, onClick, variant = "outline", size = "md", icon, title, disabled, className, type = "button", busy }: BtnProps) {
  const styles = {
    primary: "bg-accent text-[#04201c] hover:brightness-110 font-semibold shadow-sm",
    danger: "bg-bad/90 text-white hover:bg-bad font-semibold",
    soft: "bg-accent-soft text-accent-ink hover:brightness-110",
    ghost: "text-ink-2 hover:bg-panel-2 hover:text-ink",
    outline: "border border-line-2 text-ink-2 hover:text-ink hover:border-faint bg-panel",
  }[variant];
  return (
    <button type={type} title={title} disabled={disabled || busy} onClick={onClick}
      className={cx("inline-flex items-center justify-center gap-1.5 rounded-lg transition select-none whitespace-nowrap",
        "disabled:opacity-40 disabled:pointer-events-none focus-visible:outline-2 focus-visible:outline-accent",
        size === "sm" ? "h-7 px-2.5 text-xs" : "h-9 px-3.5 text-sm", styles, className)}>
      {busy ? <Spinner /> : icon && <Icon name={icon} size={size === "sm" ? 14 : 16} />}
      {children}
    </button>
  );
}

export function IconButton({ icon, title, onClick, className, active, danger, size = 16, disabled }: {
  icon: string; title: string; onClick?: (e: React.MouseEvent) => void; className?: string; active?: boolean; danger?: boolean; size?: number; disabled?: boolean;
}) {
  return (
    <button type="button" title={title} aria-label={title} disabled={disabled}
      onClick={(e) => { e.stopPropagation(); onClick?.(e); }}
      className={cx("inline-flex h-8 w-8 items-center justify-center rounded-lg transition disabled:opacity-30",
        danger ? "text-muted hover:bg-bad/15 hover:text-bad" : "text-muted hover:bg-panel-2 hover:text-ink",
        active && "text-accent", className)}>
      <Icon name={icon} size={size} />
    </button>
  );
}

export function Spinner({ size = 14 }: { size?: number }) {
  return <span style={{ width: size, height: size }} className="inline-block animate-spin rounded-full border-2 border-current border-t-transparent opacity-70" />;
}

export function Badge({ children, tone = "neutral", className, title }: { children: ReactNode; tone?: "neutral" | "ok" | "warn" | "bad" | "info" | "accent" | "violet"; className?: string; title?: string }) {
  const t = {
    neutral: "bg-panel-2 text-muted border-line",
    ok: "bg-ok/10 text-ok border-ok/25",
    warn: "bg-warn/10 text-warn border-warn/25",
    bad: "bg-bad/10 text-bad border-bad/25",
    info: "bg-info/10 text-info border-info/25",
    accent: "bg-accent-soft text-accent-ink border-accent/25",
    violet: "bg-violet-500/10 text-violet-400 border-violet-500/25",
  }[tone];
  return <span title={title} className={cx("inline-flex items-center gap-1 rounded-md border px-1.5 py-px text-[11px] font-medium leading-4 whitespace-nowrap", t, className)}>{children}</span>;
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="rounded border border-line-2 bg-panel-2 px-1.5 py-px font-mono text-[10px] text-muted">{children}</kbd>;
}

export function Dot({ tone, pulse }: { tone: "ok" | "warn" | "bad" | "muted" | "info" | "accent"; pulse?: boolean }) {
  const c = { ok: "bg-ok text-ok", warn: "bg-warn text-warn", bad: "bg-bad text-bad", muted: "bg-faint text-faint", info: "bg-info text-info", accent: "bg-accent text-accent" }[tone];
  return <span className={cx("inline-block h-2 w-2 shrink-0 rounded-full", c, pulse && "pulse")} />;
}

export function Modal({ open, onClose, title, children, width = 560, footer, subtitle }: {
  open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; width?: number; footer?: ReactNode; subtitle?: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const k = (e: KeyboardEvent) => e.key === "Escape" && (e.stopPropagation(), onClose());
    window.addEventListener("keydown", k, true);
    return () => window.removeEventListener("keydown", k, true);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/50 p-4 pt-[10vh] backdrop-blur-sm" onMouseDown={onClose}>
      <div className="card pop w-full overflow-hidden" style={{ maxWidth: width }} onMouseDown={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
          <div>
            <h2 className="text-[15px] font-semibold text-ink">{title}</h2>
            {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
          </div>
          <IconButton icon="close" title="Close (Esc)" onClick={onClose} />
        </div>
        <div className="px-5 py-4">{children}</div>
        {footer && <div className="flex items-center justify-end gap-2 border-t border-line bg-panel-2/50 px-5 py-3">{footer}</div>}
      </div>
    </div>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-ink-2">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-muted">{hint}</span>}
    </label>
  );
}

export const inputCls = "w-full rounded-lg border border-line-2 bg-panel-2/60 px-3 py-2 text-sm text-ink placeholder:text-faint outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20";

export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label?: ReactNode }) {
  return (
    <button type="button" onClick={() => onChange(!checked)} className="inline-flex items-center gap-2 text-sm text-ink-2" role="switch" aria-checked={checked}>
      <span className={cx("relative h-5 w-9 rounded-full transition", checked ? "bg-accent" : "bg-line-2")}>
        <span className={cx("absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all", checked ? "left-[18px]" : "left-0.5")} />
      </span>
      {label}
    </button>
  );
}

/* ------------------------------------------------------------------ menus */

export type MenuItem = { label: string; icon?: string; onClick: () => void; danger?: boolean; hint?: string; disabled?: boolean } | "sep";

export function Menu({ items, trigger, align = "right" }: { items: MenuItem[]; trigger: (open: () => void) => ReactNode; align?: "left" | "right" }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", esc);
    return () => { window.removeEventListener("mousedown", close); window.removeEventListener("keydown", esc); };
  }, [open]);
  return (
    <div className="relative" ref={ref} onClick={(e) => e.stopPropagation()}>
      {trigger(() => setOpen((o) => !o))}
      {open && (
        <div className={cx("card pop absolute z-40 mt-1 min-w-[230px] p-1", align === "right" ? "right-0" : "left-0")}>
          {items.map((it, i) => it === "sep" ? <div key={i} className="my-1 border-t border-line" /> : (
            <button key={i} type="button" disabled={it.disabled}
              onClick={() => { setOpen(false); it.onClick(); }}
              className={cx("flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-[13px] transition disabled:opacity-40",
                it.danger ? "text-bad hover:bg-bad/10" : "text-ink-2 hover:bg-panel-2 hover:text-ink")}>
              {it.icon && <Icon name={it.icon} size={15} className="shrink-0 opacity-80" />}
              <span className="flex-1">{it.label}</span>
              {it.hint && <span className="text-[11px] text-faint">{it.hint}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ toasts + confirm */

type Toast = { id: number; text: ReactNode; tone: "ok" | "bad" | "info" | "warn"; action?: { label: string; onClick: () => void } };
type ConfirmOpts = { title: string; body?: ReactNode; confirm?: string; danger?: boolean; requireText?: string };

const Ctx = createContext<{
  toast: (text: ReactNode, tone?: Toast["tone"], action?: Toast["action"]) => void;
  confirm: (o: ConfirmOpts) => Promise<boolean>;
}>({ toast: () => {}, confirm: async () => false });

export const useUi = () => useContext(Ctx);

export function UiProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [dlg, setDlg] = useState<(ConfirmOpts & { resolve: (v: boolean) => void }) | null>(null);
  const [typed, setTyped] = useState("");
  const toast = useCallback((text: ReactNode, tone: Toast["tone"] = "info", action?: Toast["action"]) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t.slice(-4), { id, text, tone, action }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), action ? 8000 : 4500);
  }, []);
  const confirm = useCallback((o: ConfirmOpts) => new Promise<boolean>((resolve) => { setTyped(""); setDlg({ ...o, resolve }); }), []);
  const done = (v: boolean) => { dlg?.resolve(v); setDlg(null); };
  const blocked = !!dlg?.requireText && typed.trim() !== dlg.requireText;
  return (
    <Ctx.Provider value={{ toast, confirm }}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[380px] flex-col gap-2">
        {toasts.map((t) => (
          <div key={t.id} className="card slide-in pointer-events-auto flex items-start gap-3 px-4 py-3 text-sm">
            <span className="mt-1.5"><Dot tone={t.tone === "info" ? "accent" : t.tone} /></span>
            <div className="flex-1 text-ink-2">{t.text}</div>
            {t.action && <button className="text-xs font-semibold text-accent hover:underline" onClick={() => { t.action!.onClick(); setToasts((x) => x.filter((y) => y.id !== t.id)); }}>{t.action.label}</button>}
          </div>
        ))}
      </div>
      <Modal open={!!dlg} onClose={() => done(false)} title={dlg?.title} width={460}
        footer={<>
          <Button variant="ghost" onClick={() => done(false)}>Cancel</Button>
          <Button variant={dlg?.danger ? "danger" : "primary"} disabled={blocked} onClick={() => done(true)}>{dlg?.confirm || "Confirm"}</Button>
        </>}>
        <form onSubmit={(e) => { e.preventDefault(); if (!blocked) done(true); }}>
          <div className="text-sm leading-relaxed text-ink-2">{dlg?.body}</div>
          {dlg?.requireText && (
            <div className="mt-3">
              <p className="mb-1.5 text-xs text-muted">Type <span className="font-mono text-ink">{dlg.requireText}</span> to confirm.</p>
              <input autoFocus className={inputCls} value={typed} onChange={(e) => setTyped(e.target.value)} />
            </div>
          )}
          <button type="submit" className="hidden" />
        </form>
      </Modal>
    </Ctx.Provider>
  );
}

/* ------------------------------------------------------------------ sparkline */

export function Sparkline({ values, color = "var(--accent)", width = 72, height = 22, max }: { values: number[]; color?: string; width?: number; height?: number; max?: number }) {
  if (values.length < 2) return <svg width={width} height={height} />;
  const hi = Math.max(max ?? 0, ...values, 1e-6);
  const step = width / (values.length - 1);
  const pts = values.map((v, i) => [i * step, height - 2 - (v / hi) * (height - 4)]);
  const d = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("");
  return (
    <svg width={width} height={height} className="overflow-visible">
      <path d={`${d}L${width},${height}L0,${height}Z`} fill={color} opacity={0.12} />
      <path d={d} fill="none" stroke={color} strokeWidth={1.4} strokeLinejoin="round" />
      <circle cx={pts[pts.length - 1][0]} cy={pts[pts.length - 1][1]} r={1.8} fill={color} />
    </svg>
  );
}
