import { useEffect, useMemo, useRef, useState } from "react";
import { api, type LogLine } from "../api";
import { cx } from "../util";
import { Icon } from "./Icon";
import { IconButton } from "./ui";

/* Minimal ANSI SGR → spans (colours, bold, dim). Everything else is dropped. */
function ansi(text: string) {
  const out: { t: string; c: string }[] = [];
  let cls: string[] = [];
  const re = /\x1b\[([0-9;]*)m/g;
  let last = 0, m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push({ t: text.slice(last, m.index), c: cls.join(" ") });
    for (const code of (m[1] || "0").split(";").map(Number)) {
      if (code === 0) cls = [];
      else if (code === 1) cls.push("ansi-bold");
      else if (code === 2) cls.push("ansi-dim");
      else if ((code >= 30 && code <= 37) || (code >= 90 && code <= 97)) cls = [...cls.filter((c) => !/ansi-\d/.test(c)), `ansi-${code}`];
      else if (code === 39) cls = cls.filter((c) => !/ansi-\d/.test(c));
    }
    last = re.lastIndex;
  }
  if (last < text.length) out.push({ t: text.slice(last), c: cls.join(" ") });
  return out.map((p) => ({ ...p, t: p.t.replace(/\x1b\[[0-9;?]*[A-Za-z]/g, "") }));
}

const ERR = /\b(error|failed|exception|traceback|err!|cannot|refused|eaddrinuse)\b/i;
const WARN = /\b(warn(ing)?|deprecated)\b/i;
const URL = /(https?:\/\/(?:localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0)(?::\d+)?[^\s\x1b]*)/g;

export function LogView({ appId, live }: { appId: string; live: boolean }) {
  const [lines, setLines] = useState<LogLine[]>([]);
  const [filter, setFilter] = useState("");
  const [onlyProblems, setOnlyProblems] = useState(false);
  const [follow, setFollow] = useState(true);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let es: EventSource | null = null;
    let alive = true;
    setLines([]);
    api.logs(appId).then((r) => {
      if (!alive) return;
      setLines(r.lines);
      es = new EventSource(`/api/apps/${appId}/logs/stream?after=${r.seq}`);
      es.addEventListener("lines", (e) => {
        const d = JSON.parse((e as MessageEvent).data) as { lines: LogLine[] };
        // A new run starts again at seq 1; its "$ command" line separates it from the previous run's output.
        setLines((prev) => [...prev, ...d.lines].slice(-4000));
      });
    }).catch(() => {});
    return () => { alive = false; es?.close(); };
  }, [appId]);

  const shown = useMemo(() => lines.filter((l) => (!filter || l.text.toLowerCase().includes(filter.toLowerCase())) && (!onlyProblems || ERR.test(l.text) || WARN.test(l.text))), [lines, filter, onlyProblems]);

  useEffect(() => {
    if (follow && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [shown, follow]);

  const problems = useMemo(() => lines.filter((l) => ERR.test(l.text)).length, [lines]);

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-line bg-[#05070c]">
      <div className="flex items-center gap-2 border-b border-white/5 px-3 py-2">
        <span className={cx("h-2 w-2 rounded-full", live ? "bg-emerald-400 pulse text-emerald-400" : "bg-slate-600")} />
        <span className="text-[11px] font-medium text-slate-400">{live ? "live" : "not running"} · {lines.length} lines</span>
        {problems > 0 && <button onClick={() => setOnlyProblems(!onlyProblems)} className={cx("rounded px-1.5 py-0.5 text-[11px] font-medium", onlyProblems ? "bg-red-500/20 text-red-300" : "text-red-300/80 hover:bg-red-500/10")}>{problems} error line{problems > 1 ? "s" : ""}</button>}
        <div className="ml-auto flex items-center gap-1">
          <div className="flex items-center gap-1.5 rounded-md bg-white/5 px-2 py-1">
            <Icon name="search" size={12} className="text-slate-500" />
            <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter output" className="w-36 bg-transparent text-[11px] text-slate-200 outline-none placeholder:text-slate-600" />
          </div>
          <IconButton icon="down" title={follow ? "Following new output" : "Follow new output"} active={follow} onClick={() => setFollow(!follow)} size={14} className="h-7 w-7 text-slate-400" />
          <IconButton icon="copy" title="Copy output" size={14} className="h-7 w-7 text-slate-400"
            onClick={() => void navigator.clipboard.writeText(shown.map((l) => l.text.replace(/\x1b\[[0-9;?]*[A-Za-z]/g, "")).join("\n"))} />
          <IconButton icon="trash" title="Clear output" size={14} className="h-7 w-7 text-slate-400" onClick={() => { void api.clearLogs(appId); setLines([]); }} />
        </div>
      </div>
      <div ref={box} onScroll={(e) => { const el = e.currentTarget; const atEnd = el.scrollHeight - el.scrollTop - el.clientHeight < 30; if (atEnd !== follow) setFollow(atEnd); }}
        className="min-h-0 flex-1 overflow-auto px-3 py-2 font-mono text-[11.5px] leading-[1.55] text-slate-300">
        {shown.length === 0 && <p className="py-8 text-center text-slate-600">{lines.length ? "No lines match." : "No output yet. Start the app to see its output here."}</p>}
        {shown.map((l) => (
          <div key={`${l.seq}-${l.t}`} className={cx("whitespace-pre-wrap break-all", l.stream === "porthaven" && "text-teal-300/80", ERR.test(l.text) && l.stream !== "porthaven" && "bg-red-500/[0.07]", WARN.test(l.text) && "bg-amber-500/[0.05]")}>
            {ansi(l.text).map((p, i) => <span key={i} className={p.c}>{linkify(p.t)}</span>)}
          </div>
        ))}
      </div>
    </div>
  );
}

function linkify(t: string) {
  const parts = t.split(URL);
  return parts.map((p, i) => i % 2 ? <a key={i} href={p.replace("0.0.0.0", "localhost")} target="_blank" rel="noopener" className="text-teal-300 underline decoration-teal-300/30 hover:decoration-teal-300">{p}</a> : p);
}
