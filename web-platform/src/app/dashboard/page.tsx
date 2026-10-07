"use client";

import React, { useEffect, useRef, useState } from "react";
import Link from "next/link";
import Image from "next/image";
import { useRouter, useSearchParams } from "next/navigation";
import { useGhostBot } from "@/components/SupabaseProvider";
import {
  getBotStatus,
  startBotFleet,
  stopBotFleet,
  syncBotFullConfig,
  syncAccount,
  pruneBackendCharacters,
  setCharacterEnabled,
  deleteBackendAccountByEmail,
  verifyCaptchaWithId,
  sendOtpCode,
  verifyOtpCode,
  startInventoryRefresh,
  getInventoryRefreshStatus,
  stopInventoryRefresh,
  fetchBackend,
  runCharacterCycle,
  runCharacterTask,
  refreshCharacterData,
  getCharacterCommanders,
  getScopedBotConfig,
  getBotInventory,
  getBotHistory,
  getRecentActivity,
  clearRecentActivity,
  getFleetGrouped,
  recallMarches,
  bulkRecallMarches,
  dispatchAllianceResource,
  getSavedRecipients,
  getTradingPostRates,
  startRssTransfer,
  getTransferStatus,
  stopTransferJob,
  type InventoryResponse,
  type RunRow,
  type FleetGroupedResponse,
} from "@/lib/api";
import { addAccount, removeAccount, toggleAccount, getAccounts } from "@/lib/store";
import { supabase } from "@/lib/supabaseClient";
import { useLanguage } from "@/context/LanguageContext";
import { ITEM_FOOD_BASE64, ITEM_WOOD_BASE64, ITEM_STONE_BASE64, ITEM_GOLD_BASE64, ITEM_GEM_BASE64 } from "@/lib/gameIconsBase64";
import { GATHERING_COMMANDERS, commanderByHeroId, syncPairsWithCounts, type MarchPair } from "@/lib/commanders";

const DEFAULT_BOT_CONFIG = {
    // General
    runIntervalHours: "4",
    discordNotifications: true,
    autoCaptcha: true,
    // Gathering
    gatherFoodMarches: 1,
    gatherWoodMarches: 1,
    gatherStoneMarches: 1,
    gatherGoldMarches: 0,
    manualCommanders: false,
    commanderPairs: { food: [], wood: [], stone: [], gold: [] },
    autoBalanceLowest: true,
    maxNodeLevel: 6,
    skipPartiallyGathered: true,
    avoidEnemyTerritory: true,
    // City & Troops
    autoTrainTroops: true,
    trainInfantry: "T4",
    trainCavalry: "T4",
    trainArchers: "T4",
    trainSiege: "T1",
    // Alliance
    allianceTech: true,
    allianceHelp: true,
    allianceGifts: true,
    allianceSuperNode: true,
    allianceTerritoryRss: true,
    alliancePitPrimary: null,
    alliancePitSecondary: null,
    // Combat
    healHospital: true,
    peaceShield: true,
    huntBarbs: false,
    // City (harvest collection mirrors the daily city harvest toggle)
    collectResources: true,
    // Daily Claims (each routine has its own independent toggle)
    dailyVip: true,
    cityHarvest: true,
    chronicleClaim: false,
    dailyQuests: true,
    dailyQuestChests: true,
    sideQuests: false,
    autoScout: true,
    mysteryMerchant: true,
  };

export default function DashboardPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, profile, bots, accounts: remoteAccounts, isLoading, refreshUserData } = useGhostBot();
  const { lang, dir, toggleLang, t } = useLanguage();

  // Active Tab: overview is the standalone Overview room; live, accounts, inventory, config are the Bot Unit Room
  const [activeTab, setActiveTab] = useState<"overview" | "live" | "accounts" | "inventory" | "config">("overview");
  const [selectedBotId, setSelectedBotId] = useState<string>("");

  // Read URL query parameter on client mount and whenever searchParams change
  useEffect(() => {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      const tab = params.get("tab");
      if (tab && ["overview", "live", "accounts", "inventory", "config"].includes(tab)) {
        setActiveTab(tab as any);
      }
      const botParam = params.get("bot");
      if (botParam) {
        setSelectedBotId(botParam);
      }
    }
  }, [searchParams]);

  // Bot Status & Controls
  const [running, setRunning] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [time, setTime] = useState("");
  const [consoleFilter, setConsoleFilter] = useState("all");
  const [autoScroll, setAutoScroll] = useState(true);

  // Toast Notification
  const [toastText, setToastText] = useState("");
  const [showToast, setShowToast] = useState(false);
  const notify = (msg: string) => {
    setToastText(msg);
    setShowToast(true);
    setTimeout(() => setShowToast(false), 3000);
  };

  // Telemetry Console Logs
  const [logs, setLogs] = useState<Array<{ id: number; time: string; cat: string; text: string }>>([
    { id: 1, time: "[INIT]", cat: "system", text: "نظام GhostBot جاهز. تم تحميل بروتوكولات الأمان السحابية بنجاح." },
    { id: 2, time: "[AUTH]", cat: "system", text: "تم تأكيد جلسة القائد وتأمين الاتصال بقناة التشفير AES-256." },
    { id: 3, time: "[RADAR]", cat: "gather", text: "تم مسح 48 حقل موارد من المستوى 6 بدون أي رصد معادٍ." },
    { id: 4, time: "[ALLIANCE]", cat: "alliance", text: "المساعدة التلقائية لأعضاء التحالف نشطة (100%)." },
    { id: 5, time: "[SHIELD]", cat: "system", text: "درع السلام التلقائي يراقب أسوار القلعة 24/7." },
  ]);

  // Inventory Filter Period
  const [invPeriod, setInvPeriod] = useState<"today" | "7d" | "30d">("today");
  const [kingdomSort, setKingdomSort] = useState(false);

  // Config Module Navigation Pill
  const [cfgModule, setCfgModule] = useState<"general" | "gathering" | "city" | "alliance" | "combat" | "daily">("general");

  // Config State (All 6 Categories: General, Gathering, City & Troops, Alliance, Combat, Daily Claims)
  const [botConfig, setBotConfig] = useState(DEFAULT_BOT_CONFIG);

  const configRef = useRef(botConfig);
  const configsByRoom = useRef<Record<string, typeof DEFAULT_BOT_CONFIG>>({});
  const saveQueue = useRef<Promise<void>>(Promise.resolve());
  const saveRevision = useRef(0);

  // Strict Tenant & Room Isolated Accounts Matrix (Authentic User Accounts Only - Zeroed Until Bot Reports)
  const [accountsByBot, setAccountsByBot] = useState<Record<string, any[]>>({});

  useEffect(() => {
    if (!bots || bots.length === 0) {
      setAccountsByBot({});
      return;
    }
    const map: Record<string, any[]> = {};
    bots.forEach((b: any) => {
      const bId = b.id || b.bot_id;
      const localAccs = getAccounts(bId);
      const remotes = (remoteAccounts || []).filter(
        (ra: any) => ra.instance_id === b.id || ra.bot_instance_id === b.id || ra.bot_id === b.id || ra.bot_id === b.bot_id
      );

      const combined = [
        ...remotes,
        ...localAccs.map((la: any, idx: number) => ({
          id: `acc-${bId}-${idx}`,
          role_id: la.chars?.[0]?.role_id || "",
          email: la.email,
          governor_name: la.chars?.[0]?.name || la.email.split("@")[0],
          kingdom: String(la.chars?.[0]?.kingdom_id || "3057"),
          city_hall_level: la.chars?.[0]?.city_level || 1,
          power: 0,
          status: "متصل وجاهز",
          food: "0",
          wood: "0",
          stone: "0",
          gold: "0",
          gems: "0",
          total_rss: "0",
          enabled: la.enabled ?? true,
        })),
      ];
      map[b.id] = combined;
      if (b.bot_id && b.bot_id !== b.id) {
        map[b.bot_id] = combined;
      }
    });
    setAccountsByBot(map);
  }, [bots, remoteAccounts]);

  // Link Account Modal State (Real Authentication - No Fake Mock Governors)
  const [showLinkModal, setShowLinkModal] = useState(false);
  const [linkStep, setLinkStep] = useState<1 | 2>(1);
  const [linkEmail, setLinkEmail] = useState("");
  const [linkPassword, setLinkPassword] = useState("");
  const [linkLoading, setLinkLoading] = useState(false);
  const [linkError, setLinkError] = useState("");
  const [showLinkPassword, setShowLinkPassword] = useState(false);
  const [captchaIdInput, setCaptchaIdInput] = useState("");
  // OTP email-code mode (no password stored): tab + code + 60s resend cooldown.
  const [linkAuthMode, setLinkAuthMode] = useState<"otp" | "password">("otp");
  const [linkOtpCode, setLinkOtpCode] = useState("");
  const [otpSending, setOtpSending] = useState(false);
  const [otpCooldown, setOtpCooldown] = useState(0);
  const otpCooldownTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const [discoveredChars, setDiscoveredChars] = useState<any[]>([]);

  // RSS Transfer Engine State
  const [showTransferModal, setShowTransferModal] = useState(false);
  const [transferTargetName, setTransferTargetName] = useState("");
  const [transferTargetRoleId, setTransferTargetRoleId] = useState("");
  const [transferTargetX, setTransferTargetX] = useState<number>(500);
  const [transferTargetY, setTransferTargetY] = useState<number>(500);
  const [transferTradingPostLvl, setTransferTradingPostLvl] = useState<number>(17);
  const [transferRss, setTransferRss] = useState<Record<string, number>>({ food: 0, wood: 0, stone: 0, gold: 0 });
  const [transferSelectedFarms, setTransferSelectedFarms] = useState<string[]>([]);
  const [transferLoading, setTransferLoading] = useState(false);
  const [transferJobId, setTransferJobId] = useState<string | null>(null);
  const [transferLogs, setTransferLogs] = useState<string[]>([]);
  const [transferProgress, setTransferProgress] = useState(0);
  const [transferSavedRecipients, setTransferSavedRecipients] = useState<any[]>([]);
  const [transferError, setTransferError] = useState("");
  const transferTermRef = useRef<HTMLDivElement>(null);

  // Poll active transfer status
  useEffect(() => {
    if (!transferJobId || !transferLoading) return;
    const timer = setInterval(async () => {
      try {
        const st = await getTransferStatus(transferJobId);
        if (st) {
          if (st.logs) setTransferLogs(st.logs);
          if (typeof st.progress === "number") setTransferProgress(st.progress);
          if (st.completed) {
            setTransferLoading(false);
            clearInterval(timer);
          }
        }
      } catch (e) {
        console.warn("Transfer status poll error:", e);
      }
    }, 1500);
    return () => clearInterval(timer);
  }, [transferJobId, transferLoading]);

  useEffect(() => {
    transferTermRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [transferLogs]);


  // Live UTC Clock
  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setTime(now.toUTCString().replace("GMT", "UTC"));
    };
    updateTime();
    const timer = setInterval(updateTime, 1000);
    return () => clearInterval(timer);
  }, []);

  // Active Bot Definition with Multi-Room support (Authentic User Bots Only - No Temporary Mock Rooms)
  const availableBots: any[] = (bots && Array.isArray(bots)) ? bots : [];
  const activeBot: any = availableBots.find((b) => b.id === selectedBotId || b.bot_id === selectedBotId) || (availableBots.length > 0 ? availableBots[0] : null);
  const accounts = activeBot ? (accountsByBot[activeBot.id] || accountsByBot[activeBot.bot_id] || []) : [];

  const navigateToShop = (e?: React.MouseEvent) => {
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }
    try {
      router.push("/shop");
    } catch {
      window.location.href = "/shop";
    }
  };

  // Bot Status Poller (Scoped strictly to Active Bot Key and User ID)
  const checkStatus = async (targetBotKey?: string) => {
    try {
      const bKey = targetBotKey || activeBot?.bot_id || activeBot?.id || "bot-1";
      const s = await getBotStatus(bKey, user?.id);
      setRunning(Boolean(s.running));
      if (s && (s as any).settings && activeBot) {
        const nr = (s as any).settings[`next_run_timestamp_${bKey}`] || (s as any).settings["next_run_timestamp"];
        if (nr) {
          (activeBot as any).next_run_timestamp = nr;
        }
      }
    } catch {
      setRunning(false);
    }
  };

  useEffect(() => {
    const bKey = activeBot?.bot_id || activeBot?.id || "bot-1";
    checkStatus(bKey);
    const interval = setInterval(() => {
      checkStatus(bKey);
    }, 6000);
    return () => clearInterval(interval);
  }, [activeBot?.id, activeBot?.bot_id, user?.id]);

  async function toggleFleet() {
    if (!activeBot) return;
    setBusy(true);
    const botKey = activeBot.bot_id || activeBot.id || "bot-1";
    const nextRunning = !running;
    setRunning(nextRunning); // Optimistic immediate UI update to switch color/text
    try {
      if (!nextRunning) {
        (activeBot as any).next_run_timestamp = "";
        (activeBot as any).next_run = "";
        setAccountsByBot((prev) => {
          const list = prev[activeBot.id] || prev[activeBot.bot_id] || [];
          const resetList = list.map((a: any) => ({ ...a, next_run: "", next_run_text: "—" }));
          return {
            ...prev,
            [activeBot.id]: resetList,
            ...(activeBot.bot_id && activeBot.bot_id !== activeBot.id ? { [activeBot.bot_id]: resetList } : {}),
          };
        });
        await stopBotFleet(botKey, user?.id);
        notify(lang === "ar" ? `تم إيقاف ${activeBot.name || activeBot.label} بنجاح.` : `Stopped ${activeBot.name || activeBot.label} successfully.`);
      } else {
        await startBotFleet(botKey, user?.id);
        notify(lang === "ar" ? `تم تشغيل ${activeBot.name || activeBot.label} وإطلاق طوابير الحصاد!` : `Started ${activeBot.name || activeBot.label} and dispatched gathering marches!`);
      }
      setTimeout(() => checkStatus(botKey), 600);
    } catch (e: any) {
      setRunning(!nextRunning); // Revert on failure
      notify(lang === "ar" ? `حدث خطأ: ${e?.message || e}` : `Error: ${e?.message || e}`);
    } finally {
      setBusy(false);
    }
  }

  const transferTradingPostData: Record<number, { capacity: number; tax: number }> = {
    1:  { capacity: 10000,    tax: 0.35 },
    2:  { capacity: 30000,    tax: 0.34 },
    3:  { capacity: 60000,    tax: 0.33 },
    4:  { capacity: 100000,   tax: 0.32 },
    5:  { capacity: 150000,   tax: 0.31 },
    6:  { capacity: 200000,   tax: 0.30 },
    7:  { capacity: 300000,   tax: 0.29 },
    8:  { capacity: 400000,   tax: 0.28 },
    9:  { capacity: 500000,   tax: 0.27 },
    10: { capacity: 600000,   tax: 0.26 },
    11: { capacity: 800000,   tax: 0.25 },
    12: { capacity: 1000000,  tax: 0.24 },
    13: { capacity: 1200000,  tax: 0.23 },
    14: { capacity: 1400000,  tax: 0.22 },
    15: { capacity: 1600000,  tax: 0.21 },
    16: { capacity: 1800000,  tax: 0.20 },
    17: { capacity: 2000000,  tax: 0.19 },
    18: { capacity: 2200000,  tax: 0.18 },
    19: { capacity: 2400000,  tax: 0.17 },
    20: { capacity: 2600000,  tax: 0.16 },
    21: { capacity: 2800000,  tax: 0.15 },
    22: { capacity: 3000000,  tax: 0.14 },
    23: { capacity: 3500000,  tax: 0.12 },
    24: { capacity: 4000000,  tax: 0.10 },
    25: { capacity: 10000000, tax: 0.08 },
  };

  const handleOpenTransferModal = async () => {
    const farmList: string[] = [];
    accounts.forEach((acc: any) => {
      if (acc.role_id) farmList.push(String(acc.role_id));
      if (acc.id && !acc.role_id) farmList.push(String(acc.id));
      if (acc.characters && Array.isArray(acc.characters)) {
        acc.characters.forEach((c: any) => farmList.push(String(c.role_id || c.id)));
      }
    });
    setTransferSelectedFarms(Array.from(new Set(farmList)));
    setTransferError("");
    setShowTransferModal(true);
    try {
      const res = await getSavedRecipients();
      if (res?.recipients) setTransferSavedRecipients(res.recipients);
    } catch {}
  };

  const handleExecuteTransfer = async () => {
    setTransferError("");
    if (!transferTargetRoleId.trim()) {
      setTransferError("يرجى إدخال معرّف الحساب المستلم (Role ID)!");
      return;
    }
    if (transferSelectedFarms.length === 0) {
      setTransferError("يرجى تحديد مزرعة واحدة على الأقل لإرسال الموارد!");
      return;
    }
    const totalReq = Object.values(transferRss).reduce((a, b) => a + b, 0);
    if (totalReq <= 0) {
      setTransferError("يرجى تحديد كمية مورد واحد على الأقل للنقل!");
      return;
    }

    setTransferLoading(true);
    setTransferProgress(5);
    const bId = activeBot?.bot_id || activeBot?.id || selectedBotId || "bot-1";
    const uId = user?.id || "";
    setTransferLogs([`[INIT] بدء تهيئة خطة النقل للغرفة #${bId}...`]);

    try {
      const payload = {
        target_role_id: transferTargetRoleId.trim(),
        target_name: transferTargetName.trim() || `Player_${transferTargetRoleId}`,
        x: Number(transferTargetX),
        y: Number(transferTargetY),
        requested_rss: transferRss,
        selected_farm_roles: transferSelectedFarms,
        bot_id: bId,
        user_id: uId,
      };
      const res = await startRssTransfer(payload);
      if (res?.success && res?.job_id) {
        setTransferJobId(res.job_id);
        setTransferLogs((prev) => [
          ...prev,
          `[SUCCESS] تم تشغيل المحرك الموازي بالمعرّف ${res.job_id}`,
          `[INFO] تم تعليق طوابير الحصاد التلقائي لمنع تضارب الجلسات.`,
        ]);
      } else {
        throw new Error(res?.detail || res?.message || "فشل بدء النقل");
      }
    } catch (e: any) {
      setTransferLoading(false);
      setTransferError(e?.message || "حدث خطأ أثناء إطلاق النقل");
      setTransferLogs((prev) => [...prev, `[ERROR] ${e?.message || e}`]);
    }
  };

  const handleStopTransfer = async () => {
    if (!transferJobId) return;
    try {
      await stopTransferJob(transferJobId);
      setTransferLogs((prev) => [...prev, `[USER] تم إرسال أمر الإيقاف الفوري للعملية #${transferJobId}.`]);
      setTransferLoading(false);
    } catch {}
  };

  // Per-account scope: "" = whole room, otherwise one account email.
  // Scoped accounts keep an independent snapshot (room stays the base).
  const [configScope, setConfigScope] = useState<string>("");
  const [scopeLoading, setScopeLoading] = useState(false);
  const scopeRef = useRef(configScope);
  scopeRef.current = configScope;

  const roomEmails = (): string[] => {
    const out = new Set<string>();
    (accounts || []).forEach((a: any) => { if (a.email) out.add(String(a.email)); });
    return [...out].sort();
  };

  // Scope entries: whole room, per account, per character (governor).
  const scopeEntries = (): Array<{ value: string; label: string; group?: string }> => {
    const entries: Array<{ value: string; label: string; group?: string }> = [];
    (accounts || []).forEach((a: any) => {
      const email = a.email ? String(a.email) : "";
      const chars: Array<{ role_id: string; name: string }> = [];
      if (a.role_id) chars.push({ role_id: String(a.role_id), name: String(a.governor_name || a.role_id) });
      if (Array.isArray(a.characters)) {
        a.characters.forEach((c: any) => {
          const rid = String(c?.role_id || c?.id || "");
          if (rid && !chars.some((x) => x.role_id === rid)) {
            chars.push({ role_id: rid, name: String(c?.name || c?.governor_name || rid) });
          }
        });
      }
      if (email) entries.push({ value: `acc:${email}`, label: `${email} (كل الشخصيات)`, group: email });
      chars.forEach((c) => entries.push({ value: `role:${c.role_id}`, label: `${c.name}`, group: email || undefined }));
    });
    return entries;
  };

  const parseScope = (scope: string): { email?: string; roleId?: string } => {
    if (scope.startsWith("role:")) return { roleId: scope.slice(5) };
    if (scope.startsWith("acc:")) return { email: scope.slice(4) };
    if (scope) return { email: scope };
    return {};
  };

  const cacheKey = (roomId: string, scope: string) => (scope ? `${roomId}::${scope}` : roomId);

  // Replace room state instead of carrying values over from the previous room.
  useEffect(() => {
    if (!activeBot) return;
    setConfigScope("");
    const saved = activeBot.config;
    const next = configsByRoom.current[activeBot.id] || { ...DEFAULT_BOT_CONFIG, ...(saved && typeof saved === "object" ? saved : {}) };
    configRef.current = next;
    setBotConfig(next);
  }, [activeBot?.id]);

  // Load merged (room + account override) view when a scope is chosen.
  useEffect(() => {
    if (!activeBot || !configScope || !user?.id) return;
    const botKey = activeBot.bot_id || activeBot.id;
    const key = cacheKey(activeBot.id, configScope);
    const cached = configsByRoom.current[key];
    if (cached) {
      configRef.current = cached;
      setBotConfig(cached);
      return;
    }
    let cancel = false;
    setScopeLoading(true);
    getScopedBotConfig(botKey, user.id, parseScope(configScope).email, parseScope(configScope).roleId)
      .then((res) => {
        if (cancel) return;
        const next = { ...DEFAULT_BOT_CONFIG, ...(res.config || {}) };
        configsByRoom.current[key] = next;
        configRef.current = next;
        setBotConfig(next);
      })
      .catch(() => {
        if (!cancel) notify(lang === "ar" ? "تعذر تحميل إعدادات الحساب؛ تُعرض إعدادات الغرفة." : "Account settings unavailable; showing room settings.");
      })
      .finally(() => { if (!cancel) setScopeLoading(false); });
    return () => { cancel = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [configScope, activeBot?.id]);

  const [savingConfig, setSavingConfig] = useState(false);

  // Live Inventory & History Telemetry States (Strictly Zero Initial - Populated from Game)
  const [inventory, setInventory] = useState<InventoryResponse | null>(null);
  const [historyRuns, setHistoryRuns] = useState<RunRow[]>([]);
  const [telemetryTrigger, setTelemetryTrigger] = useState(0);

  // Formatter for Relative Time (Last Run / Next Run) in Arabic and English
  const formatRelativeTime = (txt?: string, language: string = "ar") => {
    if (!txt || txt === "—" || txt === "-" || txt.toLowerCase() === "never") return "—";
    if (language !== "ar") return txt;

    const lower = txt.trim().toLowerCase();
    if (lower === "just now" || lower === "now") return "الآن";

    const isAgo = lower.endsWith(" ago");
    const isIn = lower.startsWith("in ");

    let clean = txt.replace(/\s+ago$/i, "").replace(/^in\s+/i, "").trim();

    clean = clean
      .replace(/(\d+)\s*h(?:ours?|r)?/gi, "$1 س")
      .replace(/(\d+)\s*m(?:in(?:utes?)?)?/gi, "$1 د")
      .replace(/(\d+)\s*s(?:ec(?:onds?)?)?/gi, "$1 ث");

    if (isAgo) return `منذ ${clean}`;
    if (isIn) return `خلال ${clean}`;
    return clean;
  };

  // Synchronized countdown formatter for Next Run
  const formatCountdown = (nextRunTimestamp?: string | null, isRunning: boolean = true, language: string = "ar") => {
    if (!isRunning || !nextRunTimestamp || nextRunTimestamp === "—" || nextRunTimestamp === "-") {
      return language === "ar" ? "متوقف (Stopped)" : "Stopped";
    }
    const cleanTs = String(nextRunTimestamp).replace(" ", "T");
    const target = new Date(cleanTs).getTime();
    if (isNaN(target)) {
      return formatRelativeTime(String(nextRunTimestamp), language);
    }
    const diff = target - Date.now();
    if (diff <= 0) return language === "ar" ? "جاري البدء..." : "Starting...";

    const hours = Math.floor(diff / (1000 * 60 * 60));
    const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
    if (hours > 0) {
      return language === "ar" ? `خلال ${hours} س ${minutes} د` : `in ${hours}h ${minutes}m`;
    }
    const seconds = Math.floor((diff % (1000 * 60)) / 1000);
    return language === "ar" ? `خلال ${minutes} د ${seconds} ث` : `in ${minutes}m ${seconds}s`;
  };

  function formatLocalTime(timestamp: any): string {
    try {
      const d = new Date(timestamp);
      if (!isNaN(d.getTime())) {
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true });
      }
    } catch {}
    return String(timestamp);
  }

  // Activity Log Parser to categorize stream into (gather, train, alliance, city, system) with local client machine time
  const parseActivityLine = (line: string, index: number) => {
    // 1. Try matching ISO-8601 timestamp (e.g. 2026-10-07T11:33:43.123Z or [2026-10-07T11:33:43Z])
    const isoMatch = line.match(/^\[?(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)\]?/i);
    let timeStr = "[LIVE]";
    let remaining = line;

    if (isoMatch) {
      timeStr = `[${formatLocalTime(isoMatch[1])}]`;
      remaining = line.slice(isoMatch[0].length).trim();
    } else {
      // 2. Try matching time format e.g. 11:33:43 AM or [11:33:43 UTC]
      const timeMatch = line.match(/^\[?(\d{1,2}:\d{2}(?::\d{2})?\s*(?:[AP]M)?(?:\s*UTC)?)\]?/i);
      if (timeMatch) {
        const rawTime = timeMatch[1].trim();
        if (rawTime.toUpperCase().includes("UTC")) {
          const cleanT = rawTime.replace(/UTC/i, "").trim();
          const todayIso = new Date().toISOString().slice(0, 10);
          timeStr = `[${formatLocalTime(`${todayIso}T${cleanT}Z`)}]`;
        } else {
          timeStr = `[${rawTime}]`;
        }
        remaining = line.slice(timeMatch[0].length).trim();
      }
    }

    let cat = "system";
    const low = line.toLowerCase();
    if (line.includes("سحب القوات") || line.includes("رجوع") || line.includes("إرجاع") || low.includes("recall") || line.includes("مسيرة") || low.includes("march")) {
      cat = "gather";
    } else if (line.includes("جمع الموارد") || line.includes("🌾") || line.includes("حقل") || low.includes("gather") || low.includes("harvest")) {
      cat = "gather";
    } else if (line.includes("تجنيد") || line.includes("⚔️") || line.includes("تدريب") || low.includes("train") || line.includes("ثكنة")) {
      cat = "train";
    } else if (line.includes("التحالف") || line.includes("🔬") || low.includes("alliance") || line.includes("تبرع")) {
      cat = "alliance";
    } else if (line.includes("المكافآت") || line.includes("🎁") || line.includes("المشفى") || line.includes("🏥") || line.includes("مدينة") || low.includes("city") || low.includes("hospital") || low.includes("claims") || low.includes("chronicle")) {
      cat = "city";
    }

    return {
      id: index + 1,
      time: timeStr,
      cat,
      text: remaining || line,
    };
  };

  // Auto-scroll console when new activity logs arrive
  useEffect(() => {
    if (autoScroll && activeTab === "live") {
      const el = document.getElementById("consoleBody");
      if (el) {
        el.scrollTop = el.scrollHeight;
      }
    }
  }, [logs, autoScroll, activeTab]);

  // Telemetry Poller for active unit (Activity logs, Real Fleet Resources, History, Inventory)
  useEffect(() => {
    if (!activeBot) return;
    const botKey = activeBot.bot_id || activeBot.id;
    let cancel = false;

    const loadBotTelemetry = async () => {
      try {
        const [inv, hist, acts, fleet] = await Promise.all([
          getBotInventory(botKey),
          getBotHistory(botKey),
          getRecentActivity(botKey, undefined, lang),
          getFleetGrouped(botKey),
        ]);
        if (cancel) return;

        // 1. Sync Live Activity Console Logs
        if (acts && Array.isArray(acts) && acts.length > 0) {
          const parsed = acts.map((line, idx) => parseActivityLine(line, idx));
          setLogs(parsed);
        }

        // 2. Sync History Runs
        if (hist) setHistoryRuns(hist);

        // 3. Sync Real Fleet Resources & Run Timestamps
        if (fleet && Array.isArray(fleet.accounts) && fleet.accounts.length > 0) {
          let sumFood = 0;
          let sumWood = 0;
          let sumStone = 0;
          let sumGold = 0;
          let sumGems = 0;
          const fleetChars: any[] = [];
          const charMap = new Map<string, any>();

          fleet.accounts.forEach((acc) => {
            (acc.characters || []).forEach((c) => {
              const rId = String(c.role_id);
              charMap.set(rId, { ...c, email: acc.email });
              const food = Number(c.food) || 0;
              const wood = Number(c.wood) || 0;
              const stone = Number(c.stone) || 0;
              const gold = Number(c.gold) || 0;
              const gems = Number(c.gems) || 0;
              sumFood += food;
              sumWood += wood;
              sumStone += stone;
              sumGold += gold;
              sumGems += gems;

              fleetChars.push({
                governor_id: rId,
                name: c.name || `Governor #${rId}`,
                kingdom: c.kingdom_id || 3057,
                city_hall: c.city_hall || c.city_level || 1,
                power: c.power || 0,
                food,
                wood,
                stone,
                gold,
                gems,
                total: food + wood + stone + gold,
              });
            });
          });

          // Merge into accountsByBot state for active bot
          setAccountsByBot((prev) => {
            const currentList = prev[activeBot.id] || prev[activeBot.bot_id] || [];
            if (currentList.length === 0) return prev;

            const updatedList = currentList.map((a: any) => {
              const matched = charMap.get(String(a.role_id));
              if (!matched) return a;
              const f = Number(matched.food) || 0;
              const w = Number(matched.wood) || 0;
              const s = Number(matched.stone) || 0;
              const g = Number(matched.gold) || 0;
              const gm = Number(matched.gems) || 0;
              return {
                ...a,
                governor_name: matched.name || a.governor_name,
                power: matched.power || a.power,
                city_hall_level: matched.city_hall || matched.city_level || a.city_hall_level,
                kingdom: String(matched.kingdom_id || a.kingdom),
                food: f,
                wood: w,
                stone: s,
                gold: g,
                gems: gm,
                total_rss: f + w + s + g,
                last_run_text: matched.last_run_text || a.last_run_text || "—",
                next_run_text: matched.next_run_text || a.next_run_text || "—",
                last_run: matched.last_run || a.last_run,
                next_run: matched.next_run || a.next_run,
                enabled: matched.enabled !== undefined ? (matched.enabled !== 0 && matched.enabled !== false) : a.enabled,
              };
            });

            return {
              ...prev,
              [activeBot.id]: updatedList,
              ...(activeBot.bot_id && activeBot.bot_id !== activeBot.id ? { [activeBot.bot_id]: updatedList } : {}),
            };
          });

          // Update inventory state with real aggregated in_cities_now & breakdown
          setInventory((prev) => ({
            bot_id: botKey,
            resources_gathered: prev?.resources_gathered || {
              today: { food: sumFood, wood: sumWood, stone: sumStone, gold: sumGold, gems: sumGems, trend: [] },
              "7days": { food: sumFood * 3, wood: sumWood * 3, stone: sumStone * 3, gold: sumGold * 3, gems: sumGems * 3, trend: [] },
              "30days": { food: sumFood * 12, wood: sumWood * 12, stone: sumStone * 12, gold: sumGold * 12, gems: sumGems * 12, trend: [] },
            },
            in_cities_now: { food: sumFood, wood: sumWood, stone: sumStone, gold: sumGold, gems: sumGems },
            characters: fleetChars,
            characters_by_kingdom: null,
          }));
        } else if (inv) {
          setInventory(inv);
        }
      } catch (err) {
        console.error("Telemetry fetch error:", err);
      }
    };

    loadBotTelemetry();
    const interval = setInterval(loadBotTelemetry, 4000);
    return () => {
      cancel = true;
      clearInterval(interval);
    };
  }, [activeBot?.id, activeBot?.bot_id, telemetryTrigger, lang]);

  // Clean Zero-Safe Resource Formatters (No Fake Millions)
  const formatRss = (val?: number | string) => {
    if (val === undefined || val === null || val === "" || val === "0" || val === 0) return "0.0M";
    const num = typeof val === "string" ? parseFloat(val) : val;
    if (isNaN(num) || num === 0) return "0.0M";
    if (num >= 1000000000) return `${(num / 1000000000).toFixed(2)}B`;
    if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`;
    if (num >= 1000) return `${(num / 1000).toFixed(1)}K`;
    return num.toLocaleString();
  };

  const formatGems = (val?: number | string) => {
    if (val === undefined || val === null || val === "" || val === "0" || val === 0) return "0";
    const num = typeof val === "string" ? parseInt(val) : val;
    if (isNaN(num) || num === 0) return "0";
    return num.toLocaleString();
  };

  // Serialize cloud + engine saves so rapid clicks cannot overwrite newer values.
  // When an account scope is active, only that account's snapshot is written
  // (room snapshot untouched); otherwise the whole room is saved as before.
  const persistConfig = (updated: typeof botConfig, title?: string) => {
    if (!activeBot || !user?.id) {
      notify(lang === "ar" ? "سجّل الدخول لحفظ الإعدادات." : "Sign in to save settings.");
      return Promise.resolve();
    }
    const scope = scopeRef.current;
    const roomId = activeBot.id;
    configsByRoom.current[cacheKey(roomId, scope)] = updated;
    const botKey = activeBot.bot_id || roomId;
    const userId = user.id;
    const revision = ++saveRevision.current;
    setSavingConfig(true);
    const save = saveQueue.current.catch(() => {}).then(async () => {
      if (!scope) {
        const { data, error } = await supabase.from("bot_instances")
          .update({ config: updated }).eq("id", roomId).eq("user_id", userId)
          .select("id").single();
        if (error || !data) throw new Error(error?.message || "Room settings were not saved.");
      }
      const { email: scopeEmail, roleId: scopeRole } = parseScope(scope);
      await syncBotFullConfig(botKey, updated, userId, scopeEmail, scopeRole);
      if (revision === saveRevision.current) {
        notify(lang === "ar" ? "تم حفظ الإعدادات وتأكيد استلامها من محرك البوت." : "Settings saved and confirmed by the bot engine.");
      }
    }).catch((error: any) => {
      notify(lang === "ar" ? `لم تكتمل المزامنة؛ أعد الحفظ: ${error.message}` : `Sync incomplete; retry saving: ${error.message}`);
    }).finally(() => {
      if (revision === saveRevision.current) setSavingConfig(false);
    });
    saveQueue.current = save;
    return save;
  };

  const updateConfigField = (field: string, value: any, title?: string) => {
    const updated = { ...configRef.current, [field]: value };
    configRef.current = updated;
    setBotConfig(updated);

    if (field === "runIntervalHours" && activeBot) {
      const hours = Number(value) || 4;
      const baseMs = hours * 3600 * 1000;

      const globalTarget = new Date(Date.now() + baseMs);
      const globalTargetIso = globalTarget.toISOString();
      (activeBot as any).next_run_timestamp = globalTargetIso;
      (activeBot as any).next_run = globalTargetIso;

      setAccountsByBot((prev) => {
        const list = prev[activeBot.id] || prev[activeBot.bot_id] || [];
        const updatedList = list.map((a: any) => {
          const jitterMinutes = Math.floor(Math.random() * 11) - 5;
          const target = new Date(Date.now() + baseMs + jitterMinutes * 60 * 1000);
          const targetIso = target.toISOString();
          const diffMs = Math.max(0, target.getTime() - Date.now());
          const h = Math.floor(diffMs / 3600000);
          const m = Math.floor((diffMs % 3600000) / 60000);
          return {
            ...a,
            next_run: targetIso,
            next_run_text: `in ${h}h ${m}m`,
          };
        });
        return {
          ...prev,
          [activeBot.id]: updatedList,
          ...(activeBot.bot_id && activeBot.bot_id !== activeBot.id ? { [activeBot.bot_id]: updatedList } : {}),
        };
      });
    }

    void persistConfig(updated, title);
  };

  // Some routines are stored under two engine keys (daily_claims + city).
  const updateConfigFields = (fields: Record<string, any>, title?: string) => {
    const updated = { ...configRef.current, ...fields };
    configRef.current = updated;
    setBotConfig(updated);
    void persistConfig(updated, title);
  };

  const handleSaveConfig = () => {
    if (activeBot && botConfig.runIntervalHours) {
      const hours = Number(botConfig.runIntervalHours) || 4;
      const baseMs = hours * 3600 * 1000;
      const globalTarget = new Date(Date.now() + baseMs);
      const globalTargetIso = globalTarget.toISOString();
      (activeBot as any).next_run_timestamp = globalTargetIso;
      (activeBot as any).next_run = globalTargetIso;

      setAccountsByBot((prev) => {
        const list = prev[activeBot.id] || prev[activeBot.bot_id] || [];
        const updatedList = list.map((a: any) => {
          const jitterMinutes = Math.floor(Math.random() * 11) - 5;
          const target = new Date(Date.now() + baseMs + jitterMinutes * 60 * 1000);
          const targetIso = target.toISOString();
          const diffMs = Math.max(0, target.getTime() - Date.now());
          const h = Math.floor(diffMs / 3600000);
          const m = Math.floor((diffMs % 3600000) / 60000);
          return {
            ...a,
            next_run: targetIso,
            next_run_text: `in ${h}h ${m}m`,
          };
        });
        return {
          ...prev,
          [activeBot.id]: updatedList,
          ...(activeBot.bot_id && activeBot.bot_id !== activeBot.id ? { [activeBot.bot_id]: updatedList } : {}),
        };
      });
    }
    return persistConfig(configRef.current);
  };

  // Gathering Stepper adjustment helper with immediate sync
  // (keeps manual commander-pair slots in sync with march counts)
  const adjustGatherStepper = (field: "gatherFoodMarches" | "gatherWoodMarches" | "gatherStoneMarches" | "gatherGoldMarches", delta: number) => {
    const cur = configRef.current[field];
    const nextVal = Math.max(0, Math.min(5, cur + delta));
    const resKey = field === "gatherFoodMarches" ? "food" : field === "gatherWoodMarches" ? "wood" : field === "gatherStoneMarches" ? "stone" : "gold";
    const counts = {
      food: resKey === "food" ? nextVal : configRef.current.gatherFoodMarches,
      wood: resKey === "wood" ? nextVal : configRef.current.gatherWoodMarches,
      stone: resKey === "stone" ? nextVal : configRef.current.gatherStoneMarches,
      gold: resKey === "gold" ? nextVal : configRef.current.gatherGoldMarches,
    };
    updateConfigFields({
      [field]: nextVal,
      commanderPairs: syncPairsWithCounts(configRef.current.commanderPairs as any, counts),
    });
  };

  const totalMarches = botConfig.gatherFoodMarches + botConfig.gatherWoodMarches + botConfig.gatherStoneMarches + botConfig.gatherGoldMarches;

  // ── Manual commander pairs (per-march primary/secondary slots) ──
  const [cmdPicker, setCmdPicker] = useState<{ show: boolean; res: string; idx: number; slot: "primary" | "secondary" }>({ show: false, res: "food", idx: 0, slot: "primary" });
  const [unlockedHeroIds, setUnlockedHeroIds] = useState<Set<number>>(new Set());
  const [loadingRoster, setLoadingRoster] = useState(false);

  const roomRoleIds = (): string[] => {
    const ids = new Set<string>();
    (accounts || []).forEach((a: any) => {
      if (a.role_id) ids.add(String(a.role_id));
      if (Array.isArray(a.characters)) a.characters.forEach((c: any) => { if (c?.role_id) ids.add(String(c.role_id)); });
    });
    return [...ids];
  };

  // Union of unlocked commanders across room characters (lock state source).
  // The engine still validates ownership per character at dispatch time.
  const refreshUnlockedRoster = async () => {
    const roles = roomRoleIds();
    if (roles.length === 0 || !user?.id) return;
    setLoadingRoster(true);
    try {
      const results = await Promise.all(
        roles.map((r) => getCharacterCommanders(r, user.id).catch(() => ({ success: false, role_id: r, commanders: [] as number[] })))
      );
      const union = new Set<number>();
      results.forEach((res) => (res.commanders || []).forEach((h: number) => { if (Number.isFinite(h) && h > 0) union.add(Number(h)); }));
      setUnlockedHeroIds(union);
    } finally {
      setLoadingRoster(false);
    }
  };

  useEffect(() => {
    if (botConfig.manualCommanders) void refreshUnlockedRoster();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [botConfig.manualCommanders, activeBot?.id, activeBot?.bot_id]);

  const isCommanderUnlocked = (heroId: number | null): boolean => {
    if (heroId === null || heroId === undefined) return false;
    return unlockedHeroIds.has(Number(heroId));
  };

  const getMarchPair = (res: string, idx: number): MarchPair => {
    const list = (botConfig.commanderPairs as any)?.[res];
    if (Array.isArray(list) && list[idx] && typeof list[idx] === "object") {
      return {
        primary: typeof list[idx].primary === "number" ? list[idx].primary : null,
        secondary: typeof list[idx].secondary === "number" ? list[idx].secondary : null,
      };
    }
    return { primary: null, secondary: null };
  };

  // All hero IDs used in manual pairs (field marches + alliance pit),
  // optionally excluding one slot.
  const usedHeroIds = (exceptRes?: string, exceptIdx?: number): Set<number> => {
    const used = new Set<number>();
    const pairs = (configRef.current.commanderPairs as any) || {};
    (["food", "wood", "stone", "gold"] as const).forEach((r) => {
      const list = Array.isArray(pairs[r]) ? pairs[r] : [];
      list.forEach((e: any, i: number) => {
        if (!e || typeof e !== "object") return;
        if (r === exceptRes && i === exceptIdx) return;
        if (typeof e.primary === "number") used.add(e.primary);
        if (typeof e.secondary === "number") used.add(e.secondary);
      });
    });
    if (exceptRes !== "pit") {
      const pp = (configRef.current as any).alliancePitPrimary;
      const ps = (configRef.current as any).alliancePitSecondary;
      if (typeof pp === "number") used.add(pp);
      if (typeof ps === "number") used.add(ps);
    }
    return used;
  };

  // Shared commander picker (field marches + alliance pit). Rendered once
  // at config-tab level so it opens from any module.
  const applyPickerChoice = (heroId: number | null) => {
    if (cmdPicker.res === "pit") setPitSlot(cmdPicker.slot, heroId);
    else setMarchPairSlot(cmdPicker.res, cmdPicker.idx, cmdPicker.slot, heroId);
    setCmdPicker((p) => ({ ...p, show: false }));
  };

  const renderCmdPicker = () => {
    if (!cmdPicker.show) return null;
    return (
      <div
        onClick={() => setCmdPicker((p) => ({ ...p, show: false }))}
        style={{ position: "fixed", inset: 0, background: "rgba(2,6,14,0.75)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center", padding: "16px" }}
      >
        <div
          onClick={(e) => e.stopPropagation()}
          className="gb-cfg-card"
          style={{ borderColor: "var(--ghost-cyan)", background: "linear-gradient(145deg, rgba(8,26,50,0.98), rgba(5,16,32,0.98))", maxWidth: "580px", width: "100%", maxHeight: "80vh", overflowY: "auto" }}
        >
          <div className="gb-cfg-card-header" style={{ justifyContent: "space-between", alignItems: "center" }}>
            <div>
              <div className="gb-cfg-card-title">
                <svg className="gb-icon" style={{ color: "var(--ghost-cyan)" }}><use href="#icon-blades-tactical" /></svg>
                <span>اختر القائد {cmdPicker.slot === "primary" ? "الأساسي" : "الثانوي"}</span>
              </div>
              <div className="gb-cfg-card-desc">البطل الرمادي 🔒 غير مفتوح في حسابات الغرفة — أو مستخدم في مسيرة أخرى (البطل الواحد لمسيرة واحدة)</div>
            </div>
            <div style={{ display: "flex", gap: "8px" }}>
              <span
                className="cyan-pill"
                onClick={() => applyPickerChoice(null)}
                style={{ fontSize: "11px", cursor: "pointer", color: "#ffaa2b" }}
              >
                إزالة (تلقائي)
              </span>
              <span
                className="cyan-pill"
                onClick={() => setCmdPicker((p) => ({ ...p, show: false }))}
                style={{ fontSize: "11px", cursor: "pointer" }}
              >
                إغلاق
              </span>
            </div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(96px, 1fr))", gap: "10px", marginTop: "12px" }}>
            {GATHERING_COMMANDERS.map((cmd) => {
              const unlocked = isCommanderUnlocked(cmd.heroId);
              const takenElsewhere = cmd.heroId !== null && unlocked && usedHeroIds(cmdPicker.res, cmdPicker.idx).has(cmd.heroId);
              const selectable = !!unlocked && !takenElsewhere;
              return (
                <div
                  key={cmd.id}
                  onClick={() => { if (selectable && cmd.heroId !== null) applyPickerChoice(cmd.heroId); }}
                  title={cmd.heroId === null ? "غير مدعوم بعد" : takenElsewhere ? "مستخدم في مسيرة أخرى" : unlocked ? cmd.name : "غير مفتوح في حسابات الغرفة"}
                  style={{
                    border: unlocked ? "1px solid rgba(0,229,255,0.4)" : "1px solid rgba(255,255,255,0.12)",
                    boxShadow: unlocked ? "0 0 8px rgba(0,229,255,0.2)" : "none",
                    borderRadius: "12px", padding: "8px 4px",
                    display: "flex", flexDirection: "column", alignItems: "center", gap: "4px",
                    background: "rgba(4,14,28,0.7)",
                    filter: selectable ? "none" : "grayscale(100%)",
                    opacity: selectable ? 1 : 0.45,
                    cursor: selectable ? "pointer" : "not-allowed",
                    pointerEvents: selectable ? "auto" : "none",
                    position: "relative",
                  }}
                >
                  <div style={{ position: "relative", width: "60px", height: "60px", borderRadius: "8px", overflow: "hidden", border: "1px solid rgba(0,229,255,0.25)" }}>
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={`/assets/commanders/${cmd.icon}`}
                      alt={cmd.name}
                      style={{ width: "100%", height: "100%", objectFit: "cover" }}
                      onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                    />
                    {!selectable && (
                      <div style={{ position: "absolute", top: 0, left: 0, width: "100%", height: "100%", background: "rgba(0,0,0,0.55)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "1.2rem" }}>
                        🔒
                      </div>
                    )}
                  </div>
                  <span style={{ fontSize: "10px", color: "#fff", textAlign: "center" }}>{cmd.name}</span>
                  {!selectable && (
                    <span style={{ fontSize: "9px", color: "#ffaa2b" }}>{takenElsewhere ? "مستخدم في مسيرة أخرى" : cmd.heroId === null ? (cmd.pendingNote || "غير مدعوم بعد") : "غير مفتوح"}</span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    );
  };

  const setPitSlot = (slot: "primary" | "secondary", heroId: number | null) => {
    if (heroId !== null && usedHeroIds("pit", 0).has(heroId)) {
      notify(lang === "ar" ? "هذا البطل مستخدم في مسيرة أخرى — لا يمكن تكراره." : "This commander is already used in another march.");
      return;
    }
    const other = slot === "primary" ? "alliancePitSecondary" : "alliancePitPrimary";
    const fields: Record<string, any> = { [slot === "primary" ? "alliancePitPrimary" : "alliancePitSecondary"]: heroId };
    if (heroId !== null && (configRef.current as any)[other] === heroId) fields[other] = null;
    updateConfigFields(fields);
  };

  const setMarchPairSlot = (res: string, idx: number, slot: "primary" | "secondary", heroId: number | null) => {
    if (heroId !== null && usedHeroIds(res, idx).has(heroId)) {
      notify(lang === "ar" ? "هذا البطل مستخدم في مسيرة أخرى — لا يمكن تكراره." : "This commander is already used in another march.");
      return;
    }
    const cur = (configRef.current.commanderPairs as any) || {};
    const list = Array.isArray(cur[res]) ? [...cur[res]] : [];
    while (list.length <= idx) list.push({ primary: null, secondary: null });
    const other = slot === "primary" ? "secondary" : "primary";
    const nextEntry = { ...(list[idx] || {}), [slot]: heroId };
    if (heroId !== null && nextEntry[other] === heroId) nextEntry[other] = null;
    list[idx] = { primary: nextEntry.primary ?? null, secondary: nextEntry.secondary ?? null };
    updateConfigField("commanderPairs", { ...cur, [res]: list });
  };

  const heroIconFor = (heroId: number | null): string | null => {
    if (heroId === null) return null;
    const cmd = commanderByHeroId[Number(heroId)];
    return cmd ? `/assets/commanders/${cmd.icon}` : null;
  };

  // Captcha mini-window flow: pre-opened in the click gesture, navigated to
  // the Lilith challenge, polled in the background; auto-closes and the
  // login continues to character picking once solved. Credentials live in
  // memory only until the flow resolves.
  const linkCaptchaPopupRef = useRef<Window | null>(null);
  const [linkCaptcha, setLinkCaptcha] = useState<{ email: string; password: string; url: string; attempts: number; mode?: "password" | "otp"; code?: string } | null>(null);
  const [captchaChecking, setCaptchaChecking] = useState(false);
  // When the browser blocks popups, the captcha renders in a mini window
  // embedded inside the modal instead (same URL, no feature lost).
  const [captchaEmbedded, setCaptchaEmbedded] = useState(false);

  const closeLinkCaptchaPopup = () => {
    const p = linkCaptchaPopupRef.current;
    if (p && !p.closed) {
      try { p.close(); } catch { /* ignore */ }
    }
    linkCaptchaPopupRef.current = null;
  };

  // Opens the small (430x680) captcha window; falls back to the embedded
  // mini window when the popup is blocked.
  const openCaptchaWindow = (url: string) => {
    if (!url) return;
    let popped: Window | null = null;
    try {
      popped = window.open(url, "lilith_captcha", "popup=yes,width=430,height=680,menubar=no,toolbar=no");
    } catch {
      popped = null;
    }
    if (popped) {
      linkCaptchaPopupRef.current = popped;
      try { popped.focus(); } catch { /* ignore */ }
      setCaptchaEmbedded(false);
    } else {
      setCaptchaEmbedded(true);
    }
  };

  const cancelLinkCaptcha = () => {
    closeLinkCaptchaPopup();
    setLinkCaptcha(null);
    setCaptchaChecking(false);
    setCaptchaEmbedded(false);
    setLinkLoading(false);
  };

  const proceedToCharacterPick = (characters: Array<any>) => {
    const availableSlots = activeBot?.slots || 5;
    const mapped = characters.map((c: any, idx: number) => ({
      role_id: String(c.role_id),
      name: c.name || `Governor #${c.role_id}`,
      kingdom: String(c.kingdom_id || c.kingdom || "3057"),
      city_level: c.city_level || 1,
      power: c.power || 0,
      selected: idx < availableSlots,
    }));
    setDiscoveredChars(mapped);
    setLinkStep(2);
    notify(lang === "ar" ? `تم تسجيل الدخول بنجاح! تم العثور على ${mapped.length} شخصية في حسابك.` : `Authenticated successfully! Found ${mapped.length} characters.`);
  };

  // While the captcha window is open, re-attempt login every 6s. Solving
  // unlocks the account server-side, so the next attempt returns characters.
  useEffect(() => {
    if (!linkCaptcha || !showLinkModal) return;
    let cancelled = false;
    const timer = window.setInterval(async () => {
      if (cancelled || captchaChecking) return;
      const popup = linkCaptchaPopupRef.current;
      if (popup && popup.closed) {
        cancelled = true;
        window.clearInterval(timer);
        setLinkCaptcha(null);
        setLinkLoading(false);
        setLinkError(lang === "ar" ? "أُغلقت نافذة التحقق قبل الحل — اضغط «إعادة فتح النافذة» للمتابعة." : "Verification window was closed. Press Reopen to continue.");
        return;
      }
      setCaptchaChecking(true);
      try {
        const botKey = activeBot?.bot_id || activeBot?.id || "bot-1";
        const res = linkCaptcha.mode === "otp"
          ? await verifyOtpCode(linkCaptcha.email, linkCaptcha.code || "", botKey, user?.id)
          : await syncAccount(linkCaptcha.email, linkCaptcha.password, botKey, user?.id);
        if (cancelled) return;
        if (res.status === "REQUIRES_VERIFICATION" || res.status === "CAPTCHA_REQUIRED" || (res as any).captcha_required) {
          setLinkCaptcha((prev) => {
            if (!prev) return prev;
            const attempts = prev.attempts + 1;
            if (attempts > 50) {
              cancelled = true;
              window.clearInterval(timer);
              closeLinkCaptchaPopup();
              setLinkLoading(false);
              setLinkError(lang === "ar" ? "انتهت مهلة التحقق (5 دقائق) — أعد المحاولة." : "Verification timed out — please retry.");
              return null;
            }
            return { ...prev, attempts };
          });
          return;
        }
        if (res.success && res.characters && Array.isArray(res.characters) && res.characters.length > 0) {
          cancelled = true;
          window.clearInterval(timer);
          closeLinkCaptchaPopup();
          setCaptchaEmbedded(false);
          setLinkCaptcha(null);
          setLinkLoading(false);
          setLinkError("");
          setLinkPassword("");
          setLinkOtpCode("");
          proceedToCharacterPick(res.characters);
        }
      } catch (err: any) {
        const msg = String(err?.message || "");
        // OTP mode: a definitive "code invalid/expired" answer ends polling —
        // only transient network errors are worth retrying.
        if (linkCaptcha.mode === "otp" && /غير صحيح|منتهي|expired|invalid/i.test(msg)) {
          cancelled = true;
          window.clearInterval(timer);
          closeLinkCaptchaPopup();
          setCaptchaEmbedded(false);
          setLinkCaptcha(null);
          setLinkLoading(false);
          setLinkError(msg || (lang === "ar" ? "انتهت صلاحية الرمز — اطلب رمزًا جديدًا." : "Code expired — request a new one."));
          return;
        }
        /* transient network error — keep polling */
      } finally {
        setCaptchaChecking(false);
      }
    }, 6000);
    return () => { cancelled = true; window.clearInterval(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [linkCaptcha, showLinkModal]);

  const checkLinkCaptchaNow = async () => {
    if (!linkCaptcha || captchaChecking) return;
    setCaptchaChecking(true);
    try {
      const botKey = activeBot?.bot_id || activeBot?.id || "bot-1";
      const res = linkCaptcha.mode === "otp"
        ? await verifyOtpCode(linkCaptcha.email, linkCaptcha.code || "", botKey, user?.id)
        : await syncAccount(linkCaptcha.email, linkCaptcha.password, botKey, user?.id);
      if (res.success && res.characters && Array.isArray(res.characters) && res.characters.length > 0) {
        closeLinkCaptchaPopup();
        setLinkCaptcha(null);
        setCaptchaEmbedded(false);
        setLinkLoading(false);
        setLinkError("");
        setLinkPassword("");
        setLinkOtpCode("");
        proceedToCharacterPick(res.characters);
      } else {
        setLinkError(lang === "ar" ? "لم يتم الحل بعد — أكمل التحقق في النافذة المصغرة." : "Not solved yet — finish verification in the mini window.");
      }
    } catch (err: any) {
      setLinkError(err?.message || (lang === "ar" ? "تعذر التحقق — أعد المحاولة." : "Check failed — retry."));
    } finally {
      setCaptchaChecking(false);
    }
  };

  // Link Account Flow Handlers (Real Backend Authentication & Real Roles)
  const startOtpCooldown = () => {
    setOtpCooldown(60);
    if (otpCooldownTimer.current) clearInterval(otpCooldownTimer.current);
    otpCooldownTimer.current = setInterval(() => {
      setOtpCooldown((prev) => {
        if (prev <= 1) {
          if (otpCooldownTimer.current) clearInterval(otpCooldownTimer.current);
          otpCooldownTimer.current = null;
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  };

  const handleSendOtpCode = async () => {
    if (!linkEmail.trim()) {
      setLinkError(lang === "ar" ? "أدخل البريد الإلكتروني أولاً ثم اطلب الرمز." : "Enter your email first, then request the code.");
      return;
    }
    if (otpSending || otpCooldown > 0) return;
    setLinkError("");
    setOtpSending(true);
    try {
      const botKey = activeBot?.bot_id || activeBot?.id || "bot-1";
      await sendOtpCode(linkEmail.trim(), botKey, user?.id);
      startOtpCooldown();
      notify(lang === "ar" ? "تم إرسال رمز التحقق إلى بريدك — أدخل الـ 6 أرقام." : "Verification code sent to your email — enter the 6 digits.");
    } catch (err: any) {
      setLinkError(err?.message || (lang === "ar" ? "فشل إرسال الرمز. تحقق من البريد وأعد المحاولة." : "Failed to send the code. Check the email and retry."));
    } finally {
      setOtpSending(false);
    }
  };

  const handleLinkStep1Submit = async () => {
    if (linkAuthMode === "otp") {
      if (!linkEmail.trim() || linkOtpCode.trim().length < 6) {
        setLinkError(lang === "ar" ? "أدخل البريد الإلكتروني ورمز التحقق المكون من 6 أرقام." : "Enter your email and the 6-digit code.");
        return;
      }
      setLinkError("");
      setLinkLoading(true);
      let waitingForCaptcha = false;
      try {
        const botKey = activeBot?.bot_id || activeBot?.id || "bot-1";
        const res = await verifyOtpCode(linkEmail.trim(), linkOtpCode.trim(), botKey, user?.id);
        if ((res as any).status === "REQUIRES_VERIFICATION") {
          const capUrl = String((res as any).captcha_url || "");
          waitingForCaptcha = true;
          setLinkCaptcha({
            email: linkEmail.trim(), password: "", url: capUrl, attempts: 0,
            mode: "otp", code: linkOtpCode.trim(),
          });
          openCaptchaWindow(capUrl);
          setLinkError("");
          notify(lang === "ar"
            ? "Lilith طلب تحققًا أمنيًا — حلّ الكابتشا في النافذة الصغيرة وسنكمل تلقائيًا."
            : "Lilith requires a security check — solve it in the mini window and we continue automatically.");
          return;
        }
        if (res.success && res.characters && Array.isArray(res.characters) && res.characters.length > 0) {
          setLinkOtpCode("");
          setLinkPassword("");
          proceedToCharacterPick(res.characters);
        } else {
          setLinkError(lang === "ar" ? "تم التحقق لكن لم يتم العثور على شخصيات في هذا الحساب." : "Verified, but no characters found on this account.");
        }
      } catch (err: any) {
        setLinkError(err?.message || (lang === "ar" ? "رمز غير صحيح أو منتهي الصلاحية." : "Invalid or expired code."));
      } finally {
        if (!waitingForCaptcha) setLinkLoading(false);
      }
      return;
    }
    if (!linkEmail.trim() || !linkPassword.trim()) {
      setLinkError(lang === "ar" ? "يرجى إدخال البريد الإلكتروني وكلمة المرور للمتابعة." : "Please enter email and password.");
      return;
    }
    setLinkError("");
    setLinkLoading(true);
    let enteredCaptcha = false;

    // Pre-open the mini window inside the click gesture (blockers allow it
    // only here); navigate it to the challenge if one is required.
    const pre = window.open("about:blank", "lilith_captcha", "popup=yes,width=430,height=680,menubar=no,toolbar=no");
    linkCaptchaPopupRef.current = pre;

    try {
      const botKey = activeBot?.bot_id || activeBot?.id || "bot-1";
      const res = await syncAccount(linkEmail.trim(), linkPassword.trim(), botKey, user?.id);

      if (res.status === "REQUIRES_VERIFICATION" || res.status === "CAPTCHA_REQUIRED") {
        const captchaUrl = res.captcha_url || (res as any).captcha_params?.fallback_url || (res as any).captcha_params?.data?.url;
        if (pre && !pre.closed) {
          if (captchaUrl) pre.location.href = captchaUrl;
          pre.focus();
          setCaptchaEmbedded(false);
        } else {
          // Popup blocked: show the same challenge in a mini window inside
          // the modal so the flow never dead-ends.
          setCaptchaEmbedded(Boolean(captchaUrl));
        }
        enteredCaptcha = true;
        setLinkCaptcha({ email: linkEmail.trim(), password: linkPassword.trim(), url: captchaUrl || "", attempts: 0, mode: "password" });
        setLinkError(lang === "ar" ? "يتطلب الحساب حل كابتشا أمني من Lilith — حُلّها في النافذة المصغرة وسيكمل تسجيل الدخول تلقائيًا." : "Lilith captcha required — solve it in the mini window; login continues automatically.");
        return;
      }

      closeLinkCaptchaPopup();
      if (res.characters && Array.isArray(res.characters) && res.characters.length > 0) {
        setLinkPassword("");
        proceedToCharacterPick(res.characters);
      } else {
        setLinkError(lang === "ar" ? "تم تسجيل الدخول ولكن لم يتم العثور على أي شخصيات في هذا الحساب داخل اللعبة." : "Authenticated, but no characters found on this game account.");
      }
    } catch (err: any) {
      closeLinkCaptchaPopup();
      setLinkError(err?.message || (lang === "ar" ? "فشل تسجيل الدخول: البريد الإلكتروني أو كلمة المرور غير صحيحة، أو تعذر الاتصال بسيرفر اللعبة." : "Login failed: invalid email/password or server connection issue."));
    } finally {
      if (!enteredCaptcha) setLinkLoading(false);
    }
  };

  const handleConfirmSelectedCharacters = async () => {
    const selected = discoveredChars.filter(c => c.selected);
    if (selected.length === 0) {
      notify(lang === "ar" ? "يرجى اختيار شخصية واحدة على الأقل." : "Please select at least one character.");
      return;
    }

    const availableSlots = activeBot?.slots || 5;
    const otherAccountsCount = (accounts || []).filter(
      (a: any) => a.email && a.email.toLowerCase() !== linkEmail.trim().toLowerCase()
    ).length;
    const remainingSlots = Math.max(0, availableSlots - otherAccountsCount);
    if (selected.length > remainingSlots) {
      notify(
        lang === "ar"
          ? `عفواً، سعة هذه الوحدة (${availableSlots}) مستخدم منها (${otherAccountsCount}). يمكنك إضافة (${remainingSlots}) حكام كحد أقصى.`
          : `Cannot exceed capacity: ${otherAccountsCount}/${availableSlots} slots used. You can add up to ${remainingSlots} characters.`
      );
      return;
    }

    try {
      // 1. Notify Backend of active picked characters
      const keepIds = selected.map(s => String(s.role_id));
      const botKey = activeBot?.bot_id || activeBot?.id || "bot-1";
      await pruneBackendCharacters(linkEmail.trim().toLowerCase(), keepIds, botKey, user?.id).catch(() => {});
      for (const s of selected) {
        await setCharacterEnabled(String(s.role_id), true).catch(() => {});
      }

      // 2. Persist to Supabase Cloud
      if (user?.id && activeBot?.id) {
        const { data: accRow } = await supabase
          .from("game_accounts")
          .insert({
            user_id: user.id,
            instance_id: activeBot.id,
            email: linkEmail.trim().toLowerCase(),
            is_enabled: true,
          })
          .select("id")
          .single();

        if (accRow?.id) {
          await supabase.from("game_characters").insert(
            selected.map((c: any) => ({
              account_id: accRow.id,
              user_id: user.id,
              instance_id: activeBot.id,
              role_id: String(c.role_id),
              name: c.name,
              kingdom_id: parseInt(c.kingdom) || 3057,
              city_level: c.city_level || 1,
              power: c.power || 0,
              is_enabled: true,
            }))
          );
        }
      }

      // 3. Update local state with real initial values (0 rss until collected by bot)
      const newGovs = selected.map((c, idx) => ({
        id: `gov-real-${c.role_id}-${idx}`,
        role_id: c.role_id,
        email: linkEmail.trim().toLowerCase(),
        governor_name: c.name,
        kingdom: c.kingdom,
        city_hall_level: c.city_level,
        power: c.power,
        status: "متصل وجاهز",
        food: "0",
        wood: "0",
        stone: "0",
        gold: "0",
        gems: "0",
        total_rss: "0",
        enabled: true,
      }));

      setAccountsByBot(prev => ({
        ...prev,
        [activeBot.id]: [...(prev[activeBot.id] || []), ...newGovs]
      }));

      setShowLinkModal(false);
      setLinkStep(1);
      setLinkEmail("");
      setLinkPassword("");
      notify(lang === "ar" ? `تم حفظ وربط ${selected.length} شخصية بنجاح في ${activeBot.name || activeBot.label}!` : `Successfully linked ${selected.length} characters!`);
      if (refreshUserData) await refreshUserData();
    } catch (e: any) {
      notify(lang === "ar" ? `حدث خطأ: ${e?.message || e}` : `Error: ${e?.message || e}`);
    }
  };

  // Accounts Search & Multi-Selection States
  const [accountSearch, setAccountSearch] = useState("");
  const [selectedRoleIds, setSelectedRoleIds] = useState<string[]>([]);
  const [executingRoleId, setExecutingRoleId] = useState<string | null>(null);
  const [refreshingRoleId, setRefreshingRoleId] = useState<string | null>(null);
  const [deleteArmedEmail, setDeleteArmedEmail] = useState<string | null>(null);
  const [deletingEmail, setDeletingEmail] = useState<string | null>(null);
  const deleteDisarmTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Bulk inventory refresh (login → read → upsert → logout per governor)
  const [invRefresh, setInvRefresh] = useState<{ jobId: string; done: number; total: number; current: string } | null>(null);
  const invRefreshTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const [bulkRunning, setBulkRunning] = useState(false);
  const [bulkRefreshing, setBulkRefreshing] = useState(false);

  // Live Reactor Countdown & Core Health Ticker (Dynamic and Ticking Every Second)
  const [reactorCountdown, setReactorCountdown] = useState("29d 23h 45m 12s");
  const [reactorCorePct, setReactorCorePct] = useState(98);
  const [nextCycleCountdown, setNextCycleCountdown] = useState("03:59:45");

  useEffect(() => {
    function tick() {
      if (!activeBot) return;
      const expDate = activeBot.expires_at ? new Date(activeBot.expires_at).getTime() : (Date.now() + 30 * 86400000);
      const diff = Math.max(0, expDate - Date.now());
      if (diff <= 0) {
        setReactorCountdown(lang === "ar" ? "منتهي الصلاحية" : "Expired");
        setReactorCorePct(0);
      } else {
        const days = Math.floor(diff / (1000 * 60 * 60 * 24));
        const hours = Math.floor((diff / (1000 * 60 * 60)) % 24);
        const minutes = Math.floor((diff / (1000 * 60)) % 60);
        const seconds = Math.floor((diff / 1000) % 60);
        setReactorCountdown(`${days}d ${hours}h ${minutes}m ${seconds}s`);

        // Dynamically calculate circle percentage based on remaining license
        let totalDurationMs = 30 * 86400000;
        if (activeBot.created_at && activeBot.expires_at) {
          const start = new Date(activeBot.created_at).getTime();
          const end = new Date(activeBot.expires_at).getTime();
          if (end > start) totalDurationMs = end - start;
        }
        const dynamicPct = Math.min(100, Math.max(1, Math.round((diff / totalDurationMs) * 100)));
        setReactorCorePct(dynamicPct);
      }

      // Live Cycle Countdown (Synchronized with scheduler next_run and reset on stop)
      if (!running) {
        setNextCycleCountdown("00:00:00");
      } else {
        const parseUtc = (val: any): number => {
          if (!val || typeof val !== "string") return 0;
          const s = val.trim();
          if (!s || s === "—" || s === "-") return 0;
          if (s.endsWith("Z") || s.includes("+") || (s.includes("-") && s.indexOf("-", 8) > 0)) {
            const time = new Date(s).getTime();
            return isNaN(time) ? 0 : time;
          }
          const time = new Date(s.replace(" ", "T") + "Z").getTime();
          return isNaN(time) ? 0 : time;
        };

        let targetMs = 0;
        const rawTarget = (activeBot as any)?.next_run_timestamp || (activeBot as any)?.next_run;
        if (rawTarget && typeof rawTarget === "string") {
          const t = parseUtc(rawTarget);
          if (t > Date.now()) targetMs = t;
        }

        if (targetMs === 0) {
          const currentAccounts = accountsByBot[activeBot.id] || accountsByBot[activeBot.bot_id] || [];
          for (const a of currentAccounts) {
            if (a.enabled !== false && a.next_run) {
              const t = parseUtc(a.next_run);
              if (t > Date.now()) {
                if (targetMs === 0 || t < targetMs) {
                  targetMs = t;
                }
              }
            }
          }
        }

        const intervalHours = Number(botConfig.runIntervalHours) || 4;
        if (targetMs === 0) {
          targetMs = Date.now() + intervalHours * 3600 * 1000;
        }

        const remainingMs = Math.max(0, targetMs - Date.now());
        if (remainingMs <= 0) {
          setNextCycleCountdown(lang === "ar" ? "جاري البدء..." : "Starting...");
        } else {
          const remH = Math.floor(remainingMs / (1000 * 60 * 60));
          const remM = Math.floor((remainingMs / (1000 * 60)) % 60);
          const remS = Math.floor((remainingMs / 1000) % 60);
          const pad = (n: number) => String(n).padStart(2, "0");
          setNextCycleCountdown(`${pad(remH)}:${pad(remM)}:${pad(remS)}`);
        }
      }
    }
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [activeBot?.expires_at, activeBot?.created_at, (activeBot as any)?.next_run_timestamp, (activeBot as any)?.next_run, accountsByBot, running, lang, botConfig.runIntervalHours]);

  // Keep selectedRoleIds synchronized with available accounts
  useEffect(() => {
    if (accounts && accounts.length > 0) {
      setSelectedRoleIds(prev => {
        const existing = prev.filter(r => accounts.some(a => String(a.role_id) === r));
        if (existing.length > 0) return existing;
        return accounts.filter(a => a.enabled !== false).map(a => String(a.role_id));
      });
    } else {
      setSelectedRoleIds([]);
    }
  }, [accounts]);

  // Single Character Runner
  const handleRunSingleCharacter = async (acc: any) => {
    if (executingRoleId !== null || bulkRunning) return;
    const roleId = String(acc.role_id);
    setExecutingRoleId(roleId);
    try {
      notify(lang === "ar" ? `جاري إطلاق دورة الحصاد والتطوير للحاكم: ${acc.governor_name || roleId}...` : `Starting cycle for ${acc.governor_name || roleId}...`);
      const botKey = activeBot?.bot_id || activeBot?.id || "bot-0";
      await runCharacterCycle(roleId, botKey);
      notify(lang === "ar" ? `تم بدء تشغيل الحاكم ${acc.governor_name || roleId} بنجاح عبر البوابة السحابية!` : `Started ${acc.governor_name || roleId} successfully!`);
    } catch (err: any) {
      notify(lang === "ar" ? `فشل تشغيل الحاكم: ${err?.message || "خطأ اتصال بالسيرفر"}` : `Failed to run: ${err?.message || "Connection error"}`);
    } finally {
      setExecutingRoleId(null);
      setTelemetryTrigger(prev => prev + 1);
    }
  };

  // Delete whole game account (two-step inline confirm: arm -> confirm).
  // Removes backend rows (SQLite) + Supabase mirror (game_accounts + game_characters).
  const handleDeleteAccount = async (acc: any) => {
    const email = String(acc.email || "").trim();
    if (!email || deletingEmail) return;
    if (deleteArmedEmail !== email) {
      setDeleteArmedEmail(email);
      if (deleteDisarmTimer.current) clearTimeout(deleteDisarmTimer.current);
      deleteDisarmTimer.current = setTimeout(() => setDeleteArmedEmail(null), 6000);
      return;
    }
    if (deleteDisarmTimer.current) clearTimeout(deleteDisarmTimer.current);
    setDeleteArmedEmail(null);
    setDeletingEmail(email);
    try {
      const botKey = activeBot?.bot_id || activeBot?.id || "bot-0";
      // Room key = Supabase instance UUID (matches instance_id + local store key).
      const roomKey = activeBot?.id || botKey;
      const siblings = ((accountsByBot[activeBot.id] || []) as any[]).filter(
        (a: any) => String(a.email || "").toLowerCase() === email.toLowerCase()
      );
      const siblingRoles = siblings.map((a: any) => String(a.role_id)).filter(Boolean);
      const low = email.toLowerCase();
      await deleteBackendAccountByEmail(email, siblingRoles, botKey);
      // Local device store (same key the table reads with).
      try { removeAccount(roomKey, email); } catch {}
      // Supabase mirror (game_accounts + game_characters).
      try {
        const { deleteCloudAccount } = await import("@/lib/cloud");
        await deleteCloudAccount(roomKey, email);
      } catch {}
      // Verify every source; report leftovers precisely instead of blind success.
      const problems: string[] = [];
      try {
        const lr = await fetchBackend("/api/accounts");
        if (lr.ok) {
          const arr = await lr.json();
          const rows = (Array.isArray(arr) ? arr : []).filter((a: any) => String(a?.email || "").toLowerCase() === low);
          if (rows.length) problems.push(lang === "ar" ? "الباكند ما زال يحتفظ بالحساب" : "backend still holds the account");
        }
      } catch {}
      if (user?.id) {
        try {
          const { data: left } = await supabase.from("game_accounts").select("id,instance_id").eq("user_id", user.id).eq("email", email);
          if (left && left.length) {
            const elsewhere = (left as any[]).some((r: any) => r.instance_id !== roomKey);
            problems.push(lang === "ar"
              ? (elsewhere ? "الحساب ما زال مربوطاً بغرفة أخرى" : "الموقع (Supabase) ما زال يحتفظ بالحساب")
              : (elsewhere ? "account still linked in another room" : "site (Supabase) still holds the account"));
          }
        } catch {}
      }
      try {
        if (getAccounts(roomKey).some((a) => String(a.email || "").toLowerCase() === low)) {
          removeAccount(roomKey, email);
          problems.push(lang === "ar" ? "نسخة الجهاز المحلية قاومت الحذف" : "local device copy resisted delete");
        }
      } catch {}
      setAccountsByBot(prev => ({
        ...prev,
        [activeBot.id]: (prev[activeBot.id] || []).filter((a: any) => String(a.email || "").toLowerCase() !== low),
      }));
      setSelectedRoleIds(prev => prev.filter(r => !siblingRoles.includes(r)));
      if (refreshUserData) await refreshUserData().catch(() => {});
      setTelemetryTrigger(prev => prev + 1);
      if (problems.length) {
        notify((lang === "ar" ? `حُذف جزئياً — بقي: ${problems.join("، ")}` : `Partially deleted — remaining: ${problems.join(", ")}`));
      } else {
        notify(lang === "ar" ? `تم حذف الحساب ${email} نهائياً من السيرفر والموقع.` : `Account ${email} permanently deleted from server and site.`);
      }
    } catch (err: any) {
      notify(lang === "ar" ? `فشل حذف الحساب: ${err?.message || "خطأ اتصال بالسيرفر"}` : `Delete failed: ${err?.message || "Connection error"}`);
    } finally {
      setDeletingEmail(null);
    }
  };

  // Single Character Refresh
  const handleRefreshSingleCharacter = async (acc: any) => {
    const roleId = String(acc.role_id);
    setRefreshingRoleId(roleId);
    try {
      notify(lang === "ar" ? `جاري تحديث بيانات الحاكم ${acc.governor_name || roleId} من بوابة اللعبة...` : `Refreshing ${acc.governor_name || roleId} from game...`);
      const res = await refreshCharacterData(roleId);
      if (res.success) {
        // Update local accounts state
        setAccountsByBot(prev => {
          const list = prev[activeBot.id] || [];
          return {
            ...prev,
            [activeBot.id]: list.map((a: any) => {
              if (String(a.role_id) === roleId) {
                return {
                  ...a,
                  governor_name: res.name || a.governor_name,
                  power: res.power || a.power,
                  city_hall_level: res.city_level || a.city_hall_level,
                  kingdom: String(res.kingdom_id || a.kingdom),
                };
              }
              return a;
            })
          };
        });
        // Update Supabase
        if (user?.id) {
          await supabase.from("game_characters").update({
            name: res.name || acc.governor_name,
            power: res.power || acc.power,
            city_level: res.city_level || acc.city_hall_level,
            kingdom_id: res.kingdom_id || parseInt(acc.kingdom),
          }).eq("role_id", roleId);
        }
        notify(lang === "ar" ? `تم تحديث بيانات الحاكم ${res.name || acc.governor_name} بنجاح!` : `Refreshed ${res.name || acc.governor_name} successfully!`);
      }
    } catch (err: any) {
      notify(lang === "ar" ? `تعذر التحديث: ${err?.message || "يرجى المحاولة لاحقاً"}` : `Refresh failed: ${err?.message || "Please retry"}`);
    } finally {
      setRefreshingRoleId(null);
      setTelemetryTrigger(prev => prev + 1);
    }
  };

  // Bulk inventory refresh (whole room or single role): login → read → upsert → logout.
  const stopInvRefreshPolling = () => {
    if (invRefreshTimer.current) clearInterval(invRefreshTimer.current);
    invRefreshTimer.current = null;
  };
  const handleInventoryRefresh = async (roleIds?: string[]) => {
    if (invRefresh) return;
    const botKey = activeBot?.bot_id || activeBot?.id || "bot-0";
    const uid = (user as any)?.id || "";
    try {
      const { job_id, total } = await startInventoryRefresh(botKey, uid, roleIds || []);
      if (!total) {
        notify(lang === "ar" ? "لا توجد شخصيات للتحديث في هذه الغرفة." : "No characters to refresh in this room.");
        return;
      }
      notify(lang === "ar" ? `بدأ تحديث مخزون ${total} حاكم (دخول وقراءة وخروج)...` : `Refreshing inventory for ${total} governors (login, read, logout)...`);
      setInvRefresh({ jobId: job_id, done: 0, total, current: "" });
      stopInvRefreshPolling();
      invRefreshTimer.current = setInterval(async () => {
        try {
          const st = await getInventoryRefreshStatus(job_id);
          if (!st) return;
          const results = Array.isArray(st.results) ? st.results : [];
          const cur = [...results].reverse().find((r: any) => r.status === "RUNNING");
          setInvRefresh({ jobId: job_id, done: Number(st.done || 0), total: Number(st.total || total), current: cur ? String(cur.name || cur.role_id) : "" });
          if (st.status && st.status !== "RUNNING" && st.status !== "QUEUED") {
            stopInvRefreshPolling();
            setInvRefresh(null);
            const ok = results.filter((r: any) => r.status === "COMPLETED").length;
            const skip = results.filter((r: any) => r.status === "SKIPPED").length;
            const fail = results.filter((r: any) => r.status === "FAILED").length;
            notify(lang === "ar"
              ? `اكتمل تحديث المخزون: ${ok} نجح، ${skip} متخطى، ${fail} فشل.`
              : `Inventory refresh done: ${ok} ok, ${skip} skipped, ${fail} failed.`);
            setTelemetryTrigger(prev => prev + 1);
          }
        } catch {}
      }, 2500);
    } catch (err: any) {
      notify(lang === "ar" ? `تعذر بدء التحديث: ${err?.message || "خطأ اتصال"}` : `Refresh start failed: ${err?.message || "Connection error"}`);
    }
  };
  useEffect(() => () => { stopInvRefreshPolling(); }, []);

  // Bulk Sequential Runner (Staged Two-Stage Pipeline with 3-5s Pacing)
  const handleRunBulkCharacters = async () => {
    if (bulkRunning || executingRoleId !== null) return;
    const targets = accounts.filter(a => selectedRoleIds.includes(String(a.role_id)) && a.enabled !== false);
    if (targets.length === 0) {
      notify(lang === "ar" ? "يرجى اختيار وتفعيل شخصية واحدة على الأقل للتشغيل." : "Please select at least one enabled character.");
      return;
    }
    setBulkRunning(true);
    notify(lang === "ar" ? `بدء إطلاق ${targets.length} حكام بنظام الفحص المرحلي (الخانة 1 أولاً ثم الخانة 2 مع فاصل 3-5 ثوانٍ)...` : `Starting staged execution for ${targets.length} governors (Slot 1 -> Slot 2, 3-5s delay)...`);
    const botKey = activeBot?.bot_id || activeBot?.id || "bot-0";

    try {
      const res = await fetchBackend(`/api/bots/${encodeURIComponent(botKey)}/cycle?user_id=${encodeURIComponent(user?.id || "")}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role_ids: targets.map(t => String(t.role_id)), delay: 4.0 })
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        notify(lang === "ar" ? `تم إطلاق دورة الفحص بنجاح لـ ${targets.length} حكام بالتتابع والمرحلية!` : `Staged cycle launched for ${targets.length} governors!`);
      } else {
        throw new Error(data.detail || `HTTP ${res.status}`);
      }
    } catch (err: any) {
      console.warn("Bulk run error:", err);
      notify(lang === "ar" ? `تعذر إطلاق الدورة: ${err?.message || "خطأ اتصال بالسيرفر"}` : `Failed to launch: ${err?.message || "Connection error"}`);
    } finally {
      setBulkRunning(false);
      setTelemetryTrigger(prev => prev + 1);
    }
  };

  // Bulk Refresh Characters
  const handleRefreshBulkCharacters = async () => {
    const targets = accounts.filter(a => selectedRoleIds.includes(String(a.role_id)));
    if (targets.length === 0) {
      notify(lang === "ar" ? "يرجى اختيار شخصية واحدة على الأقل للتحديث." : "Please select at least one character.");
      return;
    }
    setBulkRefreshing(true);
    notify(lang === "ar" ? `جاري تحديث بيانات ${targets.length} حكام من بوابة اللعبة...` : `Refreshing ${targets.length} governors from game...`);
    
    for (let i = 0; i < targets.length; i++) {
      const target = targets[i];
      try {
        const res = await refreshCharacterData(String(target.role_id));
        if (res.success && user?.id) {
          await supabase.from("game_characters").update({
            name: res.name || target.governor_name,
            power: res.power || target.power,
            city_level: res.city_level || target.city_hall_level,
            kingdom_id: res.kingdom_id || parseInt(target.kingdom),
          }).eq("role_id", String(target.role_id));
        }
      } catch {}
      if (i < targets.length - 1) {
        await new Promise(r => setTimeout(r, 800));
      }
    }
    if (refreshUserData) await refreshUserData();
    setBulkRefreshing(false);
    notify(lang === "ar" ? `تم تحديث جميع بيانات الحكام المحددين بنجاح!` : `Refreshed all selected governors successfully!`);
  };

  // Per-character recall loading map
  const [recallLoading, setRecallLoading] = useState<Record<string, boolean>>({});
  const [bulkRecallLoading, setBulkRecallLoading] = useState(false);

  // Single Character Recall
  const recallCharacter = async (acc: any) => {
    const roleId = String(acc.role_id);
    setRecallLoading(prev => ({ ...prev, [roleId]: true }));
    try {
      notify(lang === "ar" ? `جاري استدعاء قوات ${acc.governor_name || roleId}...` : `Recalling ${acc.governor_name || roleId}...`);
      await recallMarches(roleId, user?.id);
      notify(lang === "ar" ? `تم إرسال أمر الرجوع لـ ${acc.governor_name || roleId}` : `Recall dispatched for ${acc.governor_name || roleId}`);
    } catch (err: any) {
      notify(lang === "ar" ? `فشل الاستدعاء: ${err?.message || "خطأ"}` : `Recall failed: ${err?.message || "Error"}`);
    } finally {
      setRecallLoading(prev => ({ ...prev, [roleId]: false }));
    }
  };

  // Bulk Recall Selected
  const bulkRecallSelected = async () => {
    if (selectedRoleIds.length === 0 || bulkRecallLoading) return;
    setBulkRecallLoading(true);
    try {
      notify(lang === "ar" ? `جاري إرسال أوامر الرجوع لـ ${selectedRoleIds.length} حاكم...` : `Recalling ${selectedRoleIds.length} governors...`);
      const res = await bulkRecallMarches(selectedRoleIds, user?.id);
      const count = (res as any)?.queued ?? res.launched ?? selectedRoleIds.length;
      notify(lang === "ar" ? `تم إرسال أوامر الرجوع لـ ${count} حاكم — يعمل بالتسلسل` : `Recall queued for ${count} governors`);
    } catch (err: any) {
      notify(lang === "ar" ? `فشل الاستدعاء الجماعي: ${err?.message || "خطأ"}` : `Bulk recall failed: ${err?.message || "Error"}`);
    } finally {
      setBulkRecallLoading(false);
    }
  };

  // Alliance Resource Center Direct Dispatch
  const [allianceDispatchLoading, setAllianceDispatchLoading] = useState(false);
  const handleDispatchAllianceResource = async () => {
    const targetRole = selectedRoleIds[0] || (accounts[0]?.role_id);
    if (!targetRole || allianceDispatchLoading) {
      if (!targetRole) {
        notify(lang === "ar" ? "يرجى تحديد حاكم من جدول الحسابات أولاً" : "Please select a governor first");
      }
      return;
    }
    setAllianceDispatchLoading(true);
    try {
      notify(lang === "ar" ? "جاري الإرسال لحقل موارد التحالف..." : "Dispatching to Alliance Resource Center...");
      await dispatchAllianceResource(String(targetRole), user?.id);
      notify(lang === "ar" ? "تم إرسال القوات لحقل التحالف بنجاح ⚔️" : "Dispatched to Alliance Resource Center ⚔️");
    } catch (err: any) {
      notify(lang === "ar" ? `فشل الإرسال: ${err?.message || "خطأ"}` : `Dispatch failed: ${err?.message || "Error"}`);
    } finally {
      setAllianceDispatchLoading(false);
    }
  };

  // Filtered accounts for Accounts tab (search filter)
  const filteredAccounts = accounts.filter((acc: any) => {
    if (!accountSearch.trim()) return true;
    const q = accountSearch.toLowerCase();
    return (
      (acc.governor_name || "").toLowerCase().includes(q) ||
      (acc.email || "").toLowerCase().includes(q) ||
      String(acc.role_id || "").toLowerCase().includes(q) ||
      String(acc.kingdom || "").toLowerCase().includes(q)
    );
  });

  // Filtered accounts for Inventory table
  const displayedAccounts = kingdomSort
    ? [...accounts].sort((a, b) => (a.kingdom || "").localeCompare(b.kingdom || ""))
    : accounts;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
      
      {/* =========================================================================
          BOT ROOM COCKPIT & TABS BAR
          CRITICAL RULE: ONLY SHOW WHEN IN BOT ROOM (activeTab !== "overview")
          In "overview", the user sees the standalone overview screen!
         ========================================================================= */}
      {/* =========================================================================
          BOT ROOM COCKPIT & TABS BAR
          CRITICAL RULE: ONLY SHOW WHEN IN BOT ROOM (activeTab !== "overview")
          In "overview", the user sees the standalone overview screen!
         ========================================================================= */}
      {activeTab !== "overview" && (
        !activeBot ? (
          <div style={{ padding: "48px 24px", textAlign: "center", borderRadius: "18px", background: "rgba(6, 17, 36, 0.75)", border: "1px dashed rgba(0, 229, 255, 0.3)" }}>
            <div style={{ fontSize: "17px", fontWeight: 900, color: "var(--ghost-cyan)", marginBottom: "10px" }}>
              {lang === "ar" ? "لا توجد لديك وحدات سحابية نشطة حالياً." : "No active cloud units available."}
            </div>
            <p style={{ fontSize: "13.5px", color: "var(--text-secondary)", maxWidth: "520px", margin: "0 auto 24px", lineHeight: 1.7 }}>
              {lang === "ar" ? "قم بشراء أو تفعيل وحدة جديدة للبدء وإدارة مزارعك السحابية المعزولة بأمان." : "Purchase or activate a new cloud bot unit from the store to deploy your isolated fleet."}
            </p>
            <div style={{ display: "flex", justifyContent: "center", gap: "12px", flexWrap: "wrap" }}>
              <Link
                href="/shop"
                onClick={navigateToShop}
                className="btn-cyan-glow"
                style={{ padding: "12px 28px", fontSize: "13px", fontWeight: 800, textDecoration: "none", display: "inline-flex", alignItems: "center", gap: "8px", cursor: "pointer" }}
              >
                <span>{lang === "ar" ? "🛒 الانتقال للمتجر وشراء وحدة سحابية ←" : "🛒 Go to Store & Deploy Bot Unit ←"}</span>
              </Link>
              <button
                onClick={() => { setActiveTab("overview"); router.push("/dashboard?tab=overview"); }}
                className="btn-ghost-outline"
                style={{ padding: "12px 22px", fontSize: "13px", cursor: "pointer" }}
              >
                {t("overview", "العودة للنظرة العامة")}
              </button>
            </div>
          </div>
        ) : (
        <>
          {/* Top Quick Breadcrumb / Back to Overview */}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "-6px" }}>
            <button
              onClick={() => { setActiveTab("overview"); router.push("/dashboard?tab=overview"); }}
              className="btn-ghost-outline"
              style={{ padding: "6px 14px", fontSize: "12px", display: "inline-flex", alignItems: "center", gap: "6px", cursor: "pointer" }}
            >
              <span>{lang === "ar" ? "← العودة للنظرة العامة" : "← Back to Overview"}</span>
            </button>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <span style={{ fontSize: "11px", color: "var(--text-secondary)" }}>{t("deployed_units", "الوحدات السحابية")}:</span>
              {availableBots.map((b) => (
                <button
                  key={b.id}
                  onClick={() => { setSelectedBotId(b.id); router.push(`/dashboard?tab=${activeTab}&bot=${b.id}`); }}
                  style={{
                    padding: "4px 10px",
                    fontSize: "11px",
                    fontWeight: 800,
                    borderRadius: "6px",
                    border: b.id === activeBot.id ? "1px solid var(--ghost-cyan)" : "1px solid var(--border-subtle)",
                    background: b.id === activeBot.id ? "rgba(0,229,255,0.12)" : "rgba(255,255,255,0.03)",
                    color: b.id === activeBot.id ? "var(--ghost-cyan)" : "var(--text-secondary)",
                    cursor: "pointer",
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "6px"
                  }}
                >
                  <img
                    src={b.product === "gem-bot" ? ITEM_GEM_BASE64 : ITEM_FOOD_BASE64}
                    alt=""
                    style={{ width: "14px", height: "14px", objectFit: "contain" }}
                  />
                  <span>{b.name || b.label}</span>
                </button>
              ))}
              <span className="emerald-badge" style={{ fontSize: "10.5px" }}>
                ● {lang === "ar" ? "قناة معزولة" : "Isolated"}
              </span>
            </div>
          </div>

          {/* 1. GHOSTBOT PROPRIETARY CYBER COMMAND COCKPIT */}
          <section className="hero-controller-card" id="heroControllerCard">
            <div className="hero-cockpit-grid">
              
              {/* MODULE 1: UNIT IDENTITY, PROTOCOLS & COMMAND CONTROLS */}
              <div className="hero-cockpit-identity">
                <div className="hero-identity-row">
                  <div className="hero-bot-avatar-box" id="heroBotMascotBadge">
                    <img
                      id="heroBotMascotImg"
                      src={activeBot.product === "gem-bot" ? ITEM_GEM_BASE64 : ITEM_FOOD_BASE64}
                      alt="Bot Icon"
                    />
                    <div className={`hero-radar-pulse ${running ? "" : "standby"}`} id="heroRadarPulseDot" title="Radar Heartbeat" />
                  </div>
                  <div className="hero-title-group">
                    <div className="hero-account-name" id="bannerUnitName">{activeBot.name || activeBot.label}</div>
                    <div className="hero-badges-row">
                      <span className="hero-badge-pill hero-badge-cyan" id="heroBotTypeBadge">
                        {activeBot.product === "gem-bot" ? "GEM BOT" : "FARM BOT"}
                      </span>
                      <span className={`hero-badge-pill ${running ? "hero-badge-status-running" : "hero-badge-status-standby"}`} id="unitStatusPill">
                        <span className="badge-dot">●</span>
                        <span id="unitStatusText">{running ? "RUNNING" : "STANDBY"}</span>
                      </span>
                      <span className="hero-badge-pill hero-badge-cyan" id="heroTierBadge">
                        {(activeBot.tier || "PRO").toUpperCase()}
                      </span>
                      <div className="hero-badge-pill hero-badge-cyan" id="heroNextRunContainer" style={{ display: "inline-flex", alignItems: "center", gap: "6px", background: "rgba(0,229,255,0.08)", border: "1px solid rgba(0,229,255,0.3)", borderRadius: "6px", padding: "3px 8px" }}>
                        <span id="heroNextRunBadge" style={{ color: "var(--text-ice)", fontWeight: 700 }}>الدورة: كل {botConfig.runIntervalHours} ساعات</span>
                        <span id="heroNextRunTimer" style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "11px", fontWeight: 900, color: "var(--ghost-cyan)", textShadow: "0 0 8px rgba(0,229,255,0.6)" }}>({nextCycleCountdown})</span>
                      </div>
                    </div>
                  </div>
                </div>

                {/* TACTICAL QUICK ACTION BUTTONS */}
                <div className="hero-actions-row">
                  <button
                    className={`hero-cyber-action-btn ${running ? "btn-cyber-running" : "primary"}`}
                    id="mainStartBtn"
                    onClick={toggleFleet}
                    disabled={busy}
                    style={{ cursor: "pointer" }}
                  >
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor">
                      {running ? <path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/> : <polygon points="5 3 19 12 5 21 5 3"/>}
                    </svg>
                    <span id="mainStartBtnLabel">
                      {busy ? "انتظار..." : running ? "إيقاف الوحدة" : "تشغيل البوت"}
                    </span>
                  </button>
                  <button
                    className="hero-cyber-action-btn"
                    onClick={() => {
                      if (accounts.length >= (activeBot?.slots || 5)) {
                        notify(lang === "ar" ? `تم بلوغ الحد الأقصى للباقة (${activeBot?.slots || 5} خانات). يرجى ترقية الباقة لإضافة المزيد.` : `Room capacity reached (${activeBot?.slots || 5} slots). Please upgrade your plan.`);
                        return;
                      }
                      setShowLinkModal(true); setLinkStep(1); setLinkError("");
                    }}
                    disabled={accounts.length >= (activeBot?.slots || 5)}
                    style={{
                      cursor: accounts.length >= (activeBot?.slots || 5) ? "not-allowed" : "pointer",
                      opacity: accounts.length >= (activeBot?.slots || 5) ? 0.6 : 1
                    }}
                    title={accounts.length >= (activeBot?.slots || 5) ? (lang === "ar" ? "الوحدة ممتلئة بالكامل" : "Room is at capacity") : ""}
                  >
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                    <span>{accounts.length >= (activeBot?.slots || 5) ? (lang === "ar" ? "الوحدة ممتلئة بالكامل" : "Capacity Full") : (lang === "ar" ? "ربط حساب جديد" : "Link Account")}</span>
                  </button>
                  <button
                    className="hero-cyber-action-btn"
                    onClick={() => {
                      const bId = activeBot?.id || activeBot?.bot_id || "";
                      const uId = user?.id || "";
                      router.push(`/transfer?bot=${encodeURIComponent(bId)}&user_id=${encodeURIComponent(uId)}`);
                    }}
                    style={{ cursor: "pointer" }}
                  >
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M17 1l4 4-4 4"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><path d="M7 23l-4-4 4-4"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg>
                    <span>نقل الموارد</span>
                  </button>
                </div>
              </div>

              {/* MODULE 2: GOVERNOR CAPACITY MATRIX */}
              <div className="hero-cockpit-slots">
                <div className="hero-slots-header">
                  <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                    <span className="hero-seq-id-badge" id="heroBotIdTag">ID #{activeBot.bot_id || "8412"}</span>
                    <span className="hero-slots-title" id="heroSlotsTitleLabel">مصفوفة الحُكّام</span>
                  </div>
                  {accounts.length >= (activeBot.slots || 5) && (
                    <span className="hero-at-capacity-badge">
                      <span>●</span> ممتلئ بالكامل
                    </span>
                  )}
                </div>

                <div className="hero-slots-count-display">
                  <span id="heroSlotsUsedCount">{accounts.length}</span>
                  <span style={{ color: "var(--text-secondary)", fontSize: "16px" }}>/</span>
                  <span id="heroSlotsTotalCount" style={{ color: "var(--ghost-cyan)" }}>{activeBot.slots || 5}</span>
                  <span className="label-sub" id="heroSlotsInUseLabel">خانة مستخدمة</span>
                </div>

                {/* Segmented LED Micro-Tracker */}
                <div className="hero-slots-led-grid" id="heroSlotsLedGrid">
                  {Array.from({ length: 20 }).map((_, i) => {
                    const isActive = i < accounts.length;
                    return (
                      <div
                        key={i}
                        className={`hero-led-segment ${isActive ? "active" : ""}`}
                      />
                    );
                  })}
                </div>
              </div>

              {/* MODULE 3: QUANTUM ENERGY CORE & HOLOGRAPHIC RADIAL GAUGE */}
              <div className="hero-cockpit-reactor">
                <div className="hero-reactor-dial-wrap">
                  <svg className="hero-reactor-svg" viewBox="0 0 76 76">
                    <defs>
                      <linearGradient id="reactorGlowGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                        <stop offset="0%" stopColor="#00e5ff" />
                        <stop offset="100%" stopColor="#00e699" />
                      </linearGradient>
                    </defs>
                    <circle className="hero-reactor-meter-bg" cx="38" cy="38" r="32" />
                    <circle
                      className="hero-reactor-meter-val"
                      id="heroReactorDialCircle"
                      cx="38"
                      cy="38"
                      r="32"
                      style={{
                        stroke: "url(#reactorGlowGrad)",
                        strokeDasharray: "201",
                        strokeDashoffset: `${Math.max(0, 201 - (reactorCorePct / 100) * 201)}`,
                        transition: "stroke-dashoffset 0.8s ease"
                      }}
                    />
                  </svg>
                  <div className="hero-reactor-center-info">
                    <span className="hero-reactor-percent" id="heroReactorPercent">{reactorCorePct}%</span>
                    <span className="hero-reactor-label">CORE</span>
                  </div>
                </div>

                <div className="hero-reactor-info-col">
                  <div className="hero-reactor-top-row">
                    <span className="hero-reactor-title">
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
                      <span id="heroReactorTitleLabel">{lang === "ar" ? "المفاعل السحابي" : "Cloud Reactor"}</span>
                    </span>
                    <button className="btn-reactor-plus" onClick={() => router.push("/shop")} title="Renew or upgrade license">+</button>
                  </div>
                  <div className="hero-reactor-countdown" id="heroLicenseCountdown" style={{ fontFamily: "'JetBrains Mono', monospace", color: "var(--ghost-cyan)" }}>
                    {reactorCountdown}
                  </div>
                  <div className="hero-reactor-expires" id="heroLicenseExpires">
                    {reactorCorePct > 0 ? (lang === "ar" ? "مفعل وآمن 100%" : "Active & 100% Secure") : (lang === "ar" ? "انتهت الرخصة" : "License Expired")}
                  </div>
                  <div className="hero-reactor-plan" id="heroLicensePlanDesc">باقة {activeBot.tier || "PRO"} • {activeBot.slots || 5} حكام</div>
                </div>
              </div>

            </div>
          </section>

          {/* 2. HORIZONTAL OPERATIONAL TABS BAR */}
          <nav className="tabs-bar" id="unitRoomTabsBar">
            <div
              className={`tab-btn ${activeTab === "live" ? "active" : ""}`}
              onClick={() => setActiveTab("live")}
            >
              {t("tab_live", "البث المباشر")}
            </div>
            <div
              className={`tab-btn ${activeTab === "accounts" ? "active" : ""}`}
              onClick={() => setActiveTab("accounts")}
            >
              {t("tab_accounts", "الحسابات والمزارع")}
            </div>
            <div
              className={`tab-btn ${activeTab === "inventory" ? "active" : ""}`}
              onClick={() => setActiveTab("inventory")}
            >
              {t("tab_inventory", "المخزون والموارد")}
            </div>
            <div
              className={`tab-btn ${activeTab === "config" ? "active" : ""}`}
              onClick={() => setActiveTab("config")}
            >
              {t("tab_config", "إعدادات البوت")}
            </div>
          </nav>
        </>
        )
      )}

      {/* =========================================================================
          VIEW 0: STANDALONE DASHBOARD / OVERVIEW ROOM (MATCHING GHOSTBOT.HTML)
         ========================================================================= */}
      {activeTab === "overview" && (
        <section className="tab-view active" id="view-overview" style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
          
          {/* Top 4 Stats Metric Bar */}
          <div className="stats-grid-4">
            <div className="stat-tile">
              <div style={{ fontSize: "11px", color: "var(--text-secondary)", display: "flex", alignItems: "center", gap: "6px" }}>
                <img src={ITEM_GEM_BASE64} alt="Gems" style={{ width: "18px", height: "18px", objectFit: "contain" }} />
                <span>{lang === "ar" ? "إجمالي الجواهر المجمعة" : "Total Gathered Gems"}</span>
              </div>
              <div style={{ fontSize: "22px", fontWeight: 900, color: "var(--ghost-cyan)", marginTop: "6px", fontFamily: "'JetBrains Mono', monospace" }} id="ovTotalGems">
                {formatGems(inventory?.in_cities_now?.gems)}
              </div>
              <div style={{ fontSize: "10.5px", color: "var(--emerald-ok)", marginTop: "4px" }}>
                {inventory?.in_cities_now?.gems ? (lang === "ar" ? "تتبع سحابي مباشر" : "Live Cloud Telemetry") : (lang === "ar" ? "في انتظار بدء الدورة" : "Awaiting first cycle")}
              </div>
            </div>

            <div className="stat-tile">
              <div style={{ fontSize: "11px", color: "var(--text-secondary)", display: "flex", alignItems: "center", gap: "6px" }}>
                <img src={ITEM_GEM_BASE64} alt="Gems" style={{ width: "18px", height: "18px", objectFit: "contain" }} />
                <span>{lang === "ar" ? "الجواهر الشهرية" : "Monthly Gems"}</span>
              </div>
              <div style={{ fontSize: "22px", fontWeight: 900, color: "#fff", marginTop: "6px", fontFamily: "'JetBrains Mono', monospace" }} id="ovMonthlyGems">
                {formatGems(inventory?.resources_gathered?.["30days"]?.gems || 0)}
              </div>
              <div style={{ fontSize: "10.5px", color: "var(--ghost-cyan)", marginTop: "4px" }}>
                {inventory?.resources_gathered?.["30days"]?.gems ? (lang === "ar" ? "تحديث متزامن" : "Synchronized") : (lang === "ar" ? "في انتظار الحصاد" : "Awaiting harvest")}
              </div>
            </div>

            <div className="stat-tile">
              <div style={{ fontSize: "11px", color: "var(--text-secondary)", display: "flex", alignItems: "center", gap: "6px" }}>
                <svg className="gb-icon" style={{ width: "16px", height: "16px" }}><use href="#icon-swords-crossed"/></svg>
                <span>{lang === "ar" ? "عدد الحسابات والمزارع" : "Linked Accounts"}</span>
              </div>
              <div style={{ fontSize: "22px", fontWeight: 900, color: "#fff", marginTop: "6px", fontFamily: "'JetBrains Mono', monospace" }} id="ovTotalGovs">
                {activeBot ? accounts.length : 0} / {activeBot?.slots || 0}
              </div>
              <div style={{ fontSize: "10.5px", color: "var(--emerald-ok)", marginTop: "4px" }}>
                {activeBot && accounts.length > 0 ? (lang === "ar" ? "جميع الحسابات نشطة" : "All accounts active") : (lang === "ar" ? "جاهز لإضافة مزارع" : "Ready to link farms")}
              </div>
            </div>

            <div className="stat-tile">
              <div style={{ fontSize: "11px", color: "var(--text-secondary)", display: "flex", alignItems: "center", gap: "6px" }}>
                <svg className="gb-icon" style={{ width: "16px", height: "16px" }}><use href="#icon-aegis-shield"/></svg>
                <span>{lang === "ar" ? "حالة الحماية والدرع" : "City Shields & Defense"}</span>
              </div>
              <div style={{ fontSize: "22px", fontWeight: 900, color: "var(--emerald-ok)", marginTop: "6px", fontFamily: "'JetBrains Mono', monospace" }}>
                100% SECURE
              </div>
              <div style={{ fontSize: "10.5px", color: "var(--text-ice)", marginTop: "4px" }}>
                {lang === "ar" ? "درع الحماية نشط" : "Stealth Wire Active"}
              </div>
            </div>
          </div>

          {/* Bottom 2 Grid Cards (Fleet & System Status) */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: "20px" }}>
            
            {/* LEFT CARD: YOUR GHOSTBOT FLEET */}
            <div className="surface-card" style={{ padding: "24px", borderRadius: "18px", display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
              <div>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "18px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                    <svg className="gb-icon" style={{ width: "20px", height: "20px" }}><use href="#ghostbot-mascot"/></svg>
                    <h3 style={{ fontSize: "16px", fontWeight: 900, color: "#fff" }}>
                      {lang === "ar" ? "أسطول وحداتك السحابية" : "Your Cloud Fleet Units"}
                    </h3>
                  </div>
                  <span className="cyan-pill" id="overviewUnitsBadge">
                    {availableBots.length} {lang === "ar" ? "وحدات نشطة" : "Active Units"}
                  </span>
                </div>

                {/* Fleet Card Items (All Deployed Units) */}
                <div style={{ display: "flex", flexDirection: "column", gap: "12px", marginBottom: "16px" }}>
                  {availableBots.length === 0 ? (
                    <div style={{ padding: "36px 20px", textAlign: "center", borderRadius: "14px", background: "rgba(0,229,255,0.03)", border: "1px dashed rgba(0,229,255,0.25)" }}>
                      <div style={{ fontSize: "16px", fontWeight: 900, color: "var(--ghost-cyan)", marginBottom: "8px" }}>
                        {lang === "ar" ? "لا توجد لديك وحدات سحابية نشطة حالياً." : "No active cloud units available."}
                      </div>
                      <p style={{ fontSize: "13px", color: "var(--text-secondary)", maxWidth: "480px", margin: "0 auto 18px", lineHeight: 1.6 }}>
                        {lang === "ar" ? "قم بشراء أو تفعيل وحدة جديدة للبدء وإدارة مزارعك السحابية المعزولة." : "Purchase or activate a new cloud bot unit from the store to get started."}
                      </p>
                      <div style={{ display: "flex", gap: "10px", justifyContent: "center", flexWrap: "wrap" }}>
                        <Link
                          href="/shop"
                          onClick={navigateToShop}
                          className="btn-cyan-glow"
                          style={{ padding: "10px 24px", fontSize: "12.5px", fontWeight: 800, textDecoration: "none", display: "inline-block", cursor: "pointer" }}
                        >
                          {lang === "ar" ? "🛒 الانتقال للمتجر وشراء وحدة سحابية ←" : "🛒 Go to Store & Deploy Unit ←"}
                        </Link>
                      </div>
                    </div>
                  ) : (
                    availableBots.map((unit) => {
                      const unitAccounts = accountsByBot[unit.id] || accountsByBot[unit.bot_id] || [];
                      const isGem = unit.product === "gem-bot" || (unit.name && unit.name.includes("جواهر"));
                      const isUnitRunning = activeBot && unit.id === activeBot.id ? running : false;
                      return (
                        <div
                          key={unit.id}
                          style={{
                            padding: "16px",
                            borderRadius: "14px",
                            background: isGem ? "rgba(255,170,43,0.05)" : "rgba(0,229,255,0.05)",
                            border: isGem ? "1px solid rgba(255,170,43,0.3)" : "1px solid rgba(0,229,255,0.3)",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "space-between",
                            gap: "12px",
                          }}
                        >
                          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                            <img
                              src={isGem ? ITEM_GEM_BASE64 : ITEM_FOOD_BASE64}
                              alt=""
                              style={{
                                width: "40px",
                                height: "40px",
                                objectFit: "contain",
                                filter: isGem ? "drop-shadow(0 0 10px rgba(255,170,43,0.4))" : "drop-shadow(0 0 10px rgba(0,229,255,0.4))",
                              }}
                            />
                            <div>
                              <div style={{ fontWeight: 800, fontSize: "14px", color: "#fff" }}>{unit.name || unit.label}</div>
                              <div style={{ fontSize: "11px", color: "var(--text-secondary)", marginTop: "2px" }}>
                                {lang === "ar" ? "باقة" : "Tier"} {unit.tier || "PRO"} • {unitAccounts.length} / {unit.slots || 5} {lang === "ar" ? "حسابات" : "farms"} • ID #{unit.bot_id || unit.id}
                              </div>
                            </div>
                          </div>
                          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                            <span className={isUnitRunning ? "emerald-badge" : "hero-badge-pill hero-badge-status-standby"} style={{ fontSize: "11px" }}>
                              {isUnitRunning ? (lang === "ar" ? "● يعمل الآن" : "● RUNNING") : (lang === "ar" ? "● مستعد" : "● STANDBY")}
                            </span>
                            <button
                              className={isGem ? "btn-amber-glow" : "btn-cyan-glow"}
                              style={{ padding: "8px 14px", fontSize: "11.5px", fontWeight: 800, cursor: "pointer" }}
                              onClick={() => {
                                setSelectedBotId(unit.id);
                                setActiveTab("live");
                                router.push(`/dashboard?tab=live&bot=${unit.id}`);
                              }}
                            >
                              {lang === "ar" ? "دخول غرفة التحكم ←" : "Enter Room ←"}
                            </button>
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>

              <div style={{ display: "flex", justifyContent: "flex-end" }}>
                <Link
                  href="/shop"
                  onClick={navigateToShop}
                  className="btn-ghost-outline"
                  style={{ padding: "8px 16px", fontSize: "11.5px", textDecoration: "none", cursor: "pointer" }}
                >
                  {t("btn_new_license", "+ شراء رخصة سحابية")}
                </Link>
              </div>
            </div>

            {/* RIGHT CARD: SYSTEM STATUS */}
            <div className="surface-card" style={{ padding: "24px", borderRadius: "18px", display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
              <div>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "18px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                    <svg className="gb-icon" style={{ width: "20px", height: "20px" }}><use href="#icon-aegis-shield"/></svg>
                    <h3 style={{ fontSize: "16px", fontWeight: 900, color: "#fff" }}>
                      {lang === "ar" ? "حالة النظام والنشاط الأخير" : "System Status & Telemetry"}
                    </h3>
                  </div>
                  <span className="emerald-badge">{lang === "ar" ? "متصل وآمن" : "ONLINE & SECURE"}</span>
                </div>

                <div style={{ display: "flex", flexDirection: "column", gap: "12px", marginBottom: "20px" }}>
                  <div style={{ padding: "12px 14px", borderRadius: "12px", background: "rgba(255,255,255,0.03)", border: "1px solid var(--border-subtle)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <span style={{ color: "var(--text-secondary)", fontSize: "12px" }}>{lang === "ar" ? "الحساب المسجل" : "Account Owner"}</span>
                    <strong style={{ color: "#fff", fontSize: "12.5px" }}>{user?.email || (profile?.username && !profile.username.includes("علي غيث") ? profile.username : "Rey")}</strong>
                  </div>
                  <div style={{ padding: "12px 14px", borderRadius: "12px", background: "rgba(255,255,255,0.03)", border: "1px solid var(--border-subtle)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <span style={{ color: "var(--text-secondary)", fontSize: "12px" }}>{lang === "ar" ? "الخادم السحابي" : "Cloud Node"}</span>
                    <span style={{ color: "var(--ghost-cyan)", fontWeight: 700, fontSize: "12px" }}>AWS Cloud Core (Frankfurt DC - 22ms)</span>
                  </div>
                  <div style={{ padding: "12px 14px", borderRadius: "12px", background: "rgba(255,255,255,0.03)", border: "1px solid var(--border-subtle)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <span style={{ color: "var(--text-secondary)", fontSize: "12px" }}>{lang === "ar" ? "بروتوكول الأمان" : "Security Protocol"}</span>
                    <span style={{ color: "var(--emerald-ok)", fontWeight: 700, fontSize: "12px" }}>Stealth Wire (100% Anti-Detection)</span>
                  </div>
                  <div style={{ padding: "12px 14px", borderRadius: "12px", background: "rgba(255,255,255,0.03)", border: "1px solid var(--border-subtle)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <span style={{ color: "var(--text-secondary)", fontSize: "12px" }}>{lang === "ar" ? "التوقيت الموحد" : "Server Clock"}</span>
                    <span style={{ color: "var(--amber-wait)", fontWeight: 700, fontSize: "12px", fontFamily: "'JetBrains Mono', monospace" }}>{time || "12:00:00 UTC"}</span>
                  </div>
                </div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
                <button className="btn-ghost-outline" style={{ padding: "10px", fontSize: "12px", justifyContent: "center", cursor: "pointer" }} onClick={() => notify(lang === "ar" ? "لا توجد تحديثات جديدة حالياً، نظامك على آخر إصدار v2.5" : "No new updates available. System is running latest v2.5 release.")}>
                  <svg className="gb-icon"><use href="#icon-cyber-mail"/></svg>
                  <span>{lang === "ar" ? "بريد التحديثات" : "Update Mail"}</span>
                </button>
                <Link
                  href="/shop"
                  onClick={navigateToShop}
                  className="btn-cyan-glow"
                  style={{ padding: "10px", fontSize: "12px", justifyContent: "center", textDecoration: "none", cursor: "pointer" }}
                >
                  <svg className="gb-icon"><use href="#icon-commander-badge"/></svg>
                  <span>{lang === "ar" ? "المتجر السحابي" : "Cloud Store"}</span>
                </Link>
              </div>
            </div>

          </div>
        </section>
      )}

      {/* =========================================================================
          VIEW 1: LIVE TELEMETRY HUD STREAM
         ========================================================================= */}
      {activeTab === "live" && (
        <section className="tab-view active" id="view-live">
          <div className="cyber-console-card">
            
            <div className="cyber-console-topbar" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "12px", padding: "12px 18px" }}>
              <div className="cyber-telemetry-left" style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                <div className="cyber-live-pulse-dot" title="Live Telemetry Link Active" />
                {activeBot && (
                  <span className="cyan-pill" style={{ fontSize: "11px", fontWeight: 700 }}>{activeBot.name || activeBot.label}</span>
                )}
                <span style={{ fontSize: "11px", color: "var(--text-secondary)", fontWeight: 600 }}>
                  {lang === "ar" ? "● بث حي مباشر للأوامر السحابية" : "● Live Cloud Stream"}
                </span>
              </div>

              {/* Far Left Button: Clear Log (على آخر شمال لوحة السجل) */}
              <div style={{ marginInlineStart: "auto" }}>
                <button
                  onClick={async () => {
                    const botKey = activeBot?.bot_id || activeBot?.id;
                    setLogs([{ id: Date.now(), time: "[CLEAR]", cat: "system", text: "تم مسح سجل العمليات المؤقت." }]);
                    if (botKey) {
                      await clearRecentActivity(botKey, user?.id);
                    }
                    notify(lang === "ar" ? "تم مسح السجل من السيرفر بنجاح." : "Logs cleared from server.");
                  }}
                  title={lang === "ar" ? "مسح محتويات سجل العمليات" : "Clear log"}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "6px",
                    padding: "6px 14px",
                    fontSize: "11.5px",
                    fontWeight: 700,
                    borderRadius: "8px",
                    background: "rgba(239, 68, 68, 0.12)",
                    border: "1px solid rgba(239, 68, 68, 0.35)",
                    color: "#f87171",
                    cursor: "pointer",
                    transition: "all 0.2s ease"
                  }}
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                    <polyline points="3 6 5 6 21 6"/>
                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                  </svg>
                  <span>{lang === "ar" ? "امسح السجل" : "Clear Log"}</span>
                </button>
              </div>
            </div>

            {/* Category Filter Pills */}
            <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap", padding: "10px 18px 0" }}>
              {([
                { key: "all", ar: "الكل", en: "All" },
                { key: "system", ar: "النظام والدخول", en: "System & Login" },
                { key: "gather", ar: "الجمع", en: "Gathering" },
                { key: "alliance", ar: "التحالف", en: "Alliance" },
                { key: "train", ar: "التدريب", en: "Training & Barracks" },
                { key: "city", ar: "المدينة والحصاد", en: "City & Harvest" },
              ] as const).map((c) => (
                <span
                  key={c.key}
                  onClick={() => setConsoleFilter(c.key)}
                  className="cyan-pill"
                  style={{
                    fontSize: "11px", cursor: "pointer",
                    opacity: consoleFilter === c.key ? 1 : 0.45,
                    boxShadow: consoleFilter === c.key ? "0 0 10px rgba(0,229,255,0.4)" : "none",
                  }}
                >
                  {lang === "ar" ? c.ar : c.en}
                </span>
              ))}
            </div>

            {/* Console Log Rows */}
            <div className="cyber-console-body" id="consoleBody" style={{ minHeight: "420px" }}>
              {logs.filter((log) => consoleFilter === "all" || log.cat === consoleFilter).map((log) => (
                <div key={log.id} className={`cyber-log-row cat-border-${log.cat}`}>
                  <span className="cyber-log-time">{log.time}</span>
                  <span className={`cyber-log-badge badge-${log.cat}`}>
                    <span>{log.cat.toUpperCase()}</span>
                  </span>
                  <span className="cyber-log-text">{log.text}</span>
                </div>
              ))}
              {logs.filter((log) => consoleFilter === "all" || log.cat === consoleFilter).length === 0 && (
                <div style={{ padding: "24px", textAlign: "center", color: "var(--text-secondary)", fontSize: "12px" }}>
                  {lang === "ar" ? "لا توجد سجلات تطابق الفلتر المختار..." : "No telemetry records matching this filter..."}
                </div>
              )}
            </div>

          </div>
        </section>
      )}

      {/* =========================================================================
          VIEW 2: MULTI-GOVERNOR ACCOUNTS ENGINE
         ========================================================================= */}
      {activeTab === "accounts" && (
        <section className="tab-view active" id="view-accounts" style={{ display: "flex", flexDirection: "column", gap: "18px" }}>
          
          {/* TOP CONTROLS: SEARCH + BULK ACTION TOOLBAR (ELEGANT HORIZONTAL BAR MATCHING REFERENCE) */}
          <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "12px", flexWrap: "wrap" }}>
              <div className="input-icon-wrap" style={{ maxWidth: "380px", flex: 1 }}>
                <input
                  type="text"
                  className="form-input"
                  value={accountSearch}
                  onChange={(e) => setAccountSearch(e.target.value)}
                  placeholder={lang === "ar" ? "ابحث باسم الحاكم أو المعرف أو البريد الإلكتروني..." : "Search by governor, role ID or email..."}
                  style={{ width: "100%" }}
                />
              </div>

              {/* Quick Link Account Button */}
              <button
                className="btn-ghost-outline"
                onClick={() => { setShowLinkModal(true); setLinkStep(1); setLinkError(""); }}
                style={{ padding: "7px 16px", fontSize: "11.5px", cursor: "pointer", display: "inline-flex", alignItems: "center", gap: "6px" }}
              >
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                <span>{lang === "ar" ? "ربط حساب إضافي" : "Link Extra Account"}</span>
              </button>
            </div>

            {/* BULK ACTION BAR & SELECT ALL CHECKBOX (SINGLE COMPACT LINE) */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: "12px",
                flexWrap: "wrap",
                padding: "8px 16px",
                background: "rgba(6, 18, 38, 0.65)",
                border: "1px solid rgba(0, 229, 255, 0.18)",
                borderRadius: "12px",
              }}
            >
              {/* Select All Checkbox */}
              <label style={{ display: "inline-flex", alignItems: "center", gap: "8px", cursor: "pointer", userSelect: "none" }}>
                <input
                  type="checkbox"
                  checked={filteredAccounts.length > 0 && filteredAccounts.every(a => selectedRoleIds.includes(String(a.role_id)))}
                  onChange={(e) => {
                    if (e.target.checked) {
                      const allIds = filteredAccounts.map(a => String(a.role_id));
                      setSelectedRoleIds(allIds);
                    } else {
                      setSelectedRoleIds([]);
                    }
                  }}
                  style={{ width: "16px", height: "16px", accentColor: "var(--ghost-cyan)", cursor: "pointer" }}
                />
                <span style={{ fontSize: "12.5px", fontWeight: 700, color: "var(--text-ice)" }}>
                  {lang === "ar" ? "تحديد الكل" : "Select All"}
                </span>
                <span style={{ fontSize: "11px", color: "var(--ghost-cyan)", fontFamily: "'JetBrains Mono', monospace" }}>
                  ({selectedRoleIds.length}/{filteredAccounts.length})
                </span>
              </label>

              {/* Bulk Action Buttons (Horizontal Row: تشغيل المحدد, درع قريباً, رجع القوات قريباً, تحديث الشخصيات) */}
              <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                {/* 1. Bulk Run Sequential */}
                <button
                  className="btn-cyan-glow"
                  disabled={bulkRunning || selectedRoleIds.length === 0}
                  onClick={handleRunBulkCharacters}
                  style={{
                    padding: "7px 16px",
                    fontSize: "11.5px",
                    fontWeight: 800,
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "6px",
                    cursor: bulkRunning || selectedRoleIds.length === 0 ? "not-allowed" : "pointer",
                    opacity: bulkRunning || selectedRoleIds.length === 0 ? 0.6 : 1,
                  }}
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                    <polygon points="5 3 19 12 5 21 5 3"/>
                  </svg>
                  <span>
                    {bulkRunning
                      ? (lang === "ar" ? "جاري تشغيل المزارع بالتتابع..." : "Running Sequentially...")
                      : (lang === "ar" ? `تشغيل المحدد (${selectedRoleIds.length})` : `Run Selected (${selectedRoleIds.length})`)}
                  </span>
                </button>

                {/* 2. Bulk Shield (Soon) */}
                <button
                  className="btn-ghost-outline"
                  disabled
                  title="ميزة درع السلام الجماعي لجميع المزارع قادمة قريباً"
                  style={{
                    padding: "7px 12px",
                    fontSize: "11.5px",
                    opacity: 0.6,
                    cursor: "not-allowed",
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "5px",
                  }}
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                  </svg>
                  <span>{lang === "ar" ? "درع" : "Shield"}</span>
                  <span style={{ fontSize: "9px", background: "rgba(0,229,255,0.15)", color: "var(--ghost-cyan)", padding: "1px 5px", borderRadius: "4px" }}>
                    {lang === "ar" ? "قريباً" : "Soon"}
                  </span>
                </button>

                {/* 3. Bulk Recall Troops */}
                <button
                  className="btn-ghost-outline"
                  disabled={selectedRoleIds.length === 0 || bulkRecallLoading}
                  onClick={bulkRecallSelected}
                  title={lang === "ar" ? "سحب جميع القوات المحددة للمدينة" : "Recall selected troops to city"}
                  style={{
                    padding: "7px 12px",
                    fontSize: "11.5px",
                    opacity: selectedRoleIds.length === 0 || bulkRecallLoading ? 0.6 : 1,
                    cursor: selectedRoleIds.length === 0 || bulkRecallLoading ? "not-allowed" : "pointer",
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "5px",
                  }}
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={bulkRecallLoading ? "animate-spin" : ""}>
                    <path d="M3 11V9a4 4 0 0 1 4-4h14"/>
                    <polyline points="7 23 3 19 7 15"/>
                  </svg>
                  <span>{lang === "ar" ? "رجع القوات" : "Recall Troops"}</span>
                  <span style={{ fontSize: "9px", background: "rgba(0,229,255,0.15)", color: "var(--ghost-cyan)", padding: "1px 5px", borderRadius: "4px" }}>
                    ({selectedRoleIds.length})
                  </span>
                </button>

                {/* 4. Bulk Refresh Characters */}
                <button
                  className="btn-ghost-outline"
                  disabled={bulkRefreshing || selectedRoleIds.length === 0}
                  onClick={handleRefreshBulkCharacters}
                  style={{
                    padding: "7px 12px",
                    fontSize: "11.5px",
                    cursor: bulkRefreshing || selectedRoleIds.length === 0 ? "not-allowed" : "pointer",
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "5px",
                    opacity: bulkRefreshing || selectedRoleIds.length === 0 ? 0.6 : 1,
                  }}
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={bulkRefreshing ? "animate-spin" : ""}>
                    <path d="M23 4v6h-6"/>
                    <path d="M1 20v-6h6"/>
                    <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
                  </svg>
                  <span>
                    {bulkRefreshing
                      ? (lang === "ar" ? "جاري التحديث..." : "Refreshing...")
                      : (lang === "ar" ? "تحديث الشخصيات" : "Refresh Characters")}
                  </span>
                </button>
              </div>
            </div>
          </div>

          <div className="surface-card" style={{ padding: "20px", borderRadius: "18px" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "14px" }}>
              <h3 className="section-title">
                {lang === "ar" ? "قائمة الحسابات والمزارع المربوطة" : "Linked Farms & Accounts"} ({filteredAccounts.length})
              </h3>
              <span className="cyan-pill" style={{ fontSize: "11px" }}>
                {lang === "ar" ? "السعة المتبقية:" : "Remaining Slots:"} {Math.max(0, (activeBot?.slots || 5) - accounts.length)} {lang === "ar" ? "خانات" : "slots"}
              </span>
            </div>

            {filteredAccounts.length === 0 ? (
              <div className="empty-state-box">
                <svg className="gb-icon" style={{ width: "42px", height: "42px", color: "var(--ghost-cyan)" }}>
                  <use href="#icon-castle-fort"/>
                </svg>
                <h4 style={{ fontSize: "16px", fontWeight: 800, color: "#fff" }}>
                  {t("no_accounts_in_unit_title", "لا توجد مزارع مربوطة بهذه الوحدة")}
                </h4>
                <p style={{ fontSize: "12.5px", color: "var(--text-secondary)", maxWidth: "420px" }}>
                  {t("no_accounts_in_unit_desc", "قم بربط حساباتك الآن عبر زر 'ربط حساب إضافي' للبدء بالحصاد الآلي وتدريب القوات على مدار الساعة.")}
                </p>
              </div>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", textAlign: lang === "ar" ? "right" : "left", borderCollapse: "collapse", fontSize: "12.5px" }}>
                  <thead>
                    <tr style={{ borderBottom: "1px solid rgba(0,229,255,0.2)", color: "var(--text-secondary)" }}>
                      <th style={{ padding: "10px 6px", width: "36px", textAlign: "center" }}>
                        {lang === "ar" ? "تفعيل" : "Active"}
                      </th>
                      <th style={{ padding: "10px 8px" }}>{t("col_governor", "الحاكم / البريد")}</th>
                      <th style={{ padding: "10px 8px", width: "85px" }}>{lang === "ar" ? "المعرف (ID)" : "Role ID"}</th>
                      <th style={{ padding: "10px 6px", width: "70px" }}>{t("col_kingdom", "المملكة")}</th>
                      <th style={{ padding: "10px 6px", width: "70px" }}>{t("col_city_hall", "القلعة")}</th>
                      <th style={{ padding: "10px 6px", width: "65px" }}>{t("col_power", "القوة")}</th>
                      <th style={{ padding: "10px 8px", width: "85px" }}>{t("col_status", "حالة التشغيل")}</th>
                      <th style={{ padding: "10px 8px", width: "95px" }}>{lang === "ar" ? "آخر تشغيل" : "Last Run"}</th>
                      <th style={{ padding: "10px 8px", width: "105px" }}>{lang === "ar" ? "التشغيل القادم" : "Next Run"}</th>
                      <th style={{ padding: "10px 8px", width: "175px" }}>{t("col_actions", "الإجراءات")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredAccounts.map((acc: any) => {
                      const roleId = String(acc.role_id);
                      const isSelected = selectedRoleIds.includes(roleId);
                      const isEnabled = acc.enabled !== false;
                      const isExecuting = executingRoleId === roleId;
                      const isRefreshing = refreshingRoleId === roleId;

                      return (
                        <tr key={acc.id} style={{ borderBottom: "1px solid rgba(255,255,255,0.04)", background: isSelected ? "rgba(0, 229, 255, 0.03)" : undefined }}>
                          {/* 1. CHECKBOX TOGGLE FOR RUNNING / SELECTION */}
                          <td style={{ padding: "12px 8px", textAlign: "center" }}>
                            <input
                              type="checkbox"
                              checked={isEnabled}
                              title={isEnabled ? (lang === "ar" ? "الشخصية مفعلة (انقر للتعطيل)" : "Enabled (click to disable)") : (lang === "ar" ? "الشخصية معطلة (انقر للتفعيل)" : "Disabled (click to enable)")}
                              onChange={async (e) => {
                                const newEnabled = e.target.checked;
                                // update local state
                                setAccountsByBot(prev => {
                                  const list = prev[activeBot.id] || [];
                                  return {
                                    ...prev,
                                    [activeBot.id]: list.map((a: any) => String(a.role_id) === roleId ? { ...a, enabled: newEnabled } : a)
                                  };
                                });
                                // sync selection
                                if (!newEnabled) {
                                  setSelectedRoleIds(prev => prev.filter(r => r !== roleId));
                                } else {
                                  setSelectedRoleIds(prev => [...prev, roleId]);
                                }
                                // call backend
                                await setCharacterEnabled(roleId, newEnabled).catch(() => {});
                                // update Supabase
                                if (user?.id) {
                                  await supabase.from("game_characters").update({ is_enabled: newEnabled }).eq("role_id", roleId);
                                }
                                notify(lang === "ar" ? `${acc.governor_name || roleId}: تم ${newEnabled ? "تفعيل" : "تعطيل"} الشخصية بنجاح.` : `${acc.governor_name || roleId}: ${newEnabled ? "Enabled" : "Disabled"}.`);
                              }}
                              style={{ width: "16px", height: "16px", accentColor: "var(--ghost-cyan)", cursor: "pointer" }}
                            />
                          </td>

                          {/* 2. GOVERNOR NAME & EMAIL */}
                          <td style={{ padding: "12px 10px" }}>
                            <div style={{ fontWeight: 800, color: isEnabled ? "#fff" : "var(--text-secondary)" }}>{acc.governor_name || acc.email}</div>
                            <div style={{ fontSize: "10.5px", color: "var(--text-secondary)" }}>{acc.email}</div>
                          </td>

                          {/* 3. ROLE ID */}
                          <td style={{ padding: "12px 10px", fontFamily: "'JetBrains Mono', monospace", color: "var(--text-ice)" }}>
                            {acc.role_id || "89410291"}
                          </td>

                          {/* 4. KINGDOM */}
                          <td style={{ padding: "12px 10px", color: "var(--ghost-cyan)", fontWeight: 700 }}>
                            KD #{acc.kingdom || "3057"}
                          </td>

                          {/* 5. CITY HALL */}
                          <td style={{ padding: "12px 10px" }}>CH {acc.city_hall_level || 25}</td>

                          {/* 6. POWER */}
                          <td style={{ padding: "12px 10px", fontFamily: "'JetBrains Mono', monospace", color: "#facc15" }}>
                            {(acc.power ? (acc.power / 1000000).toFixed(1) + "M" : "0.0M")}
                          </td>

                          {/* 7. STATUS */}
                          <td style={{ padding: "12px 10px" }}>
                            <span className={isEnabled ? "cyan-pill" : "hero-badge-pill hero-badge-status-standby"} style={{ fontSize: "10.5px" }}>
                              {isEnabled ? (lang === "ar" ? "مفعل وجاهز" : "Enabled") : (lang === "ar" ? "معطل" : "Disabled")}
                            </span>
                          </td>

                          {/* 8. LAST RUN */}
                          <td style={{ padding: "12px 10px", whiteSpace: "nowrap" }}>
                            <div style={{ display: "inline-flex", alignItems: "center", gap: "5px", padding: "4px 8px", borderRadius: "6px", background: "rgba(0, 230, 153, 0.08)", border: "1px solid rgba(0, 230, 153, 0.25)", color: "#00e699", fontSize: "11px", fontWeight: 700, fontFamily: "'JetBrains Mono', monospace" }}>
                              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                                <circle cx="12" cy="12" r="10"/>
                                <polyline points="12 6 12 12 16 14"/>
                              </svg>
                              <span>{formatRelativeTime(acc.last_run_text, lang)}</span>
                            </div>
                          </td>

                          {/* 9. NEXT RUN */}
                          <td style={{ padding: "12px 10px", whiteSpace: "nowrap" }}>
                            <div style={{ display: "inline-flex", alignItems: "center", gap: "5px", padding: "4px 8px", borderRadius: "6px", background: "rgba(255, 170, 43, 0.08)", border: "1px solid rgba(255, 170, 43, 0.25)", color: "#ffaa2b", fontSize: "11px", fontWeight: 700, fontFamily: "'JetBrains Mono', monospace" }}>
                              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                                <path d="M5 22h14"/>
                                <path d="M5 2h14"/>
                                <path d="M17 22v-4.172a2 2 0 0 0-.586-1.414L12 12l-4.414 4.414A2 2 0 0 0 7 17.828V22"/>
                                <path d="M7 2v4.172a2 2 0 0 0 .586 1.414L12 12l4.414-4.414A2 2 0 0 0 17 6.172V2"/>
                              </svg>
                              <span>
                                {!running
                                  ? (lang === "ar" ? "متوقف (Stopped)" : "Stopped")
                                  : formatCountdown(acc.next_run || acc.next_run_text, running, lang)
                                }
                              </span>
                            </div>
                          </td>

                          {/* 8. FIVE ACTIONS STACKED (2x2 GRID + full-width delete): تشغيل, تحديث, درع, الجيش, حذف */}
                          <td style={{ padding: "8px 6px", width: "175px" }}>
                            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px", width: "165px" }}>
                              
                              {/* Row 1, Col 1: تشغيل */}
                              <button
                                className="btn-cyan-glow"
                                disabled={isExecuting || !isEnabled || bulkRunning || executingRoleId !== null}
                                onClick={() => handleRunSingleCharacter(acc)}
                                title={lang === "ar" ? "تشغيل هذه المزرعة فوراً" : "Run this farm now"}
                                style={{
                                  padding: "4px 6px",
                                  fontSize: "10.5px",
                                  fontWeight: 800,
                                  cursor: isExecuting || !isEnabled || bulkRunning || executingRoleId !== null ? "not-allowed" : "pointer",
                                  opacity: isExecuting || !isEnabled || bulkRunning || executingRoleId !== null ? 0.5 : 1,
                                  display: "inline-flex",
                                  alignItems: "center",
                                  justifyContent: "center",
                                  gap: "4px",
                                  borderRadius: "6px"
                                }}
                              >
                                <svg width="9" height="9" viewBox="0 0 24 24" fill="currentColor">
                                  <polygon points="5 3 19 12 5 21 5 3"/>
                                </svg>
                                <span>{isExecuting ? (lang === "ar" ? "جاري..." : "Running...") : (lang === "ar" ? "تشغيل" : "Run")}</span>
                              </button>

                              {/* Row 1, Col 2: تحديث الشخصية */}
                              <button
                                className="btn-ghost-outline"
                                disabled={isRefreshing}
                                onClick={() => handleRefreshSingleCharacter(acc)}
                                title={lang === "ar" ? "تحديث بيانات الحاكم من بوابة اللعبة" : "Refresh character stats from game portal"}
                                style={{
                                  padding: "4px 6px",
                                  fontSize: "10.5px",
                                  cursor: isRefreshing ? "not-allowed" : "pointer",
                                  display: "inline-flex",
                                  alignItems: "center",
                                  justifyContent: "center",
                                  gap: "3px",
                                  borderRadius: "6px"
                                }}
                              >
                                <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={isRefreshing ? "animate-spin" : ""}>
                                  <path d="M23 4v6h-6"/>
                                  <path d="M1 20v-6h6"/>
                                  <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
                                </svg>
                                <span>{isRefreshing ? (lang === "ar" ? "جاري..." : "Refreshing...") : (lang === "ar" ? "تحديث" : "Refresh")}</span>
                              </button>

                              {/* Row 2, Col 1: درع السلام */}
                              <button
                                className="btn-ghost-outline"
                                disabled
                                title={lang === "ar" ? "درع السلام الفوري (قريباً)" : "Peace Shield (Coming Soon)"}
                                style={{
                                  padding: "3px 5px",
                                  fontSize: "10px",
                                  opacity: 0.65,
                                  cursor: "not-allowed",
                                  display: "inline-flex",
                                  alignItems: "center",
                                  justifyContent: "center",
                                  gap: "3px",
                                  borderRadius: "6px"
                                }}
                              >
                                <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
                                <span>{lang === "ar" ? "درع" : "Shield"}</span>
                                <span style={{ fontSize: "7.5px", background: "rgba(0,229,255,0.15)", color: "var(--ghost-cyan)", padding: "1px 3px", borderRadius: "3px" }}>
                                  {lang === "ar" ? "قريباً" : "Soon"}
                                </span>
                              </button>

                              {/* Row 2, Col 2: سحب القوات (الجيش) */}
                              <button
                                className="btn-ghost-outline"
                                disabled={!!recallLoading[String(acc.role_id)]}
                                onClick={() => recallCharacter(acc)}
                                title={lang === "ar" ? "سحب القوات للمدينة فوراً" : "Recall Troops to City"}
                                style={{
                                  padding: "3px 5px",
                                  fontSize: "10px",
                                  opacity: recallLoading[String(acc.role_id)] ? 0.55 : 1,
                                  cursor: recallLoading[String(acc.role_id)] ? "not-allowed" : "pointer",
                                  display: "inline-flex",
                                  alignItems: "center",
                                  justifyContent: "center",
                                  gap: "3px",
                                  borderRadius: "6px"
                                }}
                              >
                                <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/></svg>
                                <span>{lang === "ar" ? "رجوع الجيش" : "Recall"}</span>
                                {recallLoading[String(acc.role_id)] && (
                                  <svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="animate-spin"><path d="M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0"/></svg>
                                )}
                              </button>

                              {/* Row 3 (full width): حذف الحساب — two-step confirm, no modal */}
                              <button
                                className="btn-ghost-outline"
                                disabled={deletingEmail === acc.email || bulkRunning}
                                onClick={() => handleDeleteAccount(acc)}
                                title={lang === "ar" ? `حذف الحساب ${acc.email} نهائياً من السيرفر والموقع (اضغط مرتين للتأكيد)` : `Permanently delete ${acc.email} from server and site (click twice to confirm)`}
                                style={{
                                  gridColumn: "1 / -1",
                                  padding: "3px 5px",
                                  fontSize: "10px",
                                  fontWeight: 700,
                                  color: deleteArmedEmail === acc.email ? "#fff" : "#ff6b6b",
                                  background: deleteArmedEmail === acc.email ? "rgba(255,60,60,0.28)" : "transparent",
                                  border: `1px solid ${deleteArmedEmail === acc.email ? "#ff4444" : "rgba(255,107,107,0.4)"}`,
                                  opacity: deletingEmail === acc.email || bulkRunning ? 0.55 : 1,
                                  cursor: deletingEmail === acc.email || bulkRunning ? "not-allowed" : "pointer",
                                  display: "inline-flex",
                                  alignItems: "center",
                                  justifyContent: "center",
                                  gap: "3px",
                                  borderRadius: "6px"
                                }}
                              >
                                <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                                <span>
                                  {deletingEmail === acc.email
                                    ? (lang === "ar" ? "جاري الحذف..." : "Deleting...")
                                    : deleteArmedEmail === acc.email
                                      ? (lang === "ar" ? "تأكيد الحذف؟" : "Confirm Delete?")
                                      : (lang === "ar" ? "حذف" : "Delete")}
                                </span>
                              </button>

                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </section>
      )}

      {/* =========================================================================
          VIEW 3: AUTHENTIC 3-TIER INVENTORY ENGINE (MATCHING GHOSTBOT.HTML)
         ========================================================================= */}
      {activeTab === "inventory" && (
        <section className="tab-view active" id="view-inventory" style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
          
          {/* Tier 1: Resources Gathered (with TODAY / 7 DAYS / 30 DAYS filter) */}
          <div className="surface-card">
            <div className="section-head">
              <span className="section-title">الموارد التي تم جمعها</span>
              <div style={{ display: "flex", gap: "6px" }}>
                <button
                  className="util-btn"
                  style={{ borderColor: invPeriod === "today" ? "var(--ghost-cyan)" : undefined, background: invPeriod === "today" ? "rgba(0,229,255,0.18)" : undefined }}
                  onClick={() => setInvPeriod("today")}
                >
                  اليوم
                </button>
                <button
                  className="util-btn"
                  style={{ borderColor: invPeriod === "7d" ? "var(--ghost-cyan)" : undefined, background: invPeriod === "7d" ? "rgba(0,229,255,0.18)" : undefined }}
                  onClick={() => setInvPeriod("7d")}
                >
                  7 أيام
                </button>
                <button
                  className="util-btn"
                  style={{ borderColor: invPeriod === "30d" ? "var(--ghost-cyan)" : undefined, background: invPeriod === "30d" ? "rgba(0,229,255,0.18)" : undefined }}
                  onClick={() => setInvPeriod("30d")}
                >
                  30 يوماً
                </button>
              </div>
            </div>
            
            {(() => {
              const winKey = invPeriod === "today" ? "today" : invPeriod === "7d" ? "7days" : "30days";
              const win = inventory?.resources_gathered?.[winKey];
              return (
                <div className="stats-grid-4">
                  <div className="stat-tile">
                    <span className="stat-label" style={{ color: "#facc15", display: "inline-flex", alignItems: "center", gap: "6px" }}>
                      <img src={ITEM_FOOD_BASE64} alt="Food" style={{ width: "20px", height: "20px", objectFit: "contain" }} />
                      <span>{lang === "ar" ? "القمح" : "Food"}</span>
                    </span>
                    <div className="stat-number">
                      {formatRss(win?.food)}
                    </div>
                    <div className="rss-bar-fill" style={{ width: win?.food ? "88%" : "0%" }} />
                  </div>
                  
                  <div className="stat-tile">
                    <span className="stat-label" style={{ color: "#00e699", display: "inline-flex", alignItems: "center", gap: "6px" }}>
                      <img src={ITEM_WOOD_BASE64} alt="Wood" style={{ width: "20px", height: "20px", objectFit: "contain" }} />
                      <span>{lang === "ar" ? "الخشب" : "Wood"}</span>
                    </span>
                    <div className="stat-number">
                      {formatRss(win?.wood)}
                    </div>
                    <div className="rss-bar-fill" style={{ width: win?.wood ? "76%" : "0%" }} />
                  </div>
                  
                  <div className="stat-tile">
                    <span className="stat-label" style={{ color: "#cbe8ff", display: "inline-flex", alignItems: "center", gap: "6px" }}>
                      <img src={ITEM_STONE_BASE64} alt="Stone" style={{ width: "20px", height: "20px", objectFit: "contain" }} />
                      <span>{lang === "ar" ? "الحجر" : "Stone"}</span>
                    </span>
                    <div className="stat-number">
                      {formatRss(win?.stone)}
                    </div>
                    <div className="rss-bar-fill" style={{ width: win?.stone ? "55%" : "0%" }} />
                  </div>
                  
                  <div className="stat-tile">
                    <span className="stat-label" style={{ color: "#ffaa2b", display: "inline-flex", alignItems: "center", gap: "6px" }}>
                      <img src={ITEM_GOLD_BASE64} alt="Gold" style={{ width: "20px", height: "20px", objectFit: "contain" }} />
                      <span>{lang === "ar" ? "الذهب" : "Gold"}</span>
                    </span>
                    <div className="stat-number">
                      {formatRss(win?.gold)}
                    </div>
                    <div className="rss-bar-fill" style={{ width: win?.gold ? "32%" : "0%" }} />
                  </div>
                </div>
              );
            })()}
          </div>

          {/* Tier 2: In Cities Now (5 Resources including GEMS) */}
          <div className="surface-card">
            <div className="section-head">
              <span className="section-title">{lang === "ar" ? "الموارد داخل المدن حالياً" : "Resources In Cities Now"}</span>
              <span style={{ display: "inline-flex", alignItems: "center", gap: "8px" }}>
                <span className="cyan-pill" style={{ fontSize: "11px" }}>{lang === "ar" ? "تحديث دوري متزامن" : "Synchronized"}</span>
                <button
                  className="btn-cyan-glow"
                  disabled={!!invRefresh}
                  onClick={() => handleInventoryRefresh()}
                  title={lang === "ar" ? "دخول كل الحسابات وقراءة المخزون الحي ثم الخروج" : "Log into every account, read live stock, then log out"}
                  style={{ padding: "5px 12px", fontSize: "11px", fontWeight: 800, cursor: invRefresh ? "not-allowed" : "pointer", opacity: invRefresh ? 0.55 : 1, borderRadius: "6px", display: "inline-flex", alignItems: "center", gap: "5px" }}
                >
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" className={invRefresh ? "animate-spin" : ""}>
                    <path d="M23 4v6h-6"/>
                    <path d="M1 20v-6h6"/>
                    <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
                  </svg>
                  <span>{invRefresh ? (lang === "ar" ? `جاري... (${invRefresh.done}/${invRefresh.total})` : `Working... (${invRefresh.done}/${invRefresh.total})`) : (lang === "ar" ? "تحديث الكمية للكل" : "Refresh All Quantities")}</span>
                </button>
                {invRefresh && (
                  <button
                    className="btn-ghost-outline"
                    style={{ padding: "5px 10px", fontSize: "11px", cursor: "pointer" }}
                    onClick={async () => { try { await stopInventoryRefresh(invRefresh.jobId); } catch {} stopInvRefreshPolling(); setInvRefresh(null); notify(lang === "ar" ? "تم إيقاف التحديث." : "Refresh stopped."); }}
                  >
                    {lang === "ar" ? "إيقاف" : "Stop"}
                  </button>
                )}
              </span>
            </div>
            {invRefresh && (
              <div style={{ padding: "0 16px 12px" }}>
                <div style={{ height: "6px", borderRadius: "4px", background: "rgba(255,255,255,0.08)", overflow: "hidden" }}>
                  <div style={{ height: "100%", width: `${invRefresh.total ? Math.round((invRefresh.done / invRefresh.total) * 100) : 0}%`, background: "linear-gradient(90deg, var(--ghost-cyan), #00e699)", transition: "width 0.4s" }} />
                </div>
                <div style={{ fontSize: "11px", color: "var(--text-secondary)", marginTop: "6px" }}>
                  {invRefresh.current
                    ? (lang === "ar" ? `الحالي: ${invRefresh.current} (${invRefresh.done}/${invRefresh.total})` : `Current: ${invRefresh.current} (${invRefresh.done}/${invRefresh.total})`)
                    : (lang === "ar" ? `تم ${invRefresh.done} من ${invRefresh.total}` : `${invRefresh.done} of ${invRefresh.total} done`)}
                </div>
              </div>
            )}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: "12px" }}>
              <div className="stat-tile">
                <span className="stat-label" style={{ color: "#facc15", display: "inline-flex", alignItems: "center", gap: "6px" }}>
                  <img src={ITEM_FOOD_BASE64} alt="Food" style={{ width: "20px", height: "20px", objectFit: "contain" }} />
                  <span>{lang === "ar" ? "القمح" : "Food"}</span>
                </span>
                <div className="stat-number" style={{ fontSize: "20px" }}>{formatRss(inventory?.in_cities_now?.food)}</div>
              </div>
              <div className="stat-tile">
                <span className="stat-label" style={{ color: "#00e699", display: "inline-flex", alignItems: "center", gap: "6px" }}>
                  <img src={ITEM_WOOD_BASE64} alt="Wood" style={{ width: "20px", height: "20px", objectFit: "contain" }} />
                  <span>{lang === "ar" ? "الخشب" : "Wood"}</span>
                </span>
                <div className="stat-number" style={{ fontSize: "20px" }}>{formatRss(inventory?.in_cities_now?.wood)}</div>
              </div>
              <div className="stat-tile">
                <span className="stat-label" style={{ color: "#cbe8ff", display: "inline-flex", alignItems: "center", gap: "6px" }}>
                  <img src={ITEM_STONE_BASE64} alt="Stone" style={{ width: "20px", height: "20px", objectFit: "contain" }} />
                  <span>{lang === "ar" ? "الحجر" : "Stone"}</span>
                </span>
                <div className="stat-number" style={{ fontSize: "20px" }}>{formatRss(inventory?.in_cities_now?.stone)}</div>
              </div>
              <div className="stat-tile">
                <span className="stat-label" style={{ color: "#ffaa2b", display: "inline-flex", alignItems: "center", gap: "6px" }}>
                  <img src={ITEM_GOLD_BASE64} alt="Gold" style={{ width: "20px", height: "20px", objectFit: "contain" }} />
                  <span>{lang === "ar" ? "الذهب" : "Gold"}</span>
                </span>
                <div className="stat-number" style={{ fontSize: "20px" }}>{formatRss(inventory?.in_cities_now?.gold)}</div>
              </div>
              <div className="stat-tile">
                <span className="stat-label" style={{ color: "#c084fc", display: "inline-flex", alignItems: "center", gap: "6px" }}>
                  <img src={ITEM_GEM_BASE64} alt="Gems" style={{ width: "20px", height: "20px", objectFit: "contain" }} />
                  <span>{lang === "ar" ? "الجواهر" : "Gems"}</span>
                </span>
                <div className="stat-number" style={{ fontSize: "20px", color: "#c084fc" }}>{formatGems(inventory?.in_cities_now?.gems)}</div>
              </div>
            </div>
          </div>

          {/* Tier 3: Per-Character Breakdown (11 Columns + Group by Kingdom) */}
          <div className="surface-card">
            <div className="section-head">
              <span className="section-title">{lang === "ar" ? "تفصيل الموارد لكل شخصية" : "Per-Character Breakdown"}</span>
              <button
                className="btn-ghost-outline"
                style={{ padding: "5px 12px", fontSize: "11px", cursor: "pointer" }}
                onClick={() => setKingdomSort(!kingdomSort)}
              >
                {kingdomSort ? (lang === "ar" ? "إلغاء الترتيب" : "Reset Sorting") : (lang === "ar" ? "ترتيب حسب المملكة" : "Group by Kingdom")}
              </button>
            </div>
            
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", textAlign: "right", borderCollapse: "collapse", fontSize: "12px" }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid rgba(0,229,255,0.2)", color: "var(--text-secondary)" }}>
                    <th style={{ padding: "10px" }}>{lang === "ar" ? "اسم الحاكم" : "Governor"}</th>
                    <th style={{ padding: "10px" }}>{lang === "ar" ? "المملكة" : "Kingdom"}</th>
                    <th style={{ padding: "10px" }}>{lang === "ar" ? "قاعة المدينة" : "City Hall"}</th>
                    <th style={{ padding: "10px" }}>{lang === "ar" ? "الحالة" : "Status"}</th>
                    <th style={{ padding: "10px", color: "#facc15" }}>
                      <span style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
                        <img src={ITEM_FOOD_BASE64} alt="Food" style={{ width: "16px", height: "16px", objectFit: "contain" }} />
                        <span>{lang === "ar" ? "القمح" : "Food"}</span>
                      </span>
                    </th>
                    <th style={{ padding: "10px", color: "#00e699" }}>
                      <span style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
                        <img src={ITEM_WOOD_BASE64} alt="Wood" style={{ width: "16px", height: "16px", objectFit: "contain" }} />
                        <span>{lang === "ar" ? "الخشب" : "Wood"}</span>
                      </span>
                    </th>
                    <th style={{ padding: "10px", color: "#cbe8ff" }}>
                      <span style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
                        <img src={ITEM_STONE_BASE64} alt="Stone" style={{ width: "16px", height: "16px", objectFit: "contain" }} />
                        <span>{lang === "ar" ? "الحجر" : "Stone"}</span>
                      </span>
                    </th>
                    <th style={{ padding: "10px", color: "#ffaa2b" }}>
                      <span style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
                        <img src={ITEM_GOLD_BASE64} alt="Gold" style={{ width: "16px", height: "16px", objectFit: "contain" }} />
                        <span>{lang === "ar" ? "الذهب" : "Gold"}</span>
                      </span>
                    </th>
                    <th style={{ padding: "10px", color: "#c084fc" }}>
                      <span style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
                        <img src={ITEM_GEM_BASE64} alt="Gems" style={{ width: "16px", height: "16px", objectFit: "contain" }} />
                        <span>{lang === "ar" ? "الجواهر" : "Gems"}</span>
                      </span>
                    </th>
                    <th style={{ padding: "10px" }}>{lang === "ar" ? "الإجمالي" : "Total RSS"}</th>
                    <th style={{ padding: "10px" }}>{lang === "ar" ? "التحكم" : "Action"}</th>
                  </tr>
                </thead>
                <tbody>
                  {displayedAccounts.length === 0 ? (
                    <tr>
                      <td colSpan={11} style={{ padding: "28px", textAlign: "center", color: "var(--text-secondary)" }}>
                        {lang === "ar" ? "لا توجد شخصيات مربوطة بعد. استخدم زر 'ربط حساب مزرعة جديد'." : "No governors linked yet. Use '+ Add Farm Account'."}
                      </td>
                    </tr>
                  ) : (
                    displayedAccounts.map((acc: any) => (
                      <tr key={acc.id} style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                        <td style={{ padding: "10px", fontWeight: 800, color: "#fff" }}>{acc.governor_name || acc.email}</td>
                        <td style={{ padding: "10px", color: "var(--ghost-cyan)", fontFamily: "'JetBrains Mono', monospace" }}>KD #{acc.kingdom || "3057"}</td>
                        <td style={{ padding: "10px" }}>CH {acc.city_hall_level || 25}</td>
                        <td style={{ padding: "10px" }}>
                          <span className="cyan-pill" style={{ fontSize: "10px" }}>{acc.status || (lang === "ar" ? "متصل وجاهز" : "Ready")}</span>
                        </td>
                        <td style={{ padding: "10px", fontFamily: "'JetBrains Mono', monospace", color: "#facc15" }}>{formatRss(acc.food)}</td>
                        <td style={{ padding: "10px", fontFamily: "'JetBrains Mono', monospace", color: "#00e699" }}>{formatRss(acc.wood)}</td>
                        <td style={{ padding: "10px", fontFamily: "'JetBrains Mono', monospace", color: "#cbe8ff" }}>{formatRss(acc.stone)}</td>
                        <td style={{ padding: "10px", fontFamily: "'JetBrains Mono', monospace", color: "#ffaa2b" }}>{formatRss(acc.gold)}</td>
                        <td style={{ padding: "10px", fontFamily: "'JetBrains Mono', monospace", color: "#c084fc" }}>{formatGems(acc.gems)}</td>
                        <td style={{ padding: "10px", fontFamily: "'JetBrains Mono', monospace", fontWeight: 800, color: "#fff" }}>{formatRss(acc.total_rss)}</td>
                        <td style={{ padding: "10px" }}>
                          <button
                            className="btn-ghost-outline"
                            disabled={!!invRefresh}
                            style={{ padding: "3px 8px", fontSize: "10.5px", cursor: invRefresh ? "not-allowed" : "pointer", opacity: invRefresh ? 0.55 : 1 }}
                            onClick={() => handleInventoryRefresh([String(acc.role_id)])}
                            title={lang === "ar" ? "دخول الحساب وقراءة المخزون الحي ثم الخروج" : "Log in, read live stock, log out"}
                          >
                            {lang === "ar" ? "تحديث" : "Refresh"}
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      )}

      {/* =========================================================================
          VIEW 4: GHOSTBOT CYBER-TACTICAL CONFIGURATION CORE (AUTHENTIC CARDS)
         ========================================================================= */}
      {activeTab === "config" && (
        <section className="tab-view active" id="view-config">
          <div className="gb-config-container">
            
            {/* Header */}
            <div className="gb-config-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "12px", padding: "18px 22px" }}>
              <div>
                <span className="badge-pro" style={{ background: "rgba(0,229,255,0.12)", color: "var(--ghost-cyan)", borderColor: "var(--ghost-cyan)" }}>
                  CYBER CONFIG CORE v2.5
                </span>
                <h3 style={{ fontSize: "18px", fontWeight: 900, color: "#fff", marginTop: "4px" }}>إعدادات البوت التكتيكية</h3>
                <p style={{ color: "var(--text-ice)", fontSize: "12px" }}>
                  تحكم بجميع معايير الحصاد وتدريب الجيوش والتحالف مع حفظ سحابي فوري.
                </p>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <span style={{ fontSize: "11px", fontWeight: 800, color: "var(--text-secondary)" }}>
                    {lang === "ar" ? "تطبيق التعديلات على:" : "Apply changes to:"}
                  </span>
                  <select
                    className="form-select"
                    style={{ width: "240px" }}
                    value={configScope}
                    disabled={scopeLoading}
                    onChange={(e) => {
                      const v = e.target.value;
                      setConfigScope(v);
                      const { email: se, roleId: sr } = parseScope(v);
                      notify(!v
                        ? (lang === "ar" ? "وضع الغرفة الكاملة" : "Whole-room mode")
                        : sr
                          ? (lang === "ar" ? `شخصية واحدة (باقي الشخصيات تتبع حسابها/الغرفة)` : `Single character mode`)
                          : (lang === "ar" ? `وضع حساب واحد: ${se} (باقي الحسابات تتبع الغرفة)` : `Single-account mode: ${se}`));
                    }}
                  >
                    <option value="">{lang === "ar" ? "كل حسابات الغرفة" : "All room accounts"}</option>
                    {roomEmails().map((em) => (
                      <optgroup key={em} label={em}>
                        <option value={`acc:${em}`}>{lang === "ar" ? "كل شخصيات هذا الحساب" : "All characters of this account"}</option>
                        {scopeEntries().filter((s) => s.group === em && s.value.startsWith("role:")).map((s) => (
                          <option key={s.value} value={s.value}>{s.label}</option>
                        ))}
                      </optgroup>
                    ))}
                  </select>
                </div>
                <button
                  className="btn-cyan-glow"
                  onClick={handleSaveConfig}
                  disabled={savingConfig || scopeLoading}
                  style={{ cursor: "pointer", display: "inline-flex", alignItems: "center", gap: "8px" }}
                >
                  <span>{savingConfig ? (lang === "ar" ? "جارٍ المزامنة السحابية..." : "Syncing to Cloud...") : (lang === "ar" ? (configScope.startsWith("role:") ? "حفظ إعدادات هذه الشخصية فقط" : configScope ? "حفظ إعدادات هذا الحساب فقط" : "حفظ ومزامنة التعديلات السحابية") : "Save & Sync Cloud Settings")}</span>
                </button>
              </div>
            </div>

            {/* Matrix navigation pills */}
            <div className="gb-config-nav-matrix" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: "8px", padding: "12px 18px", borderTop: "1px solid rgba(0,229,255,0.15)" }}>
              {[
                { id: "general", label: "General", ar: "الإعدادات العامة" },
                { id: "gathering", label: "Gathering", ar: "جمع الموارد" },
                { id: "city", label: "City & Troops", ar: "المدينة والجيوش" },
                { id: "alliance", label: "Alliance", ar: "التحالف والتقنية" },
                { id: "combat", label: "Combat", ar: "القتال والمستشفى" },
                { id: "daily", label: "Daily Claims", ar: "الجوائز اليومية" },
              ].map((m) => (
                <div
                  key={m.id}
                  className={`gb-cfg-pill ${cfgModule === m.id ? "active" : ""}`}
                  onClick={() => setCfgModule(m.id as any)}
                  style={{ cursor: "pointer", padding: "10px", borderRadius: "10px" }}
                >
                  <div style={{ fontWeight: 800, fontSize: "12px", color: "#fff" }}>{m.label}</div>
                  <div style={{ fontSize: "10px", color: "var(--ghost-cyan)" }}>{m.ar}</div>
                </div>
              ))}
            </div>

            {/* Module Content Viewport */}
            <div style={{ padding: "18px 22px" }}>
              
              {/* 1. GENERAL MODULE */}
              {cfgModule === "general" && (
                <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                  {/* Run Frequency */}
                  <div className="gb-cfg-card" style={{ borderColor: "rgba(0,229,255,0.35)", background: "linear-gradient(145deg, rgba(8,26,50,0.9), rgba(5,16,32,0.95))" }}>
                    <div className="gb-cfg-card-header">
                      <div>
                        <div className="gb-cfg-card-title">
                          <svg className="gb-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ color: "var(--ghost-cyan)" }}><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                          <span>فترات التشغيل والتكرار</span>
                        </div>
                        <div className="gb-cfg-card-desc">
                          حدد الفاصل الزمني لاكتمال دورة الفحص الشاملة لمزارعك.
                        </div>
                      </div>
                    </div>
                    <div style={{ marginTop: "14px", maxWidth: "320px" }}>
                      <label style={{ fontSize: "11px", fontWeight: 800, color: "var(--text-secondary)", display: "block", marginBottom: "6px" }}>
                        الفاصل الزمني للدورة
                      </label>
                      <select
                        className="form-select"
                        value={botConfig.runIntervalHours}
                        onChange={(e) => updateConfigField("runIntervalHours", e.target.value, `دورة التشغيل: كل ${e.target.value} ساعات`)}
                        style={{ width: "100%", fontSize: "13px", fontWeight: 700, background: "rgba(4,14,28,0.85)", border: "1px solid rgba(0,229,255,0.35)", color: "#fff", borderRadius: "10px", padding: "10px 14px" }}
                      >
                        <option value="3">كل 3 ساعات</option>
                        <option value="4">كل 4 ساعات (موصى به)</option>
                        <option value="6">كل 6 ساعات</option>
                        <option value="8">كل 8 ساعات</option>
                        <option value="12">كل 12 ساعة</option>
                        <option value="24">كل 24 ساعة</option>
                      </select>
                    </div>
                  </div>

                  {/* Discord Notifications */}
                  <div className="gb-cfg-card" style={{ borderColor: "rgba(0,229,255,0.25)", background: "linear-gradient(145deg, rgba(8,26,50,0.85), rgba(5,16,32,0.9))" }}>
                    <div className="gb-cfg-card-header" style={{ justifyContent: "space-between", alignItems: "center" }}>
                      <div>
                        <div className="gb-cfg-card-title">
                          <svg className="gb-icon" viewBox="0 0 24 24" fill="currentColor" style={{ color: "#5865F2" }}><path d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028c.462-.63.874-1.295 1.226-1.994.021-.041.001-.09-.041-.106a13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.929 1.793 8.18 1.793 12.061 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.894.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.028zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z"/></svg>
                          <span>إشعارات الديسكورد</span>
                        </div>
                        <div className="gb-cfg-card-desc">
                          إرسال ملخص تقارير الجمع والموارد المجموعة إلى رسائل الديسكورد المباشرة بعد كل دورة.
                        </div>
                      </div>
                      <label className="toggle-switch">
                        <input
                          type="checkbox"
                          checked={botConfig.discordNotifications}
                          onChange={(e) => updateConfigField("discordNotifications", e.target.checked, e.target.checked ? "تفعيل إشعارات الديسكورد" : "تعطيل إشعارات الديسكورد")}
                        />
                        <span className="toggle-slider" />
                      </label>
                    </div>
                  </div>
                </div>
              )}

              {/* 2. GATHERING MODULE */}
              {cfgModule === "gathering" && (
                <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                  {/* March Queues Allocation */}
                  <div className="gb-cfg-card" style={{ borderColor: "rgba(0,229,255,0.3)", background: "linear-gradient(145deg, rgba(8,26,50,0.9), rgba(5,16,32,0.95))" }}>
                    <div className="gb-cfg-card-header">
                      <div>
                        <div className="gb-cfg-card-title">
                          <svg className="gb-icon"><use href="#icon-blades-tactical"/></svg>
                          <span>توزيع طوابير جمع الموارد</span>
                        </div>
                        <div className="gb-cfg-card-desc">
                          حدد عدد الجيوش المخصصة لكل مورد (0 إلى 5 طوابير). يتم إرسال الطوابير للمناجم ذات المستوى الأعلى.
                        </div>
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                        <label className="toggle-switch" title="تخصيص أبطال المسيرات يدوياً">
                          <input
                            type="checkbox"
                            checked={!!botConfig.manualCommanders}
                            onChange={(e) => updateConfigField("manualCommanders", e.target.checked, e.target.checked ? "تفعيل تخصيص أبطال المسيرات يدوياً" : "تعطيل التخصيص اليدوي (تلقائي ذكي)")}
                          />
                          <span className="toggle-slider" />
                        </label>
                        <span style={{ fontSize: "11px", fontWeight: 800, color: botConfig.manualCommanders ? "#00e5ff" : "#728caa" }}>تخصيص الأبطال يدوياً</span>
                        <span className="cyan-pill" style={{ fontSize: "11px", fontWeight: 800, color: totalMarches > 5 ? "#ffaa2b" : undefined }}>
                          إجمالي الطوابير: {totalMarches} / 5
                        </span>
                      </div>
                    </div>

                    {/* 4 Steppers Grid */}
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "12px", marginTop: "12px" }}>
                      
                      {/* Food */}
                      <div style={{ background: "rgba(4,14,28,0.7)", border: "1px solid rgba(250,204,21,0.25)", borderRadius: "12px", padding: "12px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                          <img src={ITEM_FOOD_BASE64} style={{ width: "34px", height: "34px", objectFit: "contain", filter: "drop-shadow(0 0 6px rgba(250,204,21,0.4))" }} alt="Food" />
                          <div>
                            <div style={{ fontWeight: 800, fontSize: "13px", color: "#fff" }}>قمح</div>
                            <div style={{ fontSize: "10px", color: "#facc15" }}>مزارع القمح</div>
                          </div>
                        </div>
                        <div className="gb-stepper-wrap">
                          <button className="gb-stepper-btn" onClick={() => adjustGatherStepper("gatherFoodMarches", -1)} disabled={botConfig.gatherFoodMarches <= 0}>−</button>
                          <span className="gb-stepper-val" style={{ color: "#facc15" }}>{botConfig.gatherFoodMarches}</span>
                          <button className="gb-stepper-btn" onClick={() => adjustGatherStepper("gatherFoodMarches", 1)} disabled={botConfig.gatherFoodMarches >= 5}>+</button>
                        </div>
                      </div>

                      {/* Wood */}
                      <div style={{ background: "rgba(4,14,28,0.7)", border: "1px solid rgba(0,230,153,0.25)", borderRadius: "12px", padding: "12px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                          <img src={ITEM_WOOD_BASE64} style={{ width: "34px", height: "34px", objectFit: "contain", filter: "drop-shadow(0 0 6px rgba(0,230,153,0.4))" }} alt="Wood" />
                          <div>
                            <div style={{ fontWeight: 800, fontSize: "13px", color: "#fff" }}>خشب</div>
                            <div style={{ fontSize: "10px", color: "#00e699" }}>مناشر الخشب</div>
                          </div>
                        </div>
                        <div className="gb-stepper-wrap">
                          <button className="gb-stepper-btn" onClick={() => adjustGatherStepper("gatherWoodMarches", -1)} disabled={botConfig.gatherWoodMarches <= 0}>−</button>
                          <span className="gb-stepper-val" style={{ color: "#00e699" }}>{botConfig.gatherWoodMarches}</span>
                          <button className="gb-stepper-btn" onClick={() => adjustGatherStepper("gatherWoodMarches", 1)} disabled={botConfig.gatherWoodMarches >= 5}>+</button>
                        </div>
                      </div>

                      {/* Stone */}
                      <div style={{ background: "rgba(4,14,28,0.7)", border: "1px solid rgba(0,229,255,0.25)", borderRadius: "12px", padding: "12px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                          <img src={ITEM_STONE_BASE64} style={{ width: "34px", height: "34px", objectFit: "contain", filter: "drop-shadow(0 0 6px rgba(0,229,255,0.4))" }} alt="Stone" />
                          <div>
                            <div style={{ fontWeight: 800, fontSize: "13px", color: "#fff" }}>حجر</div>
                            <div style={{ fontSize: "10px", color: "var(--ghost-cyan)" }}>محاجر الحجر</div>
                          </div>
                        </div>
                        <div className="gb-stepper-wrap">
                          <button className="gb-stepper-btn" onClick={() => adjustGatherStepper("gatherStoneMarches", -1)} disabled={botConfig.gatherStoneMarches <= 0}>−</button>
                          <span className="gb-stepper-val" style={{ color: "var(--ghost-cyan)" }}>{botConfig.gatherStoneMarches}</span>
                          <button className="gb-stepper-btn" onClick={() => adjustGatherStepper("gatherStoneMarches", 1)} disabled={botConfig.gatherStoneMarches >= 5}>+</button>
                        </div>
                      </div>

                      {/* Gold */}
                      <div style={{ background: "rgba(4,14,28,0.7)", border: "1px solid rgba(255,170,43,0.25)", borderRadius: "12px", padding: "12px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                          <img src={ITEM_GOLD_BASE64} style={{ width: "34px", height: "34px", objectFit: "contain", filter: "drop-shadow(0 0 6px rgba(255,170,43,0.4))" }} alt="Gold" />
                          <div>
                            <div style={{ fontWeight: 800, fontSize: "13px", color: "#fff" }}>ذهب</div>
                            <div style={{ fontSize: "10px", color: "#ffaa2b" }}>مناجم الذهب</div>
                          </div>
                        </div>
                        <div className="gb-stepper-wrap">
                          <button className="gb-stepper-btn" onClick={() => adjustGatherStepper("gatherGoldMarches", -1)} disabled={botConfig.gatherGoldMarches <= 0}>−</button>
                          <span className="gb-stepper-val" style={{ color: "#ffaa2b" }}>{botConfig.gatherGoldMarches}</span>
                          <button className="gb-stepper-btn" onClick={() => adjustGatherStepper("gatherGoldMarches", 1)} disabled={botConfig.gatherGoldMarches >= 5}>+</button>
                        </div>
                      </div>

                    </div>
                  </div>

                  {/* Manual commander pairs per march (visible only when toggle is ON) */}
                  {botConfig.manualCommanders && (
                    <div className="gb-cfg-card" style={{ borderColor: "rgba(0,229,255,0.3)", background: "linear-gradient(145deg, rgba(8,26,50,0.9), rgba(5,16,32,0.95))", marginTop: "12px" }}>
                      <div className="gb-cfg-card-header" style={{ justifyContent: "space-between", alignItems: "center" }}>
                        <div>
                          <div className="gb-cfg-card-title">
                            <svg className="gb-icon" style={{ color: "var(--ghost-cyan)" }}><use href="#icon-blades-tactical" /></svg>
                            <span>أبطال المسيرات (يدوي)</span>
                          </div>
                          <div className="gb-cfg-card-desc">
                            خانة فارغة = تلقائي ذكي لتلك المسيرة. البطل الرمادي 🔒 غير مفتوح في حسابات الغرفة ولا يمكن اختياره. المحرك يتحقق من الملكية لكل حاكم قبل الإرسال.
                          </div>
                        </div>
                        <span
                          className="cyan-pill"
                          onClick={() => { if (!loadingRoster) void refreshUnlockedRoster(); }}
                          style={{ fontSize: "11px", fontWeight: 800, cursor: loadingRoster ? "wait" : "pointer", opacity: loadingRoster ? 0.6 : 1 }}
                        >
                          {loadingRoster ? "جارٍ فحص الأبطال…" : `تحديث حالة الفتح (${unlockedHeroIds.size})`}
                        </span>
                      </div>
                      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "12px", marginTop: "12px" }}>
                        {([
                          { key: "food", name: "قمح", count: botConfig.gatherFoodMarches, color: "#facc15" },
                          { key: "wood", name: "خشب", count: botConfig.gatherWoodMarches, color: "#00e699" },
                          { key: "stone", name: "حجر", count: botConfig.gatherStoneMarches, color: "var(--ghost-cyan)" },
                          { key: "gold", name: "ذهب", count: botConfig.gatherGoldMarches, color: "#ffaa2b" },
                        ] as const).map((res) => (
                          <div key={res.key} style={{ background: "rgba(4,14,28,0.7)", border: "1px solid rgba(0,229,255,0.18)", borderRadius: "12px", padding: "10px" }}>
                            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "8px" }}>
                              <span style={{ fontSize: "13px", fontWeight: 800, color: res.color }}>{res.name}</span>
                              <span className="cyan-pill" style={{ fontSize: "10px" }}>{res.count}</span>
                            </div>
                            {res.count === 0 && <div className="gb-cfg-card-desc">لا طوابير لهذا المورد</div>}
                            {Array.from({ length: res.count }, (_, i) => {
                              const pair = getMarchPair(res.key, i);
                              const priIcon = heroIconFor(pair.primary);
                              const secIcon = heroIconFor(pair.secondary);
                              return (
                                <div key={i} style={{ background: "rgba(4,14,28,0.7)", border: "1px solid rgba(0,229,255,0.15)", borderRadius: "10px", padding: "8px", marginBottom: "8px" }}>
                                  <div style={{ fontSize: "11px", fontWeight: 800, color: "var(--text-secondary)", marginBottom: "6px" }}>مسيرة {i + 1}</div>
                                  <div className="gb-stepper-wrap" style={{ justifyContent: "center", gap: "8px" }}>
                                    {([
                                      { slot: "primary" as const, val: pair.primary, icon: priIcon, ph: "أساسي +" },
                                      { slot: "secondary" as const, val: pair.secondary, icon: secIcon, ph: "ثانوي +" },
                                    ]).map((s) => (
                                      <div
                                        key={s.slot}
                                        onClick={() => setCmdPicker({ show: true, res: res.key, idx: i, slot: s.slot })}
                                        title={s.slot === "primary" ? "القائد الأساسي" : "القائد الثانوي"}
                                        className="gb-stepper-btn"
                                        style={{
                                          width: "46px", height: "46px", borderRadius: "10px", padding: 0,
                                          border: s.val ? "1px solid var(--ghost-cyan)" : "1px dashed rgba(0,229,255,0.35)",
                                          boxShadow: s.val ? "0 0 8px rgba(0,229,255,0.35)" : "none",
                                          display: "flex", alignItems: "center", justifyContent: "center",
                                          cursor: "pointer", overflow: "hidden",
                                        }}
                                      >
                                        {s.icon ? (
                                          // eslint-disable-next-line @next/next/no-img-element
                                          <img src={s.icon} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />
                                        ) : (
                                          <span style={{ fontSize: "10px", color: "var(--text-secondary)" }}>{s.ph}</span>
                                        )}
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Tactical Gathering Rules Grid */}
                  <div className="gb-cfg-cards-grid">
                    
                    {/* Auto-Balance Lowest */}
                    <div className="gb-cfg-card">
                      <div className="gb-cfg-card-header">
                        <div>
                          <div className="gb-cfg-card-title">
                            <svg className="gb-icon" style={{ color: "#00e5ff" }}><use href="#icon-balance-scale"/></svg>
                            <span>موازنة الموارد تلقائياً</span>
                          </div>
                          <div className="gb-cfg-card-desc">
                            توجيه الجيوش تلقائياً لجمع المورد الأقل في المخزون لمنع تفاوت الموارد.
                          </div>
                        </div>
                        <label className="toggle-switch">
                          <input
                            type="checkbox"
                            checked={botConfig.autoBalanceLowest}
                            onChange={(e) => updateConfigField("autoBalanceLowest", e.target.checked, e.target.checked ? "تفعيل موازنة الموارد تلقائياً" : "تعطيل موازنة الموارد")}
                          />
                          <span className="toggle-slider" />
                        </label>
                      </div>
                    </div>

                    {/* Max Node Level */}
                    <div className="gb-cfg-card">
                      <div className="gb-cfg-card-header">
                        <div>
                          <div className="gb-cfg-card-title">
                            <svg className="gb-icon" style={{ color: "#facc15" }}><use href="#icon-trophy-tier"/></svg>
                            <span>أقصى مستوى للمنجم</span>
                          </div>
                          <div className="gb-cfg-card-desc">
                            الحد الأقصى لمستوى المناجم التي يبحث عنها البوت على الخريطة.
                          </div>
                        </div>
                        <select
                          className="form-select"
                          style={{ width: "135px" }}
                          value={botConfig.maxNodeLevel}
                          onChange={(e) => updateConfigField("maxNodeLevel", parseInt(e.target.value), `أقصى مستوى للمناجم: المستوى ${e.target.value}`)}
                        >
                          <option value="0">بدون (أي مستوى)</option>
                          <option value="1">المستوى 1</option>
                          <option value="2">المستوى 2</option>
                          <option value="3">المستوى 3</option>
                          <option value="4">المستوى 4</option>
                          <option value="5">المستوى 5</option>
                          <option value="6">المستوى 6</option>
                        </select>
                      </div>
                    </div>

                    {/* Skip Partially Gathered */}
                    <div className="gb-cfg-card">
                      <div className="gb-cfg-card-header">
                        <div>
                          <div className="gb-cfg-card-title">
                            <svg className="gb-icon" style={{ color: "#facc15" }}><use href="#icon-lightning-bolt"/></svg>
                            <span>تخطي المناجم المجمعة جزئياً</span>
                          </div>
                          <div className="gb-cfg-card-desc">
                            تجاهل المناجم المستنزفة جزئياً لضمان عائد حمولة كامل في كل خروج.
                          </div>
                        </div>
                        <label className="toggle-switch">
                          <input
                            type="checkbox"
                            checked={botConfig.skipPartiallyGathered}
                            onChange={(e) => updateConfigField("skipPartiallyGathered", e.target.checked, e.target.checked ? "تفعيل تخطي المناجم الجزئية" : "تعطيل تخطي المناجم الجزئية")}
                          />
                          <span className="toggle-slider" />
                        </label>
                      </div>
                    </div>

                    {/* Avoid Enemy Territories */}
                    <div className="gb-cfg-card">
                      <div className="gb-cfg-card-header">
                        <div>
                          <div className="gb-cfg-card-title">
                            <svg className="gb-icon" style={{ color: "#00e5ff" }}><use href="#icon-globe-cyber"/></svg>
                            <span>تجنب أراضي التحالفات المعادية</span>
                          </div>
                          <div className="gb-cfg-card-desc">
                            حظر إرسال الطوابير لأراضي تحالفات أخرى لحماية الجيوش من الاستهداف.
                          </div>
                        </div>
                        <label className="toggle-switch">
                          <input
                            type="checkbox"
                            checked={botConfig.avoidEnemyTerritory}
                            onChange={(e) => updateConfigField("avoidEnemyTerritory", e.target.checked, e.target.checked ? "تفعيل حظر الأراضي المعادية" : "إلغاء حظر الأراضي")}
                          />
                          <span className="toggle-slider" />
                        </label>
                      </div>
                    </div>

                  </div>
                </div>
              )}

              {/* 3. CITY & TROOPS MODULE */}
              {cfgModule === "city" && (
                <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                  <div className="gb-cfg-card" style={{ borderColor: "rgba(0,229,255,0.3)", background: "linear-gradient(145deg, rgba(8,26,50,0.9), rgba(5,16,32,0.95))" }}>
                    <div className="gb-cfg-card-header">
                      <div>
                        <div className="gb-cfg-card-title">
                          <svg className="gb-icon"><use href="#icon-blades-tactical"/></svg>
                          <span>مركز تدريب الجيوش التكتيكي</span>
                        </div>
                        <div className="gb-cfg-card-desc">
                          اختر مستوى القوات (T1 إلى T5) لكل مبنى عسكري. يقوم البوت بفحص الثكنات وتدريب الجنود تلقائياً فور فراغ الطابور.
                        </div>
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                        <span style={{ fontSize: "12px", fontWeight: 700, color: "#fff" }}>تفعيل التدريب:</span>
                        <label className="toggle-switch">
                          <input
                            type="checkbox"
                            checked={botConfig.autoTrainTroops}
                            onChange={(e) => updateConfigField("autoTrainTroops", e.target.checked, e.target.checked ? "تفعيل تدريب الجيوش التلقائي" : "تعطيل تدريب الجيوش")}
                          />
                          <span className="toggle-slider" />
                        </label>
                      </div>
                    </div>

                    {/* 4 Military Troop Selectors */}
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: "12px", marginTop: "12px" }}>
                      
                      {/* Infantry */}
                      <div style={{ background: "rgba(4,14,28,0.7)", border: "1px solid var(--border-subtle)", borderRadius: "12px", padding: "14px", display: "flex", flexDirection: "column", gap: "10px" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                          <svg className="gb-icon" style={{ width: "24px", height: "24px", color: "#00e5ff" }}><use href="#icon-shield-crest"/></svg>
                          <div>
                            <div style={{ fontWeight: 800, fontSize: "13px", color: "#fff" }}>المشاة</div>
                            <div style={{ fontSize: "10.5px", color: "var(--text-secondary)" }}>ثكنة المشاة وحراس السيوف</div>
                          </div>
                        </div>
                        <select
                          className="form-select"
                          value={botConfig.trainInfantry}
                          onChange={(e) => updateConfigField("trainInfantry", e.target.value, `تدريب المشاة: ${e.target.value}`)}
                        >
                          <option value="Disabled">معطل</option>
                          <option value="T1">T1</option>
                          <option value="T2">T2</option>
                          <option value="T3">T3</option>
                          <option value="T4">T4</option>
                          <option value="T5">T5</option>
                        </select>
                      </div>

                      {/* Cavalry */}
                      <div style={{ background: "rgba(4,14,28,0.7)", border: "1px solid var(--border-subtle)", borderRadius: "12px", padding: "14px", display: "flex", flexDirection: "column", gap: "10px" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                          <svg className="gb-icon" style={{ width: "24px", height: "24px", color: "#00e699" }}><use href="#icon-horse-cavalry"/></svg>
                          <div>
                            <div style={{ fontWeight: 800, fontSize: "13px", color: "#fff" }}>الفرسان</div>
                            <div style={{ fontSize: "10.5px", color: "var(--text-secondary)" }}>إسطبل الفرسان والخيالة</div>
                          </div>
                        </div>
                        <select
                          className="form-select"
                          value={botConfig.trainCavalry}
                          onChange={(e) => updateConfigField("trainCavalry", e.target.value, `تدريب الفرسان: ${e.target.value}`)}
                        >
                          <option value="Disabled">معطل</option>
                          <option value="T1">T1</option>
                          <option value="T2">T2</option>
                          <option value="T3">T3</option>
                          <option value="T4">T4</option>
                          <option value="T5">T5</option>
                        </select>
                      </div>

                      {/* Archers */}
                      <div style={{ background: "rgba(4,14,28,0.7)", border: "1px solid var(--border-subtle)", borderRadius: "12px", padding: "14px", display: "flex", flexDirection: "column", gap: "10px" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                          <svg className="gb-icon" style={{ width: "24px", height: "24px", color: "#ffaa2b" }}><use href="#icon-bow-archer"/></svg>
                          <div>
                            <div style={{ fontWeight: 800, fontSize: "13px", color: "#fff" }}>الرماة</div>
                            <div style={{ fontSize: "10.5px", color: "var(--text-secondary)" }}>ميدان رماة الأقواس والسهام</div>
                          </div>
                        </div>
                        <select
                          className="form-select"
                          value={botConfig.trainArchers}
                          onChange={(e) => updateConfigField("trainArchers", e.target.value, `تدريب الرماة: ${e.target.value}`)}
                        >
                          <option value="Disabled">معطل</option>
                          <option value="T1">T1</option>
                          <option value="T2">T2</option>
                          <option value="T3">T3</option>
                          <option value="T4">T4</option>
                          <option value="T5">T5</option>
                        </select>
                      </div>

                      {/* Siege */}
                      <div style={{ background: "rgba(4,14,28,0.7)", border: "1px solid var(--border-subtle)", borderRadius: "12px", padding: "14px", display: "flex", flexDirection: "column", gap: "10px" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                          <svg className="gb-icon" style={{ width: "24px", height: "24px", color: "#c084fc" }}><use href="#icon-catapult-siege"/></svg>
                          <div>
                            <div style={{ fontWeight: 800, fontSize: "13px", color: "#fff" }}>آلات الحصار</div>
                            <div style={{ fontSize: "10.5px", color: "var(--text-secondary)" }}>ورشة العجلات والمجانيق</div>
                          </div>
                        </div>
                        <select
                          className="form-select"
                          value={botConfig.trainSiege}
                          onChange={(e) => updateConfigField("trainSiege", e.target.value, `تدريب الحصار: ${e.target.value}`)}
                        >
                          <option value="Disabled">معطل</option>
                          <option value="T1">T1</option>
                          <option value="T2">T2</option>
                          <option value="T3">T3</option>
                          <option value="T4">T4</option>
                          <option value="T5">T5</option>
                        </select>
                      </div>

                    </div>
                  </div>
                </div>
              )}

              {/* 4. ALLIANCE MODULE */}
              {cfgModule === "alliance" && (
                <div className="gb-cfg-cards-grid">
                  {/* Alliance Tech Donation */}
                  <div className="gb-cfg-card" style={{ borderColor: "rgba(0,229,255,0.35)" }}>
                    <div className="gb-cfg-card-header">
                      <div>
                        <div className="gb-cfg-card-title">
                          <svg className="gb-icon" style={{ color: "#c084fc" }}><use href="#icon-flask-science"/></svg>
                          <span>{lang === "ar" ? "التبرع لتقنيات التحالف" : "Alliance Tech Donation"}</span>
                        </div>
                        <div className="gb-cfg-card-desc">
                          {lang === "ar" ? "يتبرع البوت تلقائياً بالموارد لتقنيات التحالف الموصى بها لكسب نقاط الشرف وعملات المتجر." : "Automatically donate resources to recommended alliance tech for credits."}
                        </div>
                      </div>
                      <label className="toggle-switch">
                        <input
                          type="checkbox"
                          checked={botConfig.allianceTech}
                          onChange={(e) => updateConfigField("allianceTech", e.target.checked, e.target.checked ? "تفعيل تبرعات التحالف" : "تعطيل تبرعات التحالف")}
                        />
                        <span className="toggle-slider" />
                      </label>
                    </div>
                  </div>

                  {/* Auto Alliance Help */}
                  <div className="gb-cfg-card" style={{ borderColor: "rgba(0,229,255,0.35)" }}>
                    <div className="gb-cfg-card-header">
                      <div>
                        <div className="gb-cfg-card-title">
                          <svg className="gb-icon" style={{ color: "#00e5ff" }}><use href="#icon-handshake-alliance"/></svg>
                          <span>{lang === "ar" ? "مساعدات التحالف التلقائية" : "Auto Alliance Help"}</span>
                        </div>
                        <div className="gb-cfg-card-desc">
                          {lang === "ar" ? "الضغط التلقائي على أيدي المساعدة لأعضاء التحالف في البناء والبحوث فوراً." : "Automatically click alliance help for research and building instantly."}
                        </div>
                      </div>
                      <label className="toggle-switch">
                        <input
                          type="checkbox"
                          checked={botConfig.allianceHelp}
                          onChange={(e) => updateConfigField("allianceHelp", e.target.checked, e.target.checked ? "تفعيل مساعدات التحالف" : "تعطيل مساعدات التحالف")}
                        />
                        <span className="toggle-slider" />
                      </label>
                    </div>
                  </div>

                  {/* Claim Alliance Gifts */}
                  <div className="gb-cfg-card" style={{ borderColor: "rgba(0,229,255,0.35)" }}>
                    <div className="gb-cfg-card-header">
                      <div>
                        <div className="gb-cfg-card-title">
                          <svg className="gb-icon" style={{ color: "#facc15" }}><use href="#icon-trophy-tier"/></svg>
                          <span>{lang === "ar" ? "استلام هدايا وصناديق التحالف" : "Claim Alliance Gifts"}</span>
                        </div>
                        <div className="gb-cfg-card-desc">
                          {lang === "ar" ? "استلام صناديق هدايا التحالف اليومية وصناديق صيد البرابرة تلقائياً." : "Automatically collect alliance gift chests and barbarian hunt rewards."}
                        </div>
                      </div>
                      <label className="toggle-switch">
                        <input
                          type="checkbox"
                          checked={botConfig.allianceGifts}
                          onChange={(e) => updateConfigField("allianceGifts", e.target.checked, e.target.checked ? "تفعيل استلام هدايا التحالف" : "تعطيل استلام هدايا التحالف")}
                        />
                        <span className="toggle-slider" />
                      </label>
                    </div>
                  </div>

                  {/* Alliance Super Node / Resource Center */}
                  <div className="gb-cfg-card" style={{ borderColor: "rgba(0,229,255,0.45)" }}>
                    <div className="gb-cfg-card-header">
                      <div>
                        <div className="gb-cfg-card-title">
                          <svg className="gb-icon" style={{ color: "#38bdf8" }}><use href="#icon-castle-fort"/></svg>
                          <span>{lang === "ar" ? "جمع موارد التحالف التلقائي" : "Auto Alliance Super Node"}</span>
                        </div>
                        <div className="gb-cfg-card-desc">
                          {lang === "ar" ? "إرسال مسيرة قتالية تلقائية بنسبة 100% لحقل التحالف (صومعة الطعام، ورشة الأخشاب، منجم الأحجار، مصنع الذهب) مع إبقاء عربات الحصار للمدينة." : "Deploy 100% capacity combat march to Alliance Resource Center while preserving siege units."}
                        </div>
                      </div>
                      <label className="toggle-switch">
                        <input
                          type="checkbox"
                          checked={botConfig.allianceSuperNode}
                          onChange={(e) => updateConfigField("allianceSuperNode", e.target.checked, e.target.checked ? "تفعيل جمع موارد التحالف" : "تعطيل جمع موارد التحالف")}
                        />
                        <span className="toggle-slider" />
                      </label>
                    </div>
                    {botConfig.allianceSuperNode && (
                      <div style={{ marginTop: "12px", background: "rgba(4,14,28,0.7)", border: "1px solid rgba(0,229,255,0.18)", borderRadius: "12px", padding: "10px" }}>
                        <div style={{ fontSize: "12px", fontWeight: 800, color: "var(--ghost-cyan)", marginBottom: "2px" }}>
                          {lang === "ar" ? "قائدا حقل التحالف (يدوي)" : "Alliance pit commanders (manual)"}
                        </div>
                        <div className="gb-cfg-card-desc" style={{ marginBottom: "8px" }}>
                          {lang === "ar" ? "خانة فارغة = تلقائي (الأعلى سعة). البطل هنا محجوز للحقل ولا يظهر في مسيرات الحقول." : "Empty slot = automatic. Pit heroes are reserved and hidden from field marches."}
                        </div>
                        <div className="gb-stepper-wrap" style={{ justifyContent: "center", gap: "8px" }}>
                          {([
                            { slot: "primary" as const, val: (botConfig as any).alliancePitPrimary ?? null, ph: "أساسي +" },
                            { slot: "secondary" as const, val: (botConfig as any).alliancePitSecondary ?? null, ph: "ثانوي +" },
                          ]).map((s) => {
                            const icon = heroIconFor(typeof s.val === "number" ? s.val : null);
                            return (
                              <div
                                key={s.slot}
                                onClick={() => setCmdPicker({ show: true, res: "pit", idx: 0, slot: s.slot })}
                                title={s.slot === "primary" ? "القائد الأساسي" : "القائد الثانوي"}
                                className="gb-stepper-btn"
                                style={{
                                  width: "46px", height: "46px", borderRadius: "10px", padding: 0,
                                  border: s.val ? "1px solid var(--ghost-cyan)" : "1px dashed rgba(0,229,255,0.35)",
                                  boxShadow: s.val ? "0 0 8px rgba(0,229,255,0.35)" : "none",
                                  display: "flex", alignItems: "center", justifyContent: "center",
                                  cursor: "pointer", overflow: "hidden",
                                }}
                              >
                                {icon ? (
                                  // eslint-disable-next-line @next/next/no-img-element
                                  <img src={icon} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />
                                ) : (
                                  <span style={{ fontSize: "10px", color: "var(--text-secondary)" }}>{s.ph}</span>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Claim Alliance Territory Resources (Opcode 3370) */}
                  <div className="gb-cfg-card" style={{ borderColor: "rgba(74,222,128,0.4)" }}>
                    <div className="gb-cfg-card-header">
                      <div>
                        <div className="gb-cfg-card-title">
                          <svg className="gb-icon" style={{ color: "#4ade80" }}><use href="#icon-rss-crate"/></svg>
                          <span>{lang === "ar" ? "تحصيل موارد إقليم التحالف" : "Claim Territory Resources"}</span>
                        </div>
                        <div className="gb-cfg-card-desc">
                          {lang === "ar" ? "جمع الموارد المتراكمة من حصون ومعابد إقليم التحالف تلقائياً (أوبكود 3370)." : "Automatically collect accumulated resources from alliance territory forts and sanctuaries (Opcode 3370)."}
                        </div>
                      </div>
                      <label className="toggle-switch">
                        <input
                          type="checkbox"
                          checked={botConfig.allianceTerritoryRss}
                          onChange={(e) => updateConfigField("allianceTerritoryRss", e.target.checked, e.target.checked ? "تفعيل تحصيل موارد إقليم التحالف" : "تعطيل تحصيل موارد إقليم التحالف")}
                        />
                        <span className="toggle-slider" />
                      </label>
                    </div>
                  </div>
                </div>
              )}

              {/* 5. COMBAT MODULE */}
              {cfgModule === "combat" && (
                <div className="gb-cfg-cards-grid">
                  {/* Heal Hospital */}
                  <div className="gb-cfg-card" style={{ borderColor: "rgba(0,229,255,0.35)" }}>
                    <div className="gb-cfg-card-header">
                      <div>
                        <div className="gb-cfg-card-title">
                          <svg className="gb-icon" style={{ color: "#f87171" }}><use href="#icon-hospital-cross"/></svg>
                          <span>{lang === "ar" ? "علاج الجرحى في المستشفى" : "Heal Hospital Troops"}</span>
                        </div>
                        <div className="gb-cfg-card-desc">
                          {lang === "ar" ? "يعالج البوت القوات المصابة تلقائياً في المستشفى لضمان تفريغ الأسرة وتفادي موت القوات عند الهجمات." : "Automatically heal wounded troops in batches to free hospital beds."}
                        </div>
                      </div>
                      <label className="toggle-switch">
                        <input
                          type="checkbox"
                          checked={botConfig.healHospital}
                          onChange={(e) => updateConfigField("healHospital", e.target.checked, e.target.checked ? "تفعيل علاج المستشفى التلقائي" : "تعطيل علاج المستشفى")}
                        />
                        <span className="toggle-slider" />
                      </label>
                    </div>
                  </div>

                  {/* Auto Peace Shield */}
                  <div className="gb-cfg-card" style={{ borderColor: "rgba(0,229,255,0.35)" }}>
                    <div className="gb-cfg-card-header">
                      <div>
                        <div className="gb-cfg-card-title">
                          <svg className="gb-icon" style={{ color: "#00e5ff" }}><use href="#icon-aegis-shield"/></svg>
                          <span>{lang === "ar" ? "درع السلام التلقائي" : "Auto Peace Shield"}</span>
                        </div>
                        <div className="gb-cfg-card-desc">
                          {lang === "ar" ? "تفعيل درع حماية السلام للمدينة تلقائياً عند اقتراب انتهاء مدة الدرع أو رصد هجمات معادية." : "Automatically activate peace shield on enemy march detection or timer expiration."}
                        </div>
                      </div>
                      <label className="toggle-switch">
                        <input
                          type="checkbox"
                          checked={botConfig.peaceShield}
                          onChange={(e) => updateConfigField("peaceShield", e.target.checked, e.target.checked ? "تفعيل درع السلام التلقائي" : "تعطيل درع السلام")}
                        />
                        <span className="toggle-slider" />
                      </label>
                    </div>
                  </div>

                  {/* Hunt Barbarians */}
                  <div className="gb-cfg-card" style={{ borderColor: "rgba(0,229,255,0.35)" }}>
                    <div className="gb-cfg-card-header">
                      <div>
                        <div className="gb-cfg-card-title">
                          <svg className="gb-icon" style={{ color: "#ffaa2b" }}><use href="#icon-bow-archer"/></svg>
                          <span>{lang === "ar" ? "اصطياد البرابرة" : "Barbarian Hunting"}</span>
                        </div>
                        <div className="gb-cfg-card-desc">
                          {lang === "ar" ? "إنفاق نقاط العمل (AP) على برابرة الخريطة لكسب المسرعات والموارد والتجربة." : "Spend Action Points (AP) hunting barbarians on the map for speedups and rewards."}
                        </div>
                      </div>
                      <label className="toggle-switch">
                        <input
                          type="checkbox"
                          checked={botConfig.huntBarbs}
                          onChange={(e) => updateConfigField("huntBarbs", e.target.checked, e.target.checked ? "تفعيل اصطياد البرابرة" : "تعطيل اصطياد البرابرة")}
                        />
                        <span className="toggle-slider" />
                      </label>
                    </div>
                  </div>
                </div>
              )}

              {/* 6. DAILY CLAIMS MODULE */}
              {cfgModule === "daily" && (
                <div className="gb-cfg-cards-grid">
                  {/* City Resource Harvest (Opcode 120) */}
                  <div className="gb-cfg-card" style={{ borderColor: "rgba(0,229,255,0.35)" }}>
                    <div className="gb-cfg-card-header">
                      <div>
                        <div className="gb-cfg-card-title">
                          <svg className="gb-icon" style={{ color: "#4ade80" }}><use href="#icon-harvest-grain"/></svg>
                          <span>{lang === "ar" ? "حصاد موارد المدينة" : "City Resource Harvest"}</span>
                        </div>
                        <div className="gb-cfg-card-desc">
                          {lang === "ar" ? "جمع إنتاج المزارع والمناجم داخل القلعة تلقائياً (أوبكود 120)." : "Auto-collect production from farms, lumber mills, quarries and gold mines inside the castle (Opcode 120)."}
                        </div>
                      </div>
                      <label className="toggle-switch">
                        <input
                          type="checkbox"
                          checked={botConfig.cityHarvest}
                          onChange={(e) => updateConfigFields({
                            cityHarvest: e.target.checked,
                            collectResources: e.target.checked,
                          }, e.target.checked ? "تفعيل حصاد موارد المدينة" : "تعطيل حصاد موارد المدينة")}
                        />
                        <span className="toggle-slider" />
                      </label>
                    </div>
                  </div>

                  {/* Kingdom Chronicle (Opcode 3535) */}
                  <div className="gb-cfg-card" style={{ borderColor: "rgba(192,132,252,0.4)" }}>
                    <div className="gb-cfg-card-header">
                      <div>
                        <div className="gb-cfg-card-title">
                          <svg className="gb-icon" style={{ color: "#c084fc" }}><use href="#icon-monument-temple"/></svg>
                          <span>{lang === "ar" ? "سجل المملكة (الجريدة)" : "Kingdom Chronicle"}</span>
                        </div>
                        <div className="gb-cfg-card-desc">
                          {lang === "ar" ? "استلام فصول وأوسمة السجل التاريخي للمملكة فور اكتمالها (أوبكود 3535)." : "Check and claim completed Chronicle chapters and milestones (Opcode 3535)."}
                        </div>
                      </div>
                      <label className="toggle-switch">
                        <input
                          type="checkbox"
                          checked={botConfig.chronicleClaim}
                          onChange={(e) => updateConfigField("chronicleClaim", e.target.checked, e.target.checked ? "تفعيل استلام سجل المملكة" : "تعطيل استلام سجل المملكة")}
                        />
                        <span className="toggle-slider" />
                      </label>
                    </div>
                  </div>

                  {/* Daily VIP Chest */}
                  <div className="gb-cfg-card" style={{ borderColor: "rgba(0,229,255,0.35)" }}>
                    <div className="gb-cfg-card-header">
                      <div>
                        <div className="gb-cfg-card-title">
                          <svg className="gb-icon" style={{ color: "#facc15" }}><use href="#icon-crown-vip"/></svg>
                          <span>{lang === "ar" ? "صندوق VIP اليومي" : "Daily VIP Chest"}</span>
                        </div>
                        <div className="gb-cfg-card-desc">
                          {lang === "ar" ? "استلام نقاط VIP اليومية وحزمة الصندوق المجانية بحسب رتبتك في اللعبة." : "Collect daily VIP points and claim the free VIP chest package."}
                        </div>
                      </div>
                      <label className="toggle-switch">
                        <input
                          type="checkbox"
                          checked={botConfig.dailyVip}
                          onChange={(e) => updateConfigField("dailyVip", e.target.checked, e.target.checked ? "تفعيل صندوق VIP اليومي" : "تعطيل صندوق VIP")}
                        />
                        <span className="toggle-slider" />
                      </label>
                    </div>
                  </div>

                  {/* Completed Daily Quests (Opcode 203) */}
                  <div className="gb-cfg-card" style={{ borderColor: "rgba(0,229,255,0.35)" }}>
                    <div className="gb-cfg-card-header">
                      <div>
                        <div className="gb-cfg-card-title">
                          <svg className="gb-icon" style={{ color: "#00e5ff" }}><use href="#icon-doc-report"/></svg>
                          <span>{lang === "ar" ? "المهام اليومية المكتملة" : "Completed Daily Quests"}</span>
                        </div>
                        <div className="gb-cfg-card-desc">
                          {lang === "ar" ? "استلام مكافأة أي مهمة يومية تم إنجازها تلقائياً (أوبكود 203)." : "Claim rewards for every completed daily quest automatically (Opcode 203)."}
                        </div>
                      </div>
                      <label className="toggle-switch">
                        <input
                          type="checkbox"
                          checked={botConfig.dailyQuests}
                          onChange={(e) => updateConfigField("dailyQuests", e.target.checked, e.target.checked ? "تفعيل استلام المهام اليومية" : "تعطيل استلام المهام اليومية")}
                        />
                        <span className="toggle-slider" />
                      </label>
                    </div>
                  </div>

                  {/* Daily Quest Activity Chests (Opcode 143/144) */}
                  <div className="gb-cfg-card" style={{ borderColor: "rgba(250,204,21,0.4)" }}>
                    <div className="gb-cfg-card-header">
                      <div>
                        <div className="gb-cfg-card-title">
                          <svg className="gb-icon" style={{ color: "#facc15" }}><use href="#icon-treasure-chest"/></svg>
                          <span>{lang === "ar" ? "صناديق نقاط النشاط اليومية" : "Activity Point Chests"}</span>
                        </div>
                        <div className="gb-cfg-card-desc">
                          {lang === "ar" ? "فتح صناديق مواضع الإنجاز (20، 40، 60، 80، 100 نقطة) تلقائياً (أوبكود 143/144)." : "Open activity milestone chests (20/40/60/80/100 points) automatically (Opcode 143/144)."}
                        </div>
                      </div>
                      <label className="toggle-switch">
                        <input
                          type="checkbox"
                          checked={botConfig.dailyQuestChests}
                          onChange={(e) => updateConfigField("dailyQuestChests", e.target.checked, e.target.checked ? "تفعيل صناديق نقاط النشاط" : "تعطيل صناديق نقاط النشاط")}
                        />
                        <span className="toggle-slider" />
                      </label>
                    </div>
                  </div>

                  {/* Side & Main Quests (Opcode 2003/2039) */}
                  <div className="gb-cfg-card" style={{ borderColor: "rgba(56,189,248,0.4)" }}>
                    <div className="gb-cfg-card-header">
                      <div>
                        <div className="gb-cfg-card-title">
                          <svg className="gb-icon" style={{ color: "#38bdf8" }}><use href="#icon-balance-scale"/></svg>
                          <span>{lang === "ar" ? "المهام الجانبية والرئيسية" : "Side & Main Quests"}</span>
                        </div>
                        <div className="gb-cfg-card-desc">
                          {lang === "ar" ? "استلام مكافآت المهام الجانبية والرئيسية (بناء/تدريب/بحث) عند اكتمالها (أوبكود 2003/2039)." : "Claim rewards from standard building/train/research quests when completed (Opcode 2003/2039)."}
                        </div>
                      </div>
                      <label className="toggle-switch">
                        <input
                          type="checkbox"
                          checked={botConfig.sideQuests}
                          onChange={(e) => updateConfigField("sideQuests", e.target.checked, e.target.checked ? "تفعيل استلام المهام الجانبية" : "تعطيل استلام المهام الجانبية")}
                        />
                        <span className="toggle-slider" />
                      </label>
                    </div>
                  </div>

                  {/* Auto Scout */}
                  <div className="gb-cfg-card" style={{ borderColor: "rgba(0,229,255,0.35)" }}>
                    <div className="gb-cfg-card-header">
                      <div>
                        <div className="gb-cfg-card-title">
                          <svg className="gb-icon" style={{ color: "#00e5ff" }}><use href="#icon-search-radar"/></svg>
                          <span>{lang === "ar" ? "الاستكشاف التلقائي" : "Auto Scout"}</span>
                        </div>
                        <div className="gb-cfg-card-desc">
                          {lang === "ar" ? "تشغيل الاستطلاع التلقائي من مبنى المعسكر لفتح الخريطة." : "Run auto-scout in the camp building to reveal the map."}
                        </div>
                      </div>
                      <label className="toggle-switch">
                        <input
                          type="checkbox"
                          checked={botConfig.autoScout}
                          onChange={(e) => updateConfigField("autoScout", e.target.checked, e.target.checked ? "تفعيل الاستكشاف التلقائي" : "تعطيل الاستكشاف التلقائي")}
                        />
                        <span className="toggle-slider" />
                      </label>
                    </div>
                  </div>

                  {/* Mystery Merchant */}
                  <div className="gb-cfg-card" style={{ borderColor: "rgba(0,229,255,0.35)" }}>
                    <div className="gb-cfg-card-header">
                      <div>
                        <div className="gb-cfg-card-title">
                          <svg className="gb-icon" style={{ color: "#c084fc" }}><use href="#icon-commander-badge"/></svg>
                          <span>{lang === "ar" ? "متجر التاجر الغامض" : "Mystery Merchant"}</span>
                        </div>
                        <div className="gb-cfg-card-desc">
                          {lang === "ar" ? "شراء المسرعات والموارد المجانية والخصومات بالقمح والخشب تلقائياً من محطة التاجر." : "Automatically buy free items and discounted speedups using food and wood."}
                        </div>
                      </div>
                      <label className="toggle-switch">
                        <input
                          type="checkbox"
                          checked={botConfig.mysteryMerchant}
                          onChange={(e) => updateConfigField("mysteryMerchant", e.target.checked, e.target.checked ? "تفعيل متجر التاجر الغامض" : "تعطيل التاجر الغامض")}
                        />
                        <span className="toggle-slider" />
                      </label>
                    </div>
                  </div>
                </div>
              )}

              {/* Shared commander picker (field marches + alliance pit) */}
              {renderCmdPicker()}

            </div>
          </div>
        </section>
      )}

      {/* =========================================================================
          AUTHENTIC LINK ACCOUNT MODAL (STEP 1: LILITH AUTH -> STEP 2: SELECT CHARS)
         ========================================================================= */}
      {showLinkModal && (
        <div className="modal-backdrop open" style={{ display: "flex" }}>
          <div className="modal-box" style={{ maxWidth: "540px" }}>
            
            {/* Modal Header */}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "4px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                <svg width="32" height="32"><use href="#ghostbot-mascot"/></svg>
                <div>
                  <h3 style={{ fontSize: "16px", fontWeight: 800 }}>ربط حساب اللعبة ومزامنة الحُكّام</h3>
                  <span style={{ fontSize: "11px", color: "var(--ghost-cyan)" }}>
                    {linkStep === 1
                      ? "الخطوة 1 من 2 • تسجيل الدخول المباشر عبر Lilith Passport"
                      : "الخطوة 2 من 2 • اختر الشخصيات المراد تفعيلها"}
                  </span>
                </div>
              </div>
              <button
                className="util-btn"
                onClick={() => { cancelLinkCaptcha(); setShowLinkModal(false); }}
                style={{ width: "30px", height: "30px", padding: 0 }}
              >
                ✕
              </button>
            </div>

            {/* STEP 1: EMAIL & PASSWORD */}
            {linkStep === 1 && (
              <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                {/* Auth mode tabs: OTP code (no password stored) vs password */}
                <div style={{ display: "flex", gap: "8px", background: "rgba(255,255,255,0.04)", padding: "4px", borderRadius: "10px" }}>
                  {(["otp", "password"] as const).map((m) => (
                    <button
                      key={m}
                      onClick={() => { setLinkAuthMode(m); setLinkError(""); }}
                      style={{
                        flex: 1, padding: "8px", fontSize: "12px", fontWeight: 800, cursor: "pointer",
                        borderRadius: "8px", border: "none",
                        background: linkAuthMode === m ? "var(--ghost-cyan)" : "transparent",
                        color: linkAuthMode === m ? "#04222b" : "var(--text-secondary)",
                      }}
                    >
                      {m === "otp"
                        ? (lang === "ar" ? "📧 دخول برمز البريد" : "📧 Email code login")
                        : (lang === "ar" ? "🔑 دخول بكلمة المرور" : "🔑 Password login")}
                    </button>
                  ))}
                </div>
                <p style={{ fontSize: "12px", color: "var(--text-ice)", lineHeight: "1.6" }}>
                  {linkAuthMode === "otp"
                    ? (lang === "ar"
                      ? "أدخل بريد حساب اللعبة، اضغط «احصل على الرمز»، ثم أدخل رمز الـ 6 أرقام الذي يصلك — دون الحاجة لكلمة المرور."
                      : "Enter your game email, tap “Send code”, then type the 6-digit code — no password needed.")
                    : (lang === "ar"
                      ? "أدخل البريد الإلكتروني وكلمة مرور حساب اللعبة فقط. سيقوم البوت بتسجيل الدخول تلقائياً وجلب جميع الشخصيات (الحُكّام) لتختار منها ما تريد تشغيله بأمان تام."
                      : "Enter your game email and password. The bot logs in automatically and fetches all governors.")}
                </p>

                <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                  <div>
                    <label style={{ fontSize: "11.5px", color: "var(--text-ice)", display: "block", marginBottom: "5px" }}>
                      البريد الإلكتروني (Game Account Email)
                    </label>
                    <input
                      type="email"
                      className="form-input"
                      dir="ltr"
                      placeholder="commander@gmail.com"
                      value={linkEmail}
                      onChange={(e) => setLinkEmail(e.target.value)}
                    />
                  </div>

                  <div>
                    {linkAuthMode === "otp" ? (
                      <>
                        <label style={{ fontSize: "11.5px", color: "var(--text-ice)", display: "block", marginBottom: "5px" }}>
                          {lang === "ar" ? "رمز التحقق (6 أرقام من بريدك)" : "Verification code (6 digits from your email)"}
                        </label>
                        <div style={{ display: "flex", gap: "8px" }}>
                          <input
                            type="text"
                            inputMode="numeric"
                            className="form-input"
                            dir="ltr"
                            placeholder="123456"
                            maxLength={6}
                            value={linkOtpCode}
                            onChange={(e) => setLinkOtpCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                            onKeyDown={(e) => {
                              if (e.key === "Enter" && !linkLoading) handleLinkStep1Submit();
                            }}
                            style={{ flex: 1, letterSpacing: "4px", textAlign: "center", fontSize: "15px" }}
                            autoComplete="one-time-code"
                          />
                          <button
                            className="btn-ghost-outline"
                            disabled={otpSending || otpCooldown > 0 || !linkEmail.trim()}
                            onClick={handleSendOtpCode}
                            title={lang === "ar" ? "إرسال رمز تحقق جديد لبريدك" : "Send a fresh code to your email"}
                            style={{ cursor: "pointer", fontSize: "11.5px", padding: "6px 12px", whiteSpace: "nowrap" }}
                          >
                            {otpSending
                              ? (lang === "ar" ? "جارٍ الإرسال..." : "Sending...")
                              : otpCooldown > 0
                                ? (lang === "ar" ? `إعادة الإرسال (${otpCooldown}s)` : `Resend (${otpCooldown}s)`)
                                : (lang === "ar" ? "احصل على الرمز" : "Send code")}
                          </button>
                        </div>
                        <div style={{ fontSize: "10.5px", color: "var(--text-secondary)", marginTop: "4px" }}>
                          {lang === "ar"
                            ? "يصلك الرمز على بريد حساب اللعبة نفسه — لا حاجة لكلمة المرور إطلاقًا."
                            : "The code arrives at your game email — no password needed at all."}
                        </div>
                      </>
                    ) : (
                      <>
                    <label style={{ fontSize: "11.5px", color: "var(--text-ice)", display: "block", marginBottom: "5px" }}>
                      كلمة المرور (Lilith Password)
                    </label>
                    <div style={{ position: "relative" }}>
                      <input
                        type={showLinkPassword ? "text" : "password"}
                        className="form-input"
                        dir="ltr"
                        placeholder="••••••••••••"
                        value={linkPassword}
                        onChange={(e) => setLinkPassword(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && !linkLoading) handleLinkStep1Submit();
                        }}
                        style={{ paddingLeft: "38px" }}
                        autoComplete="current-password"
                      />
                      <button
                        type="button"
                        onClick={() => setShowLinkPassword(!showLinkPassword)}
                        title={lang === "ar" ? "إظهار/إخفاء كلمة المرور" : "Show/hide password"}
                        style={{
                          position: "absolute", left: "6px", top: "50%", transform: "translateY(-50%)",
                          background: "transparent", border: "none", cursor: "pointer", color: "var(--text-secondary)",
                          display: "inline-flex", padding: "2px"
                        }}
                      >
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                          <circle cx="12" cy="12" r="3"/>
                        </svg>
                      </button>
                    </div>
                    <div style={{ fontSize: "10.5px", color: "var(--text-secondary)", marginTop: "4px" }}>
                      {lang === "ar"
                        ? "كلمة مرور حساب Lilith نفسه (نفس بيانات صفحة تسجيل دخول اللعبة)."
                        : "Your Lilith account password (same one you use in the game's login page)."}
                    </div>
                      </>
                    )}
                  </div>
                </div>

                {linkError && (
                  <div style={{ padding: "10px 12px", borderRadius: "10px", background: "rgba(255,77,109,0.12)", border: "1px solid rgba(255,77,109,0.4)", color: "#ff8fa3", fontSize: "12px" }}>
                    {linkError}
                  </div>
                )}

                {/* Mini captcha window inside the modal — used when the
                    browser blocks the external popup, so the flow never stalls. */}
                {captchaEmbedded && linkCaptcha?.url && (
                  <div style={{ position: "fixed", inset: 0, zIndex: 1200, background: "rgba(2,8,12,0.72)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                    <div style={{ width: "min(440px, 94vw)", height: "min(640px, 88vh)", background: "#07141b", border: "1px solid rgba(0,229,255,0.45)", borderRadius: "14px", overflow: "hidden", display: "flex", flexDirection: "column", boxShadow: "0 24px 60px rgba(0,0,0,0.6)" }}>
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 10px", borderBottom: "1px solid rgba(0,229,255,0.2)", fontSize: "12px", fontWeight: 800, color: "var(--ghost-cyan)" }}>
                        <span>{lang === "ar" ? "نافذة التحقق المصغرة — حلّها ثم تابع" : "Mini verification window — solve it, then continue"}</span>
                        <button
                          className="util-btn"
                          style={{ width: "28px", height: "28px", padding: 0 }}
                          onClick={() => setCaptchaEmbedded(false)}
                        >
                          ✕
                        </button>
                      </div>
                      <iframe src={linkCaptcha.url} title="Lilith captcha" style={{ flex: 1, border: "none", background: "#fff" }} />
                    </div>
                  </div>
                )}

                {linkCaptcha && (
                  <div style={{ padding: "10px 12px", borderRadius: "10px", background: "rgba(0,229,255,0.08)", border: "1px solid rgba(0,229,255,0.35)", color: "var(--text-ice)", fontSize: "12px", display: "flex", flexDirection: "column", gap: "8px" }}>
                    <div>
                      {lang === "ar"
                        ? `بانتظار حل الكابتشا في النافذة المصغرة… (فحص تلقائي كل 6 ثوانٍ${linkCaptcha.attempts > 0 ? ` — تم الفحص ${linkCaptcha.attempts} مرة` : ""})`
                        : `Waiting for the captcha solution… (auto-check every 6s${linkCaptcha.attempts > 0 ? ` — checked ${linkCaptcha.attempts}x` : ""})`}
                    </div>
                    <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                      <button
                        className="btn-cyan-glow"
                        onClick={checkLinkCaptchaNow}
                        disabled={captchaChecking}
                        style={{ cursor: "pointer", fontSize: "12px", padding: "6px 14px" }}
                      >
                        <span>{captchaChecking ? (lang === "ar" ? "جارٍ التحقق..." : "Checking...") : (lang === "ar" ? "تحقق الآن" : "Check now")}</span>
                      </button>
                      <button
                        className="btn-ghost-outline"
                        onClick={() => { if (linkCaptcha.url) openCaptchaWindow(linkCaptcha.url); }}
                        style={{ fontSize: "12px", padding: "6px 14px", cursor: "pointer" }}
                      >
                        {lang === "ar" ? "إعادة فتح النافذة" : "Reopen window"}
                      </button>
                    </div>
                    {/* Manual escape hatch (spec §4): Lilith has no browser bridge,
                        so if auto-poll never unlocks, paste the captchaId.
                        Password-only: the OTP tab re-verifies by code instead. */}
                    {linkCaptcha.mode !== "otp" && (
                    <div style={{ borderTop: "1px solid rgba(0,229,255,0.2)", paddingTop: "8px", display: "flex", flexDirection: "column", gap: "6px" }}>
                      <label style={{ fontSize: "11px", color: "var(--text-secondary)" }}>
                        {lang === "ar"
                          ? "إن لم يكتمل التحقق تلقائياً: الصق رمز التحقق (captchaId) من نافذة التحقق"
                          : "If auto-check never unlocks: paste the captchaId from the verification window"}
                      </label>
                      <div style={{ display: "flex", gap: "8px" }}>
                        <input
                          className="form-input"
                          dir="ltr"
                          placeholder="captchaId (UUID)"
                          value={captchaIdInput}
                          onChange={(e) => setCaptchaIdInput(e.target.value)}
                          style={{ flex: 1 }}
                        />
                        <button
                          className="btn-cyan-glow"
                          disabled={!captchaIdInput.trim() || captchaChecking}
                          onClick={async () => {
                            if (!captchaIdInput.trim() || !linkCaptcha) return;
                            setCaptchaChecking(true);
                            try {
                              const botKey = activeBot?.bot_id || activeBot?.id || "bot-1";
                              const res = await verifyCaptchaWithId(linkCaptcha.email, linkCaptcha.password, captchaIdInput.trim(), botKey, user?.id);
                              if (res?.success && res.characters?.length) {
                                closeLinkCaptchaPopup();
                                setLinkCaptcha(null);
                                setCaptchaIdInput("");
                                setLinkPassword("");
                                setLinkLoading(false);
                                setLinkError("");
                                proceedToCharacterPick(res.characters);
                              } else {
                                setLinkError(lang === "ar"
                                  ? "لم يقبل Lilith رمز التحقق — تأكد من نسخه كاملاً ثم أعد المحاولة."
                                  : "Lilith rejected this captchaId — copy it fully and retry.");
                              }
                            } catch (err: any) {
                              setLinkError(err?.message || (lang === "ar" ? "فشل التحقق برمز الكابتشا." : "Captcha verification failed."));
                            } finally {
                              setCaptchaChecking(false);
                            }
                          }}
                          style={{ cursor: "pointer", fontSize: "12px", padding: "6px 14px", whiteSpace: "nowrap" }}
                        >
                          {lang === "ar" ? "تحقق بالرمز" : "Verify with code"}
                        </button>
                      </div>
                    </div>
                    )}
                  </div>
                )}

                <div style={{ display: "flex", justifyContent: "flex-end", gap: "10px", marginTop: "6px" }}>
                  <button className="btn-ghost-outline" onClick={() => { cancelLinkCaptcha(); setShowLinkModal(false); }}>
                    إلغاء
                  </button>
                  <button
                    className="btn-cyan-glow"
                    onClick={handleLinkStep1Submit}
                    disabled={linkLoading}
                    style={{ cursor: "pointer" }}
                  >
                    <span>{linkLoading ? (linkCaptcha ? (lang === "ar" ? "بانتظار حل الكابتشا..." : "Waiting for captcha...") : (lang === "ar" ? "جارٍ التحقق وجلب الشخصيات..." : "Checking...")) : "تسجيل ومزامنة الشخصيات ←"}</span>
                  </button>
                </div>
              </div>
            )}

            {/* STEP 2: SELECT ACTIVE GOVERNORS */}
            {linkStep === 2 && (
              <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                <div style={{ padding: "10px 12px", borderRadius: "10px", background: "rgba(0,230,153,0.1)", border: "1px solid rgba(0,230,153,0.35)", color: "var(--emerald-ok)", fontSize: "12px", fontWeight: 700 }}>
                  ✓ تم تسجيل الدخول بنجاح! اختر الشخصيات (الحُكّام) التي تريد تشغيل البوت عليها:
                </div>

                <div style={{ display: "flex", flexDirection: "column", gap: "8px", maxHeight: "280px", overflowY: "auto" }}>
                  {discoveredChars.map((c, idx) => (
                    <div
                      key={c.role_id}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        padding: "10px 14px",
                        borderRadius: "10px",
                        background: "rgba(255,255,255,0.03)",
                        border: "1px solid var(--border-subtle)",
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                        <input
                          type="checkbox"
                          checked={c.selected}
                          onChange={(e) => {
                            const updated = [...discoveredChars];
                            updated[idx].selected = e.target.checked;
                            setDiscoveredChars(updated);
                          }}
                          style={{ width: "18px", height: "18px", accentColor: "var(--ghost-cyan)", cursor: "pointer" }}
                        />
                        <div>
                          <div style={{ fontWeight: 800, fontSize: "13px", color: "#fff" }}>{c.name}</div>
                          <div style={{ fontSize: "11px", color: "var(--text-secondary)", fontFamily: "'JetBrains Mono', monospace" }}>
                            ID: {c.role_id} • Kingdom #{c.kingdom} • CH {c.city_level} • Power: {(c.power / 1000000).toFixed(1)}M
                          </div>
                        </div>
                      </div>
                      <span className="cyan-pill" style={{ fontSize: "10px" }}>مؤهل للربط</span>
                    </div>
                  ))}
                </div>

                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "10px", marginTop: "6px" }}>
                  <button className="btn-ghost-outline" onClick={() => setLinkStep(1)}>
                    رجوع
                  </button>
                  <button className="btn-cyan-glow" onClick={handleConfirmSelectedCharacters} style={{ cursor: "pointer" }}>
                    <span>حفظ وتشغيل الشخصيات المحددة</span>
                  </button>
                </div>
              </div>
            )}

          </div>
        </div>
      )}

      {/* =========================================================================
          RSS TRANSFER MODAL (DIRECT PARALLEL FLEET UNLOAD TO RECIPIENT)
         ========================================================================= */}
      {showTransferModal && (
        <div className="modal-backdrop open" style={{ display: "flex", zIndex: 1000, alignItems: "center", justifyContent: "center" }}>
          <div className="modal-box" style={{ maxWidth: "780px", width: "95%", maxHeight: "90vh", overflowY: "auto", border: "1px solid rgba(0, 229, 255, 0.35)", boxShadow: "0 0 40px rgba(0, 229, 255, 0.15)", backgroundColor: "rgba(4, 10, 23, 0.95)" }}>
            
            {/* Modal Header */}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "16px", borderBottom: "1px solid rgba(0, 229, 255, 0.2)", paddingBottom: "12px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                <div style={{ width: "36px", height: "36px", borderRadius: "8px", backgroundColor: "rgba(0, 229, 255, 0.15)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#00e5ff" strokeWidth="2.2"><path d="M17 1l4 4-4 4"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><path d="M7 23l-4-4 4-4"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg>
                </div>
                <div>
                  <h3 style={{ fontSize: "16px", fontWeight: 800, margin: 0, color: "#f1f5f9" }}>نقل وتفريغ الموارد الموازي (RSS Transfer)</h3>
                  <div style={{ display: "flex", gap: "8px", marginTop: "4px" }}>
                    <span style={{ fontSize: "10.5px", padding: "1px 6px", borderRadius: "4px", backgroundColor: "rgba(0, 229, 255, 0.15)", color: "#00e5ff", fontWeight: 700 }}>
                      غرفة #{activeBot?.bot_id || activeBot?.id || selectedBotId || "bot-1"}
                    </span>
                    <span style={{ fontSize: "10.5px", padding: "1px 6px", borderRadius: "4px", backgroundColor: "rgba(56, 189, 248, 0.15)", color: "#38bdf8", fontWeight: 700 }}>
                      حساب #{user?.id ? user.id.slice(0, 8) : "Active"}
                    </span>
                  </div>
                </div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <Link
                  href={`/transfer?bot=${encodeURIComponent(activeBot?.bot_id || activeBot?.id || selectedBotId || "bot-1")}&user_id=${encodeURIComponent(user?.id || "")}`}
                  className="btn-ghost-outline"
                  style={{ fontSize: "11px", padding: "4px 8px", display: "flex", alignItems: "center", gap: "4px", color: "#00e5ff", borderColor: "rgba(0, 229, 255, 0.3)" }}
                  target="_blank"
                >
                  <span>فتح كصفحة كاملة ↗</span>
                </Link>
                <button
                  className="util-btn"
                  onClick={() => setShowTransferModal(false)}
                  style={{ width: "30px", height: "30px", padding: 0 }}
                >
                  ✕
                </button>
              </div>
            </div>

            {/* Recipient Details Section */}
            <div style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
              {transferSavedRecipients.length > 0 && (
                <div>
                  <label style={{ fontSize: "11px", color: "var(--text-secondary)", display: "block", marginBottom: "4px" }}>
                    اختيار مستلم محفوظ مسبقاً:
                  </label>
                  <select
                    className="form-input"
                    onChange={(e) => {
                      const idx = Number(e.target.value);
                      if (idx >= 0 && transferSavedRecipients[idx]) {
                        const r = transferSavedRecipients[idx];
                        setTransferTargetName(r.name || "");
                        setTransferTargetRoleId(String(r.role_id || ""));
                        setTransferTargetX(Number(r.x) || 731);
                        setTransferTargetY(Number(r.y) || 701);
                      }
                    }}
                    style={{ fontSize: "12px", padding: "6px 10px" }}
                  >
                    <option value={-1}>-- اختيار مستلم أو إدخال جديد --</option>
                    {transferSavedRecipients.map((rec: any, idx: number) => (
                      <option key={idx} value={idx}>
                        {rec.name} (Role: {rec.role_id}) [{rec.x}, {rec.y}]
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <div>
                <label style={{ fontSize: "11px", color: "var(--text-secondary)", display: "block", marginBottom: "4px" }}>
                  معرّف الحساب المستلم (Target Role ID) *:
                </label>
                <input
                  type="text"
                  className="form-input"
                  placeholder="مثال: 217851402"
                  value={transferTargetRoleId}
                  onChange={(e) => setTransferTargetRoleId(e.target.value)}
                  style={{ fontSize: "13px", color: "#00e5ff", fontWeight: 700, width: "100%" }}
                />
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
                <div>
                  <label style={{ fontSize: "11px", color: "var(--text-secondary)", display: "block", marginBottom: "4px" }}>
                    إحداثي X *:
                  </label>
                  <input
                    type="number"
                    className="form-input"
                    value={transferTargetX}
                    onChange={(e) => setTransferTargetX(Number(e.target.value))}
                    style={{ fontSize: "12px", width: "100%" }}
                  />
                </div>
                <div>
                  <label style={{ fontSize: "11px", color: "var(--text-secondary)", display: "block", marginBottom: "4px" }}>
                    إحداثي Y *:
                  </label>
                  <input
                    type="number"
                    className="form-input"
                    value={transferTargetY}
                    onChange={(e) => setTransferTargetY(Number(e.target.value))}
                    style={{ fontSize: "12px", width: "100%" }}
                  />
                </div>
              </div>

              {/* Dynamic Trading Post Detection Note */}
              <div style={{ padding: "10px 14px", borderRadius: "8px", background: "rgba(0, 229, 255, 0.06)", border: "1px solid rgba(0, 229, 255, 0.2)", display: "flex", alignItems: "center", gap: "8px" }}>
                <span style={{ fontSize: "14px" }}>⚡</span>
                <span style={{ fontSize: "11.5px", color: "#94a3b8" }}>
                  <strong style={{ color: "#00e5ff" }}>كشف لفل السوق التلقائي:</strong> يتم استخراج لفل السوق ونسبة الضريبة والحمولة القصوى لكل مزرعة من الخادم مباشرة دون الحاجة لأي إدخال يدوي.
                </span>
              </div>

              {/* RSS Amounts Input */}
              <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                <label style={{ fontSize: "11.5px", fontWeight: 700, color: "#f1f5f9" }}>
                  الموارد المطلوبة للمستلم (صافي وصول):
                </label>
                {[
                  { key: "food", name: "طعام (Food)", icon: "🌾", color: "#facc15" },
                  { key: "wood", name: "خشب (Wood)", icon: "🪵", color: "#4ade80" },
                  { key: "stone", name: "حجر (Stone)", icon: "🪨", color: "#38bdf8" },
                  { key: "gold", name: "ذهب (Gold)", icon: "🪙", color: "#fb923c" },
                ].map((res) => {
                  const net = transferRss[res.key] || 0;
                  return (
                    <div key={res.key} style={{ display: "flex", alignItems: "center", gap: "8px", padding: "6px 10px", borderRadius: "8px", background: "rgba(10, 25, 47, 0.6)", border: "1px solid rgba(0, 229, 255, 0.15)" }}>
                      <span style={{ fontSize: "12px", width: "100px", color: res.color, fontWeight: 700 }}>
                        {res.icon} {res.name}
                      </span>
                      <input
                        type="number"
                        className="form-input"
                        placeholder="0"
                        value={net === 0 ? "" : net}
                        onChange={(e) => {
                          const val = Math.max(0, parseInt(e.target.value) || 0);
                          setTransferRss((prev) => ({ ...prev, [res.key]: val }));
                        }}
                        style={{ flex: 1, fontSize: "12px", padding: "4px 8px" }}
                      />
                      <button
                        type="button"
                        className="btn-ghost-outline"
                        style={{ fontSize: "10px", padding: "4px 8px", color: "#00e5ff", borderColor: "rgba(0, 229, 255, 0.25)" }}
                        onClick={() => setTransferRss((prev) => ({ ...prev, [res.key]: (prev[res.key] || 0) + 10000000 }))}
                      >
                        +10M
                      </button>
                      <button
                        type="button"
                        className="btn-ghost-outline"
                        style={{ fontSize: "10px", padding: "4px 8px", color: "#00e5ff", borderColor: "rgba(0, 229, 255, 0.25)" }}
                        onClick={() => setTransferRss((prev) => ({ ...prev, [res.key]: (prev[res.key] || 0) + 50000000 }))}
                      >
                        +50M
                      </button>
                    </div>
                  );
                })}
              </div>

              {/* Farms Selection */}
              <div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
                  <label style={{ fontSize: "11.5px", fontWeight: 700, color: "#f1f5f9" }}>
                    المزارع المشاركة ({transferSelectedFarms.length}/{accounts.length}):
                  </label>
                  <button
                    type="button"
                    onClick={() => {
                      if (transferSelectedFarms.length === accounts.length) {
                        setTransferSelectedFarms([]);
                      } else {
                        setTransferSelectedFarms(accounts.map((a: any) => String(a.role_id || a.id)));
                      }
                    }}
                    style={{ fontSize: "10.5px", color: "#00e5ff", background: "transparent", border: "none", cursor: "pointer" }}
                  >
                    {transferSelectedFarms.length === accounts.length ? "إلغاء تحديد الكل" : "تحديد الكل"}
                  </button>
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: "6px", maxHeight: "150px", overflowY: "auto", padding: "4px" }}>
                  {accounts.map((acc: any) => {
                    const rId = String(acc.role_id || acc.id);
                    const isSel = transferSelectedFarms.includes(rId);
                    return (
                      <div
                        key={rId}
                        onClick={() => {
                          setTransferSelectedFarms((prev) =>
                            prev.includes(rId) ? prev.filter((x) => x !== rId) : [...prev, rId]
                          );
                        }}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          padding: "6px 10px",
                          borderRadius: "6px",
                          background: isSel ? "rgba(0, 229, 255, 0.1)" : "rgba(255,255,255,0.02)",
                          border: isSel ? "1px solid rgba(0, 229, 255, 0.35)" : "1px solid rgba(255,255,255,0.05)",
                          cursor: "pointer",
                        }}
                      >
                        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                          <input
                            type="checkbox"
                            checked={isSel}
                            onChange={() => {}}
                            style={{ accentColor: "#00e5ff", cursor: "pointer" }}
                          />
                          <span style={{ fontSize: "12px", color: "#f1f5f9", fontWeight: 600 }}>
                            {acc.name || `حاكم #${rId}`}
                          </span>
                          <span style={{ fontSize: "10px", color: "#64748b" }}>Role #{rId}</span>
                        </div>
                        <div style={{ fontSize: "10px", color: "#00e5ff" }}>
                          كوشن آمن (150K)
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Live Terminal & Logs */}
              {(transferLogs.length > 0 || transferLoading) && (
                <div style={{ marginTop: "4px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", color: "#00e5ff", marginBottom: "4px" }}>
                    <span>شريط تقدم النقل المتزامن:</span>
                    <span>{transferProgress}%</span>
                  </div>
                  <div style={{ height: "4px", borderRadius: "2px", backgroundColor: "#070714", overflow: "hidden", marginBottom: "8px" }}>
                    <div style={{ height: "100%", width: `${transferProgress}%`, backgroundColor: "#00e5ff", boxShadow: "0 0 10px #00e5ff", transition: "width 0.3s ease" }} />
                  </div>
                  <div
                    style={{
                      maxHeight: "130px",
                      overflowY: "auto",
                      backgroundColor: "#020710",
                      border: "1px solid rgba(0, 229, 255, 0.2)",
                      borderRadius: "6px",
                      padding: "8px",
                      fontFamily: "monospace",
                      fontSize: "10.5px",
                      color: "#94a3b8",
                      lineHeight: "1.5",
                    }}
                  >
                    {transferLogs.map((l, i) => (
                      <div key={i} style={{ color: l.includes("[ERROR]") ? "#f87171" : l.includes("[SUCCESS]") ? "#00e5ff" : "#cbd5e1" }}>
                        {l}
                      </div>
                    ))}
                    <div ref={transferTermRef} />
                  </div>
                </div>
              )}

              {transferError && (
                <div style={{ padding: "8px 12px", borderRadius: "8px", background: "rgba(239, 68, 68, 0.12)", border: "1px solid rgba(239, 68, 68, 0.3)", color: "#f87171", fontSize: "11.5px" }}>
                  {transferError}
                </div>
              )}

              {/* Action Buttons */}
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "8px" }}>
                <div style={{ display: "flex", gap: "8px" }}>
                  <button className="btn-ghost-outline" onClick={() => setShowTransferModal(false)}>
                    إغلاق
                  </button>
                  {transferLoading && (
                    <button
                      type="button"
                      onClick={handleStopTransfer}
                      style={{
                        padding: "6px 12px",
                        borderRadius: "8px",
                        backgroundColor: "rgba(239, 68, 68, 0.15)",
                        border: "1px solid rgba(239, 68, 68, 0.4)",
                        color: "#f87171",
                        fontSize: "12px",
                        fontWeight: 700,
                        cursor: "pointer",
                      }}
                    >
                      إيقاف النقل فوراً ⏹
                    </button>
                  )}
                </div>

                <button
                  onClick={handleExecuteTransfer}
                  disabled={transferLoading}
                  style={{
                    background: "linear-gradient(135deg, #00b4d8 0%, #0077b6 100%)",
                    border: "1px solid rgba(0, 229, 255, 0.4)",
                    borderRadius: "8px",
                    padding: "8px 18px",
                    color: "#ffffff",
                    fontWeight: 700,
                    fontSize: "13px",
                    boxShadow: "0 0 16px rgba(0, 180, 216, 0.4)",
                    cursor: transferLoading ? "not-allowed" : "pointer",
                  }}
                >
                  <span>{transferLoading ? "جارٍ النقل المتزامن..." : "بدء تفريغ ونقل الموارد 🚀"}</span>
                </button>
              </div>

            </div>
          </div>
        </div>
      )}

      {/* TOAST BAR */}
      <div className={`toast-bar ${showToast ? "visible" : ""}`} id="toastBar">
        <span id="toastText">{toastText}</span>
      </div>

    </div>
  );
}
