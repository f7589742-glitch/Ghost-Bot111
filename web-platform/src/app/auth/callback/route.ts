import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";
import { NextResponse } from "next/server";

const SUPABASE_URL =
  process.env.NEXT_PUBLIC_SUPABASE_URL ||
  process.env.SUPABASE_URL ||
  "https://ksrfhjhldgsazqjxealh.supabase.co";

const SUPABASE_ANON_KEY =
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ||
  process.env.SUPABASE_PUBLISHABLE_KEY ||
  "sb_publishable_R2QxKP54Z6BjjPUolZoEkg_jWuqI_rB";

export async function GET(request: Request) {
  const requestUrl = new URL(request.url);
  const code = requestUrl.searchParams.get("code");
  const next = requestUrl.searchParams.get("next") || "/dashboard";

  const fwd = request.headers.get("x-forwarded-host");
  const proto = request.headers.get("x-forwarded-proto") || "https";
  const origin = fwd ? `${proto}://${fwd}` : requestUrl.origin;

  const errorParam = requestUrl.searchParams.get("error");
  const errorDesc = requestUrl.searchParams.get("error_description");

  console.log("[AuthCallback] Raw URL:", request.url);

  if (errorParam) {
    console.error("[AuthCallback] Provider returned error:", errorParam, errorDesc);
    return NextResponse.redirect(
      new URL(
        `/login?error=${encodeURIComponent(errorParam)}&error_description=${encodeURIComponent(errorDesc || errorParam)}`,
        origin
      )
    );
  }

  if (code) {
    try {
      const cookieStore = await cookies();
      let response = NextResponse.redirect(new URL(next, origin));

      const supabase = createServerClient(
        SUPABASE_URL,
        SUPABASE_ANON_KEY,
        {
          cookies: {
            getAll() {
              return cookieStore.getAll();
            },
            setAll(cookiesToSet) {
              cookiesToSet.forEach(({ name, value, options }) => {
                try {
                  cookieStore.set(name, value, options);
                } catch {}
                response.cookies.set(name, value, options);
              });
            },
          },
        }
      );

      const { data, error } = await supabase.auth.exchangeCodeForSession(code);
      if (!error && data?.user) {
        const user = data.user;
        const meta = user.user_metadata || {};
        const idMeta = (user.identities && user.identities[0]?.identity_data) || {};
        const merged = { ...idMeta, ...meta };

        const avatar =
          merged.avatar_url ||
          merged.picture ||
          idMeta.avatar_url ||
          (user.user_metadata?.avatar_url ?? null);

        const username =
          merged.custom_claims?.global_name ||
          merged.global_name ||
          merged.full_name ||
          merged.name ||
          merged.user_name ||
          (user.email ? user.email.split("@")[0] : "Commander");

        response.cookies.set(
          "ghostbot_user_profile",
          JSON.stringify({
            user_id: user.id,
            email: user.email ?? null,
            username: username,
            avatar_url: avatar ?? null,
          }),
          {
            path: "/",
            maxAge: 60 * 60 * 24 * 30,
            sameSite: "lax",
            httpOnly: false,
          }
        );

        try {
          const { createAdminClient } = await import("@/lib/supabase/admin");
          const admin = createAdminClient();
          await admin.from("profiles").upsert(
            {
              id: user.id,
              username: username,
              avatar_url: avatar ?? null,
              email: user.email ?? null,
              updated_at: new Date().toISOString(),
            },
            { onConflict: "id" }
          );
        } catch (upsertErr) {
          console.error("[AuthCallback] Profile upsert error in callback:", upsertErr);
        }

        return response;
      } else if (error) {
        console.error("[AuthCallback] exchangeCodeForSession failed:", error.message);
        return NextResponse.redirect(
          new URL(
            `/login?error=auth_callback_failed&error_description=${encodeURIComponent(error.message)}`,
            origin
          )
        );
      }
    } catch (err: any) {
      console.error("[AuthCallback] Exception during code exchange:", err);
      return NextResponse.redirect(
        new URL(
          `/login?error=auth_exception&error_description=${encodeURIComponent(err?.message || "Authentication failed")}`,
          origin
        )
      );
    }
  }

  return NextResponse.redirect(
    new URL("/login?error=auth_callback_failed&error_description=missing_code", origin)
  );
}
