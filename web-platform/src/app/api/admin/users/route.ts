import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { createAdminClient, isAdminUser, isOwnerUser } from "@/lib/supabase/admin";

export async function GET() {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();

  if (!user || (!isAdminUser(user) && !isOwnerUser(user))) {
    return NextResponse.json({ error: "Unauthorized access" }, { status: 403 });
  }

  const adminClient = createAdminClient();

  // Fetch all profiles, instances, accounts, characters, and invoices
  const [
    { data: profiles, error: pErr },
    { data: botInstances, error: bErr },
    { data: gameAccounts, error: aErr },
    { data: gameCharacters, error: cErr },
    { data: invoices, error: iErr },
  ] = await Promise.all([
    adminClient.from("profiles").select("*").order("created_at", { ascending: false }),
    adminClient.from("bot_instances").select("*").order("created_at", { ascending: true }),
    adminClient.from("game_accounts").select("id, user_id, email, is_enabled, instance_id"),
    adminClient.from("game_characters").select("id, user_id, account_id, instance_id, role_id, name, is_enabled"),
    adminClient.from("invoices").select("*").order("created_at", { ascending: false }),
  ]);

  if (pErr) {
    return NextResponse.json({ error: pErr.message }, { status: 500 });
  }

  const allProfiles = profiles || [];
  const allInstances = botInstances || [];
  const allAccounts = gameAccounts || [];
  const allCharacters = gameCharacters || [];
  const allInvoices = invoices || [];

  // Group by user
  const usersList = allProfiles.map((p) => {
    const userRooms = allInstances.filter((b) => b.user_id === p.id);
    const userAccs = allAccounts.filter((a) => a.user_id === p.id);
    const userChars = allCharacters.filter((c) => c.user_id === p.id);
    const userInvs = allInvoices.filter((i) => i.user_id === p.id);

    const isOwnerAccount = p.id === "0b13598d-6a29-4e16-8ad3-b937824294e9" || p.discord_id === "775687774417321994";
    return {
      id: p.id,
      username: p.username || "Commander",
      discord_id: p.discord_id || "N/A",
      avatar_url: p.avatar_url || "/ghostbot-logo.png",
      role: isOwnerAccount ? "owner" : "user",
      is_banned: p.is_banned === true,
      created_at: p.created_at,
      rooms: userRooms.map((r) => ({
        id: r.id,
        bot_id: r.bot_id || "bot-1",
        name: r.name || `Bot Unit`,
        status: r.status || "active",
        slots: r.slots || 5,
        created_at: r.created_at,
      })),
      rooms_count: userRooms.length,
      accounts_count: userAccs.length,
      characters_count: userChars.length,
      orders_count: userInvs.length,
    };
  });

  const totalRevenue = allInvoices.reduce((sum, inv) => sum + (Number(inv.amount) || 0), 0);

  return NextResponse.json({
    success: true,
    stats: {
      total_users: allProfiles.length,
      total_rooms: allInstances.length,
      total_accounts: allAccounts.length,
      total_characters: allCharacters.length,
      total_orders: allInvoices.length,
      total_revenue: totalRevenue.toFixed(2),
    },
    users: usersList,
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
  const { action, target_user_id, room_id, ban_status } = body;

  if (action === "delete_room") {
    if (!room_id) {
      return NextResponse.json({ error: "room_id is required" }, { status: 400 });
    }

    // Delete room and cascade delete game accounts and characters linked to it
    await adminClient.from("game_characters").delete().eq("instance_id", room_id);
    await adminClient.from("game_accounts").delete().eq("instance_id", room_id);
    const { error: delErr } = await adminClient.from("bot_instances").delete().eq("id", room_id);

    if (delErr) {
      return NextResponse.json({ error: delErr.message }, { status: 500 });
    }

    return NextResponse.json({ success: true, message: "Room and its data removed successfully." });
  }

  if (action === "toggle_ban") {
    if (!target_user_id) {
      return NextResponse.json({ error: "target_user_id is required" }, { status: 400 });
    }

    const { error: banErr } = await adminClient
      .from("profiles")
      .update({ is_banned: Boolean(ban_status) })
      .eq("id", target_user_id);

    if (banErr) {
      return NextResponse.json({ error: banErr.message }, { status: 500 });
    }

    return NextResponse.json({
      success: true,
      message: `User ${ban_status ? "banned" : "unbanned"} successfully.`,
      is_banned: Boolean(ban_status),
    });
  }

  return NextResponse.json({ error: "Invalid action" }, { status: 400 });
}
