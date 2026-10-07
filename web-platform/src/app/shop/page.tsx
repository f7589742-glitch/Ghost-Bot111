"use client";

import React, { useState, useEffect } from "react";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useGhostBot } from "@/components/SupabaseProvider";
import { supabase } from "@/lib/supabaseClient";
import { saveNewOrder, type OrderRecord } from "@/lib/orders";
import { useLanguage } from "@/context/LanguageContext";
import { ITEM_FOOD_BASE64, ITEM_GEM_BASE64, BUILDER_ICON_BASE64 } from "@/lib/gameIconsBase64";

export default function ShopPage() {
  const router = useRouter();
  const { user, profile, bots, refreshData } = useGhostBot();
  const { lang, dir, toggleLang, t } = useLanguage();

  // Mode: "checkout" | "catalog"
  const [viewMode, setViewMode] = useState<"checkout" | "catalog">("checkout");
  const [selectedProduct, setSelectedProduct] = useState<"farm-bot" | "gem-bot">("farm-bot");
  const [step, setStep] = useState<1 | 2 | 3>(1);

  // Extract clean username (strictly purging any legacy mock strings)
  const rawUserName =
    profile?.username ||
    user?.user_metadata?.custom_claims?.global_name ||
    user?.user_metadata?.full_name ||
    user?.user_metadata?.name ||
    user?.email?.split("@")[0] ||
    "Rey";

  const userName =
    rawUserName.includes("علي غيث") || rawUserName.includes("القائد") || rawUserName.toLowerCase().includes("commander")
      ? "Rey"
      : rawUserName;

  // Step 1: Specs
  const [tier, setTier] = useState<"basic" | "pro">("basic");
  const [chars, setChars] = useState(5);
  const [duration, setDuration] = useState<30 | 90>(30);

  // Step 2: Instance (Auto-filled with user's name as requested by Rey)
  const [applyMode, setApplyMode] = useState<"new" | "existing">("new");
  const [botName, setBotName] = useState(`${userName}'s Farm Bot #1`);
  const [selectedBotId, setSelectedBotId] = useState("");

  // Step 3: Payment
  const [payMethod, setPayMethod] = useState<"paypal" | "usdt" | "btc" | "eth" | "sol" | "binance">("usdt");
  const [showPromo, setShowPromo] = useState(false);
  const [promoCode, setPromoCode] = useState("");
  const [referralCode, setReferralCode] = useState("MALEK11332");
  const [startImmediate, setStartImmediate] = useState(true);

  // Status & Submit
  const [submitting, setSubmitting] = useState(false);
  const [orderSuccess, setOrderSuccess] = useState(false);
  const [createdBotSlug, setCreatedBotSlug] = useState("");

  // Update default bot name when userName is resolved
  useEffect(() => {
    if (applyMode === "new" && (!botName || botName.includes("Farm Bot #8412"))) {
      setBotName(`${userName}'s Farm Bot #1`);
    }
  }, [userName, applyMode]);

  // Pricing Calculation matching ghostbot engine
  function getRatePerChar(c: number, t: "basic" | "pro") {
    if (t === "basic") {
      if (c >= 100) return 1.20;
      if (c >= 50) return 1.40;
      if (c >= 10) return 1.80;
      return 2.00;
    } else {
      if (c >= 100) return 2.10;
      if (c >= 50) return 2.45;
      if (c >= 10) return 3.15;
      return 3.50;
    }
  }

  const rate = getRatePerChar(chars, tier);
  const monthlyCost = chars * rate;
  let rawTotal = duration === 90 ? (monthlyCost * 3 * 0.85) : monthlyCost;
  
  const isCrypto = ["usdt", "btc", "eth", "sol", "binance"].includes(payMethod);
  const cryptoDiscount = isCrypto ? rawTotal * 0.05 : 0;
  const finalTotal = (rawTotal - cryptoDiscount).toFixed(2);

  function openCheckout(product: "farm-bot" | "gem-bot") {
    setSelectedProduct(product);
    setStep(1);
    setOrderSuccess(false);
    setViewMode("checkout");
    if (typeof window !== "undefined") {
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  }

  function handleCheckoutBack() {
    if (step > 1) {
      setStep((s) => (s - 1) as 1 | 2);
    } else {
      setViewMode("catalog");
    }
  }

  // Personalized name generator using Rey's authentic name
  function generateRandomBotName() {
    const variations = [
      `${userName}'s Tactical Core #1`,
      `${userName}'s Farm Hive #84`,
      `${userName}'s Cyber Node #01`,
      `${userName}'s Harvest Unit #7`,
      `${userName}'s Fleet Core #3`,
      `${userName}'s Ghost Alpha #9`,
    ];
    const picked = variations[Math.floor(Math.random() * variations.length)];
    setBotName(picked);
  }

  async function handleFinalOrder() {
    setSubmitting(true);
    try {
      if (!user?.id) {
        alert("يجب تسجيل الدخول بحساب ديسكورد لإتمام الطلب / Please sign in to place order.");
        router.push("/login");
        return;
      }

      let botSlug = selectedBotId || "bot-0";
      let finalName = botName || `${userName}'s Farm Bot`;

      if (applyMode === "new") {
        // Call central autoincrementing global room provisioner
        const provRes = await fetch("/api/bots/provision", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            product: selectedProduct,
            tier: tier,
            slots: chars,
            duration: duration,
            pay_method: payMethod === "usdt" ? "USDT (TRC20)" : payMethod === "binance" ? "Binance Pay" : payMethod === "btc" ? "Bitcoin (BTC)" : "PayPal & Cards",
            amount: finalTotal,
            custom_name: botName,
          }),
        });

        const provData = await provRes.json();
        if (!provRes.ok || !provData.success) {
          throw new Error(provData.error || "Failed to provision global bot unit");
        }

        botSlug = provData.bot_id;
        finalName = provData.name;

        // Save to local orders cache
        const newOrder: OrderRecord = {
          id: provData.invoice_number,
          bot_id: botSlug,
          name: finalName,
          product: selectedProduct,
          tier: tier,
          slots: chars,
          duration: duration,
          amount: finalTotal,
          pay_method: payMethod === "usdt" ? "USDT (TRC20)" : payMethod === "binance" ? "Binance Pay" : payMethod === "btc" ? "Bitcoin (BTC)" : "PayPal & Cards",
          created_at: new Date().toISOString(),
          expires_at: new Date(Date.now() + duration * 86400000).toISOString(),
          status: "active",
        };
        saveNewOrder(newOrder, user.id);
      } else {
        // Extending an existing bot unit
        const existingBot = bots.find(b => b.bot_id === selectedBotId);
        botSlug = selectedBotId;
        finalName = existingBot?.name || botName || `${userName}'s Farm Bot`;
        const newExpires = new Date(Date.now() + duration * 86400000).toISOString();

        await supabase
          .from("bot_instances")
          .update({ expires_at: newExpires, tier: tier, slots: chars })
          .eq("bot_id", botSlug)
          .eq("user_id", user.id);

        const newOrder: OrderRecord = {
          id: `GB-${Math.floor(10000 + Math.random() * 90000)}`,
          bot_id: botSlug,
          name: finalName,
          product: selectedProduct,
          tier: tier,
          slots: chars,
          duration: duration,
          amount: finalTotal,
          pay_method: payMethod === "usdt" ? "USDT (TRC20)" : payMethod === "binance" ? "Binance Pay" : payMethod === "btc" ? "Bitcoin (BTC)" : "PayPal & Cards",
          created_at: new Date().toISOString(),
          expires_at: newExpires,
          status: "active",
        };
        saveNewOrder(newOrder, user.id);

        await supabase.from("invoices").insert({
          user_id: user.id,
          invoice_number: newOrder.id,
          product_name: finalName,
          tier: tier,
          slots: chars,
          billing_cycle: (duration as number) === 365 ? "yearly" : (duration as number) === 90 ? "quarterly" : "monthly",
          amount: parseFloat(finalTotal) || 0,
          currency: "USD",
          status: "active",
          payment_method: payMethod === "usdt" ? "USDT (TRC20)" : payMethod === "binance" ? "Binance Pay" : payMethod === "btc" ? "Bitcoin" : "PayPal / Card",
          expires_at: newExpires,
        });
      }

      setCreatedBotSlug(botSlug);
      setOrderSuccess(true);
      if (refreshData) await refreshData();
    } catch (e: any) {
      alert(`خطأ: ${e?.message || e}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="w-full max-w-7xl mx-auto py-3" dir={dir} style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
      
      {/* ================= VIEW 1: CATALOG SCREEN (IF USER NAVIGATES BACK) ================= */}
      {viewMode === "catalog" && (
        <div id="shopCardsView" style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
          
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: "20px" }}>
            
            {/* FARM BOT CARD */}
            <div
              className="surface-card"
              style={{
                borderRadius: "20px",
                border: "1.5px solid rgba(236,72,153,0.45)",
                background: "radial-gradient(circle at top right, rgba(236,72,153,0.16) 0%, rgba(6,16,35,0.95) 100%)",
                display: "flex",
                flexDirection: "column",
                justifyContent: "space-between",
                padding: "26px",
                boxShadow: "0 0 30px rgba(236,72,153,0.18)",
              }}
            >
              <div>
                <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: "16px" }}>
                  <div
                    style={{
                      width: "64px",
                      height: "64px",
                      borderRadius: "16px",
                      background: "rgba(0,229,255,0.15)",
                      border: "1.5px solid rgba(0,229,255,0.45)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      boxShadow: "0 0 22px rgba(0,229,255,0.35)",
                    }}
                  >
                    <img
                      src={ITEM_FOOD_BASE64}
                      alt="Farm Bot"
                      style={{ width: "48px", height: "48px", objectFit: "contain", filter: "drop-shadow(0 0 12px rgba(0,229,255,0.4))" }}
                    />
                  </div>
                  <span
                    style={{
                      display: "inline-block",
                      padding: "4px 14px",
                      borderRadius: "20px",
                      fontSize: "11px",
                      fontWeight: 800,
                      background: "rgba(236,72,153,0.25)",
                      border: "1px solid rgba(236,72,153,0.5)",
                      color: "#f472b6",
                    }}
                  >
                    {lang === "ar" ? "الأكثر طلباً ★" : "Most Popular ★"}
                  </span>
                </div>
                <h3 style={{ fontSize: "22px", fontWeight: 900, color: "#fff", marginBottom: "4px" }}>
                  {lang === "ar" ? "بوت المزارع (Farm Bot)" : "Farm Bot Fleet"}
                </h3>
                <div style={{ fontSize: "12px", color: "var(--ghost-cyan)", fontWeight: 700, marginBottom: "12px" }}>
                  {lang === "ar"
                    ? "أتمتة شاملة لجمع القمح والأخشاب والحجر والذهب 24/7"
                    : "24/7 Full Automation for Food, Wood, Stone & Gold"}
                </div>
                <p style={{ color: "var(--text-secondary)", fontSize: "13px", lineHeight: "1.6", marginBottom: "20px" }}>
                  {lang === "ar"
                    ? "تشغيل وإدارة حسابات المزارع تلقائياً على مدار الساعة. تفادي مناطق الخطر، تفعيل درع الحماية، تدريب القوات، وتفريغ الموارد للبنك بأمان تام."
                    : "Autonomous 24/7 management for all your farm accounts. Avoid hostile territories, auto shield activation, troop recruitment, and safe bank RSS deposits."}
                </p>
              </div>

              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", borderTop: "1px solid rgba(255,255,255,0.08)", paddingTop: "18px" }}>
                <div style={{ fontSize: "13px", color: "var(--text-secondary)" }}>
                  {lang === "ar" ? "يبدأ من" : "Starts at"} <strong style={{ fontSize: "24px", fontWeight: 900, color: "#fff", fontFamily: "'JetBrains Mono', monospace" }}>$6.00</strong>
                </div>
                <button
                  type="button"
                  className="btn-cyan-glow"
                  style={{
                    padding: "10px 24px",
                    fontWeight: 800,
                    borderRadius: "12px",
                    fontSize: "13.5px",
                    background: "linear-gradient(135deg, #ec4899, #a855f7)",
                    border: "none",
                    boxShadow: "0 0 22px rgba(236,72,153,0.38)",
                    cursor: "pointer",
                  }}
                  onClick={() => openCheckout("farm-bot")}
                >
                  {lang === "ar" ? "تخصيص واشتراك ←" : "Configure & Deploy →"}
                </button>
              </div>
            </div>

            {/* FARM BUILDER */}
            <div
              className="surface-card"
              style={{
                borderRadius: "20px",
                border: "1px solid rgba(0,229,255,0.25)",
                background: "radial-gradient(circle at top right, rgba(0,229,255,0.08) 0%, rgba(6,16,35,0.95) 100%)",
                display: "flex",
                flexDirection: "column",
                justifyContent: "space-between",
                padding: "26px",
                boxShadow: "0 0 20px rgba(0,229,255,0.08)",
              }}
            >
              <div>
                <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: "16px" }}>
                  <div
                    style={{
                      width: "64px",
                      height: "64px",
                      borderRadius: "16px",
                      background: "rgba(0,229,255,0.14)",
                      border: "1.5px solid rgba(0,229,255,0.35)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                    }}
                  >
                    <img src={BUILDER_ICON_BASE64} alt="Farm Builder" style={{ width: "52px", height: "52px", objectFit: "contain", filter: "drop-shadow(0 0 10px rgba(0,229,255,0.4))" }} />
                  </div>
                  <span style={{ padding: "4px 14px", borderRadius: "20px", fontSize: "11px", fontWeight: 800, background: "rgba(0,229,255,0.18)", color: "var(--ghost-cyan)" }}>
                    {lang === "ar" ? "قريباً" : "Coming Soon"}
                  </span>
                </div>
                <h3 style={{ fontSize: "22px", fontWeight: 900, color: "#fff", marginBottom: "4px" }}>
                  {lang === "ar" ? "بنّاء المزارع (Builder)" : "City Builder Bot"}
                </h3>
                <div style={{ fontSize: "12px", color: "var(--ghost-cyan)", fontWeight: 700, marginBottom: "12px" }}>
                  {lang === "ar" ? "ترقية المباني وقاعات المدينة تلقائياً" : "Auto Building & City Hall Construction"}
                </div>
                <p style={{ color: "var(--text-secondary)", fontSize: "13px", lineHeight: "1.6", marginBottom: "20px" }}>
                  {lang === "ar"
                    ? "ترقية مباني المزارع وقاعات المدينة (City Hall) تلقائياً، استكشاف الضباب والكهوف، وإنجاز أبحاث الأكاديمية والمهام الرئيسية."
                    : "Automated City Hall upgrades, queue construction, fog & cave exploration, academy tech progression, and main storyline quests."}
                </p>
              </div>

              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", borderTop: "1px solid rgba(255,255,255,0.08)", paddingTop: "18px" }}>
                <div style={{ fontSize: "13px", color: "var(--text-secondary)" }}>
                  {lang === "ar" ? "الحالة:" : "Status:"} <strong style={{ fontSize: "14px", fontWeight: 800, color: "var(--ghost-cyan)" }}>{lang === "ar" ? "قيد التطوير" : "In Development"}</strong>
                </div>
                <button type="button" className="btn-ghost-outline" style={{ padding: "10px 20px", fontWeight: 700, borderRadius: "12px", opacity: 0.6, cursor: "not-allowed" }} disabled>
                  {lang === "ar" ? "قريباً" : "Coming Soon"}
                </button>
              </div>
            </div>

            {/* GEM BOT */}
            <div
              className="surface-card"
              style={{
                borderRadius: "20px",
                border: "1px solid rgba(168,85,247,0.25)",
                background: "radial-gradient(circle at top right, rgba(168,85,247,0.08) 0%, rgba(6,16,35,0.95) 100%)",
                display: "flex",
                flexDirection: "column",
                justifyContent: "space-between",
                padding: "26px",
                boxShadow: "0 0 20px rgba(168,85,247,0.1)",
              }}
            >
              <div>
                <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: "16px" }}>
                  <div
                    style={{
                      width: "64px",
                      height: "64px",
                      borderRadius: "16px",
                      background: "rgba(168,85,247,0.18)",
                      border: "1.5px solid rgba(168,85,247,0.45)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                    }}
                  >
                    <img src={ITEM_GEM_BASE64} alt="Gem Bot" style={{ width: "46px", height: "46px", objectFit: "contain", filter: "drop-shadow(0 0 12px rgba(168,85,247,0.5))" }} />
                  </div>
                  <span style={{ padding: "4px 14px", borderRadius: "20px", fontSize: "11px", fontWeight: 800, background: "rgba(168,85,247,0.25)", color: "#d8b4fe" }}>
                    {lang === "ar" ? "قريباً" : "Coming Soon"}
                  </span>
                </div>
                <h3 style={{ fontSize: "22px", fontWeight: 900, color: "#fff", marginBottom: "4px" }}>
                  {lang === "ar" ? "بوت الجواهر (Gem Bot)" : "Gem Hunter Bot"}
                </h3>
                <div style={{ fontSize: "12px", color: "#d8b4fe", fontWeight: 700, marginBottom: "12px" }}>
                  {lang === "ar" ? "جمع الجواهر وحشود حصون البرابرة" : "24/7 Gem Mining & Barbarian Fort Rallies"}
                </div>
                <p style={{ color: "var(--text-secondary)", fontSize: "13px", lineHeight: "1.6", marginBottom: "20px" }}>
                  {lang === "ar"
                    ? "جمع الجواهر الذكي من الخريطة 24/7، حشد حصون البرابرة تلقائياً، وتغذية القلاع والمزارع الرئيسية باستمرار مع أقصى درجات الحماية."
                    : "Smart on-map gem node hunting 24/7, autonomous Barbarian Fort rally orchestration, and continuous main castle supply feeds."}
                </p>
              </div>

              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", borderTop: "1px solid rgba(255,255,255,0.08)", paddingTop: "18px" }}>
                <div style={{ fontSize: "13px", color: "var(--text-secondary)" }}>
                  {lang === "ar" ? "الحالة:" : "Status:"} <strong style={{ fontSize: "14px", fontWeight: 800, color: "#d8b4fe" }}>{lang === "ar" ? "قيد التطوير" : "In Development"}</strong>
                </div>
                <button type="button" className="btn-ghost-outline" style={{ padding: "10px 20px", fontWeight: 700, borderRadius: "12px", opacity: 0.6, cursor: "not-allowed" }} disabled>
                  {lang === "ar" ? "قريباً" : "Coming Soon"}
                </button>
              </div>
            </div>

          </div>
        </div>
      )}

      {/* ================= VIEW 2: CHECKOUT SCREEN (EXACT PATTERN & BEAUTIFUL RE-ARRANGED CARDS) ================= */}
      {viewMode === "checkout" && (
        <div id="shopCheckoutView" style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
          
          {/* Header & Back Button Card (Restored) */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "16px 22px",
              borderRadius: "16px",
              background: "rgba(6, 17, 36, 0.8)",
              backdropFilter: "blur(16px)",
              border: "1px solid rgba(0, 229, 255, 0.2)",
              boxShadow: "0 10px 30px rgba(0,0,0,0.5)",
              flexWrap: "wrap",
              gap: "12px",
            }}
          >
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "var(--ghost-cyan)", boxShadow: "0 0 10px var(--ghost-cyan)" }} />
                <span style={{ fontSize: "11px", fontFamily: "'JetBrains Mono', monospace", letterSpacing: "1.5px", color: "var(--ghost-cyan)", fontWeight: 800 }}>
                  {t("shop_title", "GHOSTBOT • SECURE CYBER CHECKOUT")}
                </span>
              </div>
              <h2 style={{ fontSize: "22px", fontWeight: 900, color: "#fff", marginTop: "4px" }}>
                {orderSuccess
                  ? (lang === "ar" ? "تم إتمام الطلب وتفعيل وحدتك بنجاح!" : "Order Completed & Unit Deployed!")
                  : step === 1
                  ? (lang === "ar" ? "تكوين مواصفات البوت وحجم الأسطول" : "Configure Bot Specs & Fleet Size")
                  : step === 2
                  ? (lang === "ar" ? "تخصيص الحاوية وتسمية الوحدة السحابية" : "Customize Container & Instance Name")
                  : (lang === "ar" ? "بوابة الدفع الإلكتروني وتأكيد الترخيص" : "Payment Gateway & License Confirmation")}
              </h2>
              <div style={{ fontSize: "12px", color: "var(--text-secondary)", marginTop: "2px" }}>
                {step === 1 && (lang === "ar" ? "حدد فئة البوت، عدد الحسابات والمزارع، ومدة الاشتراك السحابي" : "Select bot tier, farm slots, and subscription duration")}
                {step === 2 && (lang === "ar" ? "اختر إنشاء وحدة سحابية جديدة أو ترقية وحدة قائمة في أسطولك" : "Create a new cloud instance or upgrade an existing fleet unit")}
                {step === 3 && (lang === "ar" ? "اختر وسيلة الدفع المفضلة واستفد من الخصومات الفورية" : "Select payment method and apply instant discount")}
              </div>
            </div>

            <button
              className="btn-ghost-outline"
              style={{ padding: "8px 18px", fontSize: "12px", fontWeight: 800, display: "inline-flex", alignItems: "center", gap: "8px", cursor: "pointer", borderRadius: "10px" }}
              onClick={handleCheckoutBack}
            >
              <span>{lang === "ar" ? "← العودة لمتجر البوتات" : "← Back to Store"}</span>
            </button>
          </div>

          {/* Stepper Pipeline */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(3, 1fr)",
              gap: "12px",
            }}
          >
            {[
              { num: 1, title: lang === "ar" ? "01. مواصفات البوت" : "01. Bot Specs", sub: "Tier, Chars & Duration" },
              { num: 2, title: lang === "ar" ? "02. تخصيص الوحدة" : "02. Instance Setup", sub: "Personalized Instance" },
              { num: 3, title: lang === "ar" ? "03. وسيلة الدفع" : "03. Payment", sub: "Crypto & PayPal" },
            ].map((s) => {
              const active = step === s.num;
              const completed = step > s.num;
              return (
                <div
                  key={s.num}
                  onClick={() => setStep(s.num as any)}
                  style={{
                    cursor: "pointer",
                    padding: "12px 16px",
                    borderRadius: "14px",
                    background: active
                      ? "linear-gradient(135deg, rgba(0,229,255,0.14) 0%, rgba(6,17,36,0.92) 100%)"
                      : completed
                      ? "rgba(0,230,153,0.08)"
                      : "rgba(255,255,255,0.02)",
                    border: active
                      ? "1.5px solid var(--ghost-cyan)"
                      : completed
                      ? "1px solid rgba(0,230,153,0.3)"
                      : "1px solid rgba(255,255,255,0.07)",
                    boxShadow: active ? "0 0 20px rgba(0,229,255,0.2)" : "none",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    transition: "all 0.25s ease",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                    <div
                      style={{
                        width: "28px",
                        height: "28px",
                        borderRadius: "8px",
                        background: active
                          ? "var(--ghost-cyan)"
                          : completed
                          ? "var(--emerald-ok)"
                          : "rgba(255,255,255,0.08)",
                        color: active || completed ? "#03101f" : "var(--text-secondary)",
                        fontWeight: 900,
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontSize: "12px",
                      }}
                    >
                      {completed ? "✓" : s.num}
                    </div>
                    <div>
                      <div style={{ fontSize: "12.5px", fontWeight: 800, color: active ? "#fff" : "var(--text-secondary)" }}>
                        {s.title}
                      </div>
                      <div style={{ fontSize: "10px", color: active ? "var(--ghost-cyan)" : "var(--text-muted)" }}>
                        {s.sub}
                      </div>
                    </div>
                  </div>
                  <span style={{ fontSize: "12px", color: active ? "var(--ghost-cyan)" : "var(--text-muted)", fontWeight: 900 }}>
                    {active ? "●" : completed ? "✓" : "○"}
                  </span>
                </div>
              );
            })}
          </div>

          {orderSuccess ? (
            /* ORDER SUCCESS SCREEN */
            <div className="surface-card" style={{ padding: "50px 30px", textAlign: "center", borderRadius: "20px", border: "1.5px solid var(--emerald-ok)" }}>
              <div
                style={{
                  width: "74px",
                  height: "74px",
                  borderRadius: "50%",
                  background: "rgba(0,230,153,0.15)",
                  border: "2px solid #00e699",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  margin: "0 auto 18px",
                  fontSize: "32px",
                  color: "#00e699",
                  boxShadow: "0 0 35px rgba(0,230,153,0.4)",
                }}
              >
                ✓
              </div>
              <h3 style={{ fontSize: "24px", fontWeight: 900, color: "#fff", marginBottom: "8px" }}>
                {lang === "ar" ? "تم نشر وتفعيل وحدتك السحابية بنجاح!" : "Cloud Unit Deployed & Activated Successfully!"}
              </h3>
              <p style={{ fontSize: "13.5px", color: "var(--text-secondary)", maxWidth: "520px", margin: "0 auto 24px", lineHeight: "1.6" }}>
                {lang === "ar" ? (
                  <>تم تشغيل الحاوية السحابية المعزولة باسم <strong style={{ color: "var(--ghost-cyan)" }}>{botName}</strong> وتفعيل {chars} خانات لحساباتك.</>
                ) : (
                  <>Dedicated isolated container <strong style={{ color: "var(--ghost-cyan)" }}>{botName}</strong> is online with {chars} account slots activated.</>
                )}
              </p>
              <div style={{ display: "flex", justifyContent: "center", gap: "12px", flexWrap: "wrap" }}>
                <button
                  className="btn-cyan-glow"
                  style={{ padding: "12px 28px", fontSize: "13.5px", fontWeight: 800, cursor: "pointer" }}
                  onClick={() => router.push(`/dashboard?tab=live&bot=${createdBotSlug}`)}
                >
                  {lang === "ar" ? "دخول غرفة العمليات بالبوت ←" : "Enter War Room Console →"}
                </button>
                <button
                  className="btn-ghost-outline"
                  style={{ padding: "12px 24px", fontSize: "13px", cursor: "pointer" }}
                  onClick={() => router.push("/profile")}
                >
                  {lang === "ar" ? "عرض سجل طلباتي في البروفايل 📦" : "View Order Invoices in Profile 📦"}
                </button>
              </div>
            </div>
          ) : (
            /* WORKSPACE MAIN GRID: SIDE-BY-SIDE AS IN IMAGE 1 */
            <div style={{ display: "grid", gridTemplateColumns: "1.55fr 1fr", gap: "20px", alignItems: "start" }}>
              
              {/* RIGHT COLUMN (IN RTL): ACTIVE CONFIGURATION STEP */}
              <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>

                {/* STEP 1: CONFIGURE BOT (BEAUTIFULLY RE-ARRANGED CARDS) */}
                {step === 1 && (
                  <div className="surface-card" style={{ padding: "26px", borderRadius: "18px" }}>
                    
                    {/* Header */}
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "18px" }}>
                      <div>
                        <h3 style={{ fontSize: "17.5px", fontWeight: 900, color: "#fff" }}>
                          {lang === "ar" ? "1. اختر فئة البوت (Tier Selection)" : "1. Choose Bot Tier"}
                        </h3>
                        <p style={{ fontSize: "12px", color: "var(--text-secondary)", marginTop: "2px" }}>
                          {lang === "ar" ? "حدد نموذج الطاقة والمحرك السحابي لتشغيل حساباتك" : "Select cloud engine tier for your farms"}
                        </p>
                      </div>
                      <span className="cyan-pill" style={{ fontSize: "10.5px" }}>Cloud Engine 24/7</span>
                    </div>

                    {/* TWO BEAUTIFULLY RE-ARRANGED TIER CARDS */}
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginBottom: "26px" }}>
                      
                      {/* BASIC TIER CARD */}
                      <div
                        onClick={() => setTier("basic")}
                        style={{
                          cursor: "pointer",
                          padding: "20px",
                          borderRadius: "16px",
                          border: tier === "basic" ? "2px solid #00e5ff" : "1.5px solid rgba(0, 229, 255, 0.15)",
                          background: tier === "basic"
                            ? "radial-gradient(circle at 50% 0%, rgba(0, 229, 255, 0.18) 0%, rgba(5, 14, 30, 0.95) 100%)"
                            : "rgba(5, 14, 30, 0.6)",
                          boxShadow: tier === "basic" ? "0 0 25px rgba(0, 229, 255, 0.22)" : "none",
                          transition: "all 0.25s ease",
                          display: "flex",
                          flexDirection: "column",
                          justifyContent: "space-between",
                          minHeight: "265px",
                        }}
                      >
                        <div>
                          {/* Top Row: Title + Price Tag */}
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "12px" }}>
                            <div>
                              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                                <span
                                  style={{
                                    width: "12px",
                                    height: "12px",
                                    borderRadius: "50%",
                                    background: tier === "basic" ? "#00e5ff" : "rgba(255,255,255,0.2)",
                                    boxShadow: tier === "basic" ? "0 0 10px #00e5ff" : "none",
                                  }}
                                />
                                <strong style={{ fontSize: "17px", color: "#fff", fontWeight: 900 }}>Basic Pack</strong>
                              </div>
                              <span style={{ fontSize: "10.5px", color: "var(--ghost-cyan)", fontWeight: 700, display: "block", marginTop: "3px" }}>
                                {lang === "ar" ? "وحدة الصيانة والحصاد 24/7" : "24/7 Gathering & Maintenance"}
                              </span>
                            </div>

                            {/* Clean Price Pill */}
                            <div
                              style={{
                                background: "rgba(0, 229, 255, 0.1)",
                                border: "1px solid rgba(0, 229, 255, 0.35)",
                                borderRadius: "8px",
                                padding: "4px 10px",
                                textAlign: "left",
                              }}
                            >
                              <span style={{ fontSize: "15px", fontWeight: 900, color: "#00e5ff", fontFamily: "'JetBrains Mono', monospace" }}>
                                $2.00
                              </span>
                              <span style={{ fontSize: "9.5px", color: "var(--text-secondary)", display: "block" }}>{lang === "ar" ? "/ حساب شهرياً" : "/ farm / mo"}</span>
                            </div>
                          </div>

                          {/* Description */}
                          <p style={{ fontSize: "12px", color: "var(--text-ice)", lineHeight: "1.55", marginBottom: "14px" }}>
                            {lang === "ar"
                              ? "صيانة مزارعك الأساسية: جمع الموارد الآلي طوال اليوم، تفعيل الدرع، والمساعدات الفورية."
                              : "Essential farm maintenance: continuous gathering, auto peace shields, and alliance assists."}
                          </p>

                          {/* Bullet Features */}
                          <div style={{ display: "flex", flexDirection: "column", gap: "6px", borderTop: "1px solid rgba(255,255,255,0.06)", paddingTop: "10px" }}>
                            <div style={{ fontSize: "11px", color: "var(--text-secondary)", display: "flex", alignItems: "center", gap: "6px" }}>
                              <span style={{ color: "#00e5ff", fontWeight: 900 }}>✔</span> {lang === "ar" ? "مسيرات ذكية 24/7 دون توقف" : "Smart 24/7 gather marches"}
                            </div>
                            <div style={{ fontSize: "11px", color: "var(--text-secondary)", display: "flex", alignItems: "center", gap: "6px" }}>
                              <span style={{ color: "#00e5ff", fontWeight: 900 }}>✔</span> {lang === "ar" ? "تفادي أراضي الأعداء والتجميع الآمن" : "Avoid hostile alliance territories"}
                            </div>
                            <div style={{ fontSize: "11px", color: "var(--text-secondary)", display: "flex", alignItems: "center", gap: "6px" }}>
                              <span style={{ color: "#00e5ff", fontWeight: 900 }}>✔</span> {lang === "ar" ? "نقل وتفريغ الموارد للبنك تلقائياً" : "Auto resource transfer to bank"}
                            </div>
                          </div>
                        </div>

                        {/* Dedicated Bottom Selection Banner */}
                        <div style={{ marginTop: "14px" }}>
                          {tier === "basic" ? (
                            <div
                              style={{
                                padding: "6px 10px",
                                borderRadius: "8px",
                                background: "rgba(0, 229, 255, 0.16)",
                                border: "1px solid var(--ghost-cyan)",
                                textAlign: "center",
                                fontSize: "11px",
                                fontWeight: 800,
                                color: "#00e5ff",
                              }}
                            >
                              {t("tier_selected_pill", "● الوحدة المحددة حالياً ✓")}
                            </div>
                          ) : (
                            <div
                              style={{
                                padding: "6px 10px",
                                borderRadius: "8px",
                                background: "rgba(255, 255, 255, 0.03)",
                                border: "1px solid rgba(255, 255, 255, 0.1)",
                                textAlign: "center",
                                fontSize: "11px",
                                fontWeight: 700,
                                color: "var(--text-muted)",
                              }}
                            >
                              {lang === "ar" ? "انقر للاختيار والتفعيل" : "Click to Select Tier"}
                            </div>
                          )}
                        </div>
                      </div>

                      {/* PRO TIER CARD */}
                      <div
                        onClick={() => setTier("pro")}
                        style={{
                          cursor: "pointer",
                          padding: "20px",
                          borderRadius: "16px",
                          border: tier === "pro" ? "2px solid #a855f7" : "1.5px solid rgba(168, 85, 247, 0.2)",
                          background: tier === "pro"
                            ? "radial-gradient(circle at 50% 0%, rgba(168, 85, 247, 0.22) 0%, rgba(5, 14, 30, 0.95) 100%)"
                            : "rgba(5, 14, 30, 0.6)",
                          boxShadow: tier === "pro" ? "0 0 25px rgba(168, 85, 247, 0.26)" : "none",
                          transition: "all 0.25s ease",
                          display: "flex",
                          flexDirection: "column",
                          justifyContent: "space-between",
                          minHeight: "265px",
                        }}
                      >
                        <div>
                          {/* Top Row: Title + Price Tag */}
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "12px" }}>
                            <div>
                              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                                <span
                                  style={{
                                    width: "12px",
                                    height: "12px",
                                    borderRadius: "50%",
                                    background: tier === "pro" ? "#a855f7" : "rgba(255,255,255,0.2)",
                                    boxShadow: tier === "pro" ? "0 0 10px #a855f7" : "none",
                                  }}
                                />
                                <strong style={{ fontSize: "17px", color: "#fff", fontWeight: 900 }}>Pro Pack</strong>
                                <span style={{ fontSize: "9px", fontWeight: 900, padding: "2px 5px", borderRadius: "4px", background: "rgba(168,85,247,0.3)", color: "#d8b4fe" }}>
                                  {lang === "ar" ? "الأكثر طلباً ★" : "Most Popular ★"}
                                </span>
                              </div>
                              <span style={{ fontSize: "10.5px", color: "#c084fc", fontWeight: 700, display: "block", marginTop: "3px" }}>
                                {lang === "ar" ? "ترقية وبناء وتطوير شامل" : "Upgrade, Building & Full Progression"}
                              </span>
                            </div>

                            {/* Clean Price Pill */}
                            <div
                              style={{
                                background: "rgba(168, 85, 247, 0.12)",
                                border: "1px solid rgba(168, 85, 247, 0.4)",
                                borderRadius: "8px",
                                padding: "4px 10px",
                                textAlign: "left",
                              }}
                            >
                              <span style={{ fontSize: "15px", fontWeight: 900, color: "#c084fc", fontFamily: "'JetBrains Mono', monospace" }}>
                                $3.50
                              </span>
                              <span style={{ fontSize: "9.5px", color: "var(--text-secondary)", display: "block" }}>
                                {lang === "ar" ? "/ حساب شهرياً" : "/ account monthly"}
                              </span>
                            </div>
                          </div>

                          {/* Description */}
                          <p style={{ fontSize: "12px", color: "var(--text-secondary)", lineHeight: "1.55", marginBottom: "14px" }}>
                            {lang === "ar"
                              ? "بناء وترقية القلعة حتى level 22، تدريب الجيوش القتالية، وأبحاث الأكاديمية العسكرية المستمرة."
                              : "Auto-upgrades castle up to Level 22, continuous troop training, and non-stop military academy research."}
                          </p>

                          {/* Bullet Features */}
                          <div style={{ display: "flex", flexDirection: "column", gap: "6px", borderTop: "1px solid rgba(255,255,255,0.06)", paddingTop: "10px" }}>
                            <div style={{ fontSize: "11px", color: "var(--text-secondary)", display: "flex", alignItems: "center", gap: "6px" }}>
                              <span style={{ color: "#c084fc", fontWeight: 900 }}>✔</span>
                              <span>{lang === "ar" ? "ترقية المباني والقلعة آلياً حتى Lvl 22" : "Auto castle & building upgrades up to Lvl 22"}</span>
                            </div>
                            <div style={{ fontSize: "11px", color: "var(--text-secondary)", display: "flex", alignItems: "center", gap: "6px" }}>
                              <span style={{ color: "#c084fc", fontWeight: 900 }}>✔</span>
                              <span>{lang === "ar" ? "تدريب مستمر للجيوش وإدارة المسرعات" : "Continuous troop training & speedup allocation"}</span>
                            </div>
                            <div style={{ fontSize: "11px", color: "var(--text-secondary)", display: "flex", alignItems: "center", gap: "6px" }}>
                              <span style={{ color: "#c084fc", fontWeight: 900 }}>✔</span>
                              <span>{lang === "ar" ? "أبحاث الأكاديمية وتطوير القادة الذاتي" : "Academy research & automated commander leveling"}</span>
                            </div>
                          </div>
                        </div>

                        {/* Dedicated Bottom Selection Banner */}
                        <div style={{ marginTop: "14px" }}>
                          {tier === "pro" ? (
                            <div
                              style={{
                                padding: "6px 10px",
                                borderRadius: "8px",
                                background: "rgba(168, 85, 247, 0.2)",
                                border: "1px solid #a855f7",
                                textAlign: "center",
                                fontSize: "11px",
                                fontWeight: 800,
                                color: "#d8b4fe",
                              }}
                            >
                              {lang === "ar" ? "● الوحدة المحددة حالياً ✓" : "● Currently Selected Unit ✓"}
                            </div>
                          ) : (
                            <div
                              style={{
                                padding: "6px 10px",
                                borderRadius: "8px",
                                background: "rgba(255, 255, 255, 0.03)",
                                border: "1px solid rgba(255, 255, 255, 0.1)",
                                textAlign: "center",
                                fontSize: "11px",
                                fontWeight: 700,
                                color: "var(--text-muted)",
                              }}
                            >
                              {lang === "ar" ? "انقر للاختيار والتفعيل" : "Click to select and activate"}
                            </div>
                          )}
                        </div>
                      </div>

                    </div>

                    {/* 2. NUMBER OF CHARACTERS / SLOTS */}
                    <div style={{ marginBottom: "26px" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                        <span style={{ fontSize: "13.5px", fontWeight: 800, color: "#fff" }}>
                          {lang === "ar" ? "2. عدد الحسابات والمزارع (Characters / Slots)" : "2. Number of Farm Accounts (Characters / Slots)"}
                        </span>
                        <span style={{ fontSize: "11px", color: "var(--text-secondary)" }}>
                          {lang === "ar" ? "اختيار سريع للسعة:" : "Quick capacity presets:"}
                        </span>
                      </div>

                      {/* Preset Chips */}
                      <div style={{ display: "flex", gap: "8px", marginBottom: "14px", flexWrap: "wrap" }}>
                        {[5, 10, 25, 50, 100].map((num) => (
                          <button
                            key={num}
                            type="button"
                            className="btn-ghost-outline"
                            style={{
                              padding: "6px 14px",
                              fontSize: "11.5px",
                              fontWeight: 800,
                              cursor: "pointer",
                              borderRadius: "8px",
                              borderColor: chars === num ? "var(--ghost-cyan)" : undefined,
                              background: chars === num ? "rgba(0,229,255,0.18)" : undefined,
                              color: chars === num ? "var(--ghost-cyan)" : "var(--text-secondary)",
                            }}
                            onClick={() => setChars(num)}
                          >
                            {num} {lang === "ar" ? "حسابات" : "slots"}
                          </button>
                        ))}
                      </div>

                      {/* Interactive Stepper Box */}
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          background: "rgba(4,11,24,0.9)",
                          border: "1px solid rgba(0,229,255,0.25)",
                          borderRadius: "14px",
                          padding: "12px 20px",
                        }}
                      >
                        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                          <span
                            className="purple-pill"
                            style={{
                              fontSize: "11.5px",
                              background: "rgba(0,229,255,0.12)",
                              borderColor: "var(--ghost-cyan)",
                              color: "var(--ghost-cyan)",
                            }}
                          >
                            {lang === "ar" ? `المحدد: ${chars} حسابات` : `Selected: ${chars} accounts`}
                          </span>
                          <span style={{ fontSize: "12px", color: "var(--text-secondary)", fontFamily: "'JetBrains Mono', monospace" }}>
                            {lang === "ar" ? `سعر الحساب: $${rate.toFixed(2)} / شهرياً` : `Rate: $${rate.toFixed(2)} / mo each`}
                          </span>
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                          <button
                            type="button"
                            className="util-btn"
                            style={{ width: "36px", height: "36px", fontSize: "18px", fontWeight: 900, cursor: "pointer", borderRadius: "8px" }}
                            onClick={() => setChars((c) => Math.max(1, c - 1))}
                          >
                            -
                          </button>
                          <span
                            style={{
                              fontSize: "20px",
                              fontWeight: 900,
                              color: "#fff",
                              minWidth: "36px",
                              textAlign: "center",
                              fontFamily: "'JetBrains Mono', monospace",
                            }}
                          >
                            {chars}
                          </span>
                          <button
                            type="button"
                            className="util-btn"
                            style={{ width: "36px", height: "36px", fontSize: "18px", fontWeight: 900, cursor: "pointer", borderRadius: "8px" }}
                            onClick={() => setChars((c) => Math.min(200, c + 1))}
                          >
                            +
                          </button>
                        </div>
                      </div>
                    </div>

                    {/* 3. BILLING DURATION */}
                    <div>
                      <span style={{ fontSize: "13.5px", fontWeight: 800, color: "#fff", display: "block", marginBottom: "12px" }}>
                        {lang === "ar" ? "3. مدة الاشتراك السحابي (Billing Duration)" : "3. Billing Duration"}
                      </span>

                      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "14px", marginBottom: "20px" }}>
                        {/* 30 Days */}
                        <div
                          onClick={() => setDuration(30)}
                          style={{
                            cursor: "pointer",
                            padding: "16px",
                            borderRadius: "14px",
                            border: duration === 30 ? "2px solid var(--ghost-cyan)" : "1px solid rgba(255,255,255,0.08)",
                            background: duration === 30 ? "rgba(0,229,255,0.12)" : "rgba(255,255,255,0.02)",
                            boxShadow: duration === 30 ? "0 0 20px rgba(0,229,255,0.15)" : "none",
                            transition: "all 0.2s ease",
                          }}
                        >
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                            <strong style={{ fontSize: "15px", color: "#fff" }}>
                              {lang === "ar" ? "30 يوماً (شهري)" : "30 Days (Monthly)"}
                            </strong>
                            <span style={{ fontSize: "14px", fontWeight: 900, color: "#fff", fontFamily: "'JetBrains Mono', monospace" }}>
                              ${monthlyCost.toFixed(2)}
                            </span>
                          </div>
                          <p style={{ fontSize: "11px", color: "var(--text-ice)" }}>
                            {lang === "ar" ? "تجديد شهري قياسي" : "Standard monthly renewal"}
                          </p>
                        </div>

                        {/* 90 Days */}
                        <div
                          onClick={() => setDuration(90)}
                          style={{
                            cursor: "pointer",
                            padding: "16px",
                            borderRadius: "14px",
                            border: duration === 90 ? "2px solid var(--ghost-cyan)" : "1px solid rgba(255,255,255,0.08)",
                            background: duration === 90 ? "rgba(0,229,255,0.12)" : "rgba(255,255,255,0.02)",
                            boxShadow: duration === 90 ? "0 0 20px rgba(0,229,255,0.15)" : "none",
                            transition: "all 0.2s ease",
                          }}
                        >
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                              <strong style={{ fontSize: "15px", color: "#fff" }}>
                                {lang === "ar" ? "90 يوماً (3 أشهر)" : "90 Days (Quarterly)"}
                              </strong>
                              <span style={{ fontSize: "9.5px", fontWeight: 900, padding: "2px 6px", borderRadius: "4px", background: "rgba(0,230,153,0.2)", color: "var(--emerald-ok)" }}>
                                {lang === "ar" ? "خصم 15% 🔥" : "15% OFF 🔥"}
                              </span>
                            </div>
                            <span style={{ fontSize: "14px", fontWeight: 900, color: "var(--ghost-cyan)", fontFamily: "'JetBrains Mono', monospace" }}>
                              ${(monthlyCost * 3 * 0.85).toFixed(2)}
                            </span>
                          </div>
                          <p style={{ fontSize: "11px", color: "var(--emerald-ok)" }}>
                            {lang === "ar"
                              ? `توفر $${(monthlyCost * 3 * 0.15).toFixed(2)} مقارنة بالدفع الشهري`
                              : `Save $${(monthlyCost * 3 * 0.15).toFixed(2)} vs monthly renewal`}
                          </p>
                        </div>
                      </div>

                      {/* Volume Discount Ladder */}
                      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "8px" }}>
                        {[
                          { min: 1, label: lang === "ar" ? "1+ حساب" : "1+ account" },
                          { min: 10, label: lang === "ar" ? "10+ حساب" : "10+ accounts" },
                          { min: 50, label: lang === "ar" ? "50+ حساب" : "50+ accounts" },
                          { min: 100, label: lang === "ar" ? "100+ حساب" : "100+ accounts" },
                        ].map((lvl) => {
                          const lvlRate = getRatePerChar(lvl.min, tier);
                          const isCurrentLvl = chars >= lvl.min && (lvl.min === 100 || chars < (lvl.min === 1 ? 10 : lvl.min === 10 ? 50 : 100));
                          return (
                            <div
                              key={lvl.min}
                              className="stat-tile"
                              style={{
                                padding: "8px 6px",
                                textAlign: "center",
                                borderRadius: "10px",
                                borderColor: isCurrentLvl ? "var(--ghost-cyan)" : undefined,
                                background: isCurrentLvl ? "rgba(0,229,255,0.08)" : undefined,
                              }}
                            >
                              <div style={{ fontSize: "10.5px", color: isCurrentLvl ? "var(--ghost-cyan)" : "var(--text-secondary)" }}>
                                {lvl.label}
                              </div>
                              <div style={{ fontSize: "12px", fontWeight: 800, color: "#fff", marginTop: "2px" }}>
                                ${lvlRate.toFixed(2)}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>

                  </div>
                )}

                {/* STEP 2: INSTANCE NAME (AUTO-FILLS REY'S USERNAME) */}
                {step === 2 && (
                  <div className="surface-card" style={{ padding: "26px", borderRadius: "18px" }}>
                    <h3 style={{ fontSize: "18px", fontWeight: 900, color: "#fff" }}>
                      {lang === "ar" ? "تخصيص وتسمية الوحدة السحابية (Instance Customization)" : "Instance Customization & Naming"}
                    </h3>
                    <p style={{ fontSize: "12px", color: "var(--text-secondary)", marginTop: "2px", marginBottom: "20px" }}>
                      {lang === "ar"
                        ? `قم بإنشاء وحدة سحابية جديدة معزولة بالكامل، أو ترقية إحدى وحداتك القائمة بسعة ${chars} خانات.`
                        : `Provision a dedicated isolated cloud container, or upgrade an existing fleet instance with ${chars} slots.`}
                    </p>

                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px", marginBottom: "22px" }}>
                      <button
                        type="button"
                        onClick={() => setApplyMode("new")}
                        className={applyMode === "new" ? "btn-cyan-glow" : "btn-ghost-outline"}
                        style={{ padding: "14px", fontSize: "13px", fontWeight: 800, justifyContent: "center", borderRadius: "12px", cursor: "pointer" }}
                      >
                        <span>{lang === "ar" ? "+ إنشاء وحدة سحابية جديدة" : "+ Deploy New Cloud Unit"}</span>
                      </button>

                      <button
                        type="button"
                        onClick={() => setApplyMode("existing")}
                        className={applyMode === "existing" ? "btn-cyan-glow" : "btn-ghost-outline"}
                        style={{ padding: "14px", fontSize: "13px", fontWeight: 800, justifyContent: "center", borderRadius: "12px", cursor: "pointer" }}
                      >
                        <span>{lang === "ar" ? "ترقية وحدة قائمة في الحساب" : "Upgrade Existing Instance"}</span>
                      </button>
                    </div>

                    {applyMode === "new" ? (
                      <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                        <div style={{ background: "rgba(4,11,24,0.7)", border: "1.5px solid rgba(0,229,255,0.3)", borderRadius: "16px", padding: "20px" }}>
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
                            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                              <label style={{ fontSize: "13px", fontWeight: 800, color: "#fff" }}>
                                {lang === "ar" ? "اسم الوحدة السحابية (Instance Name)" : "Cloud Instance Name"}
                              </label>
                              <span style={{ fontSize: "10px", padding: "2px 8px", borderRadius: "6px", background: "rgba(0,230,153,0.15)", color: "#00e699", border: "1px solid rgba(0,230,153,0.3)" }}>
                                {lang === "ar" ? "سحب تلقائي لاسم الحساب" : "Auto-synced Username"}
                              </span>
                            </div>
                            <button
                              type="button"
                              className="util-btn"
                              style={{ fontSize: "11px", padding: "4px 10px", cursor: "pointer" }}
                              onClick={generateRandomBotName}
                            >
                              <span>{lang === "ar" ? "توليد اسم تكتيكي 🎲" : "Randomize Name 🎲"}</span>
                            </button>
                          </div>
                          
                          <input
                            type="text"
                            className="form-input"
                            style={{ width: "100%", fontSize: "14px", fontWeight: 800, color: "#fff", background: "rgba(2, 6, 15, 0.9)" }}
                            value={botName}
                            onChange={(e) => setBotName(e.target.value)}
                            placeholder={lang === "ar" ? `مثال: ${userName}'s Farm Bot #1` : `e.g. ${userName}'s Fleet Unit #1`}
                          />
                          
                          <div style={{ fontSize: "11.5px", color: "var(--text-ice)", marginTop: "8px", display: "flex", alignItems: "center", gap: "6px" }}>
                            <span style={{ color: "var(--ghost-cyan)" }}>ℹ️</span>
                            <span>
                              {lang === "ar"
                                ? `تم تعيين اسم الوحدة السحابية تلقائياً باسم حسابك [${userName}] لسهولة التعرف عليها وإدارتها.`
                                : `Auto-named after your account [${userName}] for effortless multi-bot identification.`}
                            </span>
                          </div>
                        </div>

                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
                          <div className="stat-tile" style={{ padding: "14px" }}>
                            <div style={{ fontSize: "10.5px", color: "var(--text-secondary)" }}>HOST REGION</div>
                            <div style={{ fontSize: "13px", fontWeight: 800, color: "var(--ghost-cyan)", marginTop: "3px" }}>● Frankfurt DC (22ms Ping)</div>
                            <div style={{ fontSize: "11px", color: "var(--text-ice)", marginTop: "2px" }}>
                              {lang === "ar" ? "اتصال مشفر فائق السرعة" : "Ultra-fast encrypted uplink"}
                            </div>
                          </div>
                          <div className="stat-tile" style={{ padding: "14px" }}>
                            <div style={{ fontSize: "10.5px", color: "var(--text-secondary)" }}>TENANT ISOLATION</div>
                            <div style={{ fontSize: "13px", fontWeight: 800, color: "var(--emerald-ok)", marginTop: "3px" }}>● 100% Zero Leakage</div>
                            <div style={{ fontSize: "11px", color: "var(--text-ice)", marginTop: "2px" }}>
                              {lang === "ar" ? "حاوية معزولة وبصمات فريدة" : "Isolated container & unique fingerprint"}
                            </div>
                          </div>
                        </div>
                      </div>
                    ) : (
                      <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                        {bots.length === 0 ? (
                          <div style={{ padding: "20px", textAlign: "center", background: "rgba(255,255,255,0.03)", borderRadius: "12px", border: "1px dashed rgba(0,229,255,0.3)" }}>
                            <p style={{ fontSize: "13px", color: "var(--text-secondary)" }}>
                              {lang === "ar" ? "لا توجد وحدات سحابية مسجلة مسبقاً في حسابك." : "No registered cloud instances found in your account."}
                            </p>
                            <button
                              type="button"
                              className="btn-cyan-glow"
                              style={{ marginTop: "10px", padding: "8px 16px", fontSize: "12px", cursor: "pointer" }}
                              onClick={() => setApplyMode("new")}
                            >
                              {lang === "ar" ? "التبديل إلى إنشاء وحدة جديدة" : "Switch to Create New Instance"}
                            </button>
                          </div>
                        ) : (
                          bots.map((b) => (
                            <div
                              key={b.bot_id}
                              onClick={() => setSelectedBotId(b.bot_id)}
                              style={{
                                padding: "14px",
                                borderRadius: "12px",
                                border: selectedBotId === b.bot_id ? "1.5px solid var(--ghost-cyan)" : "1px solid rgba(255,255,255,0.1)",
                                background: selectedBotId === b.bot_id ? "rgba(0,229,255,0.1)" : "rgba(255,255,255,0.03)",
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "space-between",
                                cursor: "pointer",
                              }}
                            >
                              <div>
                                <strong style={{ fontSize: "13.5px", color: "#fff" }}>{b.name || b.label}</strong>
                                <div style={{ fontSize: "11px", color: "var(--text-secondary)", marginTop: "2px" }}>
                                  {lang === "ar"
                                    ? `معرف الوحدة: ${b.bot_id} • السعة الحالية: ${b.slots} خانات`
                                    : `Instance ID: ${b.bot_id} • Current: ${b.slots} slots`}
                                </div>
                              </div>
                              <span style={{ color: selectedBotId === b.bot_id ? "var(--ghost-cyan)" : "var(--text-muted)", fontWeight: 900 }}>
                                {selectedBotId === b.bot_id ? "✓" : "○"}
                              </span>
                            </div>
                          ))
                        )}
                      </div>
                    )}
                  </div>
                )}

                {/* STEP 3: PAYMENT GATEWAYS */}
                {step === 3 && (
                  <div className="surface-card" style={{ padding: "26px", borderRadius: "18px" }}>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "16px" }}>
                      <h3 style={{ fontSize: "18px", fontWeight: 900, color: "#fff" }}>
                        {lang === "ar" ? "اختيار وسيلة الدفع (Payment Gateway)" : "Select Payment Gateway"}
                      </h3>
                      <span className="emerald-badge" style={{ fontSize: "11px" }}>
                        {lang === "ar" ? "خصم 5% إضافي بالعملات الرقمية" : "5% Extra Crypto Discount"}
                      </span>
                    </div>

                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "12px", marginBottom: "20px" }}>
                      
                      <div
                        onClick={() => setPayMethod("paypal")}
                        style={{
                          cursor: "pointer",
                          padding: "14px",
                          borderRadius: "12px",
                          border: payMethod === "paypal" ? "2px solid var(--ghost-cyan)" : "1px solid rgba(255,255,255,0.08)",
                          background: payMethod === "paypal" ? "rgba(0,229,255,0.12)" : "rgba(255,255,255,0.02)",
                          transition: "all 0.2s ease",
                        }}
                      >
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                          <strong style={{ fontSize: "13.5px", color: "#fff" }}>PayPal & Cards</strong>
                          <span style={{ fontSize: "10px", background: "#0079C1", color: "#fff", padding: "1px 6px", borderRadius: "4px", fontWeight: 800 }}>
                            {lang === "ar" ? "فوري" : "Instant"}
                          </span>
                        </div>
                        <div style={{ fontSize: "11px", color: "var(--text-secondary)" }}>Visa, Mastercard, PayPal</div>
                      </div>

                      <div
                        onClick={() => setPayMethod("usdt")}
                        style={{
                          cursor: "pointer",
                          padding: "14px",
                          borderRadius: "12px",
                          border: payMethod === "usdt" ? "2px solid var(--ghost-cyan)" : "1px solid rgba(255,255,255,0.08)",
                          background: payMethod === "usdt" ? "rgba(0,229,255,0.12)" : "rgba(255,255,255,0.02)",
                          transition: "all 0.2s ease",
                        }}
                      >
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                          <strong style={{ fontSize: "13.5px", color: "#fff" }}>USDT (TRC20/BEP20)</strong>
                          <span style={{ fontSize: "10px", background: "#26A17B", color: "#fff", padding: "1px 6px", borderRadius: "4px", fontWeight: 800 }}>
                            {lang === "ar" ? "خصم 5%" : "5% OFF"}
                          </span>
                        </div>
                        <div style={{ fontSize: "11px", color: "var(--text-secondary)" }}>
                          {lang === "ar" ? "أقل رسوم تحويل وسرعة فائقة" : "Lowest fees & zero network delays"}
                        </div>
                      </div>

                      <div
                        onClick={() => setPayMethod("btc")}
                        style={{
                          cursor: "pointer",
                          padding: "14px",
                          borderRadius: "12px",
                          border: payMethod === "btc" ? "2px solid var(--ghost-cyan)" : "1px solid rgba(255,255,255,0.08)",
                          background: payMethod === "btc" ? "rgba(0,229,255,0.12)" : "rgba(255,255,255,0.02)",
                          transition: "all 0.2s ease",
                        }}
                      >
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                          <strong style={{ fontSize: "13.5px", color: "#fff" }}>Bitcoin (BTC)</strong>
                          <span style={{ fontSize: "10px", background: "#F7931A", color: "#fff", padding: "1px 6px", borderRadius: "4px", fontWeight: 800 }}>
                            {lang === "ar" ? "خصم 5%" : "5% OFF"}
                          </span>
                        </div>
                        <div style={{ fontSize: "11px", color: "var(--text-secondary)" }}>
                          {lang === "ar" ? "تحويل بلوكتشين مباشر" : "Direct on-chain settlement"}
                        </div>
                      </div>

                      <div
                        onClick={() => setPayMethod("binance")}
                        style={{
                          cursor: "pointer",
                          padding: "14px",
                          borderRadius: "12px",
                          border: payMethod === "binance" ? "2px solid var(--ghost-cyan)" : "1px solid rgba(255,255,255,0.08)",
                          background: payMethod === "binance" ? "rgba(0,229,255,0.12)" : "rgba(255,255,255,0.02)",
                          transition: "all 0.2s ease",
                        }}
                      >
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                          <strong style={{ fontSize: "13.5px", color: "#fff" }}>Binance Pay (QR)</strong>
                          <span style={{ fontSize: "10px", background: "#F0B90B", color: "#000", padding: "1px 6px", borderRadius: "4px", fontWeight: 800 }}>
                            {lang === "ar" ? "خصم 5%" : "5% OFF"}
                          </span>
                        </div>
                        <div style={{ fontSize: "11px", color: "var(--text-secondary)" }}>
                          {lang === "ar" ? "مسح الـ QR عبر تطبيق بينانس" : "Scan QR code in Binance App"}
                        </div>
                      </div>

                    </div>

                    <div style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: "12px", padding: "14px" }}>
                      <label style={{ display: "flex", alignItems: "center", gap: "10px", cursor: "pointer", fontSize: "12px", color: "#fff" }}>
                        <input
                          type="checkbox"
                          checked={startImmediate}
                          onChange={(e) => setStartImmediate(e.target.checked)}
                          style={{ accentColor: "var(--ghost-cyan)", width: "16px", height: "16px" }}
                        />
                        <span>
                          {lang === "ar"
                            ? "أوافق على بدء تشغيل وترخيص الوحدة فوراً بعد إتمام الدفع."
                            : "I authorize immediate cloud instance provisioning & bot launch upon payment."}
                        </span>
                      </label>
                    </div>
                  </div>
                )}

              </div>

              {/* LEFT COLUMN (IN RTL): STICKY ORDER SUMMARY (EXACT MATCHING IMAGE 1) */}
              <div
                className="surface-card"
                style={{
                  padding: "26px",
                  borderRadius: "18px",
                  border: "1.5px solid rgba(0,229,255,0.35)",
                  boxShadow: "0 0 30px rgba(0,229,255,0.12)",
                  position: "sticky",
                  top: "20px",
                }}
              >
                <div style={{ fontSize: "11px", fontFamily: "'JetBrains Mono', monospace", letterSpacing: "1px", color: "var(--ghost-cyan)", fontWeight: 800, textTransform: "uppercase", marginBottom: "6px" }}>
                  {lang === "ar" ? "ملخص الفاتورة (ORDER SUMMARY)" : "ORDER SUMMARY"}
                </div>
                <h4 style={{ fontSize: "20px", fontWeight: 900, color: "#fff", marginBottom: "16px" }}>
                  Farm Bot {tier === "basic" ? "Basic" : "Pro"}
                </h4>

                <div style={{ display: "flex", flexDirection: "column", gap: "10px", fontSize: "12.5px", marginBottom: "18px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span style={{ color: "var(--text-secondary)" }}>
                      {lang === "ar" ? "عدد المزارع / الحسابات" : "Number of Slots"}
                    </span>
                    <strong style={{ color: "#fff", fontFamily: "'JetBrains Mono', monospace" }}>
                      {chars} {lang === "ar" ? "حسابات" : "slots"}
                    </strong>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span style={{ color: "var(--text-secondary)" }}>
                      {lang === "ar" ? "فئة البوت" : "Tier"}
                    </span>
                    <strong style={{ color: tier === "basic" ? "var(--ghost-cyan)" : "#c084fc" }}>
                      {tier === "basic" ? "Basic Pack" : "Pro Pack ★"}
                    </strong>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span style={{ color: "var(--text-secondary)" }}>
                      {lang === "ar" ? "مدة الاشتراك" : "Duration"}
                    </span>
                    <strong style={{ color: "#fff", fontFamily: "'JetBrains Mono', monospace" }}>
                      {duration} {lang === "ar" ? "يوماً" : "Days"}
                    </strong>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span style={{ color: "var(--text-secondary)" }}>
                      {lang === "ar" ? "الوحدة المستهدفة" : "Target Instance"}
                    </span>
                    <strong style={{ color: "var(--ghost-cyan)" }}>
                      {applyMode === "new" ? botName : (bots.find(b => b.bot_id === selectedBotId)?.name || "Existing Instance")}
                    </strong>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span style={{ color: "var(--text-secondary)" }}>
                      {lang === "ar" ? "وسيلة الدفع" : "Payment Method"}
                    </span>
                    <strong style={{ color: "#fff" }}>{payMethod.toUpperCase()}</strong>
                  </div>

                  {isCrypto && (
                    <div style={{ display: "flex", justifyContent: "space-between", color: "#00e699", fontWeight: 800 }}>
                      <span>{lang === "ar" ? "خصم العملات المشفرة (5%)" : "Crypto Discount (5%)"}</span>
                      <span>-${cryptoDiscount.toFixed(2)}</span>
                    </div>
                  )}
                </div>

                {/* Coupon Drawer */}
                <div style={{ marginBottom: "16px", borderTop: "1px solid rgba(255,255,255,0.08)", paddingTop: "12px" }}>
                  <button
                    type="button"
                    style={{ background: "transparent", border: "none", color: "var(--ghost-cyan)", fontSize: "11.5px", fontWeight: 800, cursor: "pointer", padding: 0 }}
                    onClick={() => setShowPromo(!showPromo)}
                  >
                    {lang === "ar" ? "+ هل لديك كود خصم إضافي؟" : "+ Have a promo code?"}
                  </button>
                  {showPromo && (
                    <div style={{ marginTop: "8px", display: "flex", gap: "6px" }}>
                      <input
                        type="text"
                        className="form-input"
                        style={{ flex: 1, fontFamily: "'JetBrains Mono', monospace", fontSize: "11.5px" }}
                        placeholder="PROMO CODE"
                        value={promoCode}
                        onChange={(e) => setPromoCode(e.target.value)}
                      />
                      <button
                        type="button"
                        className="btn-cyan-glow"
                        style={{ padding: "6px 12px", fontSize: "11px", cursor: "pointer" }}
                        onClick={() => alert(lang === "ar" ? "تم تطبيق كود الخصم الترحيبي بنجاح!" : "Welcome promo code applied successfully!")}
                      >
                        {lang === "ar" ? "تطبيق" : "Apply"}
                      </button>
                    </div>
                  )}
                </div>

                {/* Referral Code */}
                <div style={{ marginBottom: "18px" }}>
                  <label style={{ fontSize: "11px", fontWeight: 700, color: "var(--text-secondary)", display: "block", marginBottom: "4px" }}>
                    {lang === "ar" ? "كود الإحالة (Referral Code)" : "Referral Code"}
                  </label>
                  <input
                    type="text"
                    value={referralCode}
                    onChange={(e) => setReferralCode(e.target.value)}
                    className="form-input"
                    style={{ width: "100%", fontFamily: "'JetBrains Mono', monospace", fontSize: "12px" }}
                    placeholder="Enter code..."
                  />
                  <div style={{ fontSize: "10.5px", color: "var(--text-ice)", marginTop: "4px" }}>
                    {lang === "ar" ? "اختياري: يمنحك يوماً إضافياً مجاناً عند التفعيل." : "Optional: Grants +1 free day upon activation."}
                  </div>
                </div>

                {/* TOTAL PRICE BLOCK */}
                <div
                  style={{
                    borderTop: "1px solid rgba(255,255,255,0.1)",
                    paddingTop: "14px",
                    marginBottom: "20px",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                  }}
                >
                  <span style={{ fontSize: "15px", fontWeight: 900, color: "var(--text-secondary)" }}>
                    {lang === "ar" ? "المجموع الإجمالي" : "Total Amount"}
                  </span>
                  <strong style={{ fontSize: "30px", fontWeight: 900, color: "#fff", fontFamily: "'JetBrains Mono', monospace", textShadow: "0 0 15px rgba(0,229,255,0.4)" }}>
                    ${finalTotal}
                  </strong>
                </div>

                {/* Next CTA Button */}
                <button
                  className="btn-cyan-glow"
                  style={{ width: "100%", justifyContent: "center", padding: "14px", fontSize: "14px", fontWeight: 900, cursor: "pointer", borderRadius: "12px" }}
                  disabled={submitting}
                  onClick={() => {
                    if (step === 1) {
                      setStep(2);
                    } else if (step === 2) {
                      setStep(3);
                    } else {
                      handleFinalOrder();
                    }
                  }}
                >
                  <span>
                    {submitting
                      ? (lang === "ar" ? "جارٍ المعالجة والتفعيل السحابي..." : "Provisioning Cloud Unit...")
                      : step === 1
                      ? (lang === "ar" ? "المتابعة لتخصيص الوحدة ←" : "Proceed to Instance Setup →")
                      : step === 2
                      ? (lang === "ar" ? "المتابعة لاختيار وسيلة الدفع ←" : "Proceed to Payment →")
                      : (lang === "ar" ? "تأكيد وتفعيل الاشتراك الآن 🚀" : "Confirm & Deploy Fleet Now 🚀")}
                  </span>
                </button>
              </div>

            </div>
          )}

          {/* 3-Column Feature Matrix Cards */}
          <div className="surface-card" style={{ padding: "28px", borderRadius: "18px", marginTop: "4px" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "6px" }}>
              <h3 style={{ fontSize: "18px", fontWeight: 900, color: "#fff" }}>
                {lang === "ar" ? "ما الذي تتضمنه باقة Farm Bot السحابية؟" : "What's Included in GhostBot Cloud Farm Fleet?"}
              </h3>
              <span className="purple-pill" style={{ fontSize: "10.5px" }}>Full Feature Matrix</span>
            </div>
            <p style={{ fontSize: "12px", color: "var(--text-secondary)", marginBottom: "22px" }}>
              {lang === "ar"
                ? "باقة Basic تضمن بقاء مزارعك مجمعة للموارد وآمنة طوال 24 ساعة؛ بينما تضيف Pro التطوير التلقائي للأكاديمية والقلعة والجيوش."
                : "Basic Pack keeps your farm nodes gathering resources safely 24/7; Pro Pack adds autonomous building, troop training, and academy tech research."}
            </p>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "20px" }}>
              
              {/* CARD A: GATHERING */}
              <div style={{ padding: "18px", borderRadius: "14px", background: "rgba(0,229,255,0.03)", border: "1px solid rgba(0,229,255,0.2)" }}>
                <div style={{ fontSize: "12px", fontFamily: "'JetBrains Mono', monospace", letterSpacing: "1px", color: "var(--ghost-cyan)", fontWeight: 900, textTransform: "uppercase", marginBottom: "12px" }}>
                  {lang === "ar" ? "🌾 أتمتة جمع الموارد (GATHERING)" : "🌾 RESOURCE GATHERING AUTOMATION"}
                </div>
                <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: "8px", fontSize: "12px", color: "var(--text-ice)" }}>
                  <li style={{ display: "flex", alignItems: "flex-start", gap: "8px" }}>
                    <span style={{ color: "var(--ghost-cyan)" }}>✔</span>
                    <span>{lang === "ar" ? "مسيرات جمع ذكية 24/7 لجميع الحسابات" : "24/7 autonomous gathering marches across all farm slots"}</span>
                  </li>
                  <li style={{ display: "flex", alignItems: "flex-start", gap: "8px" }}>
                    <span style={{ color: "var(--ghost-cyan)" }}>✔</span>
                    <span>{lang === "ar" ? "تفادي أراضي التحالفات المعادية والتجميع في الأمان" : "Avoid hostile alliance territories & stick to safe zones"}</span>
                  </li>
                  <li style={{ display: "flex", alignItems: "flex-start", gap: "8px" }}>
                    <span style={{ color: "var(--ghost-cyan)" }}>✔</span>
                    <span>{lang === "ar" ? "تخصيص نوع المورد لكل حساب (قمح / خشب / حجر / ذهب)" : "Custom resource filters per node (Food / Wood / Stone / Gold)"}</span>
                  </li>
                  <li style={{ display: "flex", alignItems: "flex-start", gap: "8px" }}>
                    <span style={{ color: "var(--ghost-cyan)" }}>✔</span>
                    <span>{lang === "ar" ? "نقل وتفريغ الموارد التلقائي للمستودع البنكي" : "Automated resource transfer to designated bank accounts"}</span>
                  </li>
                  <li style={{ display: "flex", alignItems: "flex-start", gap: "8px" }}>
                    <span style={{ color: "var(--ghost-cyan)" }}>✔</span>
                    <span>{lang === "ar" ? "جدول زمني ذكي وتحكم عبر الويب دون الحاجة لجهازك" : "Smart scheduling & web telemetry without running local PC"}</span>
                  </li>
                </ul>
              </div>

              {/* CARD B: DAILY AUTOMATION */}
              <div style={{ padding: "18px", borderRadius: "14px", background: "rgba(0,230,153,0.03)", border: "1px solid rgba(0,230,153,0.2)" }}>
                <div style={{ fontSize: "12px", fontFamily: "'JetBrains Mono', monospace", letterSpacing: "1px", color: "var(--emerald-ok)", fontWeight: 900, textTransform: "uppercase", marginBottom: "12px" }}>
                  {lang === "ar" ? "⚙️ المهام اليومية (DAILY AUTOMATION)" : "⚙️ DAILY TASKS & ROUTINES"}
                </div>
                <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: "8px", fontSize: "12px", color: "var(--text-ice)" }}>
                  <li style={{ display: "flex", alignItems: "flex-start", gap: "8px" }}>
                    <span style={{ color: "var(--emerald-ok)" }}>✔</span>
                    <span>{lang === "ar" ? "شراء المسرعات الأسبوعية تلقائياً من متجر VIP" : "Weekly VIP shop speedups & key items auto-purchase"}</span>
                  </li>
                  <li style={{ display: "flex", alignItems: "flex-start", gap: "8px" }}>
                    <span style={{ color: "var(--emerald-ok)" }}>✔</span>
                    <span>{lang === "ar" ? "استلام صناديق الـ VIP اليومية والبريد وهدايا الحملة" : "Claim daily VIP chests, campaign rewards & system mail"}</span>
                  </li>
                  <li style={{ display: "flex", alignItems: "flex-start", gap: "8px" }}>
                    <span style={{ color: "var(--emerald-ok)" }}>✔</span>
                    <span>{lang === "ar" ? "علاج الجرحى في المشافي واستكشاف الضباب" : "Hospital auto-healing & scout fog exploration"}</span>
                  </li>
                  <li style={{ display: "flex", alignItems: "flex-start", gap: "8px" }}>
                    <span style={{ color: "var(--emerald-ok)" }}>✔</span>
                    <span>{lang === "ar" ? "صيد وحوش البرابرة بالقادة والمستويات المحددة" : "Barbarian hunting with selected commanders & levels"}</span>
                  </li>
                  <li style={{ display: "flex", alignItems: "flex-start", gap: "8px" }}>
                    <span style={{ color: "var(--emerald-ok)" }}>✔</span>
                    <span>{lang === "ar" ? "التبرع لتقنيات التحالف والضغط على زر مساعدة الكل" : "Alliance tech donations & 1-click alliance help assist"}</span>
                  </li>
                </ul>
              </div>

              {/* CARD C: ACCOUNT PROGRESSION [PRO] */}
              <div style={{ padding: "18px", borderRadius: "14px", background: "rgba(168,85,247,0.04)", border: "1px solid rgba(168,85,247,0.25)" }}>
                <div style={{ fontSize: "12px", fontFamily: "'JetBrains Mono', monospace", letterSpacing: "1px", color: "#c084fc", fontWeight: 900, textTransform: "uppercase", marginBottom: "12px" }}>
                  {lang === "ar" ? "👑 الترقية والتطوير [PRO PACK]" : "👑 EMPIRE PROGRESSION [PRO PACK]"}
                </div>
                <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: "8px", fontSize: "12px", color: "var(--text-ice)" }}>
                  <li style={{ display: "flex", alignItems: "flex-start", gap: "8px" }}>
                    <span style={{ color: "#c084fc" }}>✔</span>
                    <span>{lang === "ar" ? "تدريب مستمر للقوات القتالية مع إدارة المسرعات" : "Non-stop military recruitment & speedup prioritization"}</span>
                  </li>
                  <li style={{ display: "flex", alignItems: "flex-start", gap: "8px" }}>
                    <span style={{ color: "#c084fc" }}>✔</span>
                    <span>{lang === "ar" ? "ترقية المباني تلقائياً حتى مستوى قلعة 22" : "Auto city hall & building construction up to Lvl 22"}</span>
                  </li>
                  <li style={{ display: "flex", alignItems: "flex-start", gap: "8px" }}>
                    <span style={{ color: "#c084fc" }}>✔</span>
                    <span>{lang === "ar" ? "أبحاث الأكاديمية العسكرية والاقتصادية المستمرة" : "Continuous military & economy academy technology tree"}</span>
                  </li>
                  <li style={{ display: "flex", alignItems: "flex-start", gap: "8px" }}>
                    <span style={{ color: "#c084fc" }}>✔</span>
                    <span>{lang === "ar" ? "تطوير مستوى القادة وتوزيع نقاط المهارات" : "Commander skill point distribution & talent tree leveling"}</span>
                  </li>
                  <li style={{ display: "flex", alignItems: "flex-start", gap: "8px" }}>
                    <span style={{ color: "#c084fc" }}>✔</span>
                    <span>{lang === "ar" ? "توظيف وتفعيل البنّاء الثاني تلقائياً (2nd Builder)" : "Autonomous 2nd Builder lease & queue management"}</span>
                  </li>
                </ul>
              </div>

            </div>
          </div>

        </div>
      )}

    </div>
  );
}
