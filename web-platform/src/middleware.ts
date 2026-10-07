import { type NextRequest, NextResponse } from "next/server";
import { createServerClient } from "@supabase/ssr";

export async function middleware(request: NextRequest) {
  const response = NextResponse.next({ request });
  if (!process.env.NEXT_PUBLIC_SUPABASE_URL) return response;

  const { pathname } = request.nextUrl;
  const code = request.nextUrl.searchParams.get("code");
  if (code && !pathname.startsWith("/auth")) {
    const callbackUrl = request.nextUrl.clone();
    callbackUrl.pathname = "/auth/callback";
    return NextResponse.redirect(callbackUrl);
  }

  // Allow static assets, auth, api, and login routes without interference
  if (
    pathname.startsWith("/_next") ||
    pathname.startsWith("/api") ||
    pathname.startsWith("/auth")
  ) {
    return response;
  }

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll: () => request.cookies.getAll(),
        setAll: (pairs) => {
          pairs.forEach(({ name, value, options }) =>
            response.cookies.set(name, value, options)
          );
        },
      },
    }
  );

  // 1. Purge legacy guest cookies across all requests
  response.cookies.delete("ghostbot_guest");
  response.cookies.delete("ghostbot_guest_mode");

  let authenticatedUser: any = null;
  try {
    const { data } = await supabase.auth.getUser();
    authenticatedUser = data?.user && !data.user.is_anonymous ? data.user : null;
  } catch (e) {
    authenticatedUser = null;
  }

  // 2. Route Guard: public routes vs protected routes
  const isPublicRoute =
    pathname === "/" ||
    pathname === "/login" ||
    pathname.startsWith("/terms") ||
    pathname.startsWith("/privacy");

  if (!authenticatedUser) {
    // If accessing any protected internal route without verified session -> redirect to /login
    if (!isPublicRoute) {
      const loginUrl = request.nextUrl.clone();
      loginUrl.pathname = "/login";
      loginUrl.searchParams.set("redirectTo", pathname);
      const redirectResponse = NextResponse.redirect(loginUrl);
      redirectResponse.cookies.delete("ghostbot_guest");
      redirectResponse.cookies.delete("ghostbot_guest_mode");
      return redirectResponse;
    }
  } else {
    // If already authenticated and trying to access /login, redirect to /dashboard
    if (pathname === "/login") {
      const dashUrl = request.nextUrl.clone();
      dashUrl.pathname = "/dashboard";
      dashUrl.search = "tab=overview";
      return NextResponse.redirect(dashUrl);
    }

    // Sync ghostbot_user_profile cookie when authenticated session exists on server
    try {
      const user = authenticatedUser;
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
          maxAge: 60 * 60 * 24 * 30, // 30 days
          sameSite: "lax",
          httpOnly: false, // Accessible by client JS
        }
      );
    } catch (e) {}
  }

  return response;
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|images|ghostbot-bg\\.mp4|ghostbot-logo\\.png|kingdom-bg\\.jpg|.*\\.(?:svg|png|jpg|jpeg|gif|webp|mp4)$).*)",
  ],
};
