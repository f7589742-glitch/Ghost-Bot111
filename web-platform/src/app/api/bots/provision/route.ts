import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { createAdminClient } from "@/lib/supabase/admin";

export async function POST(req: NextRequest) {
  try {
    const supabase = await createClient();
    const { data: { user }, error: authErr } = await supabase.auth.getUser();

    if (authErr || !user) {
      return NextResponse.json({ error: "Unauthorized: Active user session required" }, { status: 401 });
    }

    const body = await req.json().catch(() => ({}));
    const {
      product = "farm-bot",
      tier = "pro",
      slots = 5,
      duration = 30,
      pay_method = "PayPal / Card",
      amount = "0.00",
      custom_name = "",
    } = body;

    const adminClient = createAdminClient();

    // 1. GLOBAL SEQUENTIAL BOT ID ALLOCATION
    // Query all existing bot instances globally to prevent any ID collision between any users
    const { data: allBots, error: allBotsErr } = await adminClient
      .from("bot_instances")
      .select("bot_id");

    if (allBotsErr) {
      console.error("[provision] Failed to query existing bot instances:", allBotsErr);
      return NextResponse.json({ error: "Failed to query bot fleet database" }, { status: 500 });
    }

    const usedIndices = new Set<number>();
    for (const b of allBots || []) {
      if (b.bot_id && typeof b.bot_id === "string") {
        const m = b.bot_id.match(/^bot-(\d+)$/);
        if (m) {
          usedIndices.add(parseInt(m[1], 10));
        }
      }
    }

    // Sequence starts strictly at 0: bot-0, bot-1, bot-2, bot-3...
    let nextIndex = 0;
    while (usedIndices.has(nextIndex)) {
      nextIndex++;
    }
    const globalBotSlug = `bot-${nextIndex}`;

    // 2. SMART INCREMENTAL NAMING PER USER
    // Count existing active units for this specific user
    const { data: userBots } = await adminClient
      .from("bot_instances")
      .select("id, name")
      .eq("user_id", user.id);

    const userUnitNumber = (userBots?.length || 0) + 1;

    const meta = user.user_metadata || {};
    const rawName =
      meta.custom_claims?.global_name ||
      meta.full_name ||
      meta.name ||
      (user.email ? user.email.split("@")[0] : "Commander");

    const defaultUnitName = `${rawName}'s Farm Bot #${userUnitNumber}`;
    const finalBotName = custom_name && custom_name.trim().length > 0 ? custom_name.trim() : defaultUnitName;

    const expiresAt = new Date(Date.now() + (Number(duration) || 30) * 86400000).toISOString();
    const invoiceNumber = `GB-${Math.floor(10000 + Math.random() * 90000)}`;

    // 3. ATOMIC CREATION IN BOT_INSTANCES
    const { data: newBot, error: insertErr } = await adminClient
      .from("bot_instances")
      .insert({
        user_id: user.id,
        bot_id: globalBotSlug,
        name: finalBotName,
        product: product,
        tier: tier,
        slots: Number(slots) || 5,
        status: "active",
        config: {},
        expires_at: expiresAt,
      })
      .select()
      .single();

    if (insertErr) {
      console.error("[provision] Insert error:", insertErr);
      return NextResponse.json({ error: insertErr.message }, { status: 500 });
    }

    // 4. ATOMIC CREATION IN INVOICES
    await adminClient.from("invoices").insert({
      user_id: user.id,
      bot_instance_id: newBot.id,
      invoice_number: invoiceNumber,
      product_name: finalBotName,
      tier: tier,
      slots: Number(slots) || 5,
      billing_cycle: Number(duration) === 365 ? "yearly" : Number(duration) === 90 ? "quarterly" : "monthly",
      amount: parseFloat(String(amount)) || 0,
      currency: "USD",
      status: "active",
      payment_method: pay_method,
      expires_at: expiresAt,
    });

    return NextResponse.json({
      success: true,
      bot: newBot,
      bot_id: globalBotSlug,
      name: finalBotName,
      invoice_number: invoiceNumber,
    });
  } catch (err: any) {
    console.error("[provision] Internal server error:", err);
    return NextResponse.json({ error: err?.message || "Internal server error" }, { status: 500 });
  }
}
