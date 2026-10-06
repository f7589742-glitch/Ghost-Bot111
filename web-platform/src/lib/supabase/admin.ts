import { createClient as createSupabaseClient } from "@supabase/supabase-js";

// Server-only admin client (service/secret key). NEVER import this file
// from a "use client" component — API routes / server components only.
export function createAdminClient() {
  const url =
    process.env.NEXT_PUBLIC_SUPABASE_URL ||
    process.env.SUPABASE_URL ||
    "https://ksrfhjhldgsazqjxealh.supabase.co";
  const secret =
    process.env.SUPABASE_SECRET_KEY ||
    process.env.SUPABASE_SERVICE_ROLE_KEY ||
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ||
    "sb_secret_Pmsmj4HkG7Nu_zSLsHpskw_xFAvFNVa";
  return createSupabaseClient(url, secret, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
}

function envList(name: string): string[] {
  return (process.env[name] || "")
    .split(",")
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean);
}

const KNOWN_ADMINS = new Set([
  "malek.11332",
  "malek",
  "mr.malek",
  "fm434136@gmail.com",
  "teez8888@gmail.com",
  "0b13598d-6a29-4e16-8ad3-b937824294e9",
  "775687774417321994",
]);

// Discord snowflake of the signed-in user, read from the Supabase
// Discord identity (identity_data.sub) with metadata fallbacks.
export function getDiscordId(
  user: { identities?: any[]; user_metadata?: Record<string, any> } | null | undefined
): string | null {
  if (!user) return null;
  for (const ident of user.identities || []) {
    if (ident?.provider === "discord") {
      const d = ident.identity_data || {};
      for (const k of ["sub", "id", "user_id", "provider_id"]) {
        const v = d?.[k];
        if (typeof v === "string" && /^\d{10,25}$/.test(v)) return v;
        if (typeof v === "number") return String(v);
      }
    }
  }
  const meta = user.user_metadata || {};
  for (const k of ["provider_id", "sub", "discord_id"]) {
    const v = meta?.[k];
    if (typeof v === "string" && /^\d{10,25}$/.test(v)) return v;
    if (typeof v === "number") return String(v);
  }
  return null;
}

// Extract all possible usernames, handles, and emails associated with the user
export function getUserHandles(user: any): string[] {
  if (!user) return [];
  const handles = new Set<string>();
  if (user.email) handles.add(String(user.email).toLowerCase().trim());

  const meta = user.user_metadata || {};
  for (const k of ["user_name", "preferred_username", "name", "full_name"]) {
    if (meta[k] && typeof meta[k] === "string") {
      handles.add(meta[k].toLowerCase().trim());
    }
  }
  if (meta.custom_claims?.global_name && typeof meta.custom_claims.global_name === "string") {
    handles.add(meta.custom_claims.global_name.toLowerCase().trim());
  }

  for (const ident of user.identities || []) {
    const d = ident.identity_data || {};
    for (const k of ["user_name", "preferred_username", "name", "full_name", "email"]) {
      if (d[k] && typeof d[k] === "string") {
        handles.add(d[k].toLowerCase().trim());
      }
    }
  }
  return Array.from(handles);
}

// Owner/admin gate: Discord ID allowlist OR admin email allowlist OR username allowlist.
export function isAdminUser(
  user: { email?: string | null; identities?: any[]; user_metadata?: any } | null
): boolean {
  if (!user) return false;

  // 1. Direct match with malek.11332 or known owner identifiers
  const did = getDiscordId(user);
  if (did && KNOWN_ADMINS.has(did)) return true;

  const handles = getUserHandles(user);
  for (const h of handles) {
    if (
      KNOWN_ADMINS.has(h) ||
      h === "malek.11332" ||
      h.includes("malek.11332") ||
      h.includes("11332")
    ) {
      return true;
    }
  }

  // 2. Allowlist via environment variables
  const emails = envList("ADMIN_EMAILS");
  if (user.email && emails.includes(user.email.toLowerCase())) return true;

  const ids = envList("ADMIN_DISCORD_IDS");
  if (did && ids.includes(did)) return true;

  const envUsers = envList("ADMIN_USERNAMES");
  for (const h of handles) {
    if (envUsers.includes(h)) return true;
  }

  return false;
}

export function isOwnerUser(
  user: { id?: string; email?: string | null; identities?: any[]; user_metadata?: any } | null
): boolean {
  if (!user) return false;
  if (user.id && (user.id === "0b13598d-6a29-4e16-8ad3-b937824294e9" || KNOWN_ADMINS.has(user.id))) return true;
  if (user.email && (user.email.toLowerCase() === "fm434136@gmail.com" || user.email.toLowerCase() === "teez8888@gmail.com")) return true;
  const did = getDiscordId(user);
  if (did && (did === "775687774417321994" || KNOWN_ADMINS.has(did))) return true;
  return isAdminUser(user);
}
