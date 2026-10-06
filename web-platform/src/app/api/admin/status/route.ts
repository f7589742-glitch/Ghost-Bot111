import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { isAdminUser, isOwnerUser } from "@/lib/supabase/admin";

// Tells the UI whether the signed-in user may open /admin and perform owner operations.
export async function GET() {
  const supabase = await createClient();
  const { data } = await supabase.auth.getUser();
  const user = data.user;
  if (!user) {
    return NextResponse.json({ isAdmin: false, isOwner: false }, { status: 401 });
  }
  const isAdm = isAdminUser(user);
  const isOwn = isOwnerUser(user);
  return NextResponse.json({
    isAdmin: isAdm,
    isOwner: isOwn,
    role: isOwn ? "owner" : isAdm ? "admin" : "user",
    user_id: user.id,
    email: user.email,
  });
}
