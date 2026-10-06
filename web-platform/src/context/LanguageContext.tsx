"use client";

import React, { createContext, useContext, useEffect, useState } from "react";

export type Language = "ar" | "en";
export type Direction = "rtl" | "ltr";

export interface LanguageContextType {
  lang: Language;
  dir: Direction;
  setLang: (lang: Language) => void;
  toggleLang: () => void;
  t: (key: string, fallback?: string) => string;
}

const translations: Record<Language, Record<string, string>> = {
  ar: {
    // Brand & General
    app_name: "GhostBot",
    app_subtitle: "رفيقك الذكي للأتمتة السحابية",
    ghostbot_core: "نواة GHOSTBOT السحابية",
    utc_clock: "توقيت الخادم العالمي",
    lang_toggle_label: "English",
    updates: "التحديثات",
    alerts: "الإشعارات",
    main_nav: "القائمة الرئيسية",
    overview: "نظرة عامة",
    store: "المتجر والاشتراكات",
    profile: "الملف الشخصي",
    deployed_units: "الوحدات السحابية",
    add_store: "+ متجر الوحدات",
    no_units_active: "لا توجد غرف بوت مفعلة حالياً",
    no_units_hint: "قم بطلب رخصة من المتجر لإنشاء غرفتك السحابية المعزولة.",
    create_first_unit: "تفعيل أول وحدة بوت سحابية ←",
    sign_out: "تسجيل الخروج",
    active: "نشط",
    standby: "جاهز",
    stopped: "متوقف",
    running: "قيد التشغيل",
    save_changes: "حفظ التعديلات",
    cancel: "إلغاء",
    close: "إغلاق",
    copy: "نسخ",
    copied: "تم النسخ بنجاح!",
    confirm: "تأكيد",

    // Dashboard Overview
    fleet_overview_title: "مركز القيادة والمتابعة اللحظية",
    fleet_overview_desc: "نظام تحكم شامل ومستقل لكل غرفة بوت مع عزل تام للبيانات ومتابعة دقيقة للحصاد",
    total_fleet_power: "إجمالي قوة الأسطول",
    active_marches: "المسيرات النشطة",
    daily_harvest_est: "حصاد اليوم التقديري",
    alliance_assists: "مساعدات التحالف",
    shield_status_card: "حالة الدروع والقلعة",
    shield_safe_status: "محمية 24/7 (تجديد آلي)",
    quick_fleet_actions: "إجراءات الأسطول السريعة",
    btn_start_all: "تشغيل كل الوحدات",
    btn_stop_all: "إيقاف مؤقت للجميع",
    btn_new_license: "+ شراء رخصة سحابية",
    telemetry_console_title: "وحدة القياس والمراقبة المباشرة (Live Telemetry)",
    filter_all: "الكل",
    filter_system: "النظام",
    filter_gather: "الحصاد",
    filter_alliance: "التحالف",
    console_autoscroll: "تمرير تلقائي",
    console_clear: "مسح السجل",
    no_bots_welcome_title: "مرحباً بك في منصة GhostBot السحابية!",
    no_bots_welcome_desc: "لم يتم إنشاء أي غرف أو رخص بوت بعد. لإنشاء غرفتك السحابية وربط حسابات Rise of Kingdoms الخاصة بك، يرجى الانتقال للمتجر واختيار باقتك.",
    btn_go_to_store: "الانتقال إلى متجر التراخيص السحابية ←",

    // Bot Rooms (Tabs)
    tab_overview: "نظرة عامة",
    tab_live: "المراقبة الحية",
    tab_accounts: "الحسابات والمزارع",
    tab_inventory: "المخزون والموارد",
    tab_history: "سجل العمليات",
    tab_config: "إعدادات البوت",
    unit_status_header: "حالة وحدة البوت:",
    btn_start_bot: "تشغيل الوحدة",
    btn_stop_bot: "إيقاف الوحدة",
    btn_restart_bot: "إعادة تهيئة",
    slots_allocated: "الخانات المتاحة:",
    slots_used: "الخانات المستخدمة:",
    no_accounts_in_unit_title: "لا توجد حسابات مرتبطة بهذه الغرفة حتى الآن",
    no_accounts_in_unit_desc: "قم بإضافة بيانات حسابك أو مزرعتك لبدء الحصاد التلقائي الآمن بدون أي تسريب بيانات.",
    btn_add_account: "+ ربط حساب مزرعة جديد",
    col_governor: "اسم الحاكم / القائد",
    col_kingdom: "المملكة",
    col_city_hall: "مستوى القلعة",
    col_power: "القوة",
    col_status: "الحالة الحالية",
    col_resources: "الموارد",
    col_actions: "الإجراءات",
    btn_toggle_enable: "تفعيل",
    btn_toggle_disable: "تعطيل",
    btn_delete_account: "حذف",
    rss_food: "قمح",
    rss_wood: "خشب",
    rss_stone: "حجر",
    rss_gold: "ذهب",
    rss_gems: "جواهر",

    // Inventory & Resources
    inventory_title: "المخزون المجمع وإحصائيات الحصاد",
    filter_period_today: "اليوم",
    filter_period_7d: "آخر 7 أيام",
    filter_period_30d: "آخر 30 يوماً",
    total_gathered_label: "إجمالي الموارد المجمعة:",
    breakdown_label: "توزيع الموارد:",
    export_csv: "تصدير التقرير",

    // Bot Configuration
    cfg_general: "عام والنظام",
    cfg_gathering: "الحصاد والمسيرات",
    cfg_city: "شؤون القلعة",
    cfg_alliance: "التحالف",
    cfg_combat: "التدريب والعلاج",
    cfg_interval_label: "فاصل دورات التشغيل:",
    cfg_discord_notif: "إشعارات ديسكورد الفورية:",
    cfg_gather_marches: "توزيع مسيرات الحصاد:",
    cfg_marches_food: "مسيرات القمح:",
    cfg_marches_wood: "مسيرات الخشب:",
    cfg_marches_stone: "مسيرات الحجر:",
    cfg_marches_gold: "مسيرات الذهب:",
    cfg_autotrain: "تدريب القوات التلقائي:",
    cfg_heal: "علاج المشافي التلقائي:",
    cfg_save_btn: "حفظ إعدادات الغرفة",
    cfg_saved_msg: "تم حفظ إعدادات البوت بنجاح!",

    // Shop & Checkout
    shop_title: "GHOSTBOT • الدفع والاشتراك السحابي الآمن",
    shop_subtitle: "تكوين مواصفات البوت وحجم الأسطول",
    shop_back: "← العودة للوحة التحكم",
    step1_title: "1. اختيار الباقة المناسبة",
    step2_title: "2. مواصفات الوحدة السحابية",
    step3_title: "3. تأكيد وسيلة الدفع",
    basic_pack_name: "باقة المزارع الأساسية (Basic Pack)",
    basic_pack_desc: "الخيار المثالي لتشغيل وإدارة حتى 5 مزارع بحصاد متواصل وأمان فائق.",
    pro_pack_name: "باقة الاحتراف الشاملة (Pro Pack)",
    pro_pack_desc: "أعلى أداء وأولوية معالجة مع دعم جميع الميزات وصيد الجواهر التلقائي.",
    price_basic: "$2.00 / للمزرعة شهرياً",
    price_pro: "$3.50 / للمزرعة شهرياً",
    tier_selected_pill: "● الوحدة المحددة حالياً ✓",
    select_tier_btn: "اختيار هذه الباقة",
    instance_name_label: "اسم الوحدة السحابية (Instance Name)",
    instance_name_help: "اسم مميز يساعدك في تنظيم وتسمية أسطولك السحابي",
    slots_label: "عدد خانات المزارع (Farm Slots)",
    duration_label: "مدة الاشتراك السحابي",
    dur_30: "30 يوماً (شهري)",
    dur_90: "90 يوماً (خصم 15%)",
    pay_method_label: "اختر وسيلة الدفع المناسبة",
    summary_title: "ملخص الفاتورة والطلب",
    summary_pack: "الباقة المختارة:",
    summary_slots: "عدد الخانات:",
    summary_duration: "المدة:",
    summary_total: "الإجمالي النهائي:",
    btn_deploy_now: "تأكيد الدفع ونشر البوت سحابياً ←",
    guarantee_box: "ضمان أمان الحسابات 100% بدون باند وبسيرفرات سحابية معزولة تماماً.",

    // Profile Page
    profile_top_title: "الملف الشخصي والاشتراكات السحابية",
    my_orders_btn: "📦 طلباتي السابقة",
    active_count: "نشطة",
    terms_btn: "📜 شروط الخدمة (Terms)",
    privacy_btn: "🔒 سياسة الخصوصية (Privacy)",
    refunds_btn: "💳 سياسة الاسترجاع (Refunds)",
    discord_auth_badge: "حساب ديسكورد معتمد رسمياً",
    discord_id_label: "معرّف ديسكورد (Discord ID):",
    btn_sync_discord: "🔄 تحديث ومزامنة بيانات ديسكورد",
    active_licenses_title: "التراخيص والأسطول السحابي النشط",
    no_orders_msg: "لا توجد رخص أو طلبات سابقة مسجلة حتى الآن.",
    invoice_title: "فاتورة رسمية - GhostBot Cloud Fleet",
    invoice_id: "رقم الفاتورة:",
    invoice_date: "تاريخ الطلب:",
    invoice_unit: "اسم الوحدة:",
    invoice_tier: "نوع الباقة:",
    invoice_amount: "المبلغ المدفوع:",
    invoice_method: "طريقة الدفع:",
    invoice_status: "حالة الترخيص:",
    btn_launch_bot: "دخول البوت ←",
    btn_print_pdf: "طباعة / حفظ PDF",

    // Login Page
    login_console_badge: "GHOSTBOT v2.5 • بوابة القيادة والتحكم السحابية",
    login_main_heading: "أتمتة وحصاد 24/7 لمزارع Rise of Kingdoms بأمان مطلق",
    login_sub_heading: "سيرفرات سحابية معزولة تماماً لكل مستخدم بدون كشف بيانات أو الحاجة لجهاز كمبيوتر",
    login_with_discord: "الدخول الرسمي الفوري عبر ديسكورد",
    login_guest_bypass: "الدخول السريع كضيف (Local Guest Test)",
    login_encryption_note: "تشفير كامل AES-256 مع حماية متقدمة من كشف السيرفر أو تسريب معلومات الحسابات.",
    login_status_node: "سيرفر فرانكفورت DC 22ms • عزل أمني 100%",
    login_terms_note: "بتسجيل دخولك فإنك توافق على شروط الخدمة وسياسة الخصوصية المعتمدة.",
  },

  en: {
    // Brand & General
    app_name: "GhostBot",
    app_subtitle: "Your Intelligent Cloud Automation Companion",
    ghostbot_core: "GHOSTBOT CORE CLOUD",
    utc_clock: "UTC SERVER CLOCK",
    lang_toggle_label: "العربية",
    updates: "Updates",
    alerts: "Alerts",
    main_nav: "Main Navigation",
    overview: "Overview",
    store: "Store & Licenses",
    profile: "My Profile",
    deployed_units: "Fleet Units",
    add_store: "+ Store",
    no_units_active: "No active bot instances currently",
    no_units_hint: "Order a license from the store to create your isolated cloud room.",
    create_first_unit: "Deploy First Cloud Bot Unit ←",
    sign_out: "Sign Out",
    active: "Active",
    standby: "Standby",
    stopped: "Stopped",
    running: "Running",
    save_changes: "Save Changes",
    cancel: "Cancel",
    close: "Close",
    copy: "Copy",
    copied: "Copied Successfully!",
    confirm: "Confirm",

    // Dashboard Overview
    fleet_overview_title: "Command Center & Live Telemetry",
    fleet_overview_desc: "Unified cloud orchestration for all bot units with strict account isolation & 24/7 telemetry",
    total_fleet_power: "Total Fleet Power",
    active_marches: "Active Marches",
    daily_harvest_est: "Estimated Daily Harvest",
    alliance_assists: "Alliance Assists",
    shield_status_card: "City Shields & Defense",
    shield_safe_status: "Protected 24/7 (Auto-Renew)",
    quick_fleet_actions: "Quick Fleet Controls",
    btn_start_all: "Start All Units",
    btn_stop_all: "Pause All Units",
    btn_new_license: "+ Buy Cloud License",
    telemetry_console_title: "Real-Time Telemetry & Console Log",
    filter_all: "All",
    filter_system: "System",
    filter_gather: "Gathering",
    filter_alliance: "Alliance",
    console_autoscroll: "Auto Scroll",
    console_clear: "Clear Log",
    no_bots_welcome_title: "Welcome to GhostBot Cloud Platform!",
    no_bots_welcome_desc: "No bot rooms or licenses have been deployed yet. To spin up your dedicated cloud instance and link your Rise of Kingdoms farms, please visit the store to pick a plan.",
    btn_go_to_store: "Go to Store & Choose Package ←",

    // Bot Rooms (Tabs)
    tab_overview: "Overview",
    tab_live: "Live Telemetry",
    tab_accounts: "Linked Accounts",
    tab_inventory: "Inventory & RSS",
    tab_history: "Activity Log",
    tab_config: "Bot Configuration",
    unit_status_header: "Bot Unit Status:",
    btn_start_bot: "Start Bot",
    btn_stop_bot: "Stop Bot",
    btn_restart_bot: "Restart Unit",
    slots_allocated: "Slots Allocated:",
    slots_used: "Slots Used:",
    no_accounts_in_unit_title: "No farm accounts linked to this unit yet",
    no_accounts_in_unit_desc: "Add your game farm account credentials to begin automated gathering with zero data leak.",
    btn_add_account: "+ Link New Farm Account",
    col_governor: "Governor / Commander",
    col_kingdom: "Kingdom",
    col_city_hall: "City Hall",
    col_power: "Power",
    col_status: "Current Status",
    col_resources: "Resources",
    col_actions: "Actions",
    btn_toggle_enable: "Enable",
    btn_toggle_disable: "Disable",
    btn_delete_account: "Delete",
    rss_food: "Food",
    rss_wood: "Wood",
    rss_stone: "Stone",
    rss_gold: "Gold",
    rss_gems: "Gems",

    // Inventory & Resources
    inventory_title: "Gathered Inventory & Resource Analytics",
    filter_period_today: "Today",
    filter_period_7d: "Last 7 Days",
    filter_period_30d: "Last 30 Days",
    total_gathered_label: "Total Gathered Resources:",
    breakdown_label: "Resource Breakdown:",
    export_csv: "Export CSV",

    // Bot Configuration
    cfg_general: "General & Core",
    cfg_gathering: "Gathering & Marches",
    cfg_city: "City Affairs",
    cfg_alliance: "Alliance",
    cfg_combat: "Troop Training & Heal",
    cfg_interval_label: "Run Cycle Interval:",
    cfg_discord_notif: "Instant Discord Webhooks:",
    cfg_gather_marches: "March Allocation:",
    cfg_marches_food: "Food Marches:",
    cfg_marches_wood: "Wood Marches:",
    cfg_marches_stone: "Stone Marches:",
    cfg_marches_gold: "Gold Marches:",
    cfg_autotrain: "Auto Troop Training:",
    cfg_heal: "Auto Hospital Healing:",
    cfg_save_btn: "Save Room Configuration",
    cfg_saved_msg: "Bot configuration saved successfully!",

    // Shop & Checkout
    shop_title: "GHOSTBOT • SECURE CYBER CHECKOUT",
    shop_subtitle: "Configure Bot Specifications & Fleet Size",
    shop_back: "← Back to Dashboard",
    step1_title: "1. Choose Your Tier",
    step2_title: "2. Cloud Instance Specs",
    step3_title: "3. Payment Confirmation",
    basic_pack_name: "Basic Farm Pack",
    basic_pack_desc: "The essential solution to automate up to 5 farms with 24/7 gathering and strict anti-ban.",
    pro_pack_name: "All-Inclusive Pro Pack",
    pro_pack_desc: "Maximum speed, priority CPU queue, auto gem hunting, hospital healing, and VIP support.",
    price_basic: "$2.00 / farm / month",
    price_pro: "$3.50 / farm / month",
    tier_selected_pill: "● Selected Package ✓",
    select_tier_btn: "Select This Tier",
    instance_name_label: "Instance Name",
    instance_name_help: "A distinct label to identify and organize this bot room in your fleet",
    slots_label: "Farm Slots Allocation",
    duration_label: "Subscription Duration",
    dur_30: "30 Days (Monthly)",
    dur_90: "90 Days (15% OFF)",
    pay_method_label: "Select Secure Payment Method",
    summary_title: "Invoice & Order Summary",
    summary_pack: "Selected Package:",
    summary_slots: "Allocated Slots:",
    summary_duration: "Duration:",
    summary_total: "Grand Total:",
    btn_deploy_now: "Confirm Payment & Deploy Fleet Unit ←",
    guarantee_box: "100% Anti-Ban Guarantee with isolated container runtimes and zero data leakage.",

    // Profile Page
    profile_top_title: "Profile & Cloud Subscriptions",
    my_orders_btn: "📦 My Past Orders",
    active_count: "active",
    terms_btn: "📜 Terms of Service",
    privacy_btn: "🔒 Privacy Policy",
    refunds_btn: "💳 Refund Policy",
    discord_auth_badge: "Official Discord Connected",
    discord_id_label: "Discord ID:",
    btn_sync_discord: "🔄 Sync Discord Profile",
    active_licenses_title: "Active Licenses & Deployed Fleet",
    no_orders_msg: "No licenses or past orders recorded yet.",
    invoice_title: "Official Invoice - GhostBot Cloud Fleet",
    invoice_id: "Invoice ID:",
    invoice_date: "Order Date:",
    invoice_unit: "Unit Name:",
    invoice_tier: "Package Tier:",
    invoice_amount: "Amount Paid:",
    invoice_method: "Payment Method:",
    invoice_status: "License Status:",
    btn_launch_bot: "Launch Bot Room ←",
    btn_print_pdf: "Print / Save PDF",

    // Login Page
    login_console_badge: "GHOSTBOT v2.5 • AUTONOMOUS FLEET TERMINAL",
    login_main_heading: "24/7 Rise of Kingdoms Fleet Automation with Zero Ban Risk",
    login_sub_heading: "Dedicated isolated cloud instances for each commander. No PC or emulator needed.",
    login_with_discord: "Instant Login with Discord OAuth",
    login_guest_bypass: "Explore as Local Guest (Instant Access)",
    login_encryption_note: "Enterprise AES-256 encryption with zero data leak and strict account isolation.",
    login_status_node: "Frankfurt DC 22ms • Zero Data Leak",
    login_terms_note: "By continuing you agree to our Terms of Service and Privacy Policy.",
  },
};

const LanguageContext = createContext<LanguageContextType>({
  lang: "ar",
  dir: "rtl",
  setLang: () => {},
  toggleLang: () => {},
  t: (key: string, fallback?: string) => fallback || key,
});

export function LanguageProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Language>("ar");

  useEffect(() => {
    try {
      const stored = localStorage.getItem("ghostbot_lang") as Language | null;
      if (stored === "ar" || stored === "en") {
        setLangState(stored);
        applyDocumentLang(stored);
      } else {
        applyDocumentLang("ar");
      }
    } catch {
      applyDocumentLang("ar");
    }
  }, []);

  const applyDocumentLang = (l: Language) => {
    if (typeof document !== "undefined") {
      const d: Direction = l === "ar" ? "rtl" : "ltr";
      document.documentElement.lang = l;
      document.documentElement.dir = d;
      document.body.dir = d;
      if (l === "en") {
        document.documentElement.classList.add("lang-en");
        document.documentElement.classList.remove("lang-ar");
      } else {
        document.documentElement.classList.add("lang-ar");
        document.documentElement.classList.remove("lang-en");
      }
    }
  };

  const setLang = (newLang: Language) => {
    setLangState(newLang);
    applyDocumentLang(newLang);
    try {
      localStorage.setItem("ghostbot_lang", newLang);
    } catch {}
    // Persist server-side so telemetry renders in the same language.
    (async () => {
      try {
        const [{ supabase }, api] = await Promise.all([
          import("@/lib/supabaseClient"),
          import("@/lib/api"),
        ]);
        const { data } = await supabase.auth.getSession();
        const uid = data?.session?.user?.id;
        if (!uid) return;
        await api.setUserLanguage(newLang, uid).catch(() => {});
      } catch {}
    })();
  };

  const toggleLang = () => {
    setLang(lang === "ar" ? "en" : "ar");
  };

  const t = (key: string, fallback?: string): string => {
    const dict = translations[lang] || translations.ar;
    if (dict[key] !== undefined) {
      return dict[key];
    }
    // Fallback to Arabic dict if key missing in English
    if (translations.ar[key] !== undefined) {
      return translations.ar[key];
    }
    return fallback || key;
  };

  const dir: Direction = lang === "ar" ? "rtl" : "ltr";

  return (
    <LanguageContext.Provider value={{ lang, dir, setLang, toggleLang, t }}>
      {children}
    </LanguageContext.Provider>
  );
}

export function useLanguage() {
  const ctx = useContext(LanguageContext);
  if (!ctx) {
    throw new Error("useLanguage must be used within a LanguageProvider");
  }
  return ctx;
}
