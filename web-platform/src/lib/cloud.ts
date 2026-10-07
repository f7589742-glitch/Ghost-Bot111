"use client";

import { createClient } from "@/lib/supabase/client";
import { getBots as getLocalBots, saveBot as saveLocalBot, getAccounts, type OwnedBot } from "@/lib/store";
import { fetchBackend } from "@/lib/api";

function configured() {
  return Boolean(process.env.NEXT_PUBLIC_SUPABASE_URL);
}

export async function getSessionUser() {
  if (configured()) {
    try {
      const supabase = createClient();
      const { data } = await supabase.auth.getUser();
      if (data?.user && !data.user.is_anonymous) return data.user;
    } catch {}
  }
  return null;
}

// Session-scoped store boot (cached per page load). Ensures the
// device-local store is namespaced to the logged-in Discord user BEFORE
// any page reads bots/accounts — otherwise users sharing one browser
// would see each other's local data.
let _boot: Promise<void> | null = null;
export function bootOwner(): Promise<void> {
  if (!_boot) {
    _boot = (async () => {
      const u = await getSessionUser();
      const store = await import("@/lib/store");
      if (u) {
        store.setStoreOwner(u.id);
        store.migrateLegacyToOwner(u.id);
      } else {
        store.setStoreOwner(null);
      }
    })();
  }
  return _boot;
}
export function resetOwnerCache() {
  _boot = null;
}

// Union of cloud bots + local bots (dedupe by id). Falls back to local
// when logged out or Supabase is not configured.
export async function getAllBots(): Promise<OwnedBot[]> {
  const local = getLocalBots();
  const user = await getSessionUser();
  if (!user) return local;
  try {
    const supabase = createClient();
    const { data, error } = await supabase
      .from("bot_instances")
      .select("*")
      .eq("user_id", user.id)
      .order("created_at", { ascending: false });
    if (error || !data) return local;
    const cloud: OwnedBot[] = (data as any[]).map((r: any) => ({
      id: r.id,
      bot_id: r.bot_id || r.id,
      product: r.product === "gem-bot" ? "gem-bot" : "farm-bot",
      label: r.name,
      tier: r.tier === "pro" ? "pro" : "basic",
      slots: r.slots,
      days: 30,
      room: r.room || "",
      ref: r.ref || "",
      total: r.total || "",
      createdAt: r.created_at ? Date.parse(r.created_at) : Date.now(),
    }));
    const seen = new Set(cloud.map((b) => b.id));
    return [...cloud, ...local.filter((b) => !seen.has(b.id))];
  } catch {
    return local;
  }
}

export async function createCloudBot(bot: OwnedBot) {
  const user = await getSessionUser();
  if (!user) return;
  try {
    const supabase = createClient();
    let botSlug = bot.bot_id;
    if (!botSlug || botSlug === "bot-0" || botSlug === "bot-1") {
      const { count } = await supabase
        .from("bot_instances")
        .select("*", { count: "exact", head: true })
        .eq("user_id", user.id);
      const seq = (count || 0) + 1;
      botSlug = `bot-${user.id.slice(0, 8)}-${seq}`;
    }
    const { data: createdBot, error: botErr } = await supabase.from("bot_instances").upsert(
      {
        bot_id: botSlug,
        user_id: user.id,
        product: bot.product,
        name: bot.label,
        slots: bot.slots,
        tier: bot.tier,
        status: "stopped",
        config: {},
        expires_at: new Date((bot.createdAt ?? Date.now()) + (bot.days ?? 30) * 86400000).toISOString(),
      },
      { onConflict: "user_id, bot_id" }
    ).select().single();

    if (botErr) {
      console.error("[cloud] createCloudBot error:", botErr.message);
    } else if (createdBot) {
      console.log("[cloud] createCloudBot success:", createdBot.id);
    }
    // Purchase sync: auto-generate the isolated tenant workspace on EC2.
    try {
      await fetchBackend(`/api/tenants/${encodeURIComponent(botSlug)}/ensure`, {
        method: "POST",
        body: JSON.stringify({ user_uuid: user.id, slots: bot.slots, defaults: { tier: bot.tier, days: bot.days ?? 30 } }),
      });
    } catch {
      /* workspace sync is best-effort */
    }
  } catch {
    /* offline-first: local copy already saved */
  }
}

export async function linkCloudAccount(botId: string, email: string, extra?: { role_id?: string; kingdom_id?: number; proxy_url?: string | null; device_profile?: unknown; last_login_ip?: string | null; assigned_slot?: number | null }) {
  const user = await getSessionUser();
  if (!user) return;
  const supabase = createClient();
  const { error } = await supabase.from("game_accounts").upsert(
    { instance_id: botId, user_id: user.id, email, role_id: extra?.role_id ?? null, kingdom_id: extra?.kingdom_id ?? null, is_enabled: true, proxy_url: extra?.proxy_url ?? null, device_profile: extra?.device_profile ?? null, last_login_ip: extra?.last_login_ip ?? null, assigned_slot: extra?.assigned_slot ?? 0 },
    { onConflict: "instance_id,email" }
  );
  if (error) {
    // Surface FK/RLS failures instead of failing silently — a missing profile
    // row or bot_instance row makes the upsert 403/409 and the account never
    // appears after re-login.
    console.error("[cloud] linkCloudAccount failed:", error.message);
    throw new Error(`Cloud link failed: ${error.message}`);
  }
}

export async function getCloudAccounts(botId: string): Promise<Record<string, { proxy_url: string | null }>> {
  const user = await getSessionUser();
  if (!user) return {};
  try {
    const supabase = createClient();
    const { data } = await supabase
      .from("game_accounts")
      .select("email,proxy_url")
      .eq("instance_id", botId)
      .eq("user_id", user.id);
    const out: Record<string, { proxy_url: string | null }> = {};
    for (const r of data || []) out[r.email] = { proxy_url: r.proxy_url ?? null };
    return out;
  } catch {
    return {};
  }
}

export interface CloudAccountRow {
  email: string;
  role_id: string | null;
  kingdom_id: number | null;
  is_enabled: boolean | null;
}

// Full cloud account rows for a bot — used to recover linked accounts after a
// re-login or on a new device (the local store is device-scoped; the cloud
// copy follows the user).
export async function getCloudAccountRows(botId: string): Promise<CloudAccountRow[]> {
  const user = await getSessionUser();
  if (!user) return [];
  try {
    const supabase = createClient();
    const { data, error } = await supabase
      .from("game_accounts")
      .select("email,role_id,kingdom_id,is_enabled")
      .eq("instance_id", botId)
      .eq("user_id", user.id);
    if (error) {
      console.error("[cloud] getCloudAccountRows failed:", error.message);
      return [];
    }
    return (data || []) as CloudAccountRow[];
  } catch {
    return [];
  }
}

export function shortProxy(url: string | null | undefined): string {
  if (!url) return "";
  try {
    const u = new URL(url.includes("://") ? url : `http://${url}`);
    return u.host || url;
  } catch {
    return url;
  }
}

export async function deleteCloudAccount(botId: string, email: string) {
  const user = await getSessionUser();
  if (!user) return;
  try {
    const supabase = createClient();
    // Remove mirrored characters first (linked via parent account ids).
    try {
      const { data: accRows } = await supabase
        .from("game_accounts")
        .select("id")
        .eq("instance_id", botId)
        .eq("email", email)
        .eq("user_id", user.id);
      const ids = (accRows || []).map((r: any) => r.id).filter(Boolean);
      if (ids.length) {
        await supabase.from("game_characters").delete().in("account_id", ids);
      }
    } catch {
      /* game_characters mirror may not exist — account row delete still runs */
    }
    await supabase.from("game_accounts").delete().eq("instance_id", botId).eq("email", email).eq("user_id", user.id);
  } catch {
    /* local copy already removed */
  }
}

export async function saveCloudSettings(botId: string, email: string, settingsJson: Record<string, unknown>) {
  const user = await getSessionUser();
  if (!user) return;
  try {
    const supabase = createClient();
    await supabase.from("game_accounts").upsert(
      { instance_id: botId, user_id: user.id, email, settings: settingsJson },
      { onConflict: "instance_id,email" }
    );
  } catch {
    /* local-first: engine push already attempted */
  }
}

export async function syncTenantFleet(botId: string) {
  const user = await getSessionUser();
  if (!user) return;
  try {
    const emails = getAccounts(botId).map((a) => a.email);
    await fetchBackend(`/api/tenants/${encodeURIComponent(botId)}/fleet`, {
      method: "POST",
      body: JSON.stringify({ user_uuid: user.id, emails }),
    });
  } catch {
    /* backend optional */
  }
}

export async function syncTenantConfig(botId: string, settings: Record<string, unknown>) {
  const user = await getSessionUser();
  if (!user) return;
  try {
    await fetchBackend(`/api/tenants/${encodeURIComponent(botId)}/config`, {
      method: "POST",
      body: JSON.stringify({ user_uuid: user.id, settings }),
    });
  } catch {
    /* backend optional */
  }
}

export async function getInstanceRuntime(instanceId: string) {
  const user = await getSessionUser();
  if (!user) return null;
  try {
    const supabase = createClient();
    const { data } = await supabase
      .from("bot_instances")
      .select("status,runtime_status,server_worker_id,server_node,last_heartbeat")
      .eq("id", instanceId)
      .maybeSingle();
    return data;
  } catch {
    return null;
  }
}

export { saveLocalBot };
