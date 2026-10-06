"use client";

// Device-local store, namespaced per Discord user. Without namespacing,
// two users sharing one browser would see each other's bots and accounts.
// Supabase RLS protects cloud rows; this protects the local copies.

export interface OwnedBot {
  id: string;
  bot_id?: string;
  product: "farm-bot" | "gem-bot" | string;
  label: string;
  tier: "basic" | "pro" | string;
  slots: number;
  days?: number;
  room: string;
  ref?: string;
  total?: string;
  createdAt?: number;
  expiresAt?: string;
  active?: boolean;
}

export interface SyncedChar {
  role_id: string;
  name: string;
  kingdom_id: number;
  city_level?: number;
  avatar_url?: string;
  enabled?: boolean;
}

export interface BotAccount {
  email: string;
  enabled: boolean;
  addedAt: number;
  chars?: SyncedChar[];
}

// Post-purge namespace (v2): pre-purge device-local copies are orphaned so
// no stale account/bot ghosts can resurface after the fleet wipe.
const BOTS_KEY = "zb2_bots";
const ACC_PREFIX = "zb2_accounts_";
const CFG_PREFIX = "zb2_config_";

let _owner: string | null = null;

const ns = (key: string) => (_owner ? `${key}__${_owner}` : `${key}__guest`);

export function setStoreOwner(userId: string | null) {
  _owner = userId && userId.length > 0 ? userId : null;
}

/**
 * Legacy v1 keys (aegis_*) are intentionally NOT adopted: the fleet was
 * hard-purged and every tenant starts from zero. Just bind the namespace.
 */
export function migrateLegacyToOwner(userId: string) {
  setStoreOwner(userId);
}

function read<T>(key: string, fallback: T): T {
  if (typeof window === "undefined") return fallback;
  try {
    const raw = localStorage.getItem(ns(key));
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, val: unknown) {
  try {
    localStorage.setItem(ns(key), JSON.stringify(val));
  } catch {
    /* storage unavailable */
  }
  try {
    window.dispatchEvent(new Event("aegis-store"));
  } catch {
    /* noop */
  }
}

export function getBots(): OwnedBot[] {
  return read<OwnedBot[]>(BOTS_KEY, []);
}

export function saveBot(bot: OwnedBot) {
  const bots = getBots();
  write(BOTS_KEY, [...bots.filter((b) => b.id !== bot.id), bot]);
  // Asynchronously persist to Supabase Cloud
  import("@/lib/cloud").then(({ createCloudBot }) => {
    createCloudBot(bot).catch(() => {});
  }).catch(() => {});
}

export function getBot(id: string): OwnedBot | undefined {
  return getBots().find((b) => b.id === id);
}

export function getAccounts(botId: string): BotAccount[] {
  return read<BotAccount[]>(ACC_PREFIX + botId, []);
}

export function addAccount(botId: string, email: string, chars?: SyncedChar[]) {
  const accs = getAccounts(botId);
  const first = chars?.[0];
  if (accs.some((a) => a.email.toLowerCase() === email.toLowerCase())) {
    if (chars) {
      write(
        ACC_PREFIX + botId,
        accs.map((a) => (a.email.toLowerCase() === email.toLowerCase() ? { ...a, chars } : a))
      );
    }
  } else {
    write(ACC_PREFIX + botId, [...accs, { email, enabled: true, addedAt: Date.now(), chars }]);
  }
  // Asynchronously persist to Supabase Cloud
  import("@/lib/cloud").then(({ linkCloudAccount }) => {
    linkCloudAccount(botId, email, {
      role_id: first?.role_id,
      kingdom_id: first?.kingdom_id,
      device_profile: chars ? { governors: chars } : undefined,
    }).catch(() => {});
  }).catch(() => {});
}

export function removeAccount(botId: string, email: string) {
  write(
    ACC_PREFIX + botId,
    getAccounts(botId).filter((a) => a.email !== email)
  );
  // Asynchronously delete from Supabase Cloud
  import("@/lib/cloud").then(({ deleteCloudAccount }) => {
    deleteCloudAccount(botId, email).catch(() => {});
  }).catch(() => {});
}

export function toggleAccount(botId: string, email: string) {
  write(
    ACC_PREFIX + botId,
    getAccounts(botId).map((a) => (a.email === email ? { ...a, enabled: !a.enabled } : a))
  );
}

export function getConfig<T>(botId: string, defaults: T): T {
  const stored = read<T | undefined>(CFG_PREFIX + botId, undefined);
  if (stored !== undefined && typeof defaults === "object" && defaults !== null) {
    return { ...defaults, ...stored };
  }
  return (stored as T) ?? defaults;
}

export function saveConfig(botId: string, cfg: unknown) {
  write(CFG_PREFIX + botId, cfg);
  // Asynchronously persist to Supabase Cloud
  import("@/lib/cloud").then(({ syncTenantConfig }) => {
    if (cfg && typeof cfg === "object") {
      syncTenantConfig(botId, cfg as Record<string, unknown>).catch(() => {});
    }
  }).catch(() => {});
}

// Per-email config. Falls back to the bot-level config, then defaults.
export function getAccountConfig<T>(botId: string, email: string, defaults: T): T {
  if (!email) return getConfig(botId, defaults);
  const per = read<T | undefined>(CFG_PREFIX + botId + "_" + email.toLowerCase(), undefined);
  if (per !== undefined) return { ...defaults, ...per };
  return getConfig(botId, defaults);
}

export function saveAccountConfig(botId: string, email: string, cfg: unknown) {
  write(CFG_PREFIX + botId + "_" + email.toLowerCase(), cfg);
  // Asynchronously persist to Supabase Cloud
  import("@/lib/cloud").then(({ saveCloudSettings }) => {
    if (cfg && typeof cfg === "object") {
      saveCloudSettings(botId, email, cfg as Record<string, unknown>).catch(() => {});
    }
  }).catch(() => {});
}

const RUNNING_PREFIX = "zb2_bot_running_";

export function getBotRunning(botId: string, fallback: boolean = true): boolean {
  return read<boolean>(RUNNING_PREFIX + botId, fallback);
}

export function setBotRunning(botId: string, running: boolean) {
  write(RUNNING_PREFIX + botId, running);
}

