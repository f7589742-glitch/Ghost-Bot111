import { getSupabaseBrowserClient } from "@/lib/supabaseClient";

export function createClient() {
  return getSupabaseBrowserClient();
}
