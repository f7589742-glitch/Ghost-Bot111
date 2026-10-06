import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { createAdminClient, isAdminUser, isOwnerUser } from "@/lib/supabase/admin";

export async function GET() {
  const adminClient = createAdminClient();
  const { data } = await adminClient
    .from("system_settings")
    .select("value")
    .eq("key", "maintenance_mode")
    .maybeSingle();

  const maintenanceData = data?.value || { enabled: false, message: "السيرفر تحت الصيانة" };
  return NextResponse.json({
    maintenance: Boolean(maintenanceData.enabled),
    message: maintenanceData.message || "لقد تم إطفاء السيرفر للصيانة من قبل الإدارة",
  });
}

export async function POST(req: NextRequest) {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();

  if (!user || (!isAdminUser(user) && !isOwnerUser(user))) {
    return NextResponse.json({ error: "Unauthorized access" }, { status: 403 });
  }

  const adminClient = createAdminClient();
  const body = await req.json().catch(() => ({}));
  const enabled = Boolean(body.enabled);
  const message = body.message || (enabled ? "لقد تم إطفاء السيرفر للصيانة من قبل الإدارة" : "");

  const { error } = await adminClient
    .from("system_settings")
    .upsert({
      key: "maintenance_mode",
      value: { enabled, message, updated_by: user.email, updated_at: new Date().toISOString() },
      updated_at: new Date().toISOString(),
    });

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({
    success: true,
    maintenance: enabled,
    message,
  });
}
