import { supabase } from "@/lib/supabaseClient";

/**
 * Perform a clean, irreversible sign out:
 * 1. Invalidate session via Supabase client.
 * 2. Invalidate server-side cookies via /auth/signout endpoint.
 * 3. Clear all browser localStorage and sessionStorage keys.
 * 4. Expire and clear all document cookies.
 * 5. Hard redirect user to /login.
 */
export async function performSignOut(redirectTo: string = "/login"): Promise<void> {
  try {
    // 1. Notify server route to clear server cookies
    await fetch("/auth/signout", { method: "POST" }).catch(() => {});

    // 2. Client-side Supabase sign out
    await supabase.auth.signOut().catch(() => {});
  } catch (e) {
    console.error("[performSignOut] Error during sign out:", e);
  } finally {
    // 3. Clear all local storage
    if (typeof window !== "undefined") {
      try {
        localStorage.clear();
        sessionStorage.clear();
      } catch {}

      // 4. Clear all cookies across root path and current domain
      try {
        const cookies = document.cookie.split(";");
        for (let i = 0; i < cookies.length; i++) {
          const cookie = cookies[i];
          const eqPos = cookie.indexOf("=");
          const name = eqPos > -1 ? cookie.substr(0, eqPos).trim() : cookie.trim();
          if (name) {
            document.cookie = `${name}=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; max-age=0;`;
            // Also try with domain
            const hostname = window.location.hostname;
            document.cookie = `${name}=; path=/; domain=${hostname}; expires=Thu, 01 Jan 1970 00:00:00 GMT; max-age=0;`;
          }
        }
      } catch {}

      // 5. Hard browser redirection to /login
      window.location.replace(redirectTo);
    }
  }
}
