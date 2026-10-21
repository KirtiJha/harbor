export type Probe = {
  port: number; url: string; checkedAt: number; ok: boolean; status?: number; reason?: string; server?: string | null;
  contentType?: string | null; location?: string | null; title?: string | null; poweredBy?: string; ms?: number; error?: string; tls?: boolean;
};

export type GitInfo = { branch: string | null; worktree: boolean; root: string; repo: string } | null;
export type Project = { name: string; root: string; repo: string | null; path: string; sub: string | null; git?: GitInfo };
export type ExposureRisk = { level: "critical" | "high" | "medium"; title: string; why: string; fix: string } | null;

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
  lastActive: number | null; idleFor: number | null; lanUrl: string | null; stableUrl: string | null; stableHttpsUrl?: string | null;
  exposureRisk: ExposureRisk;
  agent: AgentInfo | null; leak: Leak | null; shares: Share[]; shareRelay?: string;
};

export type AgentInfo = { agent: string; label: string; pid: number; startedAt: number | null; alive: boolean; endedAt: number | null; key: string };
export type Leak = { growthMb: number; minutes: number; perHour: number; fromMb: number; toMb: number };
export type Share = { id: string; port: number; title: string; mode: "lan" | "public"; url: string | null; relayPort: number; host: string;
  publicUrl: string | null; tunnel: string | null; startedAt: number; expiresAt: number; requests: number; lastRequest: number | null };
export type MapNode = { id: string; title: string; ports: number[]; kind: string; appId: string | null; framework: string | null; project: string | null;
  memMb: number | null; pids: number[]; self: boolean; client: boolean; gone?: boolean; stopped?: boolean };
export type MapEdge = { id: string; from: string; to: string; port: number | null; state: "active" | "idle" | "broken" | "declared"; count: number;
  since: number | null; last: number | null; declared: boolean };
export type DriftFinding = { id: string; level: "warn" | "info"; file: string; rel: string; line: number; match: string; host: string; port: number;
  key: string | null; text: string; project: string; projectRoot: string; appId: string | null; title: string; detail: string;
  target: { appId: string | null; name: string; slug?: string } | null; fix: { port: number } | null };
export type HttpsStatus = { ca: string; source: "porthaven" | "mkcert"; exists: boolean; openssl: boolean; mkcert: boolean; trusted: boolean | null; trustCommands: string[] };
export type Interval = { port: number; pid: number; start: number; end: number | null; title?: string; project?: string; framework?: string; command?: string; until?: string };
export type LogMatch = { appId: string; app: string; seq: number; t: number | null; text: string; approx: boolean; error: boolean };
export type Body = { size: number; truncated: boolean; note: string | null; text?: string; base64?: string };
export type RequestDetail = ProxyRequest & { reason: string; requestHeaders: [string, string][]; requestBody: Body; responseHeaders: [string, string][]; responseBody: Body };

export type PortMeta = { note?: string; label?: string; pinned?: boolean; watched?: boolean; color?: string };

export type AppState = "running" | "starting" | "stopped" | "exited" | "crashed" | "external" | "sleeping";

export type App = {
  id: string; name: string; cwd: string; command: string; port?: number | null; env?: Record<string, string>;
  openPath?: string; group?: string; color?: string; autoRestart?: boolean; createdAt?: number; slug?: string;
  stableUrl?: string | null; slugName?: string;
  dependsOn?: string[]; health?: string; sleepAfter?: number; wake?: boolean; branch?: string; worktreeOf?: string;
  source?: { file: string; key: string }; compose?: { service: string; file: string };
  stableHttpsUrl?: string | null; errors?: number; lastError?: string | null;
  container?: { name: string; status: string; health: string | null } | null;
  state: AppState; ports: number[]; pids: number[]; drift: boolean;
  conflict: { pid: number; title: string; command: string; risk: Risk } | null;
  run: { pid: number; status: string; exitCode: number | null; startedAt: number; endedAt: number | null; port: number | null; command: string; lines: number; agent?: { label: string; pid: number } | null } | null;
  logLines: number; logFile: string | null;
};

export type Activity = {
  id: string; ts: number; type: "opened" | "closed" | "killed" | "started" | "stopped" | "exited" | "crashed" | "ready" | "conflict" | "slept" | "woke" | "exposed"
    | "leak" | "agent-ended" | "shared" | "unshared" | "fixed";
  framework?: string | null; kind?: string; ranFor?: number | null; memMb?: number | null;
  port?: number | null; pid?: number; title: string; project?: string | null; level: "info" | "warn" | "error";
  detail?: string; notify?: boolean; appId?: string;
};

export type Settings = {
  scanInterval: number; probeInterval: number; graceSeconds: number; showSystem: boolean; probeApps: boolean; notify: boolean;
  idleHours: number; agentCleanup: "off" | "notify" | "stop"; agentCleanupMinutes: number; leakMb: number; drift: boolean; https: boolean; httpsPort: number;
};

export type Snapshot = {
  version: string; scannedAt: number; scanMs: number | null; error: string | null;
  me: { pid: number; port: number; startedAt: number; user: string; home: string; docker: boolean; lanIp: string | null; cli?: string;
    https: { enabled: boolean; port: number | null; error: string | null; status: HttpsStatus | null }; tunnels: string[] };
  listeners: Listener[]; apps: App[]; settings: Settings; activity: Activity[]; workspaces: Workspace[];
  summary: { listening: number; dev: number; projects: number; exposed: number; system: number; appsRunning: number;
    cpu: number; memMb: number; watchedDown: number[]; idle: number; idleMemMb: number; critical: number; portClaims: Record<string, string[]>;
    agentLeftovers: number; agentLeftoverMemMb: number; leaks: number; drift: number; errors: number; brokenLinks: number };
  map: { nodes: MapNode[]; edges: MapEdge[] };
  drift: { findings: DriftFinding[]; at: number };
  shares: Share[];
};

export type KillResult = { signalled: number[]; exited: number[]; killed: number[]; survivors: number[]; errors: Record<string, string>; mode: string };
export type LogLine = { seq: number; t: number | null; text: string; stream: string };
export type ProcNode = { pid: number; ppid: number; args: string; display: string; cpu: number; memMb: number; uptime: number | null; ports: number[]; mine: boolean };
export type ProcessDetail = { process: ProcNode; ancestors: ProcNode[]; root: ProcNode | null; tree: ProcNode[]; cwd: string | null };
export type Discovered = { name: string; script: string; command: string; detail: string; port: number | null; type: string; cwd: string; rel: string; saved: boolean;
  compose?: { service: string; file: string } };

export type Workspace = { id: string; name: string; apps: string[]; createdAt: number };
export type ProxyRequest = { id: number; t: number; method: string; path: string; status: number | null; ms: number | null; ttfb?: number; bytes: number; ws: boolean; port: number;
  replay?: boolean; replayOf?: number };
export type Worktree = { path: string; branch: string | null; head: string | null; main: boolean; appCwd: string; current: boolean; app: { id: string; name: string } | null };
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
  requests: (id: string) => request<{ slug: string; requests: ProxyRequest[] }>("GET", `/api/apps/${id}/requests`),
  worktrees: (id: string) => request<{ repo: string; branch: string; worktrees: Worktree[] }>("GET", `/api/apps/${id}/worktrees`),
  runInWorktree: (id: string, worktree: string) => request<{ app: App; stableUrl: string }>("POST", `/api/apps/${id}/worktree`, { worktree, start: true }),
  saveWorkspace: (name: string) => request<Workspace>("POST", "/api/workspaces", { name }),
  restoreWorkspace: (id: string, stopOthers: boolean) => request<{ starting: string[]; stopped: string[] }>("POST", `/api/workspaces/${id}/restore`, { stopOthers }),
  deleteWorkspace: (id: string) => request<unknown>("DELETE", `/api/workspaces/${id}`),
  importToml: (path: string) => request<{ file: string; added: string[]; updated: string[]; claims: Record<string, string[]> }>("POST", "/api/teamfile/import", { path }),
  upToml: (path: string) => request<{ file: string; order: string[]; claims: Record<string, string[]> }>("POST", "/api/teamfile/up", { path }),
  exportToml: (group?: string) => request<{ base: string; toml: string }>("GET", `/api/teamfile/export${group ? `?group=${encodeURIComponent(group)}` : ""}`),
  insights: (range: string) => request<Insights>("GET", `/api/insights?range=${range}`),
  settings: (s: Partial<Settings>) => request<Settings>("PUT", "/api/settings", s),
  requestDetail: (id: string, rid: number) => request<RequestDetail>("GET", `/api/apps/${id}/requests/${rid}`),
  replay: (id: string, rid: number, edits: { method?: string; path?: string; headers?: [string, string][]; body?: string } = {}) =>
    request<RequestDetail>("POST", `/api/apps/${id}/requests/${rid}/replay`, edits),
  har: (id: string) => request<unknown>("GET", `/api/apps/${id}/har`),
  history: (port: number, at?: string) => request<{ port: number; at: number | null; intervals: Interval[]; hint: string | null }>("GET",
    `/api/ports/${port}/history${at ? `?at=${encodeURIComponent(at)}` : "?days=7"}`),
  searchLogs: (p: { q: string; apps?: string[]; regex?: boolean; errors?: boolean; since?: number; limit?: number }) =>
    request<{ matches: LogMatch[]; counts: Record<string, number>; truncated: boolean; total: number; recentErrors: { appId: string; app: string; n: number; last: string }[] }>("GET",
      `/api/logs/search?${new URLSearchParams({ q: p.q, apps: (p.apps || []).join(","), regex: p.regex ? "1" : "0", errors: p.errors ? "1" : "0",
        since: String(p.since || ""), limit: String(p.limit || 500) })}`),
  driftScan: () => request<{ findings: DriftFinding[]; at: number }>("POST", "/api/drift/scan", {}),
  driftFix: (id: string, port?: number) => request<{ file: string; line: number; text: string }>("POST", "/api/drift/fix", { id, port }),
  driftDismiss: (id: string) => request<unknown>("POST", "/api/drift/dismiss", { id }),
  share: (port: number, mode: "lan" | "public", minutes: number) => request<Share>("POST", "/api/share", { port, mode, minutes }),
  unshare: (id: string) => request<unknown>("DELETE", `/api/share/${id}`),
  stopAgentServers: (session?: number, includeLive = false) => request<{ results: Record<string, string>; stopped: number }>("POST", "/api/agents/stop", { session, includeLive }),
  https: (refresh = false) => request<Snapshot["me"]["https"]>("GET", `/api/https${refresh ? "?refresh=1" : ""}`),
  httpsEnable: (port?: number) => request<Snapshot["me"]["https"]>("POST", "/api/https/enable", port ? { port } : {}),
  httpsDisable: () => request<Snapshot["me"]["https"]>("POST", "/api/https/disable", {}),
  httpsTrust: () => request<Snapshot["me"]["https"]>("POST", "/api/https/trust", {}),
  clearActivity: () => request<unknown>("POST", "/api/activity/clear", {}),
};
