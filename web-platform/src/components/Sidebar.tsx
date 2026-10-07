"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { 
  LayoutDashboard, 
  Trophy, 
  Share2, 
  ShoppingCart, 
  LogOut, 
  Layers, 
  Bot,
  CircleDot,
  User,
  ShieldAlert
} from "lucide-react";

import { useGhostBot } from "@/components/SupabaseProvider";
import { ITEM_FOOD_BASE64 } from "@/lib/gameIconsBase64";

interface TenantData {
  authenticated: boolean;
  user_id: string;
  email: string | null;
  username: string;
  avatar_url: string | null;
  bots: Array<{
    id: string;
    name?: string;
    product?: string;
    slots?: number;
    status?: string;
    tier?: string;
  }>;
}

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, profile, bots: contextBots, clearStore } = useGhostBot();
  const [tenant, setTenant] = useState<TenantData | null>(null);
  const [lang, setLang] = useState<"ar" | "en">("ar");

  useEffect(() => {
    try {
      const saved = localStorage.getItem("ghostbot_lang");
      if (saved === "en" || saved === "ar") setLang(saved);
    } catch {}
  }, []);

  useEffect(() => {
    let isMounted = true;
    async function loadTenant() {
      try {
        const res = await fetch("/api/backend/api/tenant/me");
        if (res.ok) {
          const data = await res.json();
          if (isMounted) setTenant(data);
        }
      } catch (err) {
        console.error("Failed to load tenant identity:", err);
      }
    }
    loadTenant();
    return () => {
      isMounted = false;
    };
  }, [pathname]);

  // If we are on the landing/login page, hide the sidebar
  if (pathname === "/" || pathname === "/login") {
    return null;
  }

  const isAr = lang === "ar";

  const displayBots = (contextBots && contextBots.length > 0)
    ? contextBots
    : ((tenant?.bots && tenant.bots.length > 0)
      ? tenant.bots
      : []);

  const isOwner =
    user?.id === "0b13598d-6a29-4e16-8ad3-b937824294e9" ||
    user?.email?.toLowerCase() === "fm434136@gmail.com" ||
    user?.email?.toLowerCase() === "teez8888@gmail.com" ||
    profile?.role === "owner" ||
    profile?.role === "admin";

  const navLinks = [
    { href: "/dashboard?tab=overview", label: isAr ? "نظرة عامة" : "Overview", icon: LayoutDashboard },
    { href: "/shop", label: isAr ? "المتجر والاشتراكات" : "Shop", icon: ShoppingCart },
    { href: "/profile", label: isAr ? "الملف الشخصي" : "Profile", icon: User },
    ...(isOwner ? [{ href: "/admin", label: isAr ? "👑 لوحة تحكم الأونر" : "👑 Owner Console", icon: ShieldAlert }] : []),
  ];

  async function handleSignOut() {
    if (clearStore) clearStore();
    const { performSignOut } = await import("@/lib/authSignOut");
    await performSignOut("/login");
  }

  const displayName = profile?.username || tenant?.username || (tenant?.email ? tenant.email.split("@")[0] : "Rey PRO");
  const displayEmail = profile?.email || tenant?.email || (isAr ? "معزول وسري" : "Isolated");
  const displayAvatar = profile?.avatar_url || tenant?.avatar_url;
  const userInitial = displayName.charAt(0).toUpperCase();

  return (
    <aside className="w-[240px] shrink-0 h-screen sticky top-0 bg-[#07131f] border-r border-[#00e5ff]/15 flex flex-col justify-between p-4 z-40 select-none overflow-y-auto font-sans">
      <div className="space-y-6">
        {/* Brand / Logo */}
        <Link href="/dashboard?tab=overview" className="flex items-center gap-3 px-2 py-1 group">
          <div className="w-9 h-9 rounded-xl bg-[#0b1b2b] border border-[#00e5ff]/30 p-1 flex items-center justify-center shadow-lg shadow-[#00e5ff]/10 group-hover:border-[#00e5ff]/60 transition-all shrink-0">
            <img src="/ghostbot-logo.png" alt="GhostBot" className="w-7 h-7 object-contain drop-shadow-[0_0_8px_#00e5ff]" />
          </div>
          <div className="flex flex-col leading-tight">
            <span className="text-sm font-black tracking-wider text-white flex items-center gap-1.5">
              <span>GHOSTBOT</span>
              <span className="w-1.5 h-1.5 rounded-full bg-[#00e5ff] animate-pulse"></span>
            </span>
            <span className="text-[9px] font-bold text-[#00e5ff] uppercase tracking-widest">TACTICAL HUD</span>
          </div>
        </Link>

        {/* Navigation */}
        <nav className="space-y-1">
          {navLinks.map((item) => {
            const Icon = item.icon;
            const isActive = pathname === item.href || (item.href.includes("overview") && pathname === "/dashboard");
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-xs font-semibold transition-all ${
                  isActive
                    ? "bg-[#00e5ff]/15 text-[#00e5ff] border border-[#00e5ff]/30 shadow-sm shadow-[#00e5ff]/10"
                    : "text-slate-400 hover:text-slate-200 hover:bg-white/[0.03]"
                }`}
              >
                <Icon className={`w-4 h-4 ${isActive ? "text-[#00e5ff]" : "text-slate-400"}`} />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>

        {/* YOUR BOTS Section (Isolated per tenant) */}
        <div className="space-y-2 pt-2 border-t border-white/[0.05]">
          <div className="flex items-center justify-between px-2">
            <span className="text-[10px] font-black uppercase tracking-widest text-[#00e5ff]/80">
              {isAr ? "الوحدات السحابية" : "YOUR BOTS"}
            </span>
            <span className="text-[9px] px-1.5 py-0.2 bg-[#00e5ff]/10 text-[#00e5ff] rounded font-bold border border-[#00e5ff]/20">
              {displayBots.length}
            </span>
          </div>
          <div className="space-y-1.5">
            {displayBots.length === 0 ? (
              <div className="p-3 rounded-xl bg-white/[0.02] border border-white/[0.05] text-center text-[11px] text-slate-400">
                {isAr ? "لا توجد وحدات نشطة حالياً" : "No active bots yet"}
              </div>
            ) : (
              displayBots.map((b) => {
                const isActive = pathname.startsWith("/bots") || pathname === "/dashboard";
                return (
                  <Link
                    key={b.id}
                    href="/dashboard?tab=live"
                    className={`p-2.5 rounded-xl border transition-all cursor-pointer flex items-center gap-3 ${
                      isActive
                        ? "bg-[#0b2438] border-[#00e5ff]/60 shadow-[0_0_15px_rgba(0,229,255,0.15)] text-white"
                        : "bg-[#081524] border-white/[0.06] hover:border-[#00e5ff]/40 text-slate-300"
                    }`}
                  >
                    <img src={ITEM_FOOD_BASE64} alt="Farm Bot" className="w-6 h-6 object-contain shrink-0 drop-shadow-[0_0_10px_rgba(0,229,255,0.4)]" />
                    <div className="flex flex-col min-w-0 flex-1">
                      <span className="text-xs font-bold truncate text-white">
                        {b.name || `GhostBot #${b.id.slice(-4)}`}
                      </span>
                      <div className="flex items-center gap-1.5 text-[10px] text-slate-400">
                        <span className="text-emerald-400 font-semibold flex items-center gap-1">
                          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
                          <span>{isAr ? "نشط" : "Active"}</span>
                        </span>
                        <span>•</span>
                        <span>{b.slots || 5} {isAr ? "مزارع" : "Farms"}</span>
                      </div>
                    </div>
                  </Link>
                );
              })
            )}
          </div>
        </div>
      </div>

      {/* Bottom Section */}
      <div className="space-y-3 pt-3 border-t border-white/[0.07]">
        {/* Shop Button */}
        <Link
          href="/shop"
          className="w-full flex items-center justify-center gap-2 py-2.5 px-4 rounded-xl bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white font-bold text-xs shadow-lg shadow-cyan-600/20 transition-all cursor-pointer"
        >
          <ShoppingCart className="w-3.5 h-3.5" />
          <span>{isAr ? "المتجر والاشتراكات" : "Store & Plans"}</span>
        </Link>

        {/* Dynamic User Pill */}
        <div className="p-2.5 rounded-xl bg-[#0b1a29] border border-white/[0.06] flex items-center justify-between">
          <div className="flex items-center gap-2.5 min-w-0">
            {displayAvatar ? (
              <img
                src={displayAvatar}
                alt=""
                className="w-7 h-7 rounded-lg object-cover border border-[#00e5ff]/30 shrink-0"
              />
            ) : (
              <div className="w-7 h-7 rounded-lg bg-gradient-to-tr from-cyan-600 to-blue-600 flex items-center justify-center text-white font-black text-xs shrink-0">
                {userInitial}
              </div>
            )}
            <div className="flex flex-col leading-tight min-w-0">
              {Boolean(
                user?.id === "0b13598d-6a29-4e16-8ad3-b937824294e9" ||
                user?.user_metadata?.provider_id === "775687774417321994" ||
                user?.user_metadata?.sub === "775687774417321994" ||
                profile?.discord_id === "775687774417321994"
              ) && (
                <Link
                  href="/admin"
                  title={isAr ? "غرفة قيادة الأونر السرية (Admin Console)" : "Owner Apex Command Console"}
                  className="inline-flex items-center gap-1 text-[9px] font-black text-amber-300 bg-amber-500/15 border border-amber-400/40 rounded px-1.5 py-0.5 mb-1 w-fit hover:bg-amber-500/25 transition-all shadow-[0_0_10px_rgba(245,158,11,0.25)]"
                >
                  <span className="text-[11px]">👑</span>
                  <span>OWNER</span>
                </Link>
              )}
              <span className="text-xs font-bold text-white truncate">
                {displayName}
              </span>
              <span className="text-[10px] text-[#00e5ff] font-medium truncate">
                {displayEmail}
              </span>
            </div>
          </div>
          <button
            onClick={handleSignOut}
            className="text-slate-500 hover:text-rose-400 transition-colors p-1 cursor-pointer shrink-0"
            title={isAr ? "تسجيل الخروج" : "Sign Out"}
          >
            <LogOut className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </aside>
  );
}
