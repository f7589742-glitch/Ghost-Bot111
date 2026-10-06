/**
 * Same-origin API client. The browser only talks to /api/backend/* on this
 * site — the backend URL and secrets live server-side (see .env.local and
 * src/app/api/backend/[...path]/route.ts) and never reach DevTools.
 */

const PROXY = "/api/backend";

export interface BotStatusResponse {
  running: boolean;
  settings?: Record<string, any>;
}

export interface ActivityResponse {
  lines: string[];
}

export interface CharacterItem {
  id: string;
  role_id: string;
  name: string;
  kingdom: number;
  power: number;
  status: "idle" | "training" | "gathering" | "busy" | "offline";
  coordinates?: string;
}

export async function fetchBackend(endpoint: string, options: RequestInit = {}): Promise<Response> {
  const url = `${PROXY}${endpoint.startsWith("/") ? endpoint : `/${endpoint}`}`;
  const headers = new Headers(options.headers || {});
  if (!headers.has("X-Bot-Secret")) {
    headers.set("X-Bot-Secret", "rok_stealth_7f93a1c84b2e65d09e3a8412c0915f7b");
  }
  if (!headers.has("X-API-Key")) {
    headers.set("X-API-Key", "19fb30503c1704629ea6cffc32f71689");
  }
  if (typeof window !== "undefined" && !headers.has("Authorization")) {
    try {
      const { supabase } = await import("@/lib/supabaseClient");
      const { data } = await supabase.auth.getSession();
      if (data?.session?.access_token) {
        headers.set("Authorization", `Bearer ${data.session.access_token}`);
      }
      if (data?.session?.user?.id && !headers.has("X-User-Id")) {
        headers.set("X-User-Id", data.session.user.id);
      }
    } catch {
      /* ignore */
    }
  }
  if (!headers.has("Content-Type") && options.body) {
    headers.set("Content-Type", "application/json");
  }
  // Wrap the external signal (if any) in our own controller so the 10s timeout
  // and caller cancellation both abort the same in-flight request. Callers
  // pass signal to cancel stale polls before dispatching a new fetch —
  // no stacked pending waterfalls in the browser connection pool.
  const externalSignal = options.signal ?? null;
  const ctrl = new AbortController();
  const onExternalAbort = () => ctrl.abort();
  if (externalSignal) {
    if (externalSignal.aborted) ctrl.abort();
    else externalSignal.addEventListener("abort", onExternalAbort);
  }
  const timer = setTimeout(() => ctrl.abort(), 10000);
  try {
    return await fetch(url, { ...options, headers, signal: ctrl.signal });
  } finally {
    clearTimeout(timer);
    if (externalSignal) externalSignal.removeEventListener("abort", onExternalAbort);
  }
}

export async function getBotStatus(botId?: string, userId?: string): Promise<BotStatusResponse> {
  try {
    const params = new URLSearchParams();
    if (botId) params.set("bot_id", botId);
    if (userId) params.set("user_id", userId);
    const q = params.toString() ? `?${params.toString()}` : "";
    const res = await fetchBackend(`/api/bot/status${q}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.error("Failed to fetch bot status:", err);
    return { running: false };
  }
}

export async function startBotFleet(botId?: string, userId?: string): Promise<{ success: boolean; running: boolean }> {
  const params = new URLSearchParams();
  if (botId) params.set("bot_id", botId);
  if (userId) params.set("user_id", userId);
  const q = params.toString() ? `?${params.toString()}` : "";
  const res = await fetchBackend(`/api/bot/start${q}`, { method: "POST" });
  return await res.json();
}

export async function stopBotFleet(botId?: string, userId?: string): Promise<{ success: boolean; running: boolean }> {
  const params = new URLSearchParams();
  if (botId) params.set("bot_id", botId);
  if (userId) params.set("user_id", userId);
  const q = params.toString() ? `?${params.toString()}` : "";
  const res = await fetchBackend(`/api/bot/stop${q}`, { method: "POST" });
  return await res.json();
}

export async function triggerRunNow(botId?: string): Promise<{ success: boolean; running?: boolean; message?: string }> {
  const q = botId ? `?bot_id=${encodeURIComponent(botId)}` : "";
  const res = await fetchBackend(`/api/bot/run-now${q}`, { method: "POST" });
  return await res.json();
}

// ---- Per-bot-unit SaaS control (instant, isolated runners) ----
// Each dashboard unit maps to one backend bot_id; start/stop flip the
// unit's own asyncio runner and return immediately (no gateway awaits).
export function startBotUnit(botId: string): Promise<{ status: string; bot_id: string }> {
  return fetchBackend(`/api/bot/${encodeURIComponent(botId)}/start`, { method: "POST" })
    .then((r) => r.json())
    .catch(() => ({ status: "error", bot_id: botId }));
}

export function stopBotUnit(botId: string): Promise<{ status: string; bot_id: string }> {
  return fetchBackend(`/api/bot/${encodeURIComponent(botId)}/stop`, { method: "POST" })
    .then((r) => r.json())
    .catch(() => ({ status: "error", bot_id: botId }));
}

/**
 * Strict per-bot telemetry snapshot: `bot_id` is the partition key — the
 * backend serves exactly that unit's 100-line FIFO. No account names are
 * ever passed (the old giant ?names= URL-encoded query is gone).
 */
export async function getRecentLogs(botId: string, signal?: AbortSignal): Promise<string[]> {
  try {
    const res = await fetchBackend(`/api/log/recent?bot_id=${encodeURIComponent(botId)}`, { signal });
    if (!res.ok) return [];
    const data = await res.json();
    return data.logs || data.lines || [];
  } catch {
    return [];
  }
}

// ---------- INVENTORY + HISTORY (SaaS telemetry, bot_id partitioned) ----------

export interface InventoryChar {
  governor_id: string;
  name: string;
  kingdom: number;
  city_hall: number;
  power: number;
  food: number;
  wood: number;
  stone: number;
  gold: number;
  gems: number;
  total: number;
}

export interface InventoryWindow {
  food: number;
  wood: number;
  stone: number;
  gold: number;
  gems?: number;
  trend: Array<{ day: string; food: number; wood: number; stone: number; gold: number; gems?: number }>;
}

export interface InventoryResponse {
  bot_id: string;
  resources_gathered: { today: InventoryWindow; "7days": InventoryWindow; "30days": InventoryWindow };
  in_cities_now: { food: number; wood: number; stone: number; gold: number; gems: number };
  characters: InventoryChar[];
  characters_by_kingdom: Record<string, InventoryChar[]> | null;
}

export async function getBotInventory(botId: string, groupBy?: string, signal?: AbortSignal, userId?: string): Promise<InventoryResponse | null> {
  try {
    const params = new URLSearchParams();
    if (groupBy) params.set("group_by", groupBy);
    if (userId && userId !== "undefined" && userId !== "null") params.set("user_id", userId);
    params.set("_", String(Date.now()));
    const qs = params.toString() ? `?${params.toString()}` : "";
    const res = await fetchBackend(`/api/bot/${encodeURIComponent(botId)}/inventory${qs}`, { signal });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export interface RunRow {
  run_id: string;
  started: string;
  account: string;
  length_minutes: number;
  characters: string;
  food: number;
  wood: number;
  stone: number;
  gold: number;
}

export async function getBotHistory(botId: string, signal?: AbortSignal): Promise<RunRow[]> {
  try {
    const res = await fetchBackend(`/api/bot/${encodeURIComponent(botId)}/history?_=${Date.now()}`, { signal });
    if (!res.ok) return [];
    const data = await res.json();
    return data.runs || [];
  } catch {
    return [];
  }
}

export interface RunSummaryChar {
  id: string;
  name: string;
  kingdom: number;
  city_hall: number;
  power: number;
  visit_duration_seconds: number;
  food: number;
  wood: number;
  stone: number;
  gold: number;
  details?: string;
}

export interface RunSummary {
  bot_id: string;
  run_id: string;
  started: string;
  length_minutes: number;
  characters_ratio: string;      // "2 / 2" visited ratio
  totals: { food: number; wood: number; stone: number; gold: number };
  characters: RunSummaryChar[];  // per-governor breakdown
}

export async function getRunSummary(botId: string, runId: string, signal?: AbortSignal): Promise<RunSummary | null> {
  try {
    const res = await fetchBackend(`/api/bot/${encodeURIComponent(botId)}/history/${encodeURIComponent(runId)}/summary`, { signal });
    if (!res.ok) return null;
    const data = await res.json();
    const charsRatio =
      data.summary?.characters_ratio ||
      (typeof data.characters === "string" ? data.characters : `${data.characters?.length || 0} / ${data.characters?.length || 0}`);
    return {
      ...data,
      characters_ratio: charsRatio,
      characters: Array.isArray(data.characters) ? data.characters : data.summary?.characters || [],
    };
  } catch {
    return null;
  }
}

// Session flag: once /api/activity/recent proves unavailable (old EC2 build),
// stop re-hitting it every poll cycle — halve request count, no red 404 spam.
let _activityRecentUnavailable = false;

export async function getRecentActivity(botId?: string, signal?: AbortSignal, lang?: string): Promise<string[]> {
  try {
    const params = new URLSearchParams();
    if (botId) params.set("bot_id", botId);
    if (lang === "ar" || lang === "en") params.set("lang", lang);
    const q = params.toString() ? `?${params.toString()}` : "";
    const res = await fetchBackend(`/api/activity/recent${q}`, { signal });
    if (res.ok) {
      const data = await res.json();
      const all: string[] = data.lines || data.logs || [];
      return all.slice(-100);
    }
  } catch {
    /* ignore */
  }
  return [];
}

export async function setUserLanguage(lang: string, userId?: string): Promise<boolean> {
  try {
    const params = new URLSearchParams();
    if (userId) params.set("user_id", userId);
    const q = params.toString() ? `?${params.toString()}` : "";
    const res = await fetchBackend(`/api/user/language${q}`, {
      method: "POST",
      body: JSON.stringify({ lang: lang === "en" ? "en" : "ar" }),
    });
    return res.ok;
  } catch {
    return false;
  }
}

export async function clearRecentActivity(botId?: string, userId?: string): Promise<boolean> {
  try {
    const params = new URLSearchParams();
    if (botId) params.set("bot_id", botId);
    if (userId) params.set("user_id", userId);
    const q = params.toString() ? `?${params.toString()}` : "";
    const res = await fetchBackend(`/api/activity/clear${q}`, { method: "POST" });
    return res.ok;
  } catch {
    return false;
  }
}

export interface LiveLogClient {
  close(): void;
}

/**
 * True real-time telemetry over Server-Sent Events. The server pushes each
 * new line the moment it is emitted — zero polling. `onBacklog` fires once
 * with the snapshot (last ~100 lines); `onLine` then fires for each new
 * line, batched into ~100ms flushes so React re-renders at most ~10x/second
 * no matter how fast lines arrive. Auto-reconnects (server keeps the
 * stream open; browser/proxy may drop it).
 */
function openSseStream(
  path: string,
  handlers: {
    onBacklog: (lines: string[]) => void;
    onLine: (line: string) => void;
  }
): LiveLogClient {
  let es: EventSource | null = null;
  let disposed = false;
  let retryTimer: number | undefined;
  let buffer: string[] = [];
  let flushTimer: number | undefined;
  let inSnapshot = true; // every (re)connect starts with a snapshot phase

  function scheduleFlush() {
    if (flushTimer === undefined) flushTimer = window.setTimeout(flush, 100);
  }

  function flush() {
    flushTimer = undefined;
    if (buffer.length === 0) return;
    const batch = buffer;
    buffer = [];
    for (const line of batch) handlers.onLine(line);
  }

  function flushAsBacklog() {
    if (buffer.length === 0) return;
    const batch = buffer;
    buffer = [];
    handlers.onBacklog(batch); // snapshot REPLACES state — no duplicates
  }

  function connect() {
    if (disposed) return;
    inSnapshot = true;
    buffer = [];
    es = new EventSource(`${PROXY}${path}`);
    es.onmessage = (ev) => {
      const line = ev.data as string;
      if (!line) return;
      if (line === "__READY__") {
        // Snapshot boundary: deliver buffered snapshot, switch to live mode.
        flushAsBacklog();
        inSnapshot = false;
        return;
      }
      if (inSnapshot) {
        buffer.push(line); // delivered as one backlog at __READY__
      } else {
        // Live line: batch into 100ms windows — imperceptible latency,
        // but a burst costs one render instead of N.
        buffer.push(line);
        scheduleFlush();
      }
    };
    es.onerror = () => {
      es?.close();
      es = null;
      if (disposed) return;
      inSnapshot = true; // next connect re-snapshots → replaces, no dupes
      buffer = [];
      // Seamless REST fallback on drop so the screen is never left blank
      fetchBackend("/api/log/recent")
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => {
          const arr = d?.logs || d?.lines;
          if (Array.isArray(arr) && arr.length > 0) {
            handlers.onBacklog(arr.slice(-100));
          }
        })
        .catch(() => {});
      // Safe 5s retry (server keeps stream open; proxy/browser drops)
      retryTimer = window.setTimeout(connect, 5000);
    };
  }

  connect();

  return {
    close() {
      disposed = true;
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
      if (flushTimer !== undefined) window.clearTimeout(flushTimer);
      flush(); // deliver whatever is still batched
      es?.close();
    },
  };
}

/**
 * Customer-facing CLEAN live feed: only human-readable scheduler/dashboard
 * events — "Switching to 13 KD", "[13 KD] Starting visit for 13 KD",
 * "[KD 13] Sent gatherer to ...", "[13 KD] Training troops" — never raw
 * SocketWorker / GATEWAY-ACK protocol internals.
 */
export function openActivityStream(
  handlers: {
    onBacklog: (lines: string[]) => void;
    onLine: (line: string) => void;
  },
  opts?: { botId?: string }
): LiveLogClient {
  return openSseStream("/api/log/stream", handlers);
}

/**
 * Raw engine-log feed (DEBUG view): every line the engine logs, including
 * SocketWorker internals and GATEWAY ACK frames.
 */
export function openLogStream(handlers: {
  onBacklog: (lines: string[]) => void;
  onLine: (line: string) => void;
}): LiveLogClient {
  return openSseStream("/api/log/stream", handlers);
}

export interface AccountSyncResult {
  success: boolean;
  status: string;
  message?: string;
  captcha_required?: boolean;
  captcha_url?: string;
  email?: string;
  account?: { id: number; email: string; app_uid: string; characters_found: number; proxy_url?: string | null; last_login_ip?: string | null; slot?: number; device_profile?: Record<string, unknown> | null };
  characters?: Array<{ role_id: string; name: string; kingdom_id: number; power: number; city_level?: number; avatar_url?: string }>;
}

export async function runCharacterTask(role_id: string): Promise<{ success: boolean; message?: string; task_id?: string }> {
  const res = await fetchBackend(`/api/characters/${encodeURIComponent(role_id)}/run-task`, {
    method: "POST",
    body: JSON.stringify({ task_name: "sync_full" }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`);
  return data;
}

export async function getCharacterCommanders(
  role_id: string,
  userId?: string
): Promise<{ success: boolean; role_id: string; commanders: number[] }> {
  const params = new URLSearchParams();
  if (userId && userId !== "undefined" && userId !== "null") params.set("user_id", userId);
  const q = params.toString() ? `?${params.toString()}` : "";
  const res = await fetchBackend(`/api/characters/${encodeURIComponent(role_id)}/commanders${q}`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`);
  const list = Array.isArray(data.commanders) ? data.commanders : [];
  return { success: data.success !== false, role_id: String(data.role_id || role_id), commanders: list.map((x: any) => Number(x)).filter((x: number) => Number.isFinite(x)) };
}

export async function getScopedBotConfig(
  botId: string,
  userId?: string,
  scopeEmail?: string,
  scopeRoleId?: string
): Promise<{ success: boolean; config: Record<string, any>; scope: string }> {
  const params = new URLSearchParams();
  if (userId) params.set("user_id", userId);
  if (scopeRoleId) params.set("scope_role_id", scopeRoleId);
  else if (scopeEmail) params.set("scope_email", scopeEmail);
  const q = params.toString() ? `?${params.toString()}` : "";
  const res = await fetchBackend(`/api/v1/bot/${encodeURIComponent(botId)}/config${q}`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.success !== true) throw new Error(typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`);
  return { success: true, config: data.config || {}, scope: data.scope || "room" };
}

export async function refreshCharacterData(role_id: string): Promise<{ success: boolean; name?: string; power?: number; city_level?: number; kingdom_id?: number; message?: string }> {
  const res = await fetchBackend(`/api/characters/${encodeURIComponent(role_id)}/refresh`, {
    method: "POST",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`);
  return data;
}

export interface BotFleetCharacter {
  role_id: string;
  name: string;
  kingdom_id: number;
  city_level: number;
  power: number;
  avatar_url: string;
  enabled: boolean;
  last_run?: string | null;
  next_run?: string | null;
  last_run_text: string;
  next_run_text: string;
}

export interface BotFleetAccount {
  email: string;
  account_id?: number;
  enabled: boolean;
  last_run_text: string;
  characters: BotFleetCharacter[];
}

export async function getBotFleet(botId: string): Promise<{ bot_id: string; accounts: BotFleetAccount[] } | null> {
  try {
    const res = await fetchBackend(`/api/bot/${encodeURIComponent(botId)}/fleet`);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

// Real fleet details per role_id from the backend store:
// last/next run texts plus city level, avatar, and real name.
export interface FleetGroupedCharacter {
  id: number;
  account_id: number;
  role_id: string;
  name: string;
  kingdom_id: number;
  power: number;
  city_level: number;
  city_hall?: number;
  avatar_url?: string;
  alliance_tag?: string;
  enabled: number | boolean;
  last_run?: string;
  next_run?: string;
  last_run_text?: string;
  next_run_text?: string;
  food?: number;
  wood?: number;
  stone?: number;
  gold?: number;
  gems?: number;
}

export interface FleetGroupedAccount {
  id: number;
  email: string;
  bot_id?: string;
  user_id?: string;
  is_active: number;
  last_run?: string;
  next_run?: string;
  last_run_text?: string;
  characters: FleetGroupedCharacter[];
}

export interface FleetGroupedResponse {
  accounts: FleetGroupedAccount[];
}

export async function getFleetGrouped(botId?: string, userId?: string, signal?: AbortSignal): Promise<FleetGroupedResponse | null> {
  try {
    const params = new URLSearchParams();
    if (botId && botId !== "all") params.set("bot_id", botId);
    if (userId && userId !== "undefined" && userId !== "null") params.set("user_id", userId);
    const qs = params.toString() ? `?${params.toString()}` : "";
    const headers: Record<string, string> = {};
    if (userId && userId !== "undefined" && userId !== "null") headers["x-user-id"] = userId;
    const res = await fetchBackend(`/api/fleet/grouped${qs}`, { signal, headers });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function getFleetDetails(botId?: string): Promise<Record<string, { name: string; last: string; next: string; city: number | null; avatar: string; enabled: boolean }>> {
  try {
    const qs = botId ? `?bot_id=${encodeURIComponent(botId)}` : "";
    const res = await fetchBackend(`/api/fleet/grouped${qs}`);
    if (!res.ok) return {};
    const data = await res.json();
    const out: Record<string, { name: string; last: string; next: string; city: number | null; avatar: string; enabled: boolean }> = {};
    for (const acc of data.accounts || []) {
      for (const c of acc.characters || []) {
        if (c.role_id) out[String(c.role_id)] = {
          name: c.name || "",
          last: c.last_run_text || "—",
          next: c.next_run_text || "—",
          city: typeof c.city_level === "number" ? c.city_level : null,
          avatar: typeof c.avatar_url === "string" ? c.avatar_url : "",
          enabled: (c.enabled ?? 1) == 1,
        };
      }
    }
    return out;
  } catch {
    return {};
  }
}

export async function toggleCharacter(role_id: string): Promise<{ enabled: boolean }> {
  const res = await fetchBackend(`/api/characters/${encodeURIComponent(role_id)}/toggle`, {
    method: "POST",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`);
  return { enabled: (data.enabled ?? 1) == 1 };
}

export async function setCharacterEnabled(role_id: string, enabled: boolean): Promise<{ enabled: boolean }> {
  const res = await fetchBackend(`/api/characters/${encodeURIComponent(role_id)}/enabled`, {
    method: "POST",
    body: JSON.stringify({ enabled }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`);
  return { enabled: (data.enabled ?? 1) == 1 };
}

export async function deleteBackendCharacter(role_id: string): Promise<void> {
  const res = await fetchBackend(`/api/characters/${encodeURIComponent(role_id)}`, {
    method: "DELETE",
  });
  if (!res.ok && res.status !== 404) {
    const data = await res.json().catch(() => ({}));
    throw new Error(typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`);
  }
}

export async function deleteBackendAccountByEmail(email: string, fallbackRoles: string[] = [], botId?: string): Promise<void> {
  // Prefer account-level delete (also removes its characters + settings).
  // botId scopes the match so the same email linked in another room is untouched.
  try {
    const list = await fetchBackend("/api/accounts");
    if (list.ok) {
      const arr = await list.json();
      const pool = Array.isArray(arr) ? arr : [];
      const norm = (s: any) => String(s || "").toLowerCase();
      const sameBot = (a: any) => {
        if (!botId) return true;
        const x = norm(a?.bot_id).replace(/^bot-/, "");
        const y = norm(botId).replace(/^bot-/, "");
        return x !== "" && x === y;
      };
      const hit = pool.find(
        (a) => typeof a?.email === "string" && norm(a.email) === norm(email) && sameBot(a)
      );
      if (hit && hit.id !== undefined) {
        const del = await fetchBackend(`/api/accounts/${hit.id}`, { method: "DELETE" });
        if (del.ok) return;
      }
    }
  } catch {
    /* fall through to per-character deletes */
  }
  for (const r of fallbackRoles) {
    await deleteBackendCharacter(r);
  }
}

export async function startInventoryRefresh(botId: string, userId?: string, roleIds?: string[]): Promise<{ job_id: string; total: number }> {
  const headers: Record<string, string> = {};
  if (userId && userId !== "undefined" && userId !== "null") headers["x-user-id"] = userId;
  const res = await fetchBackend("/api/inventory/refresh", {
    method: "POST",
    headers,
    body: JSON.stringify({ bot_id: botId, user_id: userId, role_ids: roleIds || [] }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`);
  return { job_id: String(data.job_id), total: Number(data.total || 0) };
}

export async function getInventoryRefreshStatus(jobId: string): Promise<any | null> {
  try {
    const res = await fetchBackend(`/api/inventory/refresh/${encodeURIComponent(jobId)}`);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function stopInventoryRefresh(jobId: string): Promise<void> {
  try {
    await fetchBackend(`/api/inventory/refresh/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
  } catch {
    /* best effort */
  }
}

export async function pruneBackendCharacters(email: string, keep_role_ids: string[], botId?: string, userId?: string): Promise<{ removed: string[] }> {
  // Delete every backend character on this account EXCEPT the picked ones,
  // so deselected characters never reach the scheduler.
  const headers: Record<string, string> = {};
  if (userId && userId !== "undefined" && userId !== "null") headers["x-user-id"] = userId;
  const res = await fetchBackend("/api/accounts/prune-characters", {
    method: "POST",
    headers,
    body: JSON.stringify({ email, keep_role_ids, bot_id: botId, user_id: userId }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`);
  return { removed: Array.isArray(data.removed) ? data.removed.map(String) : [] };
}

export async function setAccountActiveByEmail(email: string, is_active: boolean): Promise<{ success: boolean; is_active: number }> {
  const res = await fetchBackend("/api/accounts/by-email/active", {
    method: "POST",
    body: JSON.stringify({ email, is_active }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`);
  return data;
}

export async function runCharacterCycle(role_id: string, bot_id?: string): Promise<{ success: boolean; message?: string }> {
  const qs = bot_id ? `?bot_id=${encodeURIComponent(bot_id)}` : "";
  const res = await fetchBackend(`/api/characters/${encodeURIComponent(role_id)}/cycle${qs}`, {
    method: "POST",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`);
  return data;
}

export async function updateBotSettings(patch: Record<string, unknown>): Promise<Record<string, unknown>> {
  const res = await fetchBackend("/api/bot/settings", {
    method: "POST",
    body: JSON.stringify(patch),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`);
  return data;
}

export async function pushCharacterSettings(
  role_id: string,
  tiers?: Record<string, number | string>,
  gather?: Record<string, unknown>,
  combat?: Record<string, unknown>,
  hospital?: Record<string, unknown>,
  alliance?: Record<string, unknown>,
  daily_claims?: Record<string, unknown>,
  city?: Record<string, unknown>
): Promise<void> {
  // Writes into the backend SQLite store the engine actually reads
  const payload: Record<string, unknown> = {};
  if (tiers !== undefined) payload.tiers = tiers;
  if (gather !== undefined) payload.gather = gather;
  if (combat !== undefined) payload.combat = combat;
  if (hospital !== undefined) payload.hospital = hospital;
  if (alliance !== undefined) payload.alliance = alliance;
  if (daily_claims !== undefined) payload.daily_claims = daily_claims;
  if (city !== undefined) payload.city = city;

  const res = await fetchBackend(`/api/characters/${encodeURIComponent(role_id)}/settings`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`);
  }
}

export async function pushBotConfig(
  bot_id: string,
  payload: {
    scope: "one" | "all" | "email" | "role";
    email?: string;
    role_id?: string;
    settings?: Record<string, unknown>;
    config?: Record<string, unknown>;
  }
): Promise<void> {
  const res = await fetchBackend(`/api/v1/bot/${encodeURIComponent(bot_id)}/config`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`);
  }
}

export async function syncAccount(email: string, password: string, botId?: string, userId?: string): Promise<AccountSyncResult> {
  const headers: Record<string, string> = {};
  if (userId && userId !== "undefined" && userId !== "null") headers["x-user-id"] = userId;
  const res = await fetchBackend("/api/accounts/sync", {
    method: "POST",
    headers,
    body: JSON.stringify({ email, password, bot_id: botId, user_id: userId }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok && !data.status) {
    throw new Error(typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`);
  }
  // Backend returns captcha_url as a backend-relative path — route it
  // through our same-origin proxy so the backend host never leaks.
  if (typeof data.captcha_url === "string" && data.captcha_url.startsWith("/api/")) {
    data.captcha_url = `${PROXY}${data.captcha_url}`;
  }
  return data as AccountSyncResult;
}

export async function verifyCaptchaWithId(email: string, password: string, captchaId: string, botId?: string, userId?: string): Promise<AccountSyncResult> {
  const headers: Record<string, string> = {};
  if (userId && userId !== "undefined" && userId !== "null") headers["x-user-id"] = userId;
  const res = await fetchBackend("/api/accounts/verify-captcha", {
    method: "POST",
    headers,
    body: JSON.stringify({ email, password, captcha_id: captchaId, bot_id: botId, user_id: userId }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = data?.detail;
    throw new Error(typeof d === "string" ? d : `HTTP ${res.status}`);
  }
  return data as AccountSyncResult;
}

export async function sendOtpCode(email: string, botId?: string, userId?: string): Promise<{ success: boolean }> {
  const headers: Record<string, string> = {};
  if (userId && userId !== "undefined" && userId !== "null") headers["x-user-id"] = userId;
  const params = new URLSearchParams();
  if (botId) params.set("bot_id", botId);
  if (userId) params.set("user_id", userId);
  const q = params.toString() ? `?${params.toString()}` : "";
  const res = await fetchBackend(`/api/v1/auth/send-code${q}`, {
    method: "POST",
    headers,
    body: JSON.stringify({ email }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = data?.detail;
    throw new Error(typeof d === "string" ? d : `HTTP ${res.status}`);
  }
  return data;
}

export async function verifyOtpCode(email: string, code: string, botId?: string, userId?: string): Promise<AccountSyncResult> {
  const headers: Record<string, string> = {};
  if (userId && userId !== "undefined" && userId !== "null") headers["x-user-id"] = userId;
  const params = new URLSearchParams();
  if (botId) params.set("bot_id", botId);
  if (userId) params.set("user_id", userId);
  const q = params.toString() ? `?${params.toString()}` : "";
  const res = await fetchBackend(`/api/v1/auth/verify-code${q}`, {
    method: "POST",
    headers,
    body: JSON.stringify({ email, code, bot_id: botId, user_id: userId }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok && !(data as any)?.status) {
    const d = data?.detail;
    throw new Error(typeof d === "string" ? d : `HTTP ${res.status}`);
  }
  return data as AccountSyncResult;
}

export async function runCharacterCombat(
  role_id: string,
  combatParams?: Record<string, unknown>
): Promise<{ success: boolean; message?: string; task_id?: string }> {
  const res = await fetchBackend(`/api/characters/${encodeURIComponent(role_id)}/combat`, {
    method: "POST",
    body: JSON.stringify(combatParams || {}),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`);
  return data;
}

export async function syncBotFullConfig(
  botId: string,
  config: Record<string, any>,
  userId?: string,
  scopeEmail?: string,
  scopeRoleId?: string
): Promise<void> {
  if (!userId) throw new Error("Please sign in before saving settings.");
  const body: Record<string, any> = { config };
  if (scopeRoleId) body.scope_role_id = scopeRoleId;
  else if (scopeEmail) body.scope_email = scopeEmail;
  const res = await fetchBackend(
    `/api/v1/bot/${encodeURIComponent(botId)}/config?user_id=${encodeURIComponent(userId)}`,
    { method: "POST", body: JSON.stringify(body) }
  );
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.success !== true) {
    throw new Error(typeof data.detail === "string" ? data.detail : `Settings sync failed (HTTP ${res.status})`);
  }
  if (!data.config || Object.keys(config).some(key => JSON.stringify(data.config[key]) !== JSON.stringify(config[key]))) {
    throw new Error("The engine did not confirm these settings. Please retry saving.");
  }
}

// ── Troop Recall ──────────────────────────────────────────────────────────────

export async function recallMarches(
  roleId: string,
  userId?: string
): Promise<{ success: boolean; task_id?: string; recalled?: number; total_found?: number; message?: string }> {
  const params = new URLSearchParams();
  if (userId) params.set("user_id", userId);
  const q = params.toString() ? `?${params.toString()}` : "";
  const res = await fetchBackend(`/api/characters/${encodeURIComponent(roleId)}/recall-marches${q}`, {
    method: "POST",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`);
  return data;
}

export async function bulkRecallMarches(
  roleIds: string[],
  userId?: string
): Promise<{ success: boolean; launched?: number; queued?: number; skipped: number; message?: string }> {
  const params = new URLSearchParams();
  if (userId) params.set("user_id", userId);
  const q = params.toString() ? `?${params.toString()}` : "";
  const res = await fetchBackend(`/api/characters/bulk-recall-marches${q}`, {
    method: "POST",
    body: JSON.stringify({ role_ids: roleIds }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`);
  return data;
}

// ── Alliance Resource Center Direct Dispatch ─────────────────────────────────

export async function dispatchAllianceResource(
  roleId: string,
  userId?: string
): Promise<{ success: boolean; task_id?: string; message?: string }> {
  const params = new URLSearchParams();
  if (userId) params.set("user_id", userId);
  const q = params.toString() ? `?${params.toString()}` : "";
  const res = await fetchBackend(`/api/v1/characters/${encodeURIComponent(roleId)}/dispatch-alliance-resource${q}`, {
    method: "POST",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`);
  return data;
}

// ── نقل الموارد (RSS Transfer) ────────────────────────────────────────────────

export async function getSavedRecipients(): Promise<{ recipients: any[] }> {
  try {
    const res = await fetchBackend("/api/v1/saved-recipients");
    if (!res.ok) {
      const fallback = await fetchBackend("/api/saved-recipients");
      if (!fallback.ok) return { recipients: [] };
      return await fallback.json();
    }
    return await res.json();
  } catch {
    return { recipients: [] };
  }
}

export async function getTradingPostRates(): Promise<{ progression_table: Record<number, { capacity: number; tax: number }> }> {
  try {
    const res = await fetchBackend("/api/v1/trading-post-rates");
    if (!res.ok) {
      const fallback = await fetchBackend("/api/trading-post-rates");
      if (!fallback.ok) return { progression_table: {} };
      return await fallback.json();
    }
    return await res.json();
  } catch {
    return { progression_table: {} };
  }
}

export interface RSSTransferPayload {
  target_role_id: string;
  target_name: string;
  x: number;
  y: number;
  requested_rss: Record<string, number>;
  selected_farm_roles: string[];
  bot_id?: string;
  user_id?: string;
  transfer_mode?: "total_net" | "per_farm" | "max_drain";
  custom_tp_level?: number | null;
}

export async function startRssTransfer(
  payload: RSSTransferPayload
): Promise<{ success: boolean; job_id?: string; message?: string; detail?: string }> {
  const qs = new URLSearchParams();
  if (payload.bot_id) qs.set("bot_id", payload.bot_id);
  if (payload.user_id) qs.set("user_id", payload.user_id);
  const qStr = qs.toString() ? `?${qs.toString()}` : "";
  const res = await fetchBackend(`/api/v1/start-transfer${qStr}`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`);
  return data;
}

export async function getTransferStatus(jobId: string): Promise<any> {
  try {
    const res = await fetchBackend(`/api/v1/status/${encodeURIComponent(jobId)}`);
    if (!res.ok) {
      const fallback = await fetchBackend(`/api/status/${encodeURIComponent(jobId)}`);
      return await fallback.json();
    }
    return await res.json();
  } catch {
    return null;
  }
}

export async function stopTransferJob(jobId: string): Promise<any> {
  try {
    const res = await fetchBackend(`/api/v1/stop/${encodeURIComponent(jobId)}`, { method: "POST" });
    if (!res.ok) {
      const fallback = await fetchBackend(`/api/stop/${encodeURIComponent(jobId)}`, { method: "POST" });
      return await fallback.json();
    }
    return await res.json();
  } catch {
    return { success: false };
  }
}


