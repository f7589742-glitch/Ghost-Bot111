import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { createAdminClient, isAdminUser } from "@/lib/supabase/admin";

// POST { title, body, image_url? } — stores a broadcast and emails every user.
// Email delivery needs RESEND_API_KEY; without it the announcement is still
// stored and shown in-app, and the response tells you how to enable email.
export async function POST(req: NextRequest) {
  let title = "";
  let body = "";
  let imageUrl: string | null = null;
  try {
    const parsed = await req.json();
    title = String(parsed?.title || "").trim();
    body = String(parsed?.body || "").trim();
    if (typeof parsed?.image_url === "string" && parsed.image_url.trim()) {
      imageUrl = parsed.image_url.trim();
    }
  } catch {
    return NextResponse.json({ success: false, error: "Invalid JSON body." }, { status: 400 });
  }
  if (!title || !body) {
    return NextResponse.json({ success: false, error: "Title and message are required." }, { status: 400 });
  }
  if (title.length > 120 || body.length > 4000) {
    return NextResponse.json(
      { success: false, error: "Title max 120 chars, message max 4000 chars." },
      { status: 400 }
    );
  }
  // Only images uploaded through our own admin upload route are accepted
  // (prevents malicious/linked content injection).
  if (imageUrl) {
    const base = `${process.env.NEXT_PUBLIC_SUPABASE_URL}/storage/v1/object/public/broadcasts/`;
    if (!imageUrl.startsWith(base) || imageUrl.length > 500) {
      return NextResponse.json({ success: false, error: "Invalid image attachment." }, { status: 400 });
    }
  }

  // Must be signed in
  const supabase = await createClient();
  const { data: auth } = await supabase.auth.getUser();
  const sender = auth.user;
  if (!sender) {
    return NextResponse.json({ success: false, error: "Login required." }, { status: 401 });
  }
  if (!isAdminUser(sender)) {
    return NextResponse.json(
      { success: false, error: "Owners/admins only. Your account is not on the broadcast allowlist." },
      { status: 403 }
    );
  }

  // Store announcement (service key bypasses RLS on purpose)
  let admin;
  try {
    admin = createAdminClient();
  } catch (e: any) {
    return NextResponse.json(
      { success: false, error: "SUPABASE_SECRET_KEY is not configured on the server." },
      { status: 500 }
    );
  }

  let insertPayload: Record<string, any> = { title, body, created_by: sender.id };
  if (imageUrl) insertPayload.image_url = imageUrl;

  let { data: row, error: insertErr } = await admin
    .from("announcements")
    .insert(insertPayload)
    .select("id,created_at")
    .single();

  if (insertErr && (insertErr.message?.includes("image_url") || (insertErr as any).code === "42703")) {
    delete insertPayload.image_url;
    const retry = await admin
      .from("announcements")
      .insert(insertPayload)
      .select("id,created_at")
      .single();
    row = retry.data;
    insertErr = retry.error;
  }

  if (insertErr) {
    const missing = /relation .* does not exist|Could not find the table/i.test(insertErr.message);
    return NextResponse.json(
      {
        success: false,
        error: missing
          ? "Announcements table is missing. Run supabase-broadcast.sql in the Supabase SQL editor."
          : insertErr.message,
      },
      { status: 500 }
    );
  }

  // Collect recipient emails (paginated)
  const emails = new Set<string>();
  let page = 1;
  for (let i = 0; i < 20; i++) {
    const { data, error } = await admin.auth.admin.listUsers({ page, perPage: 100 });
    if (error || !data?.users?.length) break;
    for (const u of data.users) {
      if (u.email) emails.add(u.email);
    }
    if (data.users.length < 100) break;
    page++;
  }
  const recipients = [...emails];

  // Send email if a provider is configured
  const resendKey = (process.env.RESEND_API_KEY || "").trim();
  const from = (process.env.RESEND_FROM || "ZeroBot <updates@localhost>").trim();
  if (!resendKey) {
    return NextResponse.json({
      success: true,
      id: row?.id ?? null,
      emailed: 0,
      recipients: recipients.length,
      emailSkipped: true,
      note: "Saved in-app. To also send email, set RESEND_API_KEY + RESEND_FROM in .env.local and restart.",
    });
  }

  let sent = 0;
  const failures: string[] = [];
  const esc = (s: string) =>
    s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const linkedBody = esc(body).replace(
    /(https?:\/\/[^\s<]+)/g,
    '<a href="$1">$1</a>'
  );
  const htmlBody =
    `<div style="font-family:Arial,sans-serif;max-width:560px">` +
    `<h2>${esc(title)}</h2>` +
    `<p style="white-space:pre-wrap">${linkedBody}</p>` +
    (imageUrl ? `<p><img src="${esc(imageUrl)}" alt="" style="max-width:100%;border-radius:8px" /></p>` : "") +
    `<p style="color:#888">— ZeroBot team (do not reply, this mailbox is not monitored)</p></div>`;
  const textBody = `${body}${imageUrl ? `\n\nImage: ${imageUrl}` : ""}\n\n— ZeroBot team (do not reply)`;
  // Resend batch: one call per recipient keeps failure attribution simple.
  for (const to of recipients) {
    try {
      const res = await fetch("https://api.resend.com/emails", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${resendKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          from,
          to: [to],
          subject: `[ZeroBot] ${title}`,
          text: textBody,
          html: htmlBody,
        }),
      });
      if (res.ok) sent++;
      else failures.push(`${to}: HTTP ${res.status}`);
    } catch (e: any) {
      failures.push(`${to}: ${e?.message || "send failed"}`);
    }
  }

  return NextResponse.json({
    success: true,
    id: row?.id ?? null,
    emailed: sent,
    recipients: recipients.length,
    failed: failures.slice(0, 10),
  });
}
