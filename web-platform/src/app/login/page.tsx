"use client";

import React, { Suspense, useEffect, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ShieldCheck, Cpu, Activity, Lock, Zap, Server, CheckCircle2, Globe } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { getSessionUser } from "@/lib/cloud";
import { useLanguage } from "@/context/LanguageContext";

function LoginInner() {
  const router = useRouter();
  const params = useSearchParams();
  const redirectTo = params.get("redirectTo") || "/dashboard";
  const { lang, dir, toggleLang } = useLanguage();
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);
  const [policyModal, setPolicyModal] = useState<"terms" | "privacy" | null>(null);

  const features = [
    {
      icon: ShieldCheck,
      title: lang === "ar" ? "دخول رسمي ومباشر عبر ديسكورد" : "Official Discord OAuth Access",
      desc: lang === "ar"
        ? "تسجيل دخول فوري بحساب ديسكورد الخاص بك للوصول إلى مزارعك بكل سهولة وأمان تام."
        : "Instant 1-click authentication with your Discord account for secure and seamless fleet access.",
    },
    {
      icon: Cpu,
      title: lang === "ar" ? "إدارة مزارعك ووحداتك السحابية" : "Autonomous Cloud Fleet Management",
      desc: lang === "ar"
        ? "تشغيل ومتابعة جميع حساباتك وجيوشك من شاشة واحدة دون الحاجة لتشغيل جهازك أو فتح محاكيات."
        : "Deploy and oversee all your accounts, marches, and gatherers without running local emulators or PC.",
    },
    {
      icon: Activity,
      title: lang === "ar" ? "متابعة حية للحصاد والتحالف" : "Live Gathering & Alliance Telemetry",
      desc: lang === "ar"
        ? "عرض لحظي ومباشر لجمع الموارد وتدريب القوات ومساعدات التحالف بدقة تامة وعلى مدار الساعة."
        : "Real-time telemetry showing RSS gathering, speedup allocation, troop training, and alliance assist.",
    },
  ];

  useEffect(() => {
    let urlErr = params.get("error");
    let desc = params.get("error_description") || "";
    if (!urlErr && typeof window !== "undefined" && window.location.hash.includes("error=")) {
      const frag = new URLSearchParams(window.location.hash.slice(1));
      urlErr = frag.get("error");
      desc = frag.get("error_description") || "";
    }
    if (urlErr) {
      setErr(
        desc
          ? `عفواً، فشل تسجيل الدخول: ${desc.replace(/\+/g, " ")}`
          : `عفواً، حدث خطأ أثناء الاتصال: ${urlErr}`
      );
      window.history.replaceState(null, "", window.location.pathname);
    }
  }, [params]);

  useEffect(() => {
    let live = true;
    const isSignedOut = params.get("signedOut") === "1";
    if (isSignedOut) {
      try {
        const supabase = createClient();
        supabase.auth.signOut({ scope: "local" }).catch(() => {});
        if (typeof window !== "undefined") {
          Object.keys(localStorage).forEach((k) => {
            if (k.startsWith("sb-") || k.startsWith("ghostbot_")) {
              localStorage.removeItem(k);
            }
          });
          document.cookie = "ghostbot_user_profile=; path=/; max-age=0";
          document.cookie = "ghostbot_guest=; path=/; max-age=0";
        }
      } catch {}
      return () => {
        live = false;
      };
    }

    getSessionUser().then((u: any) => {
      if (!live || !u || u.is_anonymous) return;
      router.replace(redirectTo);
    }).catch(() => {});
    return () => {
      live = false;
    };
  }, [router, redirectTo, params]);

  async function handleDiscordLogin() {
    try {
      setErr("");
      setLoading(true);
      const supabase = createClient();
      const { error } = await supabase.auth.signInWithOAuth({
        provider: "discord",
        options: {
          redirectTo: `${window.location.origin}/auth/callback`,
          scopes: "identify email",
        },
      });
      if (error) setErr(error.message);
    } catch (e: any) {
      setErr(e?.message || "فشل بدء الاتصال بديسكورد / Failed to initiate Discord login");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      className="min-h-screen w-full flex items-center justify-center p-4 sm:p-6 lg:p-10 relative overflow-hidden"
      dir={dir}
      style={{
        background: "radial-gradient(circle at 50% 40%, rgba(6, 18, 38, 0.75) 0%, rgba(3, 8, 18, 0.94) 85%)",
      }}
    >
      {/* Background Ambient Glows */}
      <div
        className="fixed inset-0 z-0 pointer-events-none"
        style={{
          background:
            "radial-gradient(circle at 20% 30%, rgba(0, 229, 255, 0.08) 0%, transparent 50%), radial-gradient(circle at 80% 70%, rgba(168, 85, 247, 0.08) 0%, transparent 50%)",
        }}
      />

      {/* MASTER UNIFIED COMMAND CENTER CARD */}
      <div
        className="w-full max-w-5xl rounded-3xl relative z-10 my-auto overflow-hidden"
        style={{
          background: "rgba(5, 14, 30, 0.82)",
          backdropFilter: "blur(24px)",
          border: "1.5px solid rgba(0, 229, 255, 0.28)",
          boxShadow: "0 25px 60px rgba(0, 0, 0, 0.75), 0 0 40px rgba(0, 229, 255, 0.12)",
        }}
      >
        {/* TOP COCKPIT STATUS BAR */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "12px 24px",
            borderBottom: "1px solid rgba(0, 229, 255, 0.18)",
            background: "rgba(3, 9, 20, 0.6)",
            flexWrap: "wrap",
            gap: "10px",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <span
              style={{
                width: "8px",
                height: "8px",
                borderRadius: "50%",
                background: "#00e699",
                boxShadow: "0 0 10px #00e699",
              }}
            />
            <span style={{ fontSize: "11px", fontFamily: "'JetBrains Mono', monospace", color: "var(--ghost-cyan)", fontWeight: 800, letterSpacing: "1.5px" }}>
              GHOSTBOT v2.5 • AUTONOMOUS FLEET TERMINAL
            </span>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: "14px", fontSize: "11px", color: "var(--text-secondary)" }}>
            <span style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
              <Server style={{ width: "13px", height: "13px", color: "var(--ghost-cyan)" }} />
              <span style={{ color: "#fff", fontWeight: 700 }}>Frankfurt DC (22ms)</span>
            </span>
            <span style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
              <Lock style={{ width: "13px", height: "13px", color: "#00e699" }} />
              <span style={{ color: "#00e699", fontWeight: 800 }}>Zero Data Leak</span>
            </span>

            {/* Language Switcher Pill */}
            <button
              type="button"
              onClick={toggleLang}
              className="btn-ghost-outline"
              style={{
                padding: "3px 10px",
                fontSize: "10.5px",
                fontWeight: 900,
                borderRadius: "20px",
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: "5px",
                borderColor: "rgba(0,229,255,0.4)",
                color: "var(--ghost-cyan)",
                background: "rgba(0,229,255,0.08)",
              }}
            >
              <Globe style={{ width: "12px", height: "12px" }} />
              <span>{lang === "ar" ? "English" : "العربية"}</span>
            </button>
          </div>
        </div>

        {/* MAIN DUAL CHAMBER GRID */}
        <div className="grid grid-cols-1 lg:grid-cols-12 items-stretch">
          
          {/* AUTHENTICATION ACTION PORTAL */}
          <div
            className="lg:col-span-5 p-8 sm:p-10 flex flex-col justify-between text-center relative"
            style={{
              background: "rgba(4, 11, 25, 0.5)",
              borderInlineEnd: "1px solid rgba(0, 229, 255, 0.14)",
            }}
          >
            <div>
              {/* Animated Hologram Logo Center */}
              <div className="relative mx-auto mb-6 flex items-center justify-center" style={{ width: "100px", height: "100px" }}>
                <div
                  className="absolute inset-0 rounded-full"
                  style={{
                    background: "radial-gradient(circle, rgba(0, 229, 255, 0.25) 0%, transparent 70%)",
                    animation: "pulse 3s infinite",
                  }}
                />
                <div
                  style={{
                    width: "84px",
                    height: "84px",
                    borderRadius: "22px",
                    background: "linear-gradient(135deg, rgba(0, 229, 255, 0.15) 0%, rgba(88, 101, 242, 0.25) 100%)",
                    border: "2px solid #00e5ff",
                    boxShadow: "0 0 25px rgba(0, 229, 255, 0.4)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    padding: "8px",
                  }}
                >
                  <Image
                    src="/ghostbot-logo.png"
                    alt="GhostBot"
                    width={62}
                    height={62}
                    unoptimized
                    priority
                    style={{ objectFit: "contain", filter: "drop-shadow(0 0 10px rgba(0,229,255,0.7))" }}
                  />
                </div>
              </div>

              {/* Header Title */}
              <h1 style={{ fontSize: "24px", fontWeight: 900, color: "#fff", marginBottom: "6px" }}>
                {lang === "ar" ? "مرحباً بك في GhostBot" : "Welcome to GhostBot"}
              </h1>
              <p style={{ fontSize: "12.5px", color: "var(--text-secondary)", lineHeight: "1.6", maxWidth: "340px", margin: "0 auto 26px" }}>
                {lang === "ar"
                  ? "بوابتك الرسمية لإدارة مزارعك الذكية والتحكم في جيوشك ومواردك بكل راحة واطمئنان"
                  : "Your official command terminal to operate smart cloud farms, marches, and RSS nodes effortlessly."}
              </p>

              {/* Action Buttons Box */}
              <div className="space-y-3.5 max-w-sm mx-auto">
                {/* 1. DISCORD LOGIN BUTTON (PRIMARY) */}
                <button
                  type="button"
                  onClick={handleDiscordLogin}
                  disabled={loading}
                  style={{
                    width: "100%",
                    padding: "14px 20px",
                    borderRadius: "14px",
                    fontWeight: 800,
                    fontSize: "13.5px",
                    background: "linear-gradient(135deg, #5865F2 0%, #4752c4 100%)",
                    color: "#fff",
                    border: "none",
                    boxShadow: "0 4px 25px rgba(88, 101, 242, 0.45)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    gap: "12px",
                    cursor: "pointer",
                    transition: "all 0.25s ease",
                  }}
                  className="hover:scale-[1.015] active:scale-[0.98]"
                >
                  <svg style={{ width: "22px", height: "22px", fill: "currentColor" }} viewBox="0 0 24 24">
                    <path d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028c.462-.63.874-1.295 1.226-1.994.021-.041.001-.09-.041-.106a13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.929 1.793 8.18 1.793 12.061 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.893.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.028zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z"/>
                  </svg>
                  <span>
                    {loading
                      ? (lang === "ar" ? "جارٍ الاتصال بديسكورد..." : "Connecting to Discord...")
                      : (lang === "ar" ? "تسجيل الدخول عبر ديسكورد" : "Continue with Discord")}
                  </span>
                </button>

                {/* 2. GUEST LOGIN BUTTON (LOCAL DEMO) */}
                <button
                  type="button"
                  onClick={() => {
                    try {
                      setLoading(true);
                      if (typeof window !== "undefined") {
                        document.cookie = "ghostbot_guest=1; path=/; max-age=86400";
                        localStorage.setItem("ghostbot_guest_mode", "true");
                        localStorage.setItem(
                          "ghostbot_user_profile",
                          JSON.stringify({
                            id: "guest-commander",
                            username: "Rey",
                            avatar_url: "/ghostbot-logo.png",
                            email: "rey@ghostbot.local",
                            is_guest: true,
                          })
                        );
                        window.location.href = "/dashboard?tab=overview";
                      }
                    } finally {
                      setLoading(false);
                    }
                  }}
                  disabled={loading}
                  style={{
                    width: "100%",
                    padding: "12px 18px",
                    borderRadius: "14px",
                    fontWeight: 800,
                    fontSize: "12.5px",
                    background: "rgba(0, 229, 255, 0.08)",
                    border: "1.5px solid rgba(0, 229, 255, 0.4)",
                    color: "var(--ghost-cyan)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    gap: "10px",
                    cursor: "pointer",
                    transition: "all 0.25s ease",
                  }}
                  className="hover:bg-[rgba(0,229,255,0.16)] hover:border-[#00e5ff] hover:scale-[1.01]"
                >
                  <Zap style={{ width: "16px", height: "16px" }} />
                  <span>{lang === "ar" ? "دخول فوري كزائر (تجربة سريعة)" : "Instant Guest Demo Access"}</span>
                </button>

                {/* Security Guarantee Pill */}
                <div
                  style={{
                    padding: "10px 14px",
                    borderRadius: "12px",
                    background: "rgba(0, 230, 153, 0.06)",
                    border: "1px solid rgba(0, 230, 153, 0.25)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    gap: "8px",
                    fontSize: "11px",
                    fontWeight: 700,
                    color: "#00e699",
                  }}
                >
                  <CheckCircle2 style={{ width: "15px", height: "15px", flexShrink: 0 }} />
                  <span>
                    {lang === "ar"
                      ? "حسابك محفوظ ومحمي بالكامل مع مزامنة فورية لصورتك واسمك"
                      : "Zero credentials leaked. Secure OAuth syncs your Discord tag and avatar."}
                  </span>
                </div>
              </div>

              {err && (
                <div
                  style={{
                    marginTop: "14px",
                    padding: "10px 14px",
                    borderRadius: "12px",
                    background: "rgba(244, 63, 94, 0.15)",
                    border: "1px solid rgba(244, 63, 94, 0.4)",
                    fontSize: "11.5px",
                    color: "#fecdd3",
                    maxWidth: "380px",
                    margin: "14px auto 0",
                  }}
                >
                  {err}
                </div>
              )}
            </div>

            {/* Terms & Privacy Links Footer */}
            <div style={{ marginTop: "24px", paddingTop: "14px", borderTop: "1px solid rgba(255, 255, 255, 0.08)" }}>
              <p style={{ fontSize: "11px", color: "var(--text-secondary)" }}>
                {lang === "ar" ? "بتسجيل دخولك، فإنك توافق على " : "By signing in, you agree to our "}
                <button
                  type="button"
                  onClick={() => setPolicyModal("terms")}
                  style={{ background: "transparent", border: "none", color: "var(--ghost-cyan)", fontWeight: 800, cursor: "pointer", padding: 0 }}
                >
                  {lang === "ar" ? "شروط الخدمة" : "Terms of Service"}
                </button>
                {lang === "ar" ? " و " : " & "}
                <button
                  type="button"
                  onClick={() => setPolicyModal("privacy")}
                  style={{ background: "transparent", border: "none", color: "var(--ghost-cyan)", fontWeight: 800, cursor: "pointer", padding: 0 }}
                >
                  {lang === "ar" ? "سياسة الخصوصية" : "Privacy Policy"}
                </button>
              </p>
            </div>
          </div>

          {/* PLATFORM SHOWCASE & TELEMETRY */}
          <div
            className="lg:col-span-7 p-8 sm:p-10 flex flex-col justify-between"
            style={{
              background: "rgba(5, 14, 30, 0.35)",
            }}
          >
            <div>
              {/* Badge */}
              <div
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "8px",
                  padding: "4px 14px",
                  borderRadius: "20px",
                  background: "rgba(0, 229, 255, 0.12)",
                  border: "1px solid rgba(0, 229, 255, 0.35)",
                  color: "var(--ghost-cyan)",
                  fontSize: "11px",
                  fontWeight: 900,
                  marginBottom: "14px",
                }}
              >
                <span style={{ width: "6px", height: "6px", borderRadius: "50%", background: "var(--ghost-cyan)", boxShadow: "0 0 6px var(--ghost-cyan)" }} />
                <span>{lang === "ar" ? "المنصة السحابية الأولى لممالك RoK" : "Premier Autonomous Cloud Platform for RoK"}</span>
              </div>

              {/* Main Heading */}
              <h2 style={{ fontSize: "24px", fontWeight: 900, color: "#fff", lineHeight: "1.4", marginBottom: "8px" }}>
                {lang === "ar"
                  ? "أفضل مساعد سحابي ذكي لإدارة ممالك ومزارع Rise of Kingdoms"
                  : "Next-Generation Autonomous Assistant for Rise of Kingdoms"}
              </h2>

              {/* Subheading */}
              <p style={{ fontSize: "12.5px", color: "var(--text-secondary)", lineHeight: "1.65", marginBottom: "22px" }}>
                {lang === "ar"
                  ? "تحكم كامل وذاتي في جمع الموارد، تدريب القوات، والتبرع للتحالف بكل سلاسة وموثوقية عالية دون الحاجة لتشغيل جهازك."
                  : "Effortless 24/7 automation for resource gathering, tech research, speedups, and troop drills without keeping your PC powered."}
              </p>

              {/* Feature Cards Grid */}
              <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                {features.map((feat) => {
                  const IconComponent = feat.icon;
                  return (
                    <div
                      key={feat.title}
                      style={{
                        display: "flex",
                        alignItems: "flex-start",
                        gap: "14px",
                        padding: "14px 16px",
                        borderRadius: "14px",
                        background: "rgba(4, 11, 24, 0.75)",
                        border: "1px solid rgba(0, 229, 255, 0.18)",
                        transition: "all 0.2s ease",
                      }}
                    >
                      <div
                        style={{
                          width: "38px",
                          height: "38px",
                          borderRadius: "10px",
                          background: "rgba(0, 229, 255, 0.12)",
                          border: "1.5px solid rgba(0, 229, 255, 0.35)",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          color: "var(--ghost-cyan)",
                          flexShrink: 0,
                          marginTop: "2px",
                        }}
                      >
                        <IconComponent style={{ width: "18px", height: "18px" }} />
                      </div>
                      <div>
                        <h3 style={{ fontSize: "13.5px", fontWeight: 800, color: "#fff", marginBottom: "2px" }}>
                          {feat.title}
                        </h3>
                        <p style={{ fontSize: "11.5px", color: "var(--text-secondary)", lineHeight: "1.55" }}>
                          {feat.desc}
                        </p>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Bottom Platform Metrics Banner */}
            <div
              style={{
                marginTop: "24px",
                paddingTop: "14px",
                borderTop: "1px solid rgba(255, 255, 255, 0.08)",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                fontSize: "11.5px",
                color: "var(--text-secondary)",
                flexWrap: "wrap",
                gap: "8px",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                <span>{lang === "ar" ? "مزارع نشطة:" : "Active Nodes:"} <strong style={{ color: "var(--ghost-cyan)" }}>1,280+</strong></span>
                <span>•</span>
                <span>{lang === "ar" ? "الجاهزية:" : "Uptime:"} <strong style={{ color: "#00e699" }}>99.98%</strong></span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "6px", color: "#00e699", fontWeight: 800 }}>
                <span style={{ width: "7px", height: "7px", borderRadius: "50%", background: "#00e699", boxShadow: "0 0 8px #00e699" }} />
                <span>{lang === "ar" ? "خدمة مستمرة 24/7 دون انقطاع" : "24/7 Uninterrupted Service"}</span>
              </div>
            </div>
          </div>

        </div>
      </div>

      {/* QUICK POLICY MODAL */}
      {policyModal && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 100,
            background: "rgba(2, 6, 15, 0.85)",
            backdropFilter: "blur(12px)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "20px",
          }}
          onClick={() => setPolicyModal(null)}
        >
          <div
            className="surface-card"
            style={{
              maxWidth: "520px",
              width: "100%",
              padding: "26px",
              borderRadius: "18px",
              border: "1.5px solid var(--ghost-cyan)",
              boxShadow: "0 0 35px rgba(0, 229, 255, 0.3)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "14px" }}>
              <h3 style={{ fontSize: "16px", fontWeight: 900, color: "#fff" }}>
                {policyModal === "terms"
                  ? (lang === "ar" ? "📜 شروط الخدمة والاستخدام" : "📜 Terms of Service")
                  : (lang === "ar" ? "🔒 سياسة الخصوصية وحماية البيانات" : "🔒 Privacy & Data Protection")}
              </h3>
              <button
                type="button"
                className="util-btn"
                style={{ width: "30px", height: "30px", borderRadius: "50%", cursor: "pointer" }}
                onClick={() => setPolicyModal(null)}
              >
                ✕
              </button>
            </div>
            <div style={{ fontSize: "12px", color: "var(--text-ice)", lineHeight: "1.7" }}>
              {policyModal === "terms" ? (
                <p>
                  {lang === "ar"
                    ? "منصة GhostBot تقدم بيئة استضافة سحابية خاصة لتشغيل وإدارة مزارع Rise of Kingdoms. باستخدامك للمنصة، فإنك توافق على الالتزام بالقوانين وحماية ترخيص حسابك الشخصي."
                    : "GhostBot provides isolated cloud infrastructure to operate Rise of Kingdoms instances. By using the platform, you agree to fair use and maintain security of your credentials."}
                </p>
              ) : (
                <p>
                  {lang === "ar"
                    ? "نحن نضمن تشفير بياناتك بالكامل (TLS 1.3 و Row Level Security). لا يتم مشاركة أو تسريب أي بصمات أو كلمات مرور مع أي جهة خارجية نهائياً."
                    : "We enforce end-to-end TLS 1.3 and Supabase Row Level Security. No credentials or hardware fingerprints are ever leaked or shared with 3rd parties."}
                </p>
              )}
            </div>
            <div style={{ marginTop: "18px", display: "flex", justifyContent: "flex-end" }}>
              <button
                type="button"
                className="btn-cyan-glow"
                style={{ padding: "6px 18px", fontSize: "12px", cursor: "pointer" }}
                onClick={() => setPolicyModal(null)}
              >
                {lang === "ar" ? "حسناً، فهمت" : "Understood"}
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginInner />
    </Suspense>
  );
}
