// Porthaven for VS Code (and Cursor, Windsurf, VSCodium): the ports on this machine in the status bar.
// Talks to a running Porthaven over its local API; plain JavaScript, so there is nothing to build.
const vscode = require("vscode");
const http = require("http");

const ACTOR = "vscode";
let token = null;

function base() {
  return new URL(vscode.workspace.getConfiguration("porthaven").get("url") || "http://127.0.0.1:7475");
}

function call(method, path, body) {
  return new Promise((resolve, reject) => {
    const u = base();
    const data = body === undefined ? null : Buffer.from(JSON.stringify(body));
    const headers = { "X-Porthaven-Actor": ACTOR, Host: u.host };
    if (data) Object.assign(headers, { "Content-Type": "application/json", "Content-Length": data.length });
    if (method !== "GET" && token) headers["X-Porthaven-Token"] = token;
    const req = http.request({ hostname: u.hostname, port: u.port, path, method, headers, timeout: 8000 }, (res) => {
      let raw = "";
      res.setEncoding("utf8");
      res.on("data", (c) => (raw += c));
      res.on("end", () => {
        let json = {};
        try { json = raw ? JSON.parse(raw) : {}; } catch { /* not JSON */ }
        if (res.statusCode >= 400) reject(Object.assign(new Error(json.error || `HTTP ${res.statusCode}`), { status: res.statusCode, data: json }));
        else resolve(json);
      });
    });
    req.on("timeout", () => req.destroy(new Error("Porthaven did not answer in time.")));
    req.on("error", (e) => reject(new Error(`Porthaven is not running at ${u.origin} (${e.code || e.message}).`)));
    if (data) req.write(data);
    req.end();
  });
}

async function change(method, path, body) {
  if (!token) token = (await call("GET", "/api/session")).token;
  try {
    return await call(method, path, body);
  } catch (e) {
    if (e.status === 403) {   // Porthaven restarted: a new session token
      token = (await call("GET", "/api/session")).token;
      return call(method, path, body);
    }
    throw e;
  }
}

function rows(snap) {
  const all = vscode.workspace.getConfiguration("porthaven").get("showSystem");
  return snap.listeners.filter((r) => all || !["system", "app"].includes(r.kind));
}

function label(r) {
  const p = r.probe || {};
  const flags = [r.exposure === "network" ? "$(broadcast) network" : "", r.leak ? `$(graph-line) +${r.leak.growthMb} MB` : "",
    r.agent && !r.agent.alive ? `$(robot) left by ${r.agent.label}` : ""].filter(Boolean).join("  ");
  return {
    label: `$(${p.ok ? "globe" : "plug"}) :${r.port}  ${r.title}`,
    description: [r.framework ? r.framework.label : r.kind, p.status ? `HTTP ${p.status}` : "", flags].filter(Boolean).join(" · "),
    detail: `${(r.project && r.project.name) || ""}  pid ${r.pid} · ${r.memMb} MB · ${r.display}`,
    row: r,
  };
}

async function showPorts() {
  let snap;
  try { snap = await call("GET", "/api/state"); } catch (e) { return offer(e); }
  const pick = await vscode.window.showQuickPick(rows(snap).map(label), { placeHolder: "Ports on this machine", matchOnDescription: true, matchOnDetail: true });
  if (!pick) return;
  const r = pick.row;
  const acts = [];
  if (r.probe && r.probe.ok) acts.push({ label: "$(link-external) Open in browser", run: () => open(`http://localhost:${r.port}/`) });
  if (r.stableUrl) acts.push({ label: `$(link) Open ${r.stableUrl}`, run: () => open(r.stableUrl) });
  acts.push({ label: "$(copy) Copy URL", run: () => vscode.env.clipboard.writeText(`http://localhost:${r.port}/`) });
  if (!r.risk) {
    acts.push({ label: "$(debug-stop) Stop the process", run: () => stop(r, "process") });
    if (r.root) acts.push({ label: `$(debug-stop) Stop the whole app (${r.root.count} processes)`, run: () => stop(r, "app") });
  }
  acts.push({ label: "$(dashboard) Show in Porthaven", run: () => open(base().origin.replace("127.0.0.1", "localhost") + "/") });
  const act = await vscode.window.showQuickPick(acts, { placeHolder: `:${r.port} ${r.title}` });
  if (act) await act.run();
}

async function stop(r, mode) {
  const ok = await vscode.window.showWarningMessage(`Stop ${mode === "app" ? "the whole app" : "the process"} on :${r.port} (${r.title})?`, { modal: true }, "Stop");
  if (ok !== "Stop") return;
  try {
    const res = await change("POST", "/api/kill", { pid: r.pid, mode, confirm: false });
    vscode.window.showInformationMessage(`Stopped ${res.exited.length + res.killed.length} process(es) on :${r.port}.`);
  } catch (e) { vscode.window.showErrorMessage(e.message); }
  refresh();
}

async function pickApp(running) {
  const snap = await call("GET", "/api/state");
  const live = (a) => ["running", "starting", "external"].includes(a.state);
  const apps = snap.apps.filter((a) => live(a) === running);
  if (!apps.length) { vscode.window.showInformationMessage(running ? "No saved app is running." : "Every saved app is running (or none is saved)."); return null; }
  const pick = await vscode.window.showQuickPick(apps.map((a) => ({ label: a.name, description: `${a.ports.length ? ":" + a.ports.join(", :") : a.port ? ":" + a.port : ""}  ${a.command}`, app: a })),
    { placeHolder: running ? "Stop which app?" : "Start which app? (its dependencies start first)" });
  return pick && pick.app;
}

async function startApp() {
  try {
    const a = await pickApp(false);
    if (!a) return;
    try {
      await change("POST", `/api/apps/${a.id}/start`, {});
    } catch (e) {
      const c = e.data && e.data.conflict;
      if (!c || !c.suggest) throw e;
      const use = await vscode.window.showWarningMessage(`:${c.port} is taken${c.holder ? ` by ${c.holder.title}` : ""}.`, `Use :${c.suggest}`);
      if (!use) return;
      await change("POST", `/api/apps/${a.id}/start`, { port: c.suggest, force: true });
    }
    vscode.window.showInformationMessage(`Starting ${a.name}…`);
  } catch (e) { offer(e); }
  refresh();
}

async function stopApp() {
  try {
    const a = await pickApp(true);
    if (!a) return;
    await change("POST", `/api/apps/${a.id}/stop`, {});
    vscode.window.showInformationMessage(`Stopped ${a.name}.`);
  } catch (e) { offer(e); }
  refresh();
}

async function freePort() {
  const v = await vscode.window.showInputBox({ prompt: "Port to free", validateInput: (s) => (/^\d{1,5}$/.test(s) ? null : "A port number") });
  if (!v) return;
  try {
    const snap = await call("GET", "/api/state");
    const r = snap.listeners.find((x) => x.port === Number(v));
    if (!r) return vscode.window.showInformationMessage(`:${v} is already free.`);
    await stop(r, r.root ? "app" : "process");
  } catch (e) { offer(e); }
}

function open(url) {
  vscode.env.openExternal(vscode.Uri.parse(url));
}

function offer(e) {
  vscode.window.showErrorMessage(e.message, "How to start it").then((x) => x && open("https://github.com/KirtiJha/porthaven#install"));
}

let item, timer;

async function refresh() {
  try {
    const snap = await call("GET", "/api/state");
    const n = new Set(rows(snap).map((r) => r.port)).size;
    const s = snap.summary;
    const alert = (s.critical || 0) + (s.watchedDown || []).length + (s.leaks || 0) + (s.agentLeftovers || 0) + (s.drift || 0);
    item.text = `${alert ? "$(warning)" : "$(plug)"} ${n}`;
    const notes = [s.critical ? `${s.critical} dangerously exposed` : "", (s.watchedDown || []).length ? `watched down: :${s.watchedDown.join(", :")}` : "",
      s.leaks ? `${s.leaks} growing in memory` : "", s.agentLeftovers ? `${s.agentLeftovers} left by coding agents` : "",
      s.drift ? `${s.drift} config file(s) point at a wrong port` : ""].filter(Boolean);
    item.tooltip = `Porthaven: ${n} port${n === 1 ? "" : "s"} · ${snap.apps.filter((a) => a.state === "running").length} app(s) running${notes.length ? "\n" + notes.join("\n") : ""}`;
    item.backgroundColor = alert ? new vscode.ThemeColor("statusBarItem.warningBackground") : undefined;
  } catch {
    item.text = "$(plug) –";
    item.tooltip = "Porthaven is not running";
    item.backgroundColor = undefined;
  }
}

function activate(context) {
  item = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50);
  item.command = "porthaven.ports";
  item.show();
  context.subscriptions.push(item,
    vscode.commands.registerCommand("porthaven.ports", showPorts),
    vscode.commands.registerCommand("porthaven.startApp", startApp),
    vscode.commands.registerCommand("porthaven.stopApp", stopApp),
    vscode.commands.registerCommand("porthaven.freePort", freePort),
    vscode.commands.registerCommand("porthaven.dashboard", () => open(base().origin.replace("127.0.0.1", "localhost") + "/")));
  refresh();
  timer = setInterval(() => { if (vscode.window.state.focused) refresh(); }, 5000);
  context.subscriptions.push({ dispose: () => clearInterval(timer) });
}

function deactivate() {
  clearInterval(timer);
}

module.exports = { activate, deactivate };
