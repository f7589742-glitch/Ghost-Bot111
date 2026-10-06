import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export async function POST(req: NextRequest) {
  let guestId = `guest_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;

  // Try Supabase anonymous sign-in if configured and enabled
  try {
    const supabase = await createClient();
    const { data, error } = await supabase.auth.signInAnonymously();
    if (!error && data?.user) {
      guestId = data.user.id;
    }
  } catch {
    // If anonymous sign-in is disabled in Supabase, the guest session cookie seamlessly operates
  }

  const response = NextResponse.json({
    success: true,
    is_guest: true,
    user_id: guestId,
    username: "Guest Commander (زائر)",
    redirect: "/overview",
  });

  response.cookies.set("ghostbot_guest", guestId, {
    path: "/",
    httpOnly: true,
    sameSite: "lax",
    maxAge: 60 * 60 * 24 * 7, // 7 days
    secure: process.env.NODE_ENV === "production",
  });

  return response;
}

export async function GET(req: NextRequest) {
  let guestId = `guest_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
  try {
    const supabase = await createClient();
    const { data, error } = await supabase.auth.signInAnonymously();
    if (!error && data?.user) {
      guestId = data.user.id;
    }
  } catch {}

  const url = req.nextUrl.clone();
  url.pathname = "/overview";
  url.search = "";

  const response = NextResponse.redirect(url);
  response.cookies.set("ghostbot_guest", guestId, {
    path: "/",
    httpOnly: true,
    sameSite: "lax",
    maxAge: 60 * 60 * 24 * 7,
    secure: process.env.NODE_ENV === "production",
  });
  return response;
}
