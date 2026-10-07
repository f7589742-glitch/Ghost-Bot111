import { NextRequest, NextResponse } from "next/server";

const EC2_HOST = "http://16.171.9.216";
const BOT_SECRET = "rok_stealth_7f93a1c84b2e65d09e3a8412c0915f7b";
const API_KEY = "19fb30503c1704629ea6cffc32f71689";

async function proxyRequest(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  const pathStr = (path || []).join("/");
  
  // Normalize destination URL. If path already starts with "api/", avoid duplicating.
  const targetPath = pathStr.startsWith("api/") ? `/${pathStr}` : `/api/${pathStr}`;

  // Dedicated endpoint for tenant identity and bot fleet metadata
  if (targetPath === "/api/tenant/me" || pathStr.endsWith("tenant/me")) {
    const uid = req.headers.get("x-user-id")?.trim() || req.nextUrl.searchParams.get("user_id");
    if (!uid) {
      return NextResponse.json({ authenticated: false, bots: [] }, { status: 401 });
    }
    try {
      const { createAdminClient } = await import("@/lib/supabase/admin");
      const adminClient = createAdminClient();
      const { data: prof } = await adminClient.from("profiles").select("*").eq("id", uid).maybeSingle();
      const { data: bots } = await adminClient.from("bot_instances").select("*").eq("user_id", uid);
      return NextResponse.json({
        authenticated: true,
        user_id: uid,
        email: prof?.email || null,
        username: prof?.username || "Commander",
        avatar_url: prof?.avatar_url || null,
        is_guest: false,
        bots: (bots || []).map((b: any) => ({
          id: b.id,
          bot_id: b.bot_id || b.id,
          name: b.name,
          product: b.product,
          slots: b.slots || 5,
          status: b.status || "active",
          tier: b.tier || "pro",
        }))
      });
    } catch {
      return NextResponse.json({
        authenticated: true,
        user_id: uid,
        bots: []
      });
    }
  }
  
  // Maintenance check and Ban check
  const uidHeader = req.headers.get("x-user-id")?.trim();
  const isActionEndpoint = [
    "/bot/start",
    "/bot/toggle",
    "/bot/run-now",
    "/transfer",
    "/cycle",
    "/combat",
    "/accounts/sync",
  ].some((act) => targetPath.includes(act));

  if (uidHeader || isActionEndpoint) {
    try {
      const { createAdminClient } = await import("@/lib/supabase/admin");
      const adminClient = createAdminClient();

      if (uidHeader) {
        const { data: prof } = await adminClient
          .from("profiles")
          .select("is_banned")
          .eq("id", uidHeader)
          .maybeSingle();

        if (prof?.is_banned) {
          return NextResponse.json(
            {
              error: "تم حظر هذا الحساب من استخدام المنصة من قبل الإدارة.",
              detail: "تم حظر هذا الحساب من استخدام المنصة من قبل الإدارة.",
              banned: true,
            },
            { status: 403 }
          );
        }
      }

      if (isActionEndpoint) {
        const { data: maint } = await adminClient
          .from("system_settings")
          .select("value")
          .eq("key", "maintenance_mode")
          .maybeSingle();

        if (maint?.value?.enabled) {
          const isOwner = uidHeader === "0b13598d-6a29-4e16-8ad3-b937824294e9";
          if (!isOwner) {
            return NextResponse.json(
              {
                error: maint.value.message || "لقد تم إطفاء السيرفر للصيانة من قبل الإدارة",
                detail: maint.value.message || "لقد تم إطفاء السيرفر للصيانة من قبل الإدارة",
                maintenance: true,
              },
              { status: 503 }
            );
          }
        }
      }
    } catch {
      /* pass */
    }
  }

  // Guarantee user_id in query parameters to satisfy FastAPI endpoints expecting user_id: str = Query(...)
  const urlObj = new URL(`${EC2_HOST}${targetPath}`);
  req.nextUrl.searchParams.forEach((val, key) => {
    urlObj.searchParams.set(key, val);
  });
  if (!urlObj.searchParams.has("user_id")) {
    const uid = req.headers.get("x-user-id")?.trim();
    if (uid && uid !== "undefined" && uid !== "null") {
      urlObj.searchParams.set("user_id", uid);
    }
  }
  const targetUrl = urlObj.toString();

  const headers = new Headers();
  // Pass required stealth auth headers to EC2 Nginx & FastAPI
  headers.set("X-Bot-Secret", BOT_SECRET);
  headers.set("X-API-Key", API_KEY);
  headers.set("Accept", "application/json");

  // Forward client headers
  const forwardHeaderList = ["content-type", "authorization", "x-user-id", "cookie"];
  for (const h of forwardHeaderList) {
    const val = req.headers.get(h);
    if (val) headers.set(h, val);
  }

  let body: any = null;
  if (req.method !== "GET" && req.method !== "HEAD") {
    try {
      body = await req.text();
    } catch {
      body = null;
    }
  }

  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000); // 20s timeout for Lilith auth

    const res = await fetch(targetUrl, {
      method: req.method,
      headers,
      body,
      signal: controller.signal,
      cache: "no-store",
    });

    clearTimeout(timeout);

    const contentType = res.headers.get("content-type") || "";
    const resBody = await res.text();

    return new NextResponse(resBody, {
      status: res.status,
      headers: {
        "content-type": contentType || "application/json",
        "access-control-allow-origin": "*",
      },
    });
  } catch (error: any) {
    console.error(`[BACKEND_PROXY_ERROR] ${req.method} ${targetUrl}:`, error?.message || error);
    return NextResponse.json(
      {
        error: "Backend Service Unavailable",
        detail: error?.name === "AbortError" ? "Request to game backend timed out" : (error?.message || "Failed to connect to EC2 service"),
        target: targetPath,
        running: false,
      },
      { status: 504 }
    );
  }
}

export async function GET(req: NextRequest, ctx: any) {
  return proxyRequest(req, ctx);
}

export async function POST(req: NextRequest, ctx: any) {
  return proxyRequest(req, ctx);
}

export async function PUT(req: NextRequest, ctx: any) {
  return proxyRequest(req, ctx);
}

export async function DELETE(req: NextRequest, ctx: any) {
  return proxyRequest(req, ctx);
}

export async function PATCH(req: NextRequest, ctx: any) {
  return proxyRequest(req, ctx);
}

export async function OPTIONS() {
  return new NextResponse(null, {
    status: 204,
    headers: {
      "access-control-allow-origin": "*",
      "access-control-allow-methods": "GET, POST, PUT, DELETE, PATCH, OPTIONS",
      "access-control-allow-headers": "Content-Type, Authorization, X-Bot-Secret, X-API-Key, X-User-Id",
    },
  });
}
