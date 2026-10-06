"use client";

import React, { useEffect, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Globe, LogOut } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { getSessionUser } from "@/lib/cloud";
import { type OwnedBot } from "@/lib/store";

interface UserProfileHUDProps {
  bots?: OwnedBot[];
}

export default function UserProfileHUD({ bots = [] }: UserProfileHUDProps) {
  const router = useRouter();
  const [user, setUser] = useState<any>(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/admin/status")
      .then((r) => r.json())
      .then((d) => setIsAdmin(!!d?.isAdmin))
      .catch(() => setIsAdmin(false));
  }, [user]);

  useEffect(() => {
    let live = true;
    getSessionUser().then((u) => {
      if (live) {
        setUser(u);
        setLoading(false);
      }
    });

    const supabase = createClient();
    const { data: authListener } = supabase.auth.onAuthStateChange((_event: any, session: any) => {
      setUser(session?.user ?? null);
      setLoading(false);
    });

    return () => {
      live = false;
      authListener?.subscription.unsubscribe();
    };
  }, []);

  async function handleLogout() {
    try {
      const supabase = createClient();
      await supabase.auth.signOut();
      setUser(null);
      router.push("/login");
    } catch {
      router.push("/login");
    }
  }

  if (loading) {
    return (
      <div className="flex items-center gap-3 animate-pulse">
        <div className="w-9 h-9 rounded-full bg-zinc-800/80" />
        <div className="space-y-1 hidden sm:block">
          <div className="w-16 h-3.5 bg-zinc-800 rounded" />
          <div className="w-10 h-2.5 bg-zinc-800 rounded" />
        </div>
      </div>
    );
  }

  // Calculate membership tier based on bots purchased or pro tier
  const hasPro = bots.some((b) => b.tier === "pro");
  const totalSlots = bots.reduce((sum, b) => sum + (b.slots || 0), 0);
  const tierName = isAdmin
    ? "OWNER / ADMIN"
    : totalSlots > 20 || (hasPro && bots.length > 1)
    ? "VIP Plus"
    : bots.length > 0
    ? "VIP"
    : "Member";

  // If logged in:
  if (user) {
    const avatarUrl =
      user.user_metadata?.avatar_url ||
      user.user_metadata?.picture ||
      "/ghostbot-logo.png";

    const username =
      user.user_metadata?.custom_claims?.global_name ||
      user.user_metadata?.full_name ||
      user.user_metadata?.name ||
      user.email?.split("@")[0] ||
      "Commander";

    return (
      <div className="flex items-center gap-3">
        {/* User Identity Info */}
        <Link href="/profile" className="flex items-center gap-2.5 group" title="Open profile">
          <div className="relative w-9 h-9 rounded-full overflow-hidden border border-zinc-700/80 bg-zinc-900 shadow-[0_0_12px_rgba(99,102,241,0.25)] shrink-0 group-hover:border-emerald-500/60 transition-colors">
            <Image
              src={avatarUrl}
              alt={username}
              width={36}
              height={36}
              unoptimized
              className="object-cover w-full h-full"
            />
          </div>
          <div className="hidden sm:flex flex-col text-left">
            <span className="text-sm font-bold text-white tracking-tight leading-none truncate max-w-[110px] group-hover:text-emerald-300 transition-colors">
              {username}
            </span>
            <span
              className={`text-[11px] font-bold leading-none mt-1 tracking-wider uppercase ${
                isAdmin ? "text-amber-400 drop-shadow-[0_0_8px_rgba(251,191,36,0.4)]" : "text-[#6366f1]"
              }`}
            >
              {tierName}
            </span>
          </div>
        </Link>

        {/* Action Controls: Language & Sign Out */}
        <div className="flex items-center gap-1.5 pl-1 border-l border-zinc-800/80">
          <button
            title="Language / Region"
            className="w-8 h-8 rounded-lg bg-[#12141d]/90 border border-zinc-800/90 hover:border-zinc-700 flex items-center justify-center text-zinc-400 hover:text-white transition-colors"
          >
            <Globe className="w-4 h-4" />
          </button>
          <button
            onClick={handleLogout}
            title="Sign Out"
            className="w-8 h-8 rounded-lg bg-[#12141d]/90 border border-zinc-800/90 hover:border-red-500/40 hover:bg-red-500/10 flex items-center justify-center text-zinc-400 hover:text-red-400 transition-colors"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </div>
    );
  }

  // Fallback if not logged in
  return (
    <div className="flex items-center gap-2">
      <Link
        href="/login"
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[#5865F2] hover:bg-[#4752c4] text-white text-xs font-semibold shadow-[0_0_15px_rgba(88,101,242,0.3)] transition-all"
      >
        <Image src="/images/discord-white.svg" alt="" width={16} height={16} />
        <span>Sign In</span>
      </Link>
    </div>
  );
}

