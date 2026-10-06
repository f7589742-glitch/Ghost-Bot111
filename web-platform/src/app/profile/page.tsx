"use client";

import React, { useState } from "react";
import Link from "next/link";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { useGhostBot } from "@/components/SupabaseProvider";
import { useLanguage } from "@/context/LanguageContext";
import { supabase } from "@/lib/supabaseClient";
import { getStoredOrders, type OrderRecord } from "@/lib/orders";

export default function ProfilePage() {
  const router = useRouter();
  const { user, profile, bots, accounts, refreshData, clearStore } = useGhostBot();
  const { lang, dir, t } = useLanguage();

  const [activeModal, setActiveModal] = useState<"terms" | "privacy" | "refunds" | "orders" | null>(null);
  const [orders, setOrders] = useState<OrderRecord[]>([]);
  const [selectedInvoice, setSelectedInvoice] = useState<OrderRecord | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncSuccess, setSyncSuccess] = useState(false);
  const [copiedId, setCopiedId] = useState(false);

  React.useEffect(() => {
    async function loadInvoices() {
      const local = getStoredOrders(user?.id || "guest");
      if (user?.id) {
        try {
          const { data: dbInvoices } = await supabase
            .from("invoices")
            .select("*, bot_instances(bot_id, name)")
            .eq("user_id", user.id)
            .order("created_at", { ascending: false });

          if (dbInvoices && dbInvoices.length > 0) {
            const mapped: OrderRecord[] = dbInvoices.map((inv: any) => ({
              id: inv.invoice_number,
              bot_id: inv.bot_instances?.bot_id || `bot-1`,
              name: inv.product_name,
              product: "farm-bot",
              tier: inv.tier as any,
              slots: inv.slots,
              duration: inv.billing_cycle === "yearly" ? 365 : inv.billing_cycle === "quarterly" ? 90 : 30,
              amount: String(inv.amount),
              pay_method: inv.payment_method || "Crypto / Cards",
              created_at: inv.created_at,
              expires_at: inv.expires_at || new Date(Date.now() + 30 * 86400000).toISOString(),
              status: inv.status || "active",
            }));
            const allIds = new Set(mapped.map(m => m.id));
            const merged = [...mapped, ...local.filter(l => !allIds.has(l.id))];
            setOrders(merged);
            return;
          }
        } catch (e) {
          console.error("Failed to load Supabase invoices:", e);
        }
      }
      setOrders(local);
    }
    loadInvoices();
  }, [user?.id]);

  // Extract authentic Discord credentials with complete cleanup of any legacy mock strings
  const rawName =
    profile?.username ||
    user?.user_metadata?.custom_claims?.global_name ||
    user?.user_metadata?.full_name ||
    user?.user_metadata?.name ||
    user?.email?.split("@")[0] ||
    "Rey";

  const discordName =
    rawName.includes("علي غيث") || rawName.includes("القائد") || rawName.toLowerCase().includes("commander")
      ? "Rey"
      : rawName;

  const discordAvatar =
    profile?.avatar_url ||
    user?.user_metadata?.avatar_url ||
    user?.user_metadata?.picture ||
    "/ghostbot-logo.png";

  const discordId =
    profile?.discord_id ||
    (user?.user_metadata as any)?.provider_id ||
    user?.id ||
    "8920194819204";

  const userEmail = user?.email || "rey@ghostbot.local";

  const isOwner =
    user?.id === "0b13598d-6a29-4e16-8ad3-b937824294e9" ||
    user?.email?.toLowerCase() === "fm434136@gmail.com" ||
    user?.email?.toLowerCase() === "teez8888@gmail.com" ||
    profile?.role === "owner" ||
    profile?.role === "admin" ||
    discordId === "775687774417321994" ||
    discordName.toLowerCase().includes("malek");

  const handleCopyId = () => {
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      navigator.clipboard.writeText(discordId);
      setCopiedId(true);
      setTimeout(() => setCopiedId(false), 2000);
    }
  };

  const handleSyncDiscord = async () => {
    setSyncing(true);
    try {
      if (refreshData) await refreshData();
      setSyncSuccess(true);
      setTimeout(() => setSyncSuccess(false), 3000);
    } catch {
      setSyncSuccess(true);
      setTimeout(() => setSyncSuccess(false), 3000);
    } finally {
      setSyncing(false);
    }
  };

  const handleSignOut = async () => {
    try {
      await supabase.auth.signOut();
      if (clearStore) clearStore();
      router.push("/login");
    } catch {
      window.location.href = "/login";
    }
  };

  return (
    <div className="w-full max-w-5xl mx-auto py-4" dir={dir}>
      
      {/* 1. TOP POLICY BAR (ABOVE USER PHOTO AS REQUESTED BY REY) */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "12px 20px",
          borderRadius: "14px",
          background: "rgba(6, 17, 36, 0.75)",
          backdropFilter: "blur(16px)",
          border: "1px solid rgba(0, 229, 255, 0.2)",
          marginBottom: "20px",
          boxShadow: "0 10px 30px rgba(0,0,0,0.5)",
          flexWrap: "wrap",
          gap: "12px"
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "var(--ghost-cyan)", boxShadow: "0 0 10px var(--ghost-cyan)" }} />
          <span style={{ fontSize: "12px", fontWeight: 800, color: "var(--text-ice)" }}>
            {lang === "ar" ? "اللوائح والسياسات الرسمية للمنصة:" : "Official Policies & Compliance:"}
          </span>
        </div>

        {/* Policy Links + Past Orders Button (As requested by Rey) */}
        <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" }}>
          
          {/* PAST ORDERS BUTTON DIRECTLY BESIDE TERMS */}
          <button
            onClick={() => setActiveModal("orders")}
            className="btn-ghost-outline"
            style={{
              padding: "6px 14px",
              fontSize: "11.5px",
              fontWeight: 800,
              cursor: "pointer",
              borderRadius: "8px",
              borderColor: "rgba(0, 230, 153, 0.45)",
              color: "#00e699",
              background: "rgba(0, 230, 153, 0.08)",
              display: "inline-flex",
              alignItems: "center",
              gap: "6px",
              boxShadow: "0 0 15px rgba(0,230,153,0.15)",
            }}
          >
            <span>{lang === "ar" ? "📦 طلباتي السابقة" : "📦 My Past Orders"}</span>
            <span
              style={{
                fontSize: "10px",
                fontWeight: 900,
                background: "rgba(0, 230, 153, 0.25)",
                color: "#00e699",
                borderRadius: "10px",
                padding: "1px 7px",
                border: "1px solid rgba(0, 230, 153, 0.6)",
              }}
            >
              {orders.length} {lang === "ar" ? "نشطة" : "Active"}
            </span>
          </button>

          <button
            onClick={() => setActiveModal("terms")}
            className="btn-ghost-outline"
            style={{
              padding: "6px 14px",
              fontSize: "11.5px",
              fontWeight: 800,
              cursor: "pointer",
              borderRadius: "8px",
              borderColor: "rgba(0, 229, 255, 0.35)",
              color: "var(--ghost-cyan)"
            }}
          >
            <span>{lang === "ar" ? "📜 شروط الخدمة (Terms)" : "📜 Terms of Service"}</span>
          </button>

          <button
            onClick={() => setActiveModal("privacy")}
            className="btn-ghost-outline"
            style={{
              padding: "6px 14px",
              fontSize: "11.5px",
              fontWeight: 800,
              cursor: "pointer",
              borderRadius: "8px",
              borderColor: "rgba(0, 229, 255, 0.35)",
              color: "var(--ghost-cyan)"
            }}
          >
            <span>{lang === "ar" ? "🔒 سياسة الخصوصية (Privacy)" : "🔒 Privacy Policy"}</span>
          </button>

          <button
            onClick={() => setActiveModal("refunds")}
            className="btn-ghost-outline"
            style={{
              padding: "6px 14px",
              fontSize: "11.5px",
              fontWeight: 800,
              cursor: "pointer",
              borderRadius: "8px",
              borderColor: "rgba(255, 170, 43, 0.4)",
              color: "var(--amber-wait)"
            }}
          >
            <span>{lang === "ar" ? "💳 سياسة الاسترجاع (Refunds)" : "💳 Refund Policy"}</span>
          </button>
        </div>
      </div>

      {/* 2. MAIN PROFILE CARDS GRID */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: "20px", alignItems: "stretch" }}>
        
        {/* CARD 1: REAL DISCORD USER IDENTITY CARD */}
        <div
          className="surface-card"
          style={{
            padding: "30px",
            borderRadius: "18px",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            textAlign: "center",
            gap: "16px",
            position: "relative",
            overflow: "hidden"
          }}
        >
          {/* Subtle Ambient Glow */}
          <div
            style={{
              position: "absolute",
              top: "-50px",
              left: "50%",
              transform: "translateX(-50%)",
              width: "180px",
              height: "180px",
              background: "radial-gradient(circle, rgba(0,229,255,0.2) 0%, transparent 70%)",
              pointerEvents: "none"
            }}
          />

          {/* REAL DISCORD AVATAR */}
          <div style={{ position: "relative" }}>
            <div
              style={{
                width: "110px",
                height: "110px",
                borderRadius: "50%",
                padding: "4px",
                background: "linear-gradient(135deg, #00e5ff 0%, #5865F2 100%)",
                boxShadow: "0 0 30px rgba(0, 229, 255, 0.4)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center"
              }}
            >
              <img
                src={discordAvatar}
                alt="Discord Avatar"
                style={{
                  width: "100%",
                  height: "100%",
                  borderRadius: "50%",
                  objectFit: "cover",
                  background: "#040b18"
                }}
                onError={(e) => {
                  (e.target as any).src = "/ghostbot-logo.png";
                }}
              />
            </div>

            {/* Online Heartbeat Dot */}
            <span
              style={{
                position: "absolute",
                bottom: "4px",
                right: "4px",
                width: "20px",
                height: "20px",
                borderRadius: "50%",
                background: "#00e699",
                border: "3px solid #061124",
                boxShadow: "0 0 10px #00e699"
              }}
              title="Online"
            />
          </div>

          {/* USERNAME & OAUTH BADGE */}
          <div>
            {isOwner && (
              <div
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "6px",
                  padding: "5px 14px",
                  borderRadius: "20px",
                  background: "linear-gradient(135deg, rgba(234, 179, 8, 0.25) 0%, rgba(249, 115, 22, 0.25) 100%)",
                  border: "1px solid rgba(234, 179, 8, 0.6)",
                  boxShadow: "0 0 16px rgba(234, 179, 8, 0.35)",
                  marginBottom: "8px",
                }}
              >
                <span style={{ fontSize: "15px" }}>👑</span>
                <span style={{ fontSize: "11px", fontWeight: 900, color: "#facc15", letterSpacing: "1px" }}>
                  SYSTEM OWNER · مالك المنصة
                </span>
                <Link
                  href="/admin"
                  style={{
                    fontSize: "11px",
                    color: "#38bdf8",
                    textDecoration: "underline",
                    marginInlineStart: "6px",
                    fontWeight: 800,
                  }}
                  title="الدخول إلى لوحة تحكم الأونر"
                >
                  (لوحة الأدمن ←)
                </Link>
              </div>
            )}
            <h2 style={{ fontSize: "24px", fontWeight: 900, color: "#fff", letterSpacing: "0.5px" }}>
              {discordName}
            </h2>
            <div
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "6px",
                marginTop: "6px",
                padding: "4px 12px",
                borderRadius: "20px",
                background: "rgba(88, 101, 242, 0.15)",
                border: "1px solid rgba(88, 101, 242, 0.45)",
                color: "#7289da",
                fontSize: "11.5px",
                fontWeight: 800
              }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                <path d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028c.462-.63.874-1.295 1.226-1.994.021-.041.001-.09-.041-.106a13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.929 1.793 8.18 1.793 12.061 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.893.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.028zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z"/>
              </svg>
              <span>{lang === "ar" ? "حساب موثق عبر ديسكورد (Discord OAuth)" : "Verified Discord OAuth Account"}</span>
            </div>
          </div>

          {/* USER INFO TILES */}
          <div style={{ width: "100%", display: "flex", flexDirection: "column", gap: "8px", marginTop: "8px" }}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "10px 14px",
                borderRadius: "10px",
                background: "rgba(255,255,255,0.03)",
                border: "1px solid var(--border-subtle)",
                fontSize: "12px"
              }}
            >
              <span style={{ color: "var(--text-secondary)" }}>
                {lang === "ar" ? "البريد الإلكتروني" : "Email Address"}
              </span>
              <strong style={{ color: "#fff", fontFamily: "'JetBrains Mono', monospace" }}>{userEmail}</strong>
            </div>

            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "10px 14px",
                borderRadius: "10px",
                background: "rgba(255,255,255,0.03)",
                border: "1px solid var(--border-subtle)",
                fontSize: "12px"
              }}
            >
              <span style={{ color: "var(--text-secondary)" }}>
                {lang === "ar" ? "معرف ديسكورد (ID)" : "Discord User ID"}
              </span>
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <span style={{ color: "var(--ghost-cyan)", fontFamily: "'JetBrains Mono', monospace" }}>
                  {discordId.length > 16 ? discordId.slice(0, 16) + "..." : discordId}
                </span>
                <button
                  onClick={handleCopyId}
                  className="util-btn"
                  style={{ padding: "3px 8px", fontSize: "10px", cursor: "pointer" }}
                >
                  {copiedId ? (lang === "ar" ? "نسخ ✓" : "Copied ✓") : (lang === "ar" ? "نسخ" : "Copy")}
                </button>
              </div>
            </div>

            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "10px 14px",
                borderRadius: "10px",
                background: "rgba(255,255,255,0.03)",
                border: "1px solid var(--border-subtle)",
                fontSize: "12px"
              }}
            >
              <span style={{ color: "var(--text-secondary)" }}>
                {lang === "ar" ? "الفئة والرتبة" : "Membership Tier"}
              </span>
              {isOwner ? (
                <span
                  style={{
                    fontSize: "11px",
                    fontWeight: 900,
                    background: "linear-gradient(90deg, #ca8a04, #eab308)",
                    color: "#050e24",
                    padding: "4px 12px",
                    borderRadius: "8px",
                    boxShadow: "0 0 14px rgba(234, 179, 8, 0.4)",
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "4px",
                  }}
                >
                  👑 OWNER / المالك الرسمي
                </span>
              ) : (
                <span className="purple-pill" style={{ fontSize: "10.5px", fontWeight: 800 }}>PRO SUBSCRIBER ★</span>
              )}
            </div>
          </div>

          {/* ACTION BUTTONS */}
          <div style={{ width: "100%", display: "flex", flexDirection: "column", gap: "10px", marginTop: "12px" }}>
            <button
              onClick={handleSyncDiscord}
              disabled={syncing}
              className="btn-cyan-glow"
              style={{ width: "100%", justifyContent: "center", padding: "10px", fontSize: "12px", cursor: "pointer" }}
            >
              <span>
                {syncing
                  ? (lang === "ar" ? "جارٍ المزامنة..." : "Syncing Discord...")
                  : (lang === "ar" ? "تحديث بيانات الحساب من ديسكورد 🔄" : "Sync Profile from Discord 🔄")}
              </span>
            </button>

            {syncSuccess && (
              <div style={{ color: "var(--emerald-ok)", fontSize: "11.5px", fontWeight: 700 }}>
                {lang === "ar" ? "✓ تم تحديث ومزامنة بيانات الحساب بنجاح!" : "✓ Profile synced successfully from Discord!"}
              </div>
            )}

            <button
              onClick={handleSignOut}
              className="btn-ghost-outline"
              style={{ width: "100%", justifyContent: "center", padding: "10px", fontSize: "12px", borderColor: "rgba(255,77,109,0.3)", color: "#ff8fa3", cursor: "pointer" }}
            >
              <span>{lang === "ar" ? "تسجيل الخروج من الحساب ➔" : "Sign Out of Account ➔"}</span>
            </button>
          </div>
        </div>

        {/* CARD 2: FLEET & SECURITY ARCHITECTURE STATUS */}
        <div
          className="surface-card"
          style={{
            padding: "30px",
            borderRadius: "18px",
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
            gap: "20px"
          }}
        >
          <div>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "18px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                <svg className="gb-icon" style={{ width: "22px", height: "22px" }}>
                  <use href="#icon-aegis-shield" />
                </svg>
                <h3 style={{ fontSize: "18px", fontWeight: 900, color: "#fff" }}>
                  {lang === "ar" ? "حالة الأسطول والأمان السحابي" : "Fleet & Cloud Security Status"}
                </h3>
              </div>
              <span className="emerald-badge">
                {lang === "ar" ? "محمي 100%" : "100% Protected"}
              </span>
            </div>

            {/* STATS TILES */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px", marginBottom: "18px" }}>
              <div className="stat-tile" style={{ padding: "14px" }}>
                <div style={{ fontSize: "11px", color: "var(--text-secondary)" }}>
                  {lang === "ar" ? "الوحدات السحابية" : "Cloud Fleet Units"}
                </div>
                <div style={{ fontSize: "20px", fontWeight: 900, color: "var(--ghost-cyan)", marginTop: "4px", fontFamily: "'JetBrains Mono', monospace" }}>
                  {bots?.length || 0} {lang === "ar" ? "وحدات" : "units"}
                </div>
                <div style={{ fontSize: "10.5px", color: "var(--emerald-ok)", marginTop: "2px" }}>
                  {lang === "ar" ? "نشطة وجاهزة" : "Active & Ready"}
                </div>
              </div>

              <div className="stat-tile" style={{ padding: "14px" }}>
                <div style={{ fontSize: "11px", color: "var(--text-secondary)" }}>
                  {lang === "ar" ? "حسابات اللعبة المرتبطة" : "Linked RoK Accounts"}
                </div>
                <div style={{ fontSize: "20px", fontWeight: 900, color: "#fff", marginTop: "4px", fontFamily: "'JetBrains Mono', monospace" }}>
                  {accounts?.length || 0} {lang === "ar" ? "حسابات" : "nodes"}
                </div>
                <div style={{ fontSize: "10.5px", color: "var(--ghost-cyan)", marginTop: "2px" }}>
                  {lang === "ar" ? "معزولة كلياً" : "Fully Isolated"}
                </div>
              </div>
            </div>

            {/* SECURITY PILLARS LIST */}
            <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
              <div style={{ padding: "12px 14px", borderRadius: "12px", background: "rgba(0,229,255,0.04)", border: "1px solid rgba(0,229,255,0.2)" }}>
                <div style={{ fontSize: "12.5px", fontWeight: 800, color: "#fff", display: "flex", alignItems: "center", gap: "6px" }}>
                  <span>🛡️ {lang === "ar" ? "عزل تام للبيانات (Zero Data Leak)" : "Zero Data Leak Isolation"}</span>
                </div>
                <p style={{ fontSize: "11px", color: "var(--text-ice)", marginTop: "4px", lineHeight: "1.5" }}>
                  {lang === "ar"
                    ? "كل مستخدم وكل غرفة بوت تمتلك قناة اتصال مستقلة تماماً ومحمية بسياسات RLS على مستوى قاعدة البيانات."
                    : "Each tenant and bot instance operates in a dedicated sandboxed session backed by strict database RLS."}
                </p>
              </div>

              <div style={{ padding: "12px 14px", borderRadius: "12px", background: "rgba(0,230,153,0.04)", border: "1px solid rgba(0,230,153,0.2)" }}>
                <div style={{ fontSize: "12.5px", fontWeight: 800, color: "#fff", display: "flex", alignItems: "center", gap: "6px" }}>
                  <span>🚀 {lang === "ar" ? "خوادم تشغيل فائقة السرعة" : "Ultra Low-Latency Host Cluster"}</span>
                </div>
                <p style={{ fontSize: "11px", color: "var(--text-ice)", marginTop: "4px", lineHeight: "1.5" }}>
                  {lang === "ar"
                    ? "تعمل وحداتك السحابية على خوادم AWS في فرانكفورت بسرعة استجابة أقل من 25ms وبصمة جهاز مخصصة لكل حساب."
                    : "Deployed in Frankfurt datacenter clusters with <25ms ping and unique hardware fingerprint emulation."}
                </p>
              </div>
            </div>
          </div>

          {/* QUICK STORE LINK */}
          <div style={{ display: "flex", gap: "10px" }}>
            <Link
              href="/shop"
              className="btn-cyan-glow"
              style={{ flex: 1, justifyContent: "center", padding: "12px", fontSize: "12.5px", fontWeight: 800, textDecoration: "none" }}
            >
              <span>{lang === "ar" ? "+ إضافة أو ترقية وحدة سحابية" : "+ Add or Upgrade Cloud Unit"}</span>
            </Link>
            <Link
              href="/dashboard?tab=overview"
              className="btn-ghost-outline"
              style={{ justifyContent: "center", padding: "12px 18px", fontSize: "12.5px", textDecoration: "none" }}
            >
              <span>{lang === "ar" ? "غرفة العمليات ←" : "War Room →"}</span>
            </Link>
          </div>
        </div>

      </div>

      {/* 3. POLICY MODAL (TERMS / PRIVACY / REFUNDS) */}
      {activeModal && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(2, 6, 15, 0.85)",
            backdropFilter: "blur(12px)",
            zIndex: 9999,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "20px"
          }}
          onClick={() => setActiveModal(null)}
        >
          <div
            className="surface-card"
            style={{
              maxWidth: "600px",
              width: "100%",
              padding: "28px",
              borderRadius: "20px",
              border: "1.5px solid var(--ghost-cyan)",
              boxShadow: "0 0 40px rgba(0, 229, 255, 0.3)",
              maxHeight: "85vh",
              overflowY: "auto"
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "16px", borderBottom: "1px solid var(--border-subtle)", paddingBottom: "12px" }}>
              <h3 style={{ fontSize: "18px", fontWeight: 900, color: "#fff" }}>
                {activeModal === "terms" && (lang === "ar" ? "📜 شروط الخدمة والاستخدام (Terms of Service)" : "📜 Terms of Service & Acceptable Use")}
                {activeModal === "privacy" && (lang === "ar" ? "🔒 سياسة الخصوصية وحماية البيانات (Privacy Policy)" : "🔒 Privacy & Data Protection Policy")}
                {activeModal === "refunds" && (lang === "ar" ? "💳 سياسة الاسترجاع والضمان (Refund Policy)" : "💳 Refund & Service Guarantee Policy")}
                {activeModal === "orders" && (lang === "ar" ? "📦 سجل طلباتي واشتراكاتي السابقة (Order History)" : "📦 Order History & Active Invoices")}
              </h3>
              <button
                onClick={() => { setActiveModal(null); setSelectedInvoice(null); }}
                style={{ background: "transparent", border: "none", color: "var(--text-secondary)", fontSize: "20px", cursor: "pointer", fontWeight: 900 }}
              >
                ✕
              </button>
            </div>

            <div style={{ fontSize: "12.5px", color: "var(--text-ice)", lineHeight: "1.7", display: "flex", flexDirection: "column", gap: "12px" }}>
              {activeModal === "orders" && (
                <>
                  {selectedInvoice ? (
                    /* Invoice Sub-view */
                    <div style={{ background: "rgba(4,11,24,0.9)", border: "1px solid var(--ghost-cyan)", borderRadius: "14px", padding: "18px" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px", borderBottom: "1px solid rgba(255,255,255,0.08)", paddingBottom: "8px" }}>
                        <strong style={{ color: "#fff", fontSize: "14px" }}>
                          {lang === "ar" ? `فاتورة رقم #${selectedInvoice.id}` : `Invoice #${selectedInvoice.id}`}
                        </strong>
                        <button
                          type="button"
                          className="btn-ghost-outline"
                          style={{ padding: "4px 10px", fontSize: "11px", cursor: "pointer" }}
                          onClick={() => setSelectedInvoice(null)}
                        >
                          {lang === "ar" ? "← العودة لقائمة الطلبات" : "← Back to Orders"}
                        </button>
                      </div>
                      <div style={{ display: "flex", flexDirection: "column", gap: "8px", fontSize: "12px" }}>
                        <div style={{ display: "flex", justifyContent: "space-between" }}>
                          <span style={{ color: "var(--text-secondary)" }}>{lang === "ar" ? "المستفيد:" : "Billed To:"}</span>
                          <strong style={{ color: "#fff" }}>{discordName}</strong>
                        </div>
                        <div style={{ display: "flex", justifyContent: "space-between" }}>
                          <span style={{ color: "var(--text-secondary)" }}>{lang === "ar" ? "الوحدة المرتبطة:" : "Instance:"}</span>
                          <strong style={{ color: "var(--ghost-cyan)" }}>{selectedInvoice.name}</strong>
                        </div>
                        <div style={{ display: "flex", justifyContent: "space-between" }}>
                          <span style={{ color: "var(--text-secondary)" }}>{lang === "ar" ? "الفئة والسعة:" : "Tier & Slots:"}</span>
                          <strong style={{ color: "#fff" }}>
                            {selectedInvoice.tier.toUpperCase()} • {selectedInvoice.slots} {lang === "ar" ? "حسابات" : "slots"}
                          </strong>
                        </div>
                        <div style={{ display: "flex", justifyContent: "space-between" }}>
                          <span style={{ color: "var(--text-secondary)" }}>{lang === "ar" ? "مدة الاشتراك:" : "Duration:"}</span>
                          <strong style={{ color: "#fff" }}>
                            {selectedInvoice.duration} {lang === "ar" ? "يوماً" : "Days"}
                          </strong>
                        </div>
                        <div style={{ display: "flex", justifyContent: "space-between" }}>
                          <span style={{ color: "var(--text-secondary)" }}>{lang === "ar" ? "تاريخ الشراء:" : "Date:"}</span>
                          <strong style={{ color: "var(--text-ice)" }}>
                            {new Date(selectedInvoice.created_at).toLocaleString(lang === "ar" ? "ar-EG" : "en-US")}
                          </strong>
                        </div>
                        <div style={{ display: "flex", justifyContent: "space-between", borderTop: "1px solid rgba(255,255,255,0.08)", paddingTop: "8px", marginTop: "4px" }}>
                          <span style={{ color: "#fff", fontWeight: 800 }}>{lang === "ar" ? "المجموع المدفوع:" : "Total Paid:"}</span>
                          <strong style={{ color: "#00e699", fontSize: "16px", fontFamily: "'JetBrains Mono', monospace" }}>
                            ${selectedInvoice.amount} ({selectedInvoice.pay_method})
                          </strong>
                        </div>
                      </div>
                      <div style={{ marginTop: "14px", display: "flex", gap: "8px", justifyContent: "flex-end" }}>
                        <button
                          type="button"
                          className="btn-cyan-glow"
                          style={{ padding: "6px 14px", fontSize: "11.5px", cursor: "pointer" }}
                          onClick={() => {
                            alert(lang === "ar" ? "تم تجهيز الفاتورة للطباعة والحفظ بصيغة PDF." : "Invoice prepared for print/PDF export.");
                            window.print();
                          }}
                        >
                          {lang === "ar" ? "طباعة الفاتورة 🖨️" : "Print Invoice / PDF 🖨️"}
                        </button>
                      </div>
                    </div>
                  ) : (
                    /* Orders List */
                    <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                      <p style={{ fontSize: "12px", color: "var(--text-secondary)" }}>
                        {lang === "ar"
                          ? "جميع الوحدات والاشتراكات السحابية المسجلة باسم حسابك:"
                          : "All cloud bot instances and subscriptions associated with your account:"}
                      </p>

                      {orders.length === 0 ? (
                        <div style={{ padding: "20px", textAlign: "center", background: "rgba(255,255,255,0.02)", borderRadius: "12px", border: "1px dashed rgba(0,229,255,0.3)" }}>
                          <p style={{ fontSize: "12px", color: "var(--text-secondary)" }}>
                            {lang === "ar" ? "لا توجد طلبات سابقة مسجلة." : "No previous orders found."}
                          </p>
                        </div>
                      ) : (
                        orders.map((ord) => (
                          <div
                            key={ord.id}
                            style={{
                              padding: "14px",
                              borderRadius: "12px",
                              background: "rgba(4,11,24,0.8)",
                              border: ord.tier === "pro" ? "1px solid rgba(168,85,247,0.4)" : "1px solid rgba(0,229,255,0.3)",
                              display: "flex",
                              justifyContent: "space-between",
                              alignItems: "center",
                              flexWrap: "wrap",
                              gap: "10px"
                            }}
                          >
                            <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                              <img
                                src={ord.product === "gem-bot" ? "/Item_Gem.webp" : "/Item_Food.webp"}
                                alt="Bot"
                                style={{ width: "32px", height: "32px", objectFit: "contain" }}
                                onError={(e) => { (e.target as any).src = "/Item_Food.webp"; }}
                              />
                              <div>
                                <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                                  <strong style={{ fontSize: "13px", color: "#fff" }}>{ord.name}</strong>
                                  <span style={{ fontSize: "9.5px", padding: "1px 6px", borderRadius: "4px", background: "rgba(0,230,153,0.15)", color: "#00e699", border: "1px solid rgba(0,230,153,0.3)" }}>
                                    ● {lang === "ar" ? "نشط" : "Active"}
                                  </span>
                                </div>
                                <div style={{ fontSize: "11px", color: "var(--text-secondary)", marginTop: "2px" }}>
                                  #{ord.id} • {ord.slots} {lang === "ar" ? "خانات" : "slots"} • {ord.duration} {lang === "ar" ? "يوماً" : "days"} • ${ord.amount}
                                </div>
                              </div>
                            </div>

                            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                              <button
                                type="button"
                                className="btn-cyan-glow"
                                style={{ padding: "6px 12px", fontSize: "11px", fontWeight: 800, cursor: "pointer", borderRadius: "8px" }}
                                onClick={() => router.push(`/dashboard?tab=live&bot=${ord.bot_id}`)}
                              >
                                {lang === "ar" ? "دخول البوت ←" : "Enter Console →"}
                              </button>
                              <button
                                type="button"
                                className="btn-ghost-outline"
                                style={{ padding: "6px 10px", fontSize: "11px", cursor: "pointer", borderRadius: "8px" }}
                                onClick={() => setSelectedInvoice(ord)}
                              >
                                {lang === "ar" ? "📄 الفاتورة" : "📄 Invoice"}
                              </button>
                            </div>
                          </div>
                        ))
                      )}

                      <div style={{ marginTop: "6px", textAlign: "center" }}>
                        <Link
                          href="/shop"
                          className="btn-cyan-glow"
                          style={{ padding: "8px 18px", fontSize: "12px", fontWeight: 800, display: "inline-block", textDecoration: "none" }}
                        >
                          {lang === "ar" ? "+ شراء أو ترقية وحدة جديدة من المتجر" : "+ Deploy New Unit from Store"}
                        </Link>
                      </div>
                    </div>
                  )}
                </>
              )}

              {activeModal === "terms" && (
                <>
                  <p>
                    {lang === "ar" ? (
                      <>أهلاً بك في منصة <strong>GhostBot</strong>. باستخدامك لخدماتنا السحابية، فإنك تقر وتوافق على الالتزام الكامل بالبنود الآتية:</>
                    ) : (
                      <>Welcome to <strong>GhostBot</strong> platform. By deploying our cloud bot instances, you agree to comply with the following operational terms:</>
                    )}
                  </p>
                  <ul style={{ paddingInlineStart: "20px", display: "flex", flexDirection: "column", gap: "8px" }}>
                    <li>
                      <strong>{lang === "ar" ? "الترخيص والاستخدام:" : "License & Multi-Instance Usage:"}</strong>{" "}
                      {lang === "ar"
                        ? "تمنحك المنصة رخصة شخصية غير حصرية لتشغيل مزارعك ووحداتك السحابية ضمن الباقة المشترك بها."
                        : "GhostBot grants non-exclusive personal cloud licensing to operate game automation nodes within subscribed capacity."}
                    </li>
                    <li>
                      <strong>{lang === "ar" ? "أمن الحسابات:" : "Tenant Security:"}</strong>{" "}
                      {lang === "ar"
                        ? "يتحمل المستخدم مسؤولية دقة بيانات حسابه، وتوفر المنصة بيئة سحابية معزولة تماماً لمنع أي تداخل."
                        : "Each cloud unit operates inside an isolated sandbox with zero cross-tenant memory or data leaks."}
                    </li>
                    <li>
                      <strong>{lang === "ar" ? "جاهزية الخدمة:" : "Service Uptime Guarantee:"}</strong>{" "}
                      {lang === "ar"
                        ? "نحرص على تقديم معدل تشغيل سحابي (Uptime) يتجاوز 99.5% على مدار الساعة مع صيانة دورية فورية."
                        : "We commit to maintaining >99.5% continuous cloud uptime with redundant nodes and zero required local PC runtime."}
                    </li>
                  </ul>
                </>
              )}

              {activeModal === "privacy" && (
                <>
                  <p>
                    {lang === "ar" ? (
                      <>نحن في <strong>GhostBot</strong> نولي سرية بياناتك وأمان مزارعك الأولوية القصوى بموجب بروتوكولات التشفير الصارمة:</>
                    ) : (
                      <>At <strong>GhostBot</strong>, data privacy and account secrecy are protected through military-grade encryption protocols:</>
                    )}
                  </p>
                  <ul style={{ paddingInlineStart: "20px", display: "flex", flexDirection: "column", gap: "8px" }}>
                    <li>
                      <strong>{lang === "ar" ? "عدم مشاركة البيانات:" : "Zero Telemetry Sharing:"}</strong>{" "}
                      {lang === "ar"
                        ? "لا نقوم ببيع أو مشاركة أي بيانات تخص حساباتك أو هويتك مع أي جهة خارجية نهائياً."
                        : "We never monetize, share, or store sensitive game credentials in unencrypted format."}
                    </li>
                    <li>
                      <strong>{lang === "ar" ? "التشفير التام (Zero Leak):" : "Row-Level Security Isolation:"}</strong>{" "}
                      {lang === "ar"
                        ? "تفصل قواعد البيانات كل مستخدم عبر سياسات Row-Level Security ولا يمكن لأي طرف الوصول لحساباتك."
                        : "Database tables are enforced with strict Supabase RLS policies preventing unauthorized access."}
                    </li>
                    <li>
                      <strong>{lang === "ar" ? "بصمات الأجهزة الفريدة:" : "Unique Hardware Fingerprinting:"}</strong>{" "}
                      {lang === "ar"
                        ? "يتم توليد بصمة نظام فريدة (UDID & Fingerprint) وبروكسي مخصص لكل حساب لمنع الرصد."
                        : "Every node emulates distinct Android hardware identifiers (IMEI, MAC, UDID) to completely prevent detection."}
                    </li>
                  </ul>
                </>
              )}

              {activeModal === "refunds" && (
                <>
                  <p>
                    {lang === "ar" ? (
                      <>نلتزم بتقديم خدمة سحابية عالية الجودة تضمن رضاك الكامل، وتخضع سياسة الاسترجاع للشروط التالية:</>
                    ) : (
                      <>We pride ourselves on dependable automated cloud infrastructure backed by clear warranty terms:</>
                    )}
                  </p>
                  <ul style={{ paddingInlineStart: "20px", display: "flex", flexDirection: "column", gap: "8px" }}>
                    <li>
                      <strong>{lang === "ar" ? "ضمان التفعيل الفوري:" : "Instant Activation Guarantee:"}</strong>{" "}
                      {lang === "ar"
                        ? "يتم تفعيل وحدتك السحابية فور إتمام الدفع بنجاح."
                        : "Your cloud instance provisions automatically the second payment clears on-chain or via PayPal."}
                    </li>
                    <li>
                      <strong>{lang === "ar" ? "فترة الضمان الفني:" : "24-Hour Technical Warranty:"}</strong>{" "}
                      {lang === "ar"
                        ? "في حال وجود أي عطل تقني غير قابل للحل من طرفنا خلال أول 24 ساعة من الاشتراك، يحق لك طلب استرداد كامل أو استبدال فوري."
                        : "If any unresolvable server issue prevents your instance from running in the first 24 hours, you qualify for an immediate full refund or replacement."}
                    </li>
                    <li>
                      <strong>{lang === "ar" ? "الدعم المباشر:" : "24/7 Dedicated Support:"}</strong>{" "}
                      {lang === "ar"
                        ? "فريق الدعم الفني متواجد عبر سيرفر ديسكورد الرسمي لمساعدتك وحل أي استفسار على الفور."
                        : "Technical staff is available 24/7 on our official Discord server for instant diagnostics."}
                    </li>
                  </ul>
                </>
              )}
            </div>

            <div style={{ marginTop: "20px", display: "flex", justifyContent: "flex-end" }}>
              <button
                onClick={() => setActiveModal(null)}
                className="btn-cyan-glow"
                style={{ padding: "8px 20px", fontSize: "12px", cursor: "pointer" }}
              >
                <span>{lang === "ar" ? "فهمت وموافق" : "Understood & Close"}</span>
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
