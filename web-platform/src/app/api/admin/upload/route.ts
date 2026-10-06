import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { createAdminClient, isAdminUser } from "@/lib/supabase/admin";

const MAX_BYTES = 5 * 1024 * 1024;
const ALLOWED_TYPES = ["image/png", "image/jpeg", "image/webp", "image/gif"];
const EXT_BY_TYPE: Record<string, string> = {
  "image/png": "png",
  "image/jpeg": "jpg",
  "image/webp": "webp",
  "image/gif": "gif",
};

// POST multipart/form-data { file } — admin-only upload to the
// public "broadcasts" bucket. Returns { success, url }.
export async function POST(req: NextRequest) {
  const supabase = await createClient();
  const { data: auth } = await supabase.auth.getUser();
  if (!auth.user) {
    return NextResponse.json({ success: false, error: "Login required." }, { status: 401 });
  }
  if (!isAdminUser(auth.user)) {
    return NextResponse.json({ success: false, error: "Owners/admins only." }, { status: 403 });
  }

  let file: File | null = null;
  try {
    const form = await req.formData();
    const v = form.get("file");
    if (v instanceof File) file = v;
  } catch {
    return NextResponse.json({ success: false, error: "Invalid upload." }, { status: 400 });
  }
  if (!file || file.size === 0) {
    return NextResponse.json({ success: false, error: "No file received." }, { status: 400 });
  }
  if (!ALLOWED_TYPES.includes(file.type)) {
    return NextResponse.json(
      { success: false, error: "Only PNG, JPG, WEBP or GIF images are allowed." },
      { status: 400 }
    );
  }
  if (file.size > MAX_BYTES) {
    return NextResponse.json({ success: false, error: "Max image size is 5MB." }, { status: 400 });
  }

  let admin;
  try {
    admin = createAdminClient();
  } catch {
    return NextResponse.json(
      { success: false, error: "SUPABASE_SECRET_KEY is not configured on the server." },
      { status: 500 }
    );
  }

  const ext = EXT_BY_TYPE[file.type] || "png";
  const path = `${auth.user.id}/${crypto.randomUUID()}.${ext}`;
  const bytes = Buffer.from(await file.arrayBuffer());

  // Best-effort bucket creation (idempotent — ignore "already exists")
  await admin.storage.createBucket("broadcasts", { public: true }).catch(() => {});

  const { error: upErr } = await admin.storage
    .from("broadcasts")
    .upload(path, bytes, { contentType: file.type, upsert: false });
  if (upErr) {
    return NextResponse.json({ success: false, error: upErr.message }, { status: 500 });
  }
  const { data } = admin.storage.from("broadcasts").getPublicUrl(path);
  return NextResponse.json({ success: true, url: data.publicUrl });
}
