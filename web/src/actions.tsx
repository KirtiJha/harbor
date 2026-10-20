import { useMemo } from "react";
import { api, ApiError, type App, type Listener } from "./api";
import { useUi } from "./components/ui";
import { copy, duration, mb, url } from "./util";

/** Every action on a port or an app, with its confirmation and its toast, so rows, the drawer and the
 * command palette behave the same way. */
export function useActions(onEditApp?: (a: Partial<App>) => void) {
  const { toast, confirm } = useUi();

  return useMemo(() => {
    const fail = (e: unknown) => toast(e instanceof Error ? e.message : String(e), "bad");

    async function kill(l: Listener, mode: "process" | "app" = "process") {
      const whole = mode === "app" && l.root;
      const what = whole ? `${l.root!.display}` : l.display;
      const sys = l.risk === "system" || l.risk === "app";
      const ok = await confirm({
        title: whole ? `Stop the whole app on :${l.port}?` : `Stop the process on :${l.port}?`,
        danger: true,
        confirm: whole ? `Stop ${l.root!.count} processes` : "Stop process",
        requireText: sys ? String(l.port) : undefined,
        body: (
          <div className="space-y-2">
            <p><span className="font-semibold text-ink">{l.title}</span>{l.project && <span className="text-muted"> · {l.project.name}</span>}</p>
            <p className="break-all rounded-lg bg-panel-2 px-3 py-2 font-mono text-xs text-ink-2">{what}</p>
            {whole && <p className="text-xs text-muted">Stops the launcher (pid {l.root!.pid}) and every process under it, so nothing restarts the server.</p>}
            {sys && <p className="text-xs text-warn">This is {l.risk === "system" ? "a macOS service" : `part of ${l.appBundle || "a desktop app"}`}. Stopping it may break that app until it restarts.</p>}
            <p className="text-xs text-muted">Harbor asks politely first (SIGTERM) and forces it (SIGKILL) only if it is still running after a few seconds.</p>
          </div>
        ),
      });
      if (!ok) return false;
      try {
        const r = await api.kill(l.pid, mode, sys);
        const n = r.exited.length + r.killed.length;
        if (r.survivors.length) toast(`${n} stopped, but ${r.survivors.length} would not stop (pid ${r.survivors.join(", ")}).`, "warn");
        else toast(<>Stopped <b>{l.title}</b> on :{l.port}{r.killed.length ? ` (${r.killed.length} forced)` : ""}.</>, "ok",
          { label: "Restart", onClick: () => void restartFrom(l) });
        return true;
      } catch (e) {
        fail(e);
        return false;
      }
    }

    async function restartFrom(l: Listener) {
      try {
        const r = await api.restart(l.pid).catch(async (e) => {
          if (e instanceof ApiError && e.status === 404) {
            // already stopped: run it again from the saved app Harbor made
            const app = await api.appFromProcess(l.pid).catch(() => null);
            if (app) { await api.startApp(app.id, { force: true }); return { app }; }
          }
          throw e;
        });
        toast(<>Restarting <b>{r.app.name}</b>. Harbor now runs it and keeps its logs.</>, "ok");
      } catch (e) {
        fail(e);
      }
    }

    async function restart(l: Listener) {
      const ok = await confirm({
        title: `Restart ${l.title}?`, confirm: "Restart",
        body: <div className="space-y-2">
          <p>Harbor stops <span className="font-mono text-xs">{(l.root || l).display}</span> and runs it again in <span className="font-mono text-xs">{l.root?.cwd || l.cwd}</span>.</p>
          <p className="text-xs text-muted">It is saved under Apps, so you can see its output and start it with one click next time.</p>
        </div>,
      });
      if (!ok) return;
      try {
        const r = await api.restart(l.pid);
        toast(<>Restarting <b>{r.app.name}</b>…</>, "ok");
      } catch (e) {
        fail(e);
      }
    }

    function open(l: Listener, path = "/") {
      window.open(`http://localhost:${l.port}${path}`, "_blank", "noopener");
    }

    async function copyUrl(l: Listener) {
      toast((await copy(url(l))) ? <>Copied <span className="font-mono">{url(l)}</span></> : "Could not copy to the clipboard.", "ok");
    }

    async function copyText(text: string, what = "Copied") {
      toast((await copy(text)) ? what : "Could not copy to the clipboard.", "ok");
    }

    async function meta(l: Listener, values: Partial<Listener["meta"]>) {
      try {
        await api.updatePort(l.port, { ...l.meta, ...values });
      } catch (e) {
        fail(e);
      }
    }

    async function saveApp(l: Listener) {
      try {
        const a = await api.appFromProcess(l.pid);
        toast(<>Saved <b>{a.name}</b> to Apps.</>, "ok", onEditApp ? { label: "Edit", onClick: () => onEditApp(a) } : undefined);
      } catch (e) {
        fail(e);
      }
    }

    async function reveal(path: string | null | undefined, target: "finder" | "editor" | "terminal") {
      if (!path) return;
      try {
        await api.reveal(path, target);
      } catch (e) {
        fail(e);
      }
    }

    async function probe(l: Listener) {
      try {
        const p = await api.probe(l.port);
        toast(p.ok ? <>:{l.port} answered <b>{p.status}</b> in {p.ms} ms{p.title ? ` · ${p.title}` : ""}</> : <>:{l.port}: {p.error}</>, p.ok ? "ok" : "warn");
      } catch (e) {
        fail(e);
      }
    }

    async function startApp(a: App, opts: { port?: number; takeOver?: boolean; force?: boolean } = {}): Promise<void> {
      try {
        await api.startApp(a.id, opts);
        toast(<>Starting <b>{a.name}</b>{opts.port || a.port ? ` on :${opts.port || a.port}` : ""}…</>, "ok");
      } catch (e) {
        if (e instanceof ApiError && e.status === 409 && e.data.conflict) {
          const c = e.data.conflict as { port: number; holder: { pid: number; title: string } | null; suggest: number | null };
          const choice = await confirm({
            title: `Port ${c.port} is taken`,
            confirm: c.suggest ? `Use :${c.suggest} instead` : "OK",
            body: <div className="space-y-2">
              <p>{c.holder ? <><b>{c.holder.title}</b> (pid {c.holder.pid})</> : "Another process"} is listening on :{c.port}.</p>
              {c.suggest && <p className="text-xs text-muted">Harbor sets <span className="font-mono">PORT={c.suggest}</span> and fills <span className="font-mono">{"{port}"}</span> in the command. Apps that ignore both will still try :{c.port}.</p>}
              {c.holder && <p className="text-xs"><button className="font-semibold text-bad hover:underline" onClick={(ev) => { ev.preventDefault(); void startApp(a, { takeOver: true, force: true }); document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })); }}>Stop {c.holder.title} and take :{c.port}</button></p>}
            </div>,
          });
          if (choice && c.suggest) return startApp(a, { port: c.suggest, force: true });
          return;
        }
        if (e instanceof ApiError && e.status === 409 && e.data.external) {
          const ok = await confirm({ title: `${a.name} is already running`, confirm: "Restart under Harbor",
            body: <p>It was started outside Harbor (pid {(e.data.external as number[]).join(", ")}). Restart it under Harbor to capture its logs?</p> });
          if (ok) { await api.restartApp(a.id).catch(fail); toast(`Restarting ${a.name}…`, "ok"); }
          return;
        }
        fail(e);
      }
    }

    async function stopApp(a: App) {
      try {
        await api.stopApp(a.id);
        toast(<>Stopped <b>{a.name}</b>.</>, "ok");
      } catch (e) {
        fail(e);
      }
    }

    async function restartApp(a: App) {
      try {
        await api.restartApp(a.id);
        toast(<>Restarting <b>{a.name}</b>…</>, "ok");
      } catch (e) {
        fail(e);
      }
    }

    async function deleteApp(a: App) {
      const ok = await confirm({ title: `Remove ${a.name} from Apps?`, danger: true, confirm: "Remove",
        body: <p>Only Harbor's saved entry is removed. Your project and its files are untouched.</p> });
      if (!ok) return;
      try {
        await api.deleteApp(a.id);
        toast(`Removed ${a.name}.`, "ok");
      } catch (e) {
        fail(e);
      }
    }

    async function killMany(rows: Listener[], mode: "process" | "app", title?: string) {
      const targets = rows.filter((l) => l.risk !== "self" && l.risk !== "foreign");
      if (!targets.length) return false;
      const sys = targets.some((l) => l.risk === "system" || l.risk === "app");
      const ok = await confirm({
        title: title || `Stop ${targets.length} ${mode === "app" ? "app" : "process"}${targets.length > 1 ? "es" : ""}?`, danger: true,
        confirm: `Stop ${targets.length}`, requireText: sys ? "stop" : undefined,
        body: <div className="space-y-1.5">
          <div className="max-h-56 space-y-1 overflow-y-auto rounded-lg bg-panel-2 p-2">
            {targets.map((l) => (
              <div key={l.id} className="flex items-center gap-2 text-xs">
                <span className="tnum w-12 font-mono font-semibold text-ink">:{l.port}</span>
                <span className="truncate text-ink-2">{l.title}</span>
                {l.idleFor && <span className="ml-auto shrink-0 text-faint">idle {duration(l.idleFor)} · {mb(l.memMb)}</span>}
              </div>
            ))}
          </div>
          {mode === "app" && <p className="text-xs text-muted">Each app's launcher and child processes are stopped too.</p>}
          {sys && <p className="text-xs text-warn">Includes desktop apps or macOS services.</p>}
        </div>,
      });
      if (!ok) return false;
      try {
        const r = await api.killMany(targets.map((l) => l.pid), mode);
        const failed = Object.values(r.results).filter((x) => !x.ok);
        toast(failed.length ? `Stopped ${r.stopped}; ${failed.length} failed: ${failed[0].error}` : `Stopped ${r.stopped} of ${targets.length}.`, failed.length ? "warn" : "ok");
        return true;
      } catch (e) {
        fail(e);
        return false;
      }
    }

    async function group(name: string, action: "start" | "stop") {
      try {
        const r = await api.group(name, action);
        const lines = Object.entries(r.results);
        const bad = lines.filter(([, v]) => !["started", "stopped", "already running"].includes(v));
        toast(bad.length ? <>{name}: {bad.map(([k, v]) => `${k}: ${v}`).join("; ")}</> : <>{action === "start" ? "Starting" : "Stopped"} <b>{name}</b> ({lines.length} app{lines.length > 1 ? "s" : ""}).</>, bad.length ? "warn" : "ok");
      } catch (e) {
        fail(e);
      }
    }

    async function exportApps() {
      try {
        const data = await api.exportApps();
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `harbor-apps-${new Date().toISOString().slice(0, 10)}.json`;
        a.click();
        URL.revokeObjectURL(a.href);
        toast(`Exported ${data.apps.length} app${data.apps.length === 1 ? "" : "s"}.`, "ok");
      } catch (e) {
        fail(e);
      }
    }

    async function importApps(file: File) {
      try {
        const parsed = JSON.parse(await file.text());
        const r = await api.importApps(Array.isArray(parsed) ? parsed : parsed.apps || []);
        toast(`Imported ${r.added.length}${r.skipped.length ? `, skipped ${r.skipped.length} (${r.skipped[0].why})` : ""}.`, r.added.length ? "ok" : "warn");
      } catch (e) {
        fail(e instanceof SyntaxError ? new Error("That file is not Harbor JSON.") : e);
      }
    }

    return { killMany, group, exportApps, importApps, kill, restart, open, copyUrl, copyText, meta, saveApp, reveal, probe, startApp, stopApp, restartApp, deleteApp, fail, toast };
  }, [toast, confirm, onEditApp]);
}

export type Actions = ReturnType<typeof useActions>;
