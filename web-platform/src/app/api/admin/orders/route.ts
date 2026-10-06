import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { createAdminClient, isAdminUser, isOwnerUser } from "@/lib/supabase/admin";

export async function GET() {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();

  if (!user || (!isAdminUser(user) && !isOwnerUser(user))) {
    return NextResponse.json({ error: "Unauthorized access" }, { status: 403 });
  }

  const adminClient = createAdminClient();

  const [{ data: invoices, error: invErr }, { data: profiles }] = await Promise.all([
    adminClient.from("invoices").select("*").order("created_at", { ascending: false }),
    adminClient.from("profiles").select("id, username, discord_id, avatar_url"),
  ]);

  if (invErr) {
    return NextResponse.json({ error: invErr.message }, { status: 500 });
  }

  const profileMap = new Map((profiles || []).map((p) => [p.id, p]));

  const ordersList = (invoices || []).map((inv) => {
    const buyer = profileMap.get(inv.user_id);
    return {
      id: inv.id,
      invoice_number: inv.invoice_number || `INV-${inv.id.slice(0, 8)}`,
      user_id: inv.user_id,
      buyer_name: buyer?.username || "Unknown Commander",
      discord_id: buyer?.discord_id || "N/A",
      avatar_url: buyer?.avatar_url || "/ghostbot-logo.png",
      product_name: inv.product_name,
      tier: inv.tier,
      slots: inv.slots || 5,
      amount: String(inv.amount || "0.00"),
      currency: inv.currency || "USD",
      payment_method: inv.payment_method || "Crypto / Cards",
      billing_cycle: inv.billing_cycle || "monthly",
      status: inv.status || "active",
      created_at: inv.created_at,
      expires_at: inv.expires_at,
    };
  });

  return NextResponse.json({
    success: true,
    orders: ordersList,
  });
}
