import { NextRequest, NextResponse } from "next/server";
import { createServerClient } from "@supabase/ssr";

function clearAllAuthCookies(req: NextRequest, res: NextResponse) {
  const allCookies = req.cookies.getAll();
  for (const c of allCookies) {
    if (
      c.name.startsWith("sb-") ||
      c.name === "ghostbot_user_profile" ||
      c.name === "ghostbot_guest"
    ) {
      res.cookies.delete(c.name);
      res.cookies.set(c.name, "", { path: "/", maxAge: 0 });
    }
  }
  res.cookies.delete("ghostbot_user_profile");
  res.cookies.set("ghostbot_user_profile", "", { path: "/", maxAge: 0 });
  res.cookies.delete("ghostbot_guest");
  res.cookies.set("ghostbot_guest", "", { path: "/", maxAge: 0 });
}

export async function GET(req: NextRequest) {
  const url = req.nextUrl.clone();
  url.pathname = "/login";
  url.search = "?signedOut=1";
  const res = NextResponse.redirect(url);
  try {
    const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
    const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
    if (supabaseUrl && supabaseAnonKey) {
      const supabase = createServerClient(supabaseUrl, supabaseAnonKey, {
        cookies: {
          getAll() {
            return req.cookies.getAll();
          },
          setAll(cookiesToSet) {
            cookiesToSet.forEach(({ name, value, options }) =>
              res.cookies.set(name, value, options)
            );
          },
        },
      });
      await supabase.auth.signOut();
    }
  } catch {
    /* ignore */
  }
  clearAllAuthCookies(req, res);
  return res;
}

export async function POST(req: NextRequest) {
  const res = NextResponse.json({ success: true });
  try {
    const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
    const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
    if (supabaseUrl && supabaseAnonKey) {
      const supabase = createServerClient(supabaseUrl, supabaseAnonKey, {
        cookies: {
          getAll() {
            return req.cookies.getAll();
          },
          setAll(cookiesToSet) {
            cookiesToSet.forEach(({ name, value, options }) =>
              res.cookies.set(name, value, options)
            );
          },
        },
      });
      await supabase.auth.signOut();
    }
  } catch {
    /* ignore */
  }
  clearAllAuthCookies(req, res);
  return res;
}
