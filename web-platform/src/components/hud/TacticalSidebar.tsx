"use client";

import React, { useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import Image from "next/image";
import { type OwnedBot } from "@/lib/store";
import { useGhostBot } from "@/components/SupabaseProvider";
import { supabase } from "@/lib/supabaseClient";

import { useLanguage } from "@/context/LanguageContext";
import { ITEM_FOOD_BASE64, ITEM_GEM_BASE64 } from "@/lib/gameIconsBase64";

interface TacticalSidebarProps {
  bots?: any[];
}

export default function TacticalSidebar({ bots }: TacticalSidebarProps) {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, profile, bots: contextBots, clearStore } = useGhostBot();
  const { lang, toggleLang, t } = useLanguage();

  const currentTab = searchParams?.get("tab") || "overview";
  const currentBotId = searchParams?.get("bot") || "";

  const links = [
    { href: "/dashboard?tab=overview", label: t("overview", "نظرة عامة"), nav: "overview" },
    { href: "/shop", label: t("store", "المتجر والاشتراكات"), nav: "upgrade" },
    { href: "/profile", label: t("profile", "الملف الشخصي"), nav: "profile" },
  ];

  async function handleSignOut() {
    try {
      await supabase.auth.signOut();
      if (clearStore) clearStore();
      router.push("/login");
    } catch {
      window.location.href = "/login";
    }
  }

  // Pure authentic bots only - Prioritize live Supabase bots from context, fall back to props
  const displayBots = (contextBots && Array.isArray(contextBots) && contextBots.length > 0)
    ? contextBots
    : (bots && Array.isArray(bots) ? bots : []);

  return (
    <aside className="sidebar" id="mainSidebar">
      <div>
        {/* 1. Integrated Logo */}
        <div className="sidebar-brand-box">
          <div className="sidebar-logo-emblem">
            <svg>
              <use href="#ghostbot-mascot" />
            </svg>
          </div>
          <div>
            <div className="ghostbot-wordmark">
              <span className="w-ghost">Ghost</span>
              <span className="w-bot">Bot</span>
            </div>
            <span className="brand-sub-caption">YOUR INTELLIGENT AI COMPANION</span>
          </div>
        </div>

        {/* 1.5 Quick Updates Mail & Notifications Bar */}
        <div className="sidebar-quick-comm">
          <button
            className="tactical-icon-btn"
            onClick={() => alert(lang === "ar" ? "بريد التحديثات: تم استقرار الإصدار السيبراني الشامل بنجاح!" : "Updates: Cloud fleet cyber engine is 100% operational!")}
            title={t("updates", "التحديثات")}
          >
            <svg>
              <use href="#icon-cyber-mail" />
            </svg>
            <span>{t("updates", "التحديثات")}</span>
            <span className="unread-counter-badge" id="sideMailBadge">3</span>
          </button>

          <button
            className="tactical-icon-btn"
            onClick={() => alert(lang === "ar" ? "الإشعارات: جميع خدمات الأسطول متصلة وتعمل 100%" : "Alerts: All cloud fleet services are healthy.")}
            title={t("alerts", "الإشعارات")}
          >
            <svg>
              <use href="#icon-cyber-bell" />
            </svg>
            <span>{t("alerts", "الإشعارات")}</span>
            <span className="unread-counter-badge badge-amber" id="sideNotifBadge">2</span>
          </button>
        </div>

        {/* 1.6 Prominent Language Switcher Pill */}
        <div style={{ margin: "10px 0 14px" }}>
          <button
            className="lang-switch-pill"
            style={{ width: "100%", justifyContent: "center" }}
            onClick={toggleLang}
            id="sideLangSwitchBtn"
            title={lang === "ar" ? "Switch interface to English" : "تحويل الواجهة إلى العربية"}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10" />
              <line x1="2" y1="12" x2="22" y2="12" />
              <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
            </svg>
            <span>{lang === "ar" ? "English" : "العربية"}</span>
          </button>
        </div>

        {/* 2. Navigation */}
        <div className="sidebar-section-title">
          <span>{t("main_nav", "القائمة الرئيسية")}</span>
        </div>
        <nav className="sidebar-nav">
          {links.map((link) => {
            const active = pathname === link.href || (link.nav === "overview" && pathname === "/dashboard");
            return (
              <Link
                key={link.href}
                href={link.href}
                onClick={(e) => {
                  e.preventDefault();
                  router.push(link.href);
                }}
                className={`side-link ${active ? "active" : ""}`}
                data-nav={link.nav}
                style={{ cursor: "pointer" }}
              >
                {link.nav === "overview" && (
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <rect x="3" y="3" width="7" height="7" />
                    <rect x="14" y="3" width="7" height="7" />
                    <rect x="14" y="14" width="7" height="7" />
                    <rect x="3" y="14" width="7" height="7" />
                  </svg>
                )}
                {link.nav === "upgrade" && (
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="9" cy="21" r="1" />
                    <circle cx="20" cy="21" r="1" />
                    <path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6" />
                  </svg>
                )}
                {link.nav === "profile" && (
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                    <circle cx="12" cy="7" r="4" />
                  </svg>
                )}
                <span>{link.label}</span>
              </Link>
            );
          })}
        </nav>

        {/* 4. Deployed Units Stack */}
        <div className="sidebar-section-title">
          <span>{t("deployed_units", "الوحدات السحابية")} ({displayBots.length})</span>
          <Link
            href="/shop"
            onClick={(e) => {
              e.preventDefault();
              router.push("/shop");
            }}
            style={{ color: "var(--ghost-cyan)", cursor: "pointer" }}
          >
            {t("add_store", "+ متجر الوحدات")}
          </Link>
        </div>

        <div className="deployed-units-list" id="deployedUnitsList">
          {displayBots.length === 0 ? (
            <div
              style={{
                padding: "14px 10px",
                borderRadius: "10px",
                background: "rgba(0, 229, 255, 0.04)",
                border: "1px dashed rgba(0, 229, 255, 0.22)",
                textAlign: "center",
                margin: "6px 0",
              }}
            >
              <div style={{ fontSize: "11px", fontWeight: 800, color: "var(--ghost-cyan)", marginBottom: "3px" }}>
                {t("no_units_active", "لا توجد غرف بوت مفعلة")}
              </div>
              <div style={{ fontSize: "9.5px", color: "var(--text-secondary)", lineHeight: 1.4, marginBottom: "8px" }}>
                {t("no_units_hint", "قم بطلب رخصة من المتجر لإنشاء غرفتك السحابية المعزولة.")}
              </div>
              <Link
                href="/shop"
                onClick={(e) => {
                  e.preventDefault();
                  router.push("/shop");
                }}
                className="btn-ghost-primary"
                style={{
                  padding: "5px 10px",
                  fontSize: "10.5px",
                  fontWeight: 800,
                  display: "inline-block",
                  borderRadius: "6px",
                  background: "linear-gradient(135deg, rgba(0,229,255,0.2), rgba(0,229,255,0.08))",
                  border: "1px solid rgba(0,229,255,0.4)",
                  color: "#00e5ff",
                  cursor: "pointer",
                }}
              >
                {t("create_first_unit", "تفعيل أول وحدة بوت سحابية ←")}
              </Link>
            </div>
          ) : (
            displayBots.map((bot: any, idx: number) => {
              const botKey = bot.id || bot.bot_id || `bot-${idx}`;
              const isThisBotSelected = pathname === "/dashboard" && currentTab !== "overview" && (currentBotId === bot.id || currentBotId === bot.bot_id);
              const botName = bot.name || bot.label || (lang === "ar" ? "غرفة بوت سحابية" : "Cloud Bot Unit");
              const isGem = bot.product === "gem-bot" || (botName && botName.toLowerCase().includes("gem"));
              const slotsCount = bot.slots || 1;
              const botTier = bot.tier || "PRO";

              return (
                <Link
                  key={botKey}
                  href={`/dashboard?tab=live&bot=${bot.id || bot.bot_id}`}
                  className={`unit-card-mini ${isThisBotSelected ? "selected" : ""}`}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                    <div style={{ width: "28px", height: "28px", borderRadius: "8px", display: "flex", alignItems: "center", justifyContent: "center", background: isGem ? "rgba(255,170,43,0.12)" : "rgba(0,229,255,0.12)", border: `1px solid ${isGem ? "rgba(255,170,43,0.35)" : "rgba(0,229,255,0.35)"}`, flexShrink: 0, overflow: "hidden" }}>
                      <img
                        src={isGem ? ITEM_GEM_BASE64 : ITEM_FOOD_BASE64}
                        alt="Bot"
                        style={{ width: "22px", height: "22px", objectFit: "contain" }}
                      />
                    </div>
                    <div>
                      <div style={{ fontSize: "12px", fontWeight: 800, color: "#fff" }}>{botName}</div>
                      <div style={{ fontSize: "10px", color: "var(--text-secondary)", fontFamily: "'JetBrains Mono', monospace" }}>
                        {slotsCount} {lang === "ar" ? "خانات متزامنة" : "slots"}
                      </div>
                    </div>
                  </div>
                  <span
                    style={{
                      fontSize: "9.5px",
                      fontWeight: 900,
                      padding: "2px 6px",
                      borderRadius: "4px",
                      background: isGem ? "rgba(255,170,43,0.18)" : "rgba(0,229,255,0.18)",
                      color: isGem ? "var(--amber-wait)" : "var(--ghost-cyan)",
                    }}
                  >
                    {botTier.toUpperCase()}
                  </span>
                </Link>
              );
            })
          )}
        </div>
      </div>

      {/* 5. User Profile Bottom Card & Sign Out */}
      <div style={{ marginTop: "auto", paddingTop: "12px" }}>
        <div className="user-profile-bottom-card" id="userProfileBottomCard">
          <button
            className="btn-signout-inline"
            onClick={handleSignOut}
            title={t("sign_out", "تسجيل الخروج")}
          >
            <span>{t("sign_out", "تسجيل خروج")}</span>
            <span style={{ fontSize: "13px", fontWeight: 800, transform: lang === "ar" ? "scaleX(-1)" : "none", display: "inline-block" }}>➔</span>
          </button>

          <div className="user-profile-info-side">
            <div className="user-profile-meta">
              {Boolean(
                profile?.role === "owner" ||
                profile?.role === "admin" ||
                user?.user_metadata?.provider_id === "775687774417321994" ||
                user?.user_metadata?.sub === "775687774417321994" ||
                user?.email?.toLowerCase().includes("rey") ||
                user?.email?.toLowerCase().includes("malek")
              ) && (
                <Link
                  href="/admin"
                  title={lang === "ar" ? "غرفة قيادة الأونر السرية (Admin Console)" : "Owner Apex Command Console"}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "4px",
                    fontSize: "9.5px",
                    fontWeight: 900,
                    color: "#f59e0b",
                    background: "rgba(245,158,11,0.18)",
                    border: "1px solid rgba(245,158,11,0.5)",
                    borderRadius: "6px",
                    padding: "1px 6px",
                    textDecoration: "none",
                    boxShadow: "0 0 12px rgba(245,158,11,0.35)",
                    marginBottom: "3px",
                    width: "fit-content",
                    transition: "all 0.2s ease",
                  }}
                >
                  <span style={{ fontSize: "12px" }}>👑</span>
                  <span>OWNER APEX</span>
                </Link>
              )}
              <div className="user-name-label" id="sidebarProfileName">
                {(() => {
                  const raw = profile?.username || user?.user_metadata?.custom_claims?.global_name || user?.user_metadata?.full_name || user?.user_metadata?.name || "Rey";
                  return raw.includes("علي غيث") || raw.includes("القائد") || raw.toLowerCase().includes("commander") ? "Rey" : raw;
                })()}
              </div>
              <div className="user-tier-badge pro" id="sidebarProfileRankBadge">PRO ★</div>
            </div>
            <div className="user-avatar-wrap">
              <img
                src={profile?.avatar_url || user?.user_metadata?.avatar_url || "/ghostbot-logo.png"}
                className="user-avatar-circle"
                id="sidebarProfileAvatar"
                alt="Avatar"
                onError={(e) => { (e.target as any).src = "/ghostbot-logo.png"; }}
              />
            </div>
          </div>
        </div>

        {/* Subtle Language Controls */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "4px 8px 0", fontSize: "11px" }}>
          <span
            style={{ color: "var(--text-secondary)", cursor: "pointer", fontWeight: 700 }}
            onClick={toggleLang}
          >
            {lang === "ar" ? "English" : "العربية"}
          </span>
          <span style={{ color: "var(--text-secondary)", fontWeight: 700 }}>v2.5 Core</span>
        </div>
      </div>
    </aside>
  );
}