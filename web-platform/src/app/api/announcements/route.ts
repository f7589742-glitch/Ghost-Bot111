import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

// Public feed of past broadcasts for signed-in users.
export async function GET() {
  try {
    const supabase = await createClient();
    const { data: auth } = await supabase.auth.getUser();
    if (!auth.user) {
      return NextResponse.json({ success: false, error: "Login required" }, { status: 401 });
    }
    let { data, error } = await supabase
      .from("announcements")
      .select("id,title,body,image_url,created_at")
      .order("created_at", { ascending: false })
      .limit(30);

    // If image_url column doesn't exist yet in the database, fall back gracefully
    if (error && (error.message?.includes("image_url") || (error as any).code === "42703")) {
      const fallback = await supabase
        .from("announcements")
        .select("id,title,body,created_at")
        .order("created_at", { ascending: false })
        .limit(30);
      data = fallback.data?.map((a: any) => ({ ...a, image_url: null })) ?? [];
      error = fallback.error;
    }

    if (error) throw error;
    return NextResponse.json({ success: true, announcements: data ?? [] });
  } catch (e: any) {
    const msg = e?.message || "Failed to load announcements";
    const missing =
      /relation .* does not exist|table .*announcements|Could not find the table/i.test(msg);
    return NextResponse.json(
      {
        success: false,
        error: missing
          ? "Announcements table is missing. Run supabase-broadcast.sql in the Supabase SQL editor."
          : msg,
      },
      { status: 500 }
    );
  }
}
