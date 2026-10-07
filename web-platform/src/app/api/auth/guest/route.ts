import { NextRequest, NextResponse } from "next/server";

export async function POST(req: NextRequest) {
  const response = NextResponse.json(
    { success: false, error: "Guest mode is disabled. Please sign in with Discord." },
    { status: 403 }
  );
  response.cookies.delete("ghostbot_guest");
  response.cookies.delete("ghostbot_guest_mode");
  return response;
}

export async function GET(req: NextRequest) {
  const url = req.nextUrl.clone();
  url.pathname = "/login";
  url.search = "";
  const response = NextResponse.redirect(url);
  response.cookies.delete("ghostbot_guest");
  response.cookies.delete("ghostbot_guest_mode");
  return response;
}
