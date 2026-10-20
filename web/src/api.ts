export type Probe = {
  port: number; url: string; checkedAt: number; ok: boolean; status?: number; reason?: string; server?: string | null;
  contentType?: string | null; location?: string | null; title?: string | null; poweredBy?: string; ms?: number; error?: string;
};

export type Project = { name: string; root: string; repo: string | null; path: string; sub: string | null };

export type Kind = "dev" | "service" | "database" | "app" | "system" | "tool" | "other";
export type Risk = null | "self" | "foreign" | "system" | "app";

export type Listener = {
  id: string; port: number; pid: number; addresses: string[]; exposure: "local" | "network";
  user: string; owned: boolean; command: string; args: string; display: string; cwd: string | null;
  project: Project | null; framework: { id: string; label: string } | null; kind: Kind; appBundle: string | null;
  title: string; cpu: number | null; memMb: number | null; uptime: number | null; connections: number; probe: Probe | null;
  root: { pid: number; args: string; display: string; cwd: string | null; count: number } | null;
  managed: string | null; appId: string | null; risk: Risk; hint: string | null; firstSeen: number | null;
  meta: PortMeta; spark: { cpu: number[]; mem: number[] };
  docker: { id: string; name: string; image: string; status: string; mapping: string } | null;
  workers?: { pid: number; display: string; cpu: number | null; memMb: number | null }[];
  health: { ms: (number | null)[]; status: number[]; up: number; n: number } | null;
  lastActive: number | null; idleFor: number | null; lanUrl: string | null; stableUrl: string | null;
};

export type PortMeta = { note?: string; label?: string; pinned?: boolean; watched?: boolean; color?: string };

export type AppState = "running" | "starting" | "stopped" | "exited" | "crashed" | "external";

export type App = {
  id: string; name: string; cwd: string; command: string; port?: number | null; env?: Record<string, string>;
  openPath?: string; group?: string; color?: string; autoRestart?: boolean; createdAt?: number; slug?: string;
  stableUrl?: string | null; slugName?: string;
  state: AppState; ports: number[]; pids: number[]; drift: boolean;
  conflict: { pid: number; title: string; command: string; risk: Risk } | null;
  run: { pid: number; status: string; exitCode: number | null; startedAt: number; endedAt: number | null; port: number | null; command: string; lines: number } | null;
  logLines: number; logFile: string | null;
};

export type Activity = {
  id: string; ts: number; type: "opened" | "closed" | "killed" | "started" | "stopped" | "exited" | "crashed" | "ready" | "conflict";
  framework?: string | null; kind?: string; ranFor?: number | null; memMb?: number | null;
  port?: number | null; pid?: number; title: string; project?: string | null; level: "info" | "warn" | "error";
  detail?: string; notify?: boolean; appId?: string;
};

export type Settings = {
  scanInterval: number; probeInterval: number; graceSeconds: number; showSystem: boolean; probeApps: boolean; notify: boolean;
  idleHours: number;
};

export type Snapshot = {
  version: string; scannedAt: number; scanMs: number | null; error: string | null;
  me: { pid: number; port: number; startedAt: number; user: string; home: string; docker: boolean; lanIp: string | null };
  listeners: Listener[]; apps: App[]; settings: Settings; activity: Activity[];
  summary: { listening: number; dev: number; projects: number; exposed: number; system: number; appsRunning: number;
    cpu: number; memMb: number; watchedDown: number[]; idle: number; idleMemMb: number };
};

export type KillResult = { signalled: number[]; exited: number[]; killed: number[]; survivors: number[]; errors: Record<string, string>; mode: string };
export type LogLine = { seq: number; t: number | null; text: string; stream: string };
export type ProcNode = { pid: number; ppid: number; args: string; display: string; cpu: number; memMb: number; uptime: number | null; ports: number[]; mine: boolean };
export type ProcessDetail = { process: ProcNode; ancestors: ProcNode[]; root: ProcNode | null; tree: ProcNode[]; cwd: string | null };
export type Discovered = { name: string; script: string; command: string; detail: string; port: number | null; type: string; cwd: string; rel: string; saved: boolean };

export type Sample = { ts: number; ports: number; dev: number; memMb: number; cpu: number; conns: number; idle: number; exposed: number; apps: number; byProject: Record<string, number> };
export type Insights = {
  range: string; seconds: number; now: number; porthavenStarted: number; samples: Sample[]; activity: Activity[];
  health: Record<string, { n: number; ok: number; avg: number | null; p95: number | null }>;
};

export class ApiError extends Error {
  status: number;
  data: Record<string, unknown>;
  constructor(message: string, status: number, data: Record<string, unknown>) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

let token = document.querySelector<HTMLMetaElement>('meta[name="porthaven-token"]')?.content || "";

async function ensureToken() {
  if (token) return token;
  const r = await fetch("/api/session");
  token = (await r.json()).token;
  return token;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  if (method !== "GET") headers["X-Porthaven-Token"] = await ensureToken();
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let r: Response;
  try {
    r = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError("Porthaven is not reachable. Is it still running?", 0, {});
  }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError((data as { error?: string }).error || `${r.status} ${r.statusText}`, r.status, data);
  return data as T;
}

export const api = {
  state: () => request<Snapshot>("GET", "/api/state"),
  refresh: () => request<Snapshot>("POST", "/api/refresh"),
  kill: (pid: number, mode: "process" | "app", confirm = false, force = true) =>
    request<KillResult>("POST", "/api/kill", { pid, mode, confirm, force }),
  restart: (pid: number) => request<{ app: App }>("POST", "/api/restart", { pid }),
  probe: (port: number) => request<Probe>("POST", `/api/probe/${port}`),
  checkPort: (port: number) => request<{ port: number; free: boolean; listeners: Listener[]; hint: string | null; next: number[] }>("GET", `/api/ports/${port}`),
  free: (from: number, count = 5) => request<{ ports: number[] }>("GET", `/api/free?from=${from}&count=${count}`),
  updatePort: (port: number, meta: PortMeta) => request<PortMeta>("PUT", `/api/ports/${port}`, meta),
  process: (pid: number) => request<ProcessDetail>("GET", `/api/process/${pid}`),
  createApp: (a: Partial<App>) => request<App>("POST", "/api/apps", a),
  appFromProcess: (pid: number) => request<App>("POST", "/api/apps/from-process", { pid }),
  updateApp: (id: string, a: Partial<App>) => request<App>("PUT", `/api/apps/${id}`, a),
  deleteApp: (id: string) => request<unknown>("DELETE", `/api/apps/${id}`),
  startApp: (id: string, opts: { port?: number; force?: boolean; takeOver?: boolean } = {}) => request<unknown>("POST", `/api/apps/${id}/start`, opts),
  stopApp: (id: string) => request<unknown>("POST", `/api/apps/${id}/stop`, {}),
  restartApp: (id: string) => request<unknown>("POST", `/api/apps/${id}/restart`, {}),
  logs: (id: string) => request<{ lines: LogLine[]; seq: number; live: boolean }>("GET", `/api/apps/${id}/logs`),
  clearLogs: (id: string) => request<unknown>("POST", `/api/apps/${id}/logs/clear`, {}),
  discover: (folder: string, depth = 3) => request<{ root: string; items: Discovered[]; truncated: boolean }>("POST", "/api/discover", { folder, depth }),
  reveal: (path: string, target: "finder" | "editor" | "terminal") => request<unknown>("POST", "/api/reveal", { path, target }),
  dockerStop: (id: string) => request<unknown>("POST", "/api/docker/stop", { id }),
  killMany: (pids: number[], mode: "process" | "app" = "process") =>
    request<{ results: Record<string, { ok: boolean; error?: string }>; stopped: number }>("POST", "/api/kill-many", { pids, mode }),
  group: (group: string, action: "start" | "stop") => request<{ group: string; results: Record<string, string> }>("POST", `/api/groups/${action}`, { group }),
  exportApps: () => request<{ apps: Partial<App>[] }>("GET", "/api/apps/export"),
  importApps: (apps: unknown[]) => request<{ added: string[]; skipped: { app: unknown; why: string }[] }>("POST", "/api/apps/import", { apps }),
  insights: (range: string) => request<Insights>("GET", `/api/insights?range=${range}`),
  settings: (s: Partial<Settings>) => request<Settings>("PUT", "/api/settings", s),
  clearActivity: () => request<unknown>("POST", "/api/activity/clear", {}),
};
