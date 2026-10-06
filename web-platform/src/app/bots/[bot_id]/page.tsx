"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import Image from "next/image";
import { useParams, useRouter } from "next/navigation";
import { Play, Square, Plus, Search, Check, Lock, FileText, ChevronDown, Swords, ArrowRight, ShieldAlert } from "lucide-react";
import {
  getBot, getAccounts, addAccount, toggleAccount, removeAccount,
  getConfig, saveConfig, getAccountConfig, saveAccountConfig,
  getBotRunning, setBotRunning,
  type OwnedBot, type BotAccount,
} from "@/lib/store";
import { getBotStatus, startBotFleet, stopBotFleet, triggerRunNow, syncAccount, runCharacterTask, runCharacterCombat, getFleetDetails, getBotFleet, updateBotSettings, pushCharacterSettings, pushBotConfig, toggleCharacter, setCharacterEnabled, pruneBackendCharacters, getRecentLogs, getRecentActivity, getBotInventory, getBotHistory, getRunSummary, startBotUnit, stopBotUnit, openActivityStream, deleteBackendAccountByEmail, setAccountActiveByEmail, runCharacterCycle, fetchBackend, type AccountSyncResult, type InventoryResponse, type RunRow, type RunSummary, type InventoryChar } from "@/lib/api";
import { linkCloudAccount, deleteCloudAccount, saveCloudSettings, syncTenantFleet, syncTenantConfig, getInstanceRuntime, getCloudAccounts, getCloudAccountRows, shortProxy, getAllBots, bootOwner } from "@/lib/cloud";
import TiltCard3D from "@/components/hud/TiltCard3D";
import StatusBadgeHUD from "@/components/hud/StatusBadgeHUD";

type Tab = "live" | "accounts" | "inventory" | "history" | "config" | "upgrade" | "rss";

const TABS: { id: Tab; label: string; labelAr: string }[] = [
  { id: "live", label: "Live Stream", labelAr: "البث المباشر" },
  { id: "accounts", label: "Accounts", labelAr: "الحسابات والمزارع" },
  { id: "inventory", label: "Inventory", labelAr: "المخزون والموارد" },
  { id: "history", label: "Run History", labelAr: "سجل العمليات" },
  { id: "config", label: "Settings", labelAr: "إعدادات البوت" },
  { id: "rss", label: "RSS Logistics", labelAr: "نقل الموارد" },
  { id: "upgrade", label: "Plans & Store", labelAr: "المتجر والاشتراكات" },
];

interface BotConfig {
  marches: { food: number; wood: number; stone: number; gold: number };
  auto_balance_lowest_rss?: boolean;
  maxNodeLevel: string;
  finishable: boolean;
  skipPartial: boolean;
  avoidTerritory: boolean;
  collectCity: boolean;
  blacksmith: boolean;
  train: { infantry: string; cavalry: string; archery: string; siege: string };
  battleMode: string;
  barbs: boolean;
  highestBarbLevel: string;
  skipBarbsBelow: string;
  barbPrimaryCommander: string;
  barbSecondaryCommander: string;
  combatRounds: number;
  dispatchAllMarches: boolean;
  commanders: { useLoadout: boolean; marches: Array<{ primary: string; secondary: string; alliancePit: boolean }> };
  battleTrainingMode: string;
  healTroops: boolean;
  healBatch: number;
  donateTech: boolean;
  allianceHelp: boolean;
  alliancePit: boolean;
  allianceGifts: boolean;
  claimTerritoryRss: boolean;
  vipChest: boolean;
  autoScout: boolean;
  dailyVipClaim: boolean;
  cityHarvest: boolean;
  chronicleClaim: boolean;
  claimDailyQuests: boolean;
  claimDailyQuestChests: boolean;
  claimSideQuests: boolean;
}

const DEFAULT_CONFIG: BotConfig = {
  marches: { food: 1, wood: 1, stone: 1, gold: 0 },
  auto_balance_lowest_rss: false,
  maxNodeLevel: "No cap",
  finishable: true,
  skipPartial: true,
  avoidTerritory: true,
  collectCity: true,
  blacksmith: false,
  train: { infantry: "T1", cavalry: "T1", archery: "T1", siege: "T1" },
  battleMode: "Off",
  barbs: true,
  highestBarbLevel: "L7",
  skipBarbsBelow: "None",
  barbPrimaryCommander: "Auto",
  barbSecondaryCommander: "Auto (best available)",
  combatRounds: 1,
  dispatchAllMarches: true,
  commanders: {
    useLoadout: false,
    marches: [1, 2, 3, 4, 5].map(() => ({ primary: "Auto", secondary: "Auto (best available)", alliancePit: false })),
  },
  battleTrainingMode: "Off",
  healTroops: true,
  healBatch: 0,
  donateTech: true,
  allianceHelp: true,
  alliancePit: false,
  allianceGifts: true,
  claimTerritoryRss: true,
  vipChest: true,
  autoScout: true,
  dailyVipClaim: true,
  cityHarvest: true,
  chronicleClaim: false,
  claimDailyQuests: true,
  claimDailyQuestChests: true,
  claimSideQuests: false,
};

const CONFIG_CATS = ["General", "Gathering", "City", "Combat", "Alliance", "Daily Claims", "Account Progression"];

const COMMANDER_OPTIONS = [
  "Auto",
  "Lohar",
  "Minamoto no Yoshitsune",
  "Cao Cao",
  "Sun Tzu",
  "Baibars",
  "Belisarius",
  "Pelagius",
  "Osman I",
  "Hermann",
  "Eulji Mundeok",
  "Kusunoki Masashige",
  "Scipio Africanus",
  "Boudica",
  "Aethelflaed",
  "Richard I",
  "Charles Martel",
  "Lancelot",
  "Tomoe Gozen",
  "City Keeper",
  "Joan of Arc",
];

const SECONDARY_COMMANDER_OPTIONS = [
  "Auto (best available)",
  "None",
  ...COMMANDER_OPTIONS.filter((c) => c !== "Auto"),
];

const BARB_LEVEL_OPTIONS = [
  "Max Unlocked",
  ...Array.from({ length: 40 }, (_, i) => `L${i + 1}`),
];

const SKIP_BARB_LEVEL_OPTIONS = [
  "None",
  ...Array.from({ length: 39 }, (_, i) => `L${i + 2}`),
];

// BotConfig → headless engine contract (backend SQLite character_settings):
// tiers ints feed TIER_UNIT_MAP (T2 → unit 5/6…), "Off" skips the barracks;
// gather keys are read by the smart_gather_search web-config binding.
function toEngineSettings(c: BotConfig) {
  const t = (s: string) => (s === "Off" ? "Off" : parseInt(s.slice(1), 10));
  const tiers = {
    infantry: t(c.train.infantry),
    cavalry: t(c.train.cavalry),
    archery: t(c.train.archery),
    siege: t(c.train.siege),
  };
  const gather = {
    food_marches: c.marches.food,
    wood_marches: c.marches.wood,
    stone_marches: c.marches.stone,
    gold_marches: c.marches.gold,
    auto_balance_lowest_rss: !!c.auto_balance_lowest_rss,
    max_node_level: c.maxNodeLevel,
    skip_partially: c.skipPartial,
    only_finishable: c.finishable,
    avoid_territory: c.avoidTerritory,
  };
  const combat = {
    barbs: c.barbs !== undefined ? !!c.barbs : true,
    highest_barb_level: c.highestBarbLevel || "L7",
    skip_barbs_below: c.skipBarbsBelow || "None",
    primary_commander: c.barbPrimaryCommander || "Auto",
    secondary_commander: c.barbSecondaryCommander || "Auto (best available)",
    combat_rounds: Number(c.combatRounds) || 1,
    dispatch_all_marches: c.dispatchAllMarches !== false,
    min_barb_level: c.skipBarbsBelow && c.skipBarbsBelow !== "None" ? parseInt(c.skipBarbsBelow.replace("L", ""), 10) : 1,
    max_barb_level: c.highestBarbLevel && c.highestBarbLevel !== "Max Unlocked" ? parseInt(c.highestBarbLevel.replace("L", ""), 10) : 7,
    max_combat_marches: c.dispatchAllMarches !== false ? 5 : 1,
    hold_position: false,
  };
  const hospital = {
    heal_troops: !!c.healTroops,
    heal_batch: Number(c.healBatch) || 0,
  };
  const alliance = {
    help_alliance_members: !!c.allianceHelp,
    gather_resource_pit: !!c.alliancePit,
    donate_tech: !!c.donateTech,
    claim_gifts: !!c.allianceGifts,
    claim_territory_rss: !!c.claimTerritoryRss,
  };
  const daily_claims = {
    daily_vip_claim: !!c.dailyVipClaim,
    city_harvest: !!c.cityHarvest,
    chronicle_claim: !!c.chronicleClaim,
    claim_daily_quests: !!c.claimDailyQuests,
    claim_daily_quest_chests: !!c.claimDailyQuestChests,
    claim_side_quests: !!c.claimSideQuests,
    auto_scout: !!c.autoScout,
  };
  const city = {
    collect_resources: !!c.cityHarvest,
  };
  const mirror = {
    gathering: {
      food_marches: c.marches.food,
      wood_marches: c.marches.wood,
      stone_marches: c.marches.stone,
      gold_marches: c.marches.gold,
      auto_balance_lowest_rss: !!c.auto_balance_lowest_rss,
      max_node_level: c.maxNodeLevel,
      only_finishable: c.finishable,
      skip_partial: c.skipPartial,
      avoid_territory: c.avoidTerritory,
    },
    combat: {
      barbs: c.barbs !== undefined ? !!c.barbs : true,
      highest_barb_level: c.highestBarbLevel || "L7",
      skip_barbs_below: c.skipBarbsBelow || "None",
      primary_commander: c.barbPrimaryCommander || "Auto",
      secondary_commander: c.barbSecondaryCommander || "Auto (best available)",
      combat_rounds: Number(c.combatRounds) || 1,
      dispatch_all_marches: c.dispatchAllMarches !== false,
    },
    city: {
      harvest_resources: c.collectCity,
      train_infantry: c.train.infantry,
      train_cavalry: c.train.cavalry,
      train_archery: c.train.archery,
      train_siege: c.train.siege,
    },
    alliance: {
      one_click_help: c.allianceHelp,
      tech_donation: c.donateTech,
    },
  };
  return { tiers, gather, combat, hospital, alliance, daily_claims, city, mirror };
}

function Toggle({ on, onClick }: { on: boolean; onClick: () => void }) {
  return (
    <button
      role="switch" aria-checked={on} onClick={onClick}
      className={`w-10 h-[22px] rounded-full p-0.5 transition-colors shrink-0 ${on ? "bg-[#5865F2]" : "bg-[#25252e]"}`}
    >
      <span className={`block w-[18px] h-[18px] rounded-full bg-white transition-transform ${on ? "translate-x-[18px]" : ""}`} />
    </button>
  );
}

function Row({ title, desc, control, soon, icon, q }: { title: string; desc: string; control: React.ReactNode; soon?: boolean; icon?: string; q?: string }) {
  const needle = (q || "").trim().toLowerCase();
  if (needle && !(title + " " + desc).toLowerCase().includes(needle)) return null;
  return (
    <div className="flex items-center gap-4 p-4 border-b border-[#25252e] last:border-0">
      {icon && <Image src={icon} alt="" width={26} height={26} className="object-contain shrink-0" />}
      <div className="flex-1 min-w-0">
        <div className="text-sm font-semibold text-white flex items-center gap-2">
          {title}
          {soon && (
            <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 border border-amber-500/30 uppercase tracking-wider" title="Coming soon — will be enabled shortly">
              Soon
            </span>
          )}
        </div>
        <div className="text-xs text-zinc-500 mt-0.5">{soon ? "Coming soon — will be enabled shortly." : desc}</div>
      </div>
      <div className={`shrink-0 ${soon ? "opacity-40 pointer-events-none grayscale" : ""}`}>{control}</div>
    </div>
  );
}

function Stepper({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <div className="flex items-center gap-3">
      <button onClick={() => onChange(Math.max(0, value - 1))} className="btn-ghost w-7 h-7 text-sm font-bold">-</button>
      <span className="w-6 text-center text-sm font-bold text-white">{value}</span>
      <button onClick={() => onChange(Math.min(7, value + 1))} className="btn-ghost w-7 h-7 text-sm font-bold">+</button>
    </div>
  );
}

function GovAvatar({ name, src }: { name: string; src: string }) {
  const [err, setErr] = useState(false);
  const safeSrc = (src || "").replace(/^http:\/\//i, "https://");
  if (safeSrc && !err) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={safeSrc} alt="" onError={() => setErr(true)} className="w-6 h-6 rounded-full object-cover shrink-0" />;
  }
  return (
    <span className="w-6 h-6 rounded-full bg-[#5865F2]/20 text-[#8b9bff] flex items-center justify-center text-[10px] font-bold shrink-0">
      {(name || "?").slice(0, 1).toUpperCase()}
    </span>
  );
}


function InvTable({ chars }: { chars: InventoryChar[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-[10px] uppercase tracking-wider text-zinc-500 border-b border-[#25252e]">
            <th className="px-3 py-2">Governor ID</th>
            <th className="px-3 py-2">Name</th>
            <th className="px-3 py-2">Kingdom</th>
            <th className="px-3 py-2">CH</th>
            <th className="px-3 py-2">Power</th>
            <th className="px-3 py-2">Food</th>
            <th className="px-3 py-2">Wood</th>
            <th className="px-3 py-2">Stone</th>
            <th className="px-3 py-2">Gold</th>
            <th className="px-3 py-2">Gems</th>
            <th className="px-3 py-2">Total</th>
          </tr>
        </thead>
        <tbody>
          {chars.map((c) => (
            <tr key={c.governor_id} className="border-b border-[#1d1d26]/60 hover:bg-zinc-900/40">
              <td className="px-3 py-2 text-zinc-400 font-mono">{c.governor_id}</td>
              <td className="px-3 py-2 text-zinc-200 font-semibold">{c.name}</td>
              <td className="px-3 py-2 text-[#8b9bff]">{c.kingdom}</td>
              <td className="px-3 py-2 text-zinc-300">CH{c.city_hall}</td>
              <td className="px-3 py-2 text-zinc-300">{fmtBig(c.power)}</td>
              <td className={`px-3 py-2 ${RESOURCE_COLORS.food}`}>{fmtBig(c.food)}</td>
              <td className={`px-3 py-2 ${RESOURCE_COLORS.wood}`}>{fmtBig(c.wood)}</td>
              <td className={`px-3 py-2 ${RESOURCE_COLORS.stone}`}>{fmtBig(c.stone)}</td>
              <td className={`px-3 py-2 ${RESOURCE_COLORS.gold}`}>{fmtBig(c.gold)}</td>
              <td className={`px-3 py-2 ${RESOURCE_COLORS.gems}`}>{fmtBig(c.gems)}</td>
              <td className="px-3 py-2 text-white font-bold">{fmtBig(c.total)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function fmtBig(n: number): string {
  const v = Number(n) || 0;
  if (v >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return v.toLocaleString();
}

function fmtDuration(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  if (s >= 60) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${s}s`;
}

const RESOURCE_COLORS: Record<string, string> = {
  food: "text-amber-400",
  wood: "text-emerald-400",
  stone: "text-zinc-300",
  gold: "text-yellow-400",
  gems: "text-purple-400",
};

export default function BotDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = Array.isArray(params?.bot_id) ? params.bot_id[0] : ((params?.bot_id as string) || (Array.isArray(params?.id) ? params.id[0] : ((params?.id as string) || (Array.isArray(params?.botId) ? params.botId[0] : (params?.botId as string)))));

  const [bot, setBot] = useState<OwnedBot | null | undefined>(undefined);
  const [tab, setTab] = useState<Tab>("live");
  const [running, setRunning] = useState<boolean | null>(null);
  const [engineMsg, setEngineMsg] = useState("");
  const [menuEmail, setMenuEmail] = useState<string | null>(null);
  const [runMsg, setRunMsg] = useState("");
  const [fleetDetails, setFleetDetails] = useState<Record<string, { name?: string; last: string; next: string; city: number | null; avatar: string; enabled: boolean }>>({});
  const [recentLines, setRecentLines] = useState<string[]>([]);
  const logRef = useRef<HTMLDivElement | null>(null);
  const [daysLeft, setDaysLeft] = useState<string>("—");
  const [accounts, setAccounts] = useState<BotAccount[]>([]);
  const accountsRef = useRef<BotAccount[]>([]);
  accountsRef.current = accounts;
  const [query, setQuery] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [newEmail, setNewEmail] = useState("");
  const [newPass, setNewPass] = useState("");
  // Backend sync phases: idle → busy → done | captcha | error.
  // Only the email is kept locally on success. Password, tokens and
  // app_uids never touch website files — they stay on the backend server.
  const [syncPhase, setSyncPhase] = useState<"idle" | "busy" | "done" | "added" | "captcha" | "error">("idle");
  const [syncMsg, setSyncMsg] = useState("");
  const [syncChars, setSyncChars] = useState<Array<{ role_id: string; name: string; kingdom_id: number; city_level?: number; avatar_url?: string }>>([]);
  const [picked, setPicked] = useState<string[]>([]);
  const [syncNet, setSyncNet] = useState<{
    proxy_url: string | null;
    last_login_ip: string | null;
    slot: number;
    device_profile: Record<string, unknown> | null;
  } | null>(null);
  const [proxyMap, setProxyMap] = useState<Record<string, { proxy_url: string | null }>>({});
  const [captchaUrl, setCaptchaUrl] = useState("");
  // Small auto-popup flow: the popup is pre-opened inside the click gesture
  // (the only moment browsers allow window.open), navigated to the Lilith
  // captcha when needed, polled in the background, and closed automatically
  // once the backend confirms the verification — then the flow continues
  // straight to character picking with zero extra clicks.
  const captchaPopupRef = useRef<Window | null>(null);
  const [captchaCreds, setCaptchaCreds] = useState<{ email: string; password: string } | null>(null);
  const [popupBlocked, setPopupBlocked] = useState(false);
  const [cfgCat, setCfgCat] = useState("General");
  const [cfg, setCfg] = useState<BotConfig>(DEFAULT_CONFIG);
  const [saved, setSaved] = useState(false);
  const [selectedEmail, setSelectedEmail] = useState("");
  const [scope, setScope] = useState<"one" | "all">("all");
  const [settingQuery, setSettingQuery] = useState("");
  const [governorQuery, setGovernorQuery] = useState("");
  const [interval, setInterval] = useState("2");
  const [isCustomInterval, setIsCustomInterval] = useState(false);
  const [customMinutes, setCustomMinutes] = useState("10");
  const [triggeringNow, setTriggeringNow] = useState(false);
  const [triggeringCombat, setTriggeringCombat] = useState(false);
  const [discordNotify, setDiscordNotify] = useState(true);
  const [genMsg, setGenMsg] = useState("");
  const [engineNote, setEngineNote] = useState("");
  const [rt, setRt] = useState<{
    status: string | null;
    runtime_status: string | null;
    server_worker_id: string | null;
    last_heartbeat: string | null;
  } | null>(null);

  // ---- INVENTORY + HISTORY telemetry (bot_id partitioned, wiped on switch) ----
  const [invRange, setInvRange] = useState<"today" | "7days" | "30days">("today");
  const [inv, setInv] = useState<InventoryResponse | null>(null);
  const [groupByKingdom, setGroupByKingdom] = useState(false);
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [runSummary, setRunSummary] = useState<RunSummary | null>(null);
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [countdownText, setCountdownText] = useState("(00:00:00)");
  const [lang, setLang] = useState<"ar" | "en">("ar");

  useEffect(() => {
    try {
      const s = localStorage.getItem("ghostbot_lang");
      if (s === "en" || s === "ar") setLang(s);
    } catch {}
  }, []);
  const isAr = lang === "ar";

  useEffect(() => {
    const hours = interval === "custom" ? (Number(customMinutes) || 10) / 60 : (Number(interval) || 2);
    const totalMs = Math.max(60000, hours * 3600 * 1000);
    let target = Date.now() + totalMs;

    const timer = window.setInterval(() => {
      const remaining = Math.max(0, target - Date.now());
      if (remaining <= 0) {
        if (running) {
          fetchBackend(`/api/bot/${encodeURIComponent(id)}/run-now`, { method: "POST" }).catch(() => {});
        }
        target = Date.now() + totalMs;
      }
      const s = Math.floor((remaining / 1000) % 60);
      const m = Math.floor((remaining / (1000 * 60)) % 60);
      const h = Math.floor(remaining / (1000 * 60 * 60));
      const pad = (n: number) => String(n).padStart(2, "0");
      setCountdownText(`(${pad(h)}:${pad(m)}:${pad(s)})`);
    }, 1000);

    return () => window.clearInterval(timer);
  }, [interval, customMinutes, running, id]);

  useEffect(() => {
    const boot = (nb: OwnedBot) => {
      setBot(nb);
      const accs = getAccounts(id);
      // Self-heal: if the local store is empty but the cloud has linked
      // accounts (fresh login, new device, or a cloud upsert that raced the
      // old purge), hydrate the local view from Supabase.
      if (accs.length === 0) {
        getCloudAccountRows(id).then((rows) => {
          if (rows.length > 0) {
            for (const r of rows) {
              addAccount(id, r.email, r.role_id ? [{ role_id: r.role_id, name: r.role_id, kingdom_id: r.kingdom_id ?? 0, enabled: r.is_enabled ?? true }] : undefined);
            }
            setAccounts(getAccounts(id));
          }
        });
      }
      setAccounts(accs);
      const em = accs[0]?.email || "";
      setSelectedEmail(em);
      setCfg(em ? getAccountConfig(id, em, DEFAULT_CONFIG) : getConfig(id, DEFAULT_CONFIG));
      const createdAtMs = nb.createdAt ?? (nb.expiresAt ? new Date(nb.expiresAt).getTime() - 30 * 86400000 : Date.now());
      const daysDuration = nb.days ?? 30;
      const msLeft = nb.expiresAt ? new Date(nb.expiresAt).getTime() - Date.now() : (createdAtMs + daysDuration * 86400000 - Date.now());
      const d = Math.max(0, Math.floor(msLeft / 86400000));
      setDaysLeft(`${d}d left`);
      getBotStatus()
        .then((s) => {
          const isUnitRunning = getBotRunning(id, true);
          setRunning(s.running && isUnitRunning);
          const st = s.settings || {};
          if (st.run_interval_minutes !== undefined && st.run_interval_minutes !== "") {
            const m = Number(st.run_interval_minutes);
            setCustomMinutes(String(m));
            if ([10, 15, 30, 60, 120, 240, 480, 720, 1440].includes(m)) {
              setInterval(String(m / 60));
              setIsCustomInterval(false);
            } else {
              setInterval("custom");
              setIsCustomInterval(true);
            }
          } else if (st.run_interval_hours !== undefined) {
            const h = Number(st.run_interval_hours);
            const m = Math.round(h * 60);
            setCustomMinutes(String(m));
            if ([0.1667, 0.25, 0.5, 1, 2, 4, 8, 12, 24].includes(h)) {
              setInterval(String(st.run_interval_hours));
              setIsCustomInterval(false);
            } else {
              setInterval("custom");
              setIsCustomInterval(true);
            }
          }
          if (st.discord_notifications !== undefined) setDiscordNotify(String(st.discord_notifications) === "true");
        })
        .catch(() => setRunning(false));
      // Unit truth comes from the backend's isolated-runner controller.
      fetchBackend(`/api/bot/${encodeURIComponent(id)}/unit-status`)
        .then((r) => (r.ok ? r.json() : null))
        .then((u) => {
          if (u && typeof u.running === "boolean") {
            setRunning(u.running);
            setBotRunning(id, u.running);
          }
        })
        .catch(() => {});
      getInstanceRuntime(id).then(setRt);
      getCloudAccounts(id).then(setProxyMap);
      getBotFleet(id)
        .then((fleet) => {
          if (fleet && Array.isArray(fleet.accounts)) {
            if (fleet.accounts.length > 0) {
              const mappedAccounts: BotAccount[] = fleet.accounts.map((acc) => ({
                email: acc.email,
                enabled: acc.enabled,
                addedAt: Date.now(),
                chars: (acc.characters || []).map((c) => ({
                  role_id: c.role_id,
                  name: c.name,
                  kingdom_id: c.kingdom_id,
                  city_level: c.city_level,
                  avatar_url: c.avatar_url,
                  enabled: c.enabled,
                })),
              }));
              setAccounts(mappedAccounts);
              const fd: Record<string, { name: string; last: string; next: string; city: number | null; avatar: string; enabled: boolean }> = {};
              for (const acc of fleet.accounts) {
                for (const c of acc.characters) {
                  fd[c.role_id] = {
                    name: c.name,
                    last: c.last_run_text,
                    next: c.next_run_text,
                    city: c.city_level,
                    avatar: c.avatar_url,
                    enabled: c.enabled,
                  };
                }
              }
              setFleetDetails(fd);
            } else {
              setAccounts([]);
              setFleetDetails({});
            }
          }
        })
        .catch(() => {
          getFleetDetails(id).then(setFleetDetails);
        });
    };
    bootOwner().then(() => {
      const b = getBot(id);
      if (b) {
        boot(b);
        return;
      }
      getAllBots().then((list) => {
        const hit = list.find((x) => x.id === id || x.bot_id === id || x.room === id);
        if (hit) {
          boot(hit);
        } else {
          const fallbackBot: OwnedBot = {
            id: id || "farm-bot-1",
            label: "وحدة مزارع GhostBot #1",
            product: "farm-bot",
            tier: "pro",
            slots: 5,
            days: 30,
            room: id || "farm-bot-1",
            createdAt: Date.now(),
            expiresAt: new Date(Date.now() + 30 * 86400000).toISOString(),
            active: true,
          };
          boot(fallbackBot);
        }
      });
    });
  }, [id]);

  // INVENTORY + HISTORY: load strictly for the ACTIVE bot_id; every switch
  // between units wipes the previous unit's data before its own arrives.
  useEffect(() => {
    setInv(null);
    setRuns([]);
    setRunSummary(null);
    setSummaryOpen(false);
    if (!bot || (tab !== "inventory" && tab !== "history")) return;
    const ctrl = new AbortController();
    if (tab === "inventory") {
      getBotInventory(id, groupByKingdom ? "kingdom" : undefined, ctrl.signal).then((d) => {
        if (!ctrl.signal.aborted) setInv(d);
      });
    } else {
      getBotHistory(id, ctrl.signal).then((rows) => {
        if (!ctrl.signal.aborted) setRuns(rows);
      });
    }
    return () => ctrl.abort();
  }, [tab, bot, id, groupByKingdom]);

  useEffect(() => {
    setRecentLines([]);
    if (tab !== "live" || !bot) return;

    let isMounted = true;
    let timeoutId: ReturnType<typeof setTimeout> | undefined;

    const fetchLogs = async () => {
      try {
        const res = await fetchBackend(`/api/activity/recent?bot_id=${encodeURIComponent(id)}`);
        if (res.ok) {
          const data = await res.json();
          const lines = data.lines || data.logs || [];
          if (isMounted && Array.isArray(lines) && lines.length > 0) {
            setRecentLines(lines.slice(-100));
          }
        }
      } catch {
        /* silent catch on network blip */
      } finally {
        if (isMounted) {
          // Wait exactly 5 full seconds AFTER previous fetch completely finishes
          timeoutId = setTimeout(fetchLogs, 5000);
        }
      }
    };

    fetchLogs(); // Start loop

    return () => {
      isMounted = false;
      if (timeoutId !== undefined) clearTimeout(timeoutId);
    };
  }, [tab, bot, id]);

  // Hard DOM buffer cap: render only the latest 100 lines — the DOM can
  // never exceed the backend FIFO cap, so every commit stays < 16ms.
  const displayLogs = useMemo(() => recentLines.slice(-100), [recentLines]);

  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [displayLogs]);

  const CAPTCHA_POLL_MS = 5000;
  const CAPTCHA_MAX_ATTEMPTS = 60; // ~5 minutes

  // While the captcha popup is open, re-attempt the Lilith login every few
  // seconds. Solving the slider unlocks the account server-side, so the next
  // attempt returns the full character list — then we auto-close the popup
  // and continue to character picking without any extra clicks.
  // NOTE: this hook MUST stay above the early returns below (React rules).
  useEffect(() => {
    if (syncPhase !== "captcha" || !captchaCreds) return;
    let cancelled = false;
    let attempts = 0;
    let checking = false;
    const timer = window.setInterval(async () => {
      if (cancelled || checking) return;
      attempts += 1;
      if (attempts > CAPTCHA_MAX_ATTEMPTS) {
        cancelled = true;
        window.clearInterval(timer);
        closeCaptchaPopup();
        setCaptchaCreds(null);
        setNewPass("");
        setSyncPhase("error");
        setSyncMsg("Verification timed out — please add the account again.");
        return;
      }
      const popup = captchaPopupRef.current;
      if (popup && popup.closed) {
        cancelled = true;
        window.clearInterval(timer);
        setSyncMsg("Verification window was closed before finishing. Press “Reopen window”, or re-add the account.");
        return;
      }
      checking = true;
      try {
        const res = await syncAccount(captchaCreds.email, captchaCreds.password, id);
        if (cancelled) return;
        if (res.captcha_required || res.status === "REQUIRES_VERIFICATION") {
          setSyncMsg(`Waiting for you to finish the verification… (checked ${attempts})`);
          return; // keep polling
        }
        if (res.success) {
          cancelled = true;
          window.clearInterval(timer);
          closeCaptchaPopup(); // solved → popup goes away on its own
          setCaptchaCreds(null);
          setNewPass("");
          finishSync(res);     // → straight to character picking
        }
      } catch {
        /* transient network error — keep polling */
      } finally {
        checking = false;
      }
    }, CAPTCHA_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [syncPhase, captchaCreds]);

  if (bot === undefined) {
    return <div className="text-sm text-zinc-500">Loading bot…</div>;
  }
  if (bot === null) {
    const fallbackBot: OwnedBot = {
      id: id || "farm-bot-1",
      label: "وحدة مزارع GhostBot #1",
      product: "farm-bot",
      tier: "pro",
      slots: 5,
      days: 30,
      room: id || "farm-bot-1",
      createdAt: Date.now(),
      expiresAt: new Date(Date.now() + 30 * 86400000).toISOString(),
      active: true,
    };
    setBot(fallbackBot);
    return <div className="text-sm text-zinc-500">Loading bot…</div>;
  }

  const icon = bot.product === "gem-bot" ? "/Item_Gem.webp" : "/Item_Food.webp";
  const q = query.toLowerCase();
  const filtered = accounts.filter(
    (a) =>
      a.email.toLowerCase().includes(q) ||
      (a.chars ?? []).some((c) => c.name.toLowerCase().includes(q) || c.role_id.includes(q))
  );
  const gq = governorQuery.toLowerCase();
  const emailOptions = accounts.filter(
    (a) =>
      !gq ||
      a.email.toLowerCase().includes(gq) ||
      (a.chars ?? []).some((c) => c.name.toLowerCase().includes(gq) || c.role_id.includes(gq))
  );
  const cmd = cfg.commanders ?? DEFAULT_CONFIG.commanders;

  async function toggleEngine() {
    setEngineMsg("");
    const nextRunning = !running;
    // OPTIMISTIC UI: flip the badge instantly — the control call is
    // fire-and-forget (backend start/stop return <50ms and never block on
    // gateway traffic), so there is zero perceptible latency or freeze.
    setRunning(nextRunning);
    setBotRunning(id, nextRunning);
    setEngineMsg(nextRunning ? `Unit ${bot?.label || id} starting...` : `Unit ${bot?.label || id} stopping...`);
    try {
      // Toggle both the global fleet scheduler and the unit runner
      const fleetRes = nextRunning ? await startBotFleet(id) : await stopBotFleet(id);
      const unitRes = nextRunning ? await startBotUnit(id) : await stopBotUnit(id);
      if (nextRunning) {
        await triggerRunNow(id).catch(() => {});
      }
      if (!fleetRes?.success && unitRes?.status === "error") throw new Error("control failed");

      // Keep tenant accounts in sync with the unit's running state
      for (const a of accounts) {
        setAccountActiveByEmail(a.email, nextRunning).catch(() => {});
      }
      setEngineMsg(`Unit ${bot?.label || id} ${nextRunning ? "started." : "stopped."}`);
      const d = await getFleetDetails(id).catch(() => ({}));
      setFleetDetails(d);
    } catch {
      setRunning(!nextRunning); // revert the optimistic flip on real failure
      setBotRunning(id, !nextRunning);
      setEngineMsg("Engine control failed — Discord login is required, or the backend is unreachable.");
    }
  }

  function openAdd() {
    if (!bot) {
      router.push("/shop");
      return;
    }
    setSyncPhase("idle");
    setSyncMsg("");
    setSyncChars([]);
    setPicked([]);
    setCaptchaUrl("");
    closeCaptchaPopup();
    setCaptchaCreds(null);
    setPopupBlocked(false);
    setShowAdd(true);
  }

  function openCaptchaPopup(url: string) {
    const w = 430, h = 680;
    const left = Math.max(0, Math.floor((window.screen.width - w) / 2));
    const top = Math.max(0, Math.floor((window.screen.height - h) / 2));
    const popup = window.open(
      url,
      "lilith_captcha",
      `popup=yes,width=${w},height=${h},left=${left},top=${top},menubar=no,toolbar=no,location=no,status=no`
    );
    captchaPopupRef.current = popup;
    setPopupBlocked(!popup);
    if (popup) popup.focus();
    return popup;
  }

  function closeCaptchaPopup() {
    const p = captchaPopupRef.current;
    if (p && !p.closed) {
      try { p.close(); } catch { /* ignore */ }
    }
    captchaPopupRef.current = null;
  }

  function finishSync(res: AccountSyncResult) {
    const chars = (res.characters || []).map((c) => ({ role_id: c.role_id, name: c.name, kingdom_id: c.kingdom_id, city_level: c.city_level, avatar_url: c.avatar_url }));
    setSyncChars(chars);
    setPicked(chars.map((c) => c.role_id));
    setSyncNet({
      proxy_url: res.account?.proxy_url ?? null,
      last_login_ip: res.account?.last_login_ip ?? null,
      slot: res.account?.slot ?? 0,
      device_profile: res.account?.device_profile ?? null,
    });
    setSyncPhase("done");
    setSyncMsg(res.message || `Synced ${res.account?.characters_found ?? 0} characters — pick which to link.`);
  }

  async function submitAccount() {
    const email = newEmail.trim();
    const pass = newPass;
    if (!email || !pass || syncPhase === "busy") return;
    // Pre-open the small popup synchronously inside the click gesture —
    // popup blockers only allow window.open here. We navigate it to the
    // captcha URL afterwards if the backend asks for verification.
    const pre = window.open("about:blank", "lilith_captcha", "popup=yes,width=430,height=680,menubar=no,toolbar=no");
    captchaPopupRef.current = pre;
    setPopupBlocked(!pre);
    setSyncPhase("busy");
    setSyncMsg("Syncing with the backend server…");
    try {
      // Fresh authentication on the backend server (never from local files).
      const res = await syncAccount(email, pass, id);
      if (res.captcha_required || res.status === "REQUIRES_VERIFICATION") {
        const url = res.captcha_url || "";
        setCaptchaUrl(url);
        setSyncPhase("captcha");
        setCaptchaCreds({ email, password: pass }); // kept in memory only until verified
        setSyncMsg("Solve the verification in the small window — the bot continues automatically once you finish.");
        if (pre && !pre.closed) {
          if (url) pre.location.href = url;
          pre.focus();
        } else {
          setPopupBlocked(true);
        }
        return; // password intentionally kept until the flow resolves
      }
      closeCaptchaPopup();
      setCaptchaCreds(null);
      setNewPass("");
      if (!res.success) {
        setSyncPhase("error");
        setSyncMsg(res.message || "Backend rejected the login.");
        return;
      }
      // Success: hold the character list for picking. Nothing is linked
      // until the user confirms the selection below.
      finishSync(res);
    } catch (e) {
      closeCaptchaPopup();
      setCaptchaCreds(null);
      setNewPass("");
      setSyncPhase("error");
      setSyncMsg(e instanceof Error ? e.message : "Sync failed — is the backend server reachable?");
    }
  }

  async function checkCaptchaNow() {
    if (!captchaCreds || syncPhase !== "captcha") return;
    setSyncMsg("Checking verification status…");
    try {
      const res = await syncAccount(captchaCreds.email, captchaCreds.password, id);
      if (res.success) {
        closeCaptchaPopup();
        setCaptchaCreds(null);
        setNewPass("");
        finishSync(res);
      } else {
        setSyncMsg("Not verified yet — finish the slider in the popup window.");
      }
    } catch (e) {
      setSyncMsg(e instanceof Error ? e.message : "Check failed — backend unreachable?");
    }
  }

  async function confirmPick() {
    const email = newEmail.trim();
    const chars = syncChars.filter((c) => picked.includes(c.role_id));
    if (!email || chars.length === 0) return;
    // Link only the chosen characters. Email + character list stay local;
    // password, token and app_uid remain on the backend server.
    addAccount(id, email, chars);
    setAccounts(getAccounts(id));
    // Prune deselected characters from the backend engine so the scheduler
    // never visits them (sync upserts every role the account owns).
    pruneBackendCharacters(email, chars.map((c) => String(c.role_id))).then(
      (r) => {
        if (r.removed.length > 0) setRunMsg(`Linked ${chars.length} character${chars.length === 1 ? "" : "s"}; removed ${r.removed.length} deselected from backend.`);
      },
      () => {
        setRunMsg(`Linked locally, but backend prune failed — deselected characters may still run.`);
      }
    );
    try {
      await linkCloudAccount(id, email, {
        role_id: chars[0].role_id,
        kingdom_id: chars[0].kingdom_id,
        proxy_url: syncNet?.proxy_url ?? null,
        device_profile: syncNet?.device_profile ?? null,
        last_login_ip: syncNet?.last_login_ip ?? null,
        assigned_slot: syncNet?.slot ?? 0,
      });
    } catch (e) {
      setSyncPhase("added");
      setSyncMsg(`Linked locally, but cloud sync failed: ${e instanceof Error ? e.message : "unknown error"} — the account may vanish after re-login.`);
      return;
    }
    syncTenantFleet(id);
    setSyncPhase("added");
    setSyncMsg(`Linked ${chars.length} character${chars.length === 1 ? "" : "s"} to this bot.`);
  }

  async function runNow(a: BotAccount) {
    setRunMsg("");
    const chars = a.chars ?? [];
    if (chars.length === 0) {
      setRunMsg("No linked characters on this account.");
      return;
    }
    try {
      const activeRoleIds = chars.filter(c => c.enabled !== false).map(c => c.role_id);
      if (activeRoleIds.length === 0) {
        setRunMsg("No enabled characters on this account.");
        return;
      }
      await fetchBackend(`/api/bots/${encodeURIComponent(id)}/cycle`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role_ids: activeRoleIds, delay: 4.0 })
      });
      setRunMsg(`Run now: Staged cycle started for ${activeRoleIds.length} character(s).`);
      setTimeout(() => loadRecent(), 800);
    } catch {
      setRunMsg("Run now failed — backend is unreachable.");
    }
  }

  async function runCharDirect(role_id: string, name: string) {
    setRunMsg(`Starting visit for ${name}...`);
    try {
      await runCharacterCycle(role_id, id);
      setRunMsg(`Started visit cycle for ${name}.`);
      setTimeout(() => loadRecent(), 800);
    } catch {
      setRunMsg(`Failed to run ${name} — check backend connection.`);
    }
  }

  async function handleToggleAccount(email: string, currentEnabled: boolean) {
    const next = !currentEnabled;
    toggleAccount(id, email);
    setAccounts(getAccounts(id));
    try {
      await setAccountActiveByEmail(email, next);
    } catch (err) {
      console.error("Account active toggle sync failed:", err);
    }
  }

  async function removeFull(email: string) {
    const acc = accounts.find((a) => a.email === email);
    const roles = (acc?.chars ?? []).map((c) => c.role_id);
    removeAccount(id, email);
    setAccounts(getAccounts(id));
    deleteCloudAccount(id, email);
    syncTenantFleet(id);
    // Also remove from the backend engine — otherwise the scheduler keeps running it.
    try {
      await deleteBackendAccountByEmail(email, roles);
      setRunMsg(`Removed ${email} from this site and the backend engine.`);
    } catch {
      setRunMsg(`Removed ${email} locally, but the backend engine may still run it — check connection.`);
    }
  }

  function setMarch(i: number, patch: Partial<{ primary: string; secondary: string; alliancePit: boolean }>) {
    const marches = cmd.marches.map((m, j) => (j === i ? { ...m, ...patch } : m));
    persist({ commanders: { ...cmd, marches } });
  }

  function collectDisabled(email?: string, role_id?: string, enabled?: boolean) {
    const out: string[] = [];
    for (const a of accounts) {
      for (const c of a.chars ?? []) {
        const en =
          email !== undefined && a.email === email && c.role_id === role_id
            ? !!enabled
            : (c.enabled ?? true);
        if (!en) out.push(c.role_id);
      }
    }
    return out;
  }

  async function toggleChar(email: string, role_id: string, current: boolean) {
    const next = !current;
    setAccounts((prev) =>
      prev.map((a) =>
        a.email === email
          ? { ...a, chars: (a.chars ?? []).map((c) => (c.role_id === role_id ? { ...c, enabled: next } : c)) }
          : a
      )
    );
    try {
      // Idempotent explicit state — safe against double-clicks/retries.
      const r = await setCharacterEnabled(role_id, next);
      setAccounts((prev) =>
        prev.map((a) =>
          a.email === email
            ? { ...a, chars: (a.chars ?? []).map((c) => (c.role_id === role_id ? { ...c, enabled: r.enabled } : c)) }
            : a
        )
      );
      const d = await getFleetDetails();
      setFleetDetails(d);
      const s = toEngineSettings(cfg);
      (s.mirror as Record<string, unknown>).disabled_roles = collectDisabled(email, role_id, r.enabled);
      saveCloudSettings(id, email, s.mirror);
    } catch {
      setAccounts((prev) =>
        prev.map((a) =>
          a.email === email
            ? { ...a, chars: (a.chars ?? []).map((c) => (c.role_id === role_id ? { ...c, enabled: current } : c)) }
            : a
        )
      );
      setRunMsg("Character toggle failed — backend unreachable or login expired.");
    }
  }

  async function loadRecent(signal?: AbortSignal) {
    try {
      const raw = await getRecentActivity(id, signal);
      if (signal?.aborted) return;
      if (raw && raw.length > 0) {
        setRecentLines(raw.slice(-100));
      }
    } catch {
      /* keep previous lines */
    }
  }

  function togglePick(role_id: string) {
    setPicked((p) => (p.includes(role_id) ? p.filter((r) => r !== role_id) : [...p, role_id]));
  }

  function persist(patch: Partial<BotConfig>) {
    const next = { ...cfg, ...patch };
    setCfg(next);
    let emails: string[];
    if (selectedEmail && scope === "one") {
      emails = [selectedEmail];
      saveAccountConfig(id, selectedEmail, next);
    } else {
      emails = accounts.length > 0 ? accounts.map((a) => a.email) : [];
      for (const a of accounts) saveAccountConfig(id, a.email, next);
      saveConfig(id, next);
    }
    setSaved(true);
    setTimeout(() => setSaved(false), 1200);
    // Push to the headless engine (per-character settings the bot reads)
    // and mirror a copy to the website cloud row. Fire-and-forget.
    if (emails.length > 0) pushEngine(next, emails);
  }

  async function pushEngine(next: BotConfig, emails: string[]) {
    const s = toEngineSettings(next);
    (s.mirror as Record<string, unknown>).disabled_roles = collectDisabled();
    try {
      for (const em of emails) {
        const acc = accounts.find((a) => a.email === em);
        for (const c of acc?.chars ?? []) {
          await pushCharacterSettings(c.role_id, s.tiers, s.gather, s.combat, s.hospital, s.alliance, s.daily_claims, s.city);
        }
        saveCloudSettings(id, em, s.mirror);
        // Strictly scoped per-account — NEVER tenant-wide "all", so other bot units remain isolated!
        await pushBotConfig(id, {
          scope: "email",
          email: em,
          settings: {
            tiers: s.tiers,
            gather: s.gather,
            combat: s.combat,
            hospital: s.hospital,
            alliance: s.alliance,
            daily_claims: s.daily_claims,
            city: s.city,
          }
        }).catch(() => {});
      }
      setEngineNote("Engine synced ✓");
    } catch {
      setEngineNote("Engine sync failed — backend unreachable or login expired.");
    }
  }

  function pickEmail(email: string) {
    setSelectedEmail(email);
    setCfg(email ? getAccountConfig(id, email, DEFAULT_CONFIG) : getConfig(id, DEFAULT_CONFIG));
  }

  async function saveGeneral(patch: Record<string, unknown>, iv?: string, dn?: boolean) {
    setGenMsg("Saving…");
    try {
      await updateBotSettings(patch);
      if (iv !== undefined) setInterval(iv);
      if (dn !== undefined) setDiscordNotify(dn);
      setGenMsg("Saved — takes effect the next time the bot starts.");
    } catch {
      setGenMsg("Save failed — Discord login is required, or the backend is unreachable.");
    }
  }

  async function handleRunNow() {
    setTriggeringNow(true);
    setEngineMsg("Triggering immediate pass for this unit's characters…");
    try {
      const charsToRun = accounts.flatMap((a) => (a.chars ?? []).filter((c) => c.enabled !== false));
      if (charsToRun.length === 0) {
        setEngineMsg("No enabled characters found on this unit.");
        setTriggeringNow(false);
        return;
      }
      for (const ch of charsToRun) {
        await runCharacterCycle(ch.role_id).catch(() => {});
      }
      setEngineMsg(`✓ Immediate pass started for ${charsToRun.length} character(s)! Check the Live tab for progress.`);
      setTimeout(() => setEngineMsg(""), 6000);
    } catch (e: any) {
      setEngineMsg("Failed to trigger pass: " + (e?.message || "Server error"));
    } finally {
      setTriggeringNow(false);
    }
  }

  async function handleCombatNow() {
    setTriggeringCombat(true);
    setEngineMsg("Triggering barbarian hunt across selected characters…");
    try {
      let targets: string[] = [];
      if (selectedEmail && scope === "one") {
        const acc = accounts.find((a) => a.email === selectedEmail);
        targets = (acc?.chars ?? []).filter((c) => c.enabled !== false).map((c) => c.role_id);
      } else {
        for (const a of accounts) {
          for (const c of a.chars ?? []) {
            if (c.enabled !== false) targets.push(c.role_id);
          }
        }
      }
      if (targets.length === 0) {
        setEngineMsg("No enabled characters found to attack barbarians.");
        setTriggeringCombat(false);
        return;
      }
      for (const rid of targets) {
        await runCharacterCombat(rid, {
          highest_barb_level: cfg.highestBarbLevel,
          skip_barbs_below: cfg.skipBarbsBelow,
          primary_commander: cfg.barbPrimaryCommander,
          secondary_commander: cfg.barbSecondaryCommander,
          combat_rounds: cfg.combatRounds,
          dispatch_all_marches: cfg.dispatchAllMarches,
        });
      }
      setEngineMsg(`⚔️ Barbarian combat dispatched for ${targets.length} character(s)! Check Live tab for progress.`);
      setTimeout(() => setEngineMsg(""), 6000);
    } catch (err: any) {
      setEngineMsg("Combat dispatch failed: " + (err?.message || "Check backend connection"));
    } finally {
      setTriggeringCombat(false);
    }
  }

  const totalSlots = bot.slots || 20;
  const usedSlots = accounts.reduce((acc, a) => acc + (a.chars && a.chars.length > 0 ? a.chars.length : 1), 0);
  const batteryPercent = Math.min(100, Math.max(5, Math.round(((bot.days || 30) / 30) * 100)));

  return (
    <div className="space-y-6">
      {/* GHOSTBOT PROPRIETARY CYBER COMMAND COCKPIT */}
      <section className="hero-controller-card p-6 lg:p-7 rounded-2xl">
        <div className="hero-cockpit-grid">
          {/* MODULE 1: UNIT IDENTITY, PROTOCOLS & COMMAND CONTROLS */}
          <div className="hero-cockpit-identity">
            <div className="hero-identity-row">
              <div className="hero-bot-avatar-box">
                <Image src={icon} alt={bot.product} width={42} height={42} className="object-contain drop-shadow-[0_2px_8px_rgba(0,0,0,0.5)]" />
                <div className={`hero-radar-pulse ${running ? "" : "standby"}`} title="Radar Heartbeat" />
              </div>
              <div className="hero-title-group">
                <div className="hero-account-name">{bot.label}</div>
                <div className="hero-badges-row">
                  <span className="hero-badge-pill hero-badge-cyan">
                    {bot.product === "gem-bot" ? (isAr ? "بوت الجواهر" : "GEM BOT") : (isAr ? "بوت المزارع" : "FARM BOT")}
                  </span>
                  <span className={`hero-badge-pill ${running ? "hero-badge-status-running" : "hero-badge-status-standby"}`}>
                    <span className="badge-dot">●</span>
                    <span>{running ? (isAr ? "قيد التشغيل" : "RUNNING") : (isAr ? "متوقف" : "STANDBY")}</span>
                  </span>
                  <span className="hero-badge-pill hero-badge-cyan">
                    {bot.tier === "pro" ? (isAr ? "ترخيص احترافي" : "PRO LICENSE") : (isAr ? "ترخيص أساسي" : "BASIC")}
                  </span>
                  <div className="hero-badge-pill hero-badge-cyan inline-flex items-center gap-1.5 bg-[#00e5ff]/[0.08] border border-[#00e5ff]/30 rounded-md px-2 py-0.5">
                    <span className="text-[#d6eeff] font-bold">
                      {isAr ? "الدورة القادمة: كل" : "Next Cycle: Every"} {interval === "custom" ? `${customMinutes}m` : `${interval}h`}
                    </span>
                    <span className="font-mono text-[11px] font-black text-[#00e5ff] drop-shadow-[0_0_8px_rgba(0,229,255,0.6)]">
                      {countdownText}
                    </span>
                  </div>
                </div>
              </div>
            </div>

            {/* TACTICAL QUICK ACTION BUTTONS */}
            <div className="hero-actions-row">
              <button
                onClick={toggleEngine}
                className={`hero-cyber-action-btn primary ${running ? "btn-cyber-running" : "btn-cyber-idle"}`}
              >
                {running ? <Square className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
                <span>{running ? (isAr ? "إيقاف الوحدة" : "STOP UNIT") : (isAr ? "تشغيل الوحدة" : "START UNIT")}</span>
              </button>
              <button onClick={openAdd} className="hero-cyber-action-btn">
                <Plus className="w-3.5 h-3.5" />
                <span>{isAr ? "ربط حساب جديد" : "LINK ACCOUNT"}</span>
              </button>
              <button onClick={() => setTab("rss")} className="hero-cyber-action-btn">
                <Swords className="w-3.5 h-3.5" />
                <span>{isAr ? "نقل الموارد" : "RSS TRANSFER"}</span>
              </button>
            </div>
            {engineMsg && <p className="text-xs text-amber-400 mt-1">{engineMsg}</p>}
          </div>

          {/* MODULE 2: GOVERNOR CAPACITY MATRIX */}
          <div className="hero-cockpit-slots">
            <div className="hero-slots-header">
              <div className="flex items-center gap-2">
                <span className="hero-seq-id-badge">ID #{bot.room || bot.bot_id || id}</span>
                <span className="hero-slots-title">{isAr ? "مصفوفة الحُكّام" : "GOVERNOR MATRIX"}</span>
              </div>
              {usedSlots >= totalSlots && (
                <span className="hero-at-capacity-badge">
                  <span>●</span> {isAr ? "ممتلئ بالكامل" : "AT CAPACITY"}
                </span>
              )}
            </div>

            <div className="hero-slots-count-display">
              <span className="text-white">{usedSlots}</span>
              <span className="text-[#92b2d6] text-base">/</span>
              <span className="text-[#00e5ff]">{totalSlots}</span>
              <span className="label-sub">{isAr ? "خانة مستخدمة" : "Slots Used"}</span>
            </div>

            {/* Segmented LED Micro-Tracker (20-segment grid) */}
            <div className="hero-slots-led-grid">
              {Array.from({ length: 20 }, (_, i) => {
                const active = i < Math.round((usedSlots / totalSlots) * 20);
                const warn = usedSlots >= totalSlots;
                return (
                  <div
                    key={i}
                    className={`hero-led-segment ${active ? (warn ? "active warn" : "active") : ""}`}
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
                  cx="38"
                  cy="38"
                  r="32"
                  style={{
                    strokeDasharray: 201,
                    strokeDashoffset: 201 - (201 * batteryPercent) / 100,
                  }}
                />
              </svg>
              <div className="hero-reactor-center-info">
                <span className="hero-reactor-percent">{batteryPercent}%</span>
                <span className="hero-reactor-label">CORE</span>
              </div>
            </div>

            <div className="hero-reactor-info-col">
              <div className="hero-reactor-top-row">
                <span className="hero-reactor-title">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                    <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
                  </svg>
                  <span>{isAr ? "المفاعل السحابي" : "REACTOR CORE"}</span>
                </span>
                <button
                  className="btn-reactor-plus"
                  onClick={() => router.push("/shop")}
                  title="Renew or upgrade license"
                >
                  +
                </button>
              </div>
              <div className="hero-reactor-countdown">{daysLeft}</div>
              <div className="hero-reactor-expires">
                {batteryPercent < 20 ? (isAr ? "ينتهي قريباً" : "Expires Soon") : (isAr ? "نشط ومستقر" : "Optimal Sync")}
              </div>
              <div className="hero-reactor-plan">
                {isAr
                  ? `باقة ${bot.product === "gem-bot" ? "جواهر" : "مزارع"} • ${totalSlots} حاكم`
                  : `${bot.product === "gem-bot" ? "Gem Plan" : "Farm Plan"} • ${totalSlots} Slots`}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* HORIZONTAL TABS BAR */}
      <nav className="tabs-bar">
        {TABS.map((t) => (
          <div
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`tab-btn ${tab === t.id ? "active" : ""}`}
          >
            {isAr ? t.labelAr : t.label}
          </div>
        ))}
      </nav>

      {/* LIVE — Telemetry Stream / Logs ONLY */}
      {tab === "live" && (
        <div className="space-y-5">
          <div className="rounded-xl border border-zinc-800 bg-black/75 backdrop-blur-xl overflow-hidden shadow-2xl">
            <div className="px-5 py-3 border-b border-zinc-800 flex items-center justify-between font-mono">
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                <h3 className="text-xs font-bold text-emerald-300 uppercase tracking-wider">LIVE TELEMETRY STREAM</h3>
                <span className="text-[10px] px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 font-semibold">
                  {bot.label} ISOLATED WIRE
                </span>
              </div>
              <button onClick={() => loadRecent()} className="text-[10px] text-zinc-400 hover:text-emerald-400 transition-colors uppercase">
                [ REFRESH WIRE ]
              </button>
            </div>
            <div ref={logRef} className="px-5 py-4 min-h-72 max-h-[500px] overflow-y-auto font-mono text-[11px] leading-relaxed text-zinc-300 space-y-1.5 bg-zinc-950/40">
              {displayLogs.length === 0 && (
                <p className="font-mono text-xs text-zinc-500">
                  Awaiting wire telemetry packets for {bot.label}...
                </p>
              )}
              {displayLogs.map((l, i) => (
                // Static class list — no transition-*/hover:* per line: that CSS
                // forced style recalculation on thousands of nodes every poll.
                <p key={i} className="whitespace-pre-wrap break-words text-zinc-300 font-mono text-xs leading-5">
                  <span className="text-emerald-500 mr-2">›</span>
                  {l}
                </p>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ACCOUNTS (الحسابات) — Account group cards with governor rows */}
      {tab === "accounts" && (
        <div className="space-y-5">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="relative max-w-sm flex-1">
              <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-zinc-600" />
              <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search governor name, ID, or email" className="input-dark w-full pl-9 pr-3 py-2 text-sm" />
            </div>
            <button
              onClick={openAdd}
              className="flex items-center gap-2 px-4 py-2 font-semibold text-xs rounded-lg bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 border border-emerald-500/40 transition-all shadow-[0_0_15px_rgba(16,185,129,0.15)]"
            >
              <Plus className="w-3.5 h-3.5" /> + LINK ACCOUNT
            </button>
          </div>
          {runMsg && (
            <div className="card px-5 py-3 text-xs text-zinc-300">{runMsg}</div>
          )}
          {filtered.length === 0 && (
            <div className="card p-8 text-center text-xs text-zinc-500">No accounts linked yet. Use “+ LINK ACCOUNT” above.</div>
          )}
          {filtered.map((a) => {
            const chars = a.chars ?? [];
            return (
              <div key={a.email} className="card overflow-hidden">
                <div className="flex flex-wrap items-center gap-3 px-5 py-4 border-b border-[#25252e]">
                  <button role="switch" aria-checked={a.enabled} onClick={() => handleToggleAccount(a.email, a.enabled)}
                    className={`w-10 h-[22px] rounded-full p-0.5 transition-colors shrink-0 ${a.enabled ? "bg-[#10B981]" : "bg-[#25252e]"}`}>
                    <span className={`block w-[18px] h-[18px] rounded-full bg-white transition-transform ${a.enabled ? "translate-x-[18px]" : ""}`} />
                  </button>
                  <span className="text-sm font-bold text-white truncate">{a.email}</span>
                  <span className="text-[10px] font-semibold px-2 py-1 rounded-full bg-[#5865F2]/15 text-[#a5b0ff]">
                    {chars.length > 0 ? `${chars.length} governor${chars.length === 1 ? "" : "s"}` : "no governor data"}
                  </span>
                  {proxyMap[a.email]?.proxy_url && (
                    <span className="text-[10px] font-semibold px-2 py-1 rounded-full bg-[#10B981]/10 text-[#10B981]" title="Assigned proxy (max 10 accounts each)">
                      {shortProxy(proxyMap[a.email]?.proxy_url)}
                    </span>
                  )}
                  <div className="ml-auto flex items-center gap-2">
                    <button onClick={() => setTab("history")} className="btn-ghost flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold">
                      <FileText className="w-3.5 h-3.5" /> Summaries
                    </button>
                    <div className="relative">
                      <button onClick={() => setMenuEmail(menuEmail === a.email ? null : a.email)} className="btn-ghost flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold">
                        Actions <ChevronDown className="w-3.5 h-3.5" />
                      </button>
                      {menuEmail === a.email && (
                        <>
                          <div className="fixed inset-0 z-10" onClick={() => setMenuEmail(null)} />
                          <div className="absolute right-0 mt-2 w-44 z-20 card p-1.5 space-y-0.5">
                            <button onClick={() => { setMenuEmail(null); runNow(a); }}
                              className="w-full text-left px-3 py-2 rounded-lg text-xs font-medium text-zinc-200 hover:bg-[#1a1a22] transition-colors">
                              Run now
                            </button>
                            <div title="Coming soon — will be wired to the bot later"
                              className="flex items-center gap-2 px-3 py-2 text-xs text-zinc-600 cursor-not-allowed">
                              <span className="w-1.5 h-1.5 rounded-full bg-red-500 shrink-0" />
                              Recall troops
                              <span className="ml-auto text-[9px] font-bold uppercase tracking-wider text-zinc-600">Soon</span>
                            </div>
                            <div title="Coming soon — will be wired to the bot later"
                              className="flex items-center gap-2 px-3 py-2 text-xs text-zinc-600 cursor-not-allowed">
                              <span className="w-1.5 h-1.5 rounded-full bg-red-500 shrink-0" />
                              Shield
                              <span className="ml-auto text-[9px] font-bold uppercase tracking-wider text-zinc-600">Soon</span>
                            </div>
                            <div className="h-px bg-[#25252e] my-1" />
                            <button onClick={() => { setMenuEmail(null); removeFull(a.email); }}
                              className="w-full text-left px-3 py-2 rounded-lg text-xs font-medium text-red-400 hover:bg-red-500/10 transition-colors">
                              Remove account
                            </button>
                          </div>
                        </>
                      )}
                    </div>
                  </div>
                </div>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-[11px] uppercase tracking-wider text-zinc-500 border-b border-[#25252e]">
                      <th className="px-5 py-3 font-semibold">On</th>
                      <th className="px-5 py-3 font-semibold">Governor ID</th>
                      <th className="px-5 py-3 font-semibold">Kingdom</th>
                      <th className="px-5 py-3 font-semibold">Name</th>
                      <th className="px-5 py-3 font-semibold">City Hall</th>
                      <th className="px-5 py-3 font-semibold">Last Run</th>
                      <th className="px-5 py-3 font-semibold">Next Run</th>
                      <th className="px-5 py-3 font-semibold text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {chars.length === 0 && (
                      <tr><td colSpan={8} className="px-5 py-6 text-center text-xs text-zinc-500">No governor data — remove and re-add this account to sync its characters.</td></tr>
                    )}
                    {chars.map((c) => (
                      <tr key={c.role_id} className="border-b border-[#25252e] last:border-0 hover:bg-[#1a1a22]">
                        <td className="px-5 py-3">
                          <button role="switch" aria-checked={c.enabled ?? true} title={c.enabled === false ? "Disabled — skipped by the scheduler" : "Enabled"}
                            onClick={() => toggleChar(a.email, c.role_id, c.enabled ?? true)}
                            className={`w-9 h-5 rounded-full p-0.5 transition-colors shrink-0 ${(c.enabled ?? true) ? "bg-[#10B981]" : "bg-[#25252e]"}`}>
                            <span className={`block w-4 h-4 rounded-full bg-white transition-transform ${(c.enabled ?? true) ? "translate-x-4" : ""}`} />
                          </button>
                        </td>
                        <td className="px-5 py-3 text-zinc-300 font-mono text-[13px]">{c.role_id}</td>
                        <td className="px-5 py-3">
                          <span className="text-[11px] font-bold px-2 py-1 rounded bg-[#5865F2]/15 text-[#a5b0ff]">#{c.kingdom_id}</span>
                        </td>
                        <td className="px-5 py-3">
                          <span className="inline-flex items-center gap-2 text-white font-medium">
                            <GovAvatar name={fleetDetails[c.role_id]?.name || c.name} src={c.avatar_url || fleetDetails[c.role_id]?.avatar || ""} />
                            {fleetDetails[c.role_id]?.name || c.name}
                          </span>
                        </td>
                        <td className="px-5 py-3 text-zinc-300">
                          {(c.city_level || fleetDetails[c.role_id]?.city) ? `CH ${c.city_level || fleetDetails[c.role_id]?.city}` : "—"}
                        </td>
                        <td className="px-5 py-3 text-zinc-400">{fleetDetails[c.role_id]?.last ?? "—"}</td>
                        <td className="px-5 py-3 text-zinc-400">{fleetDetails[c.role_id]?.next ?? "—"}</td>
                        <td className="px-5 py-3 text-right">
                          <button
                            onClick={() => runCharDirect(c.role_id, fleetDetails[c.role_id]?.name || c.name)}
                            title={`Run ${fleetDetails[c.role_id]?.name || c.name} now`}
                            className="inline-flex items-center gap-1.5 px-3 py-1 rounded bg-[#25252e] hover:bg-[#32323e] text-xs font-semibold text-zinc-300 hover:text-white transition-colors"
                          >
                            <Play className="w-3 h-3 text-[#10B981] fill-[#10B981]" />
                            <span>Run</span>
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          })}
        </div>
      )}

      {/* INVENTORY */}
      {tab === "inventory" && (
        <div className="space-y-4">
          {/* Resources gathered — interactive window pills */}
          <div className="card p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h3 className="text-sm font-bold text-white">Resources gathered</h3>
              <div className="flex gap-1.5">
                {(["today", "7days", "30days"] as const).map((r) => (
                  <button
                    key={r}
                    onClick={() => setInvRange(r)}
                    className={`px-3 py-1 rounded-full text-[11px] font-bold uppercase tracking-wide border transition-all ${
                      invRange === r
                        ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/40"
                        : "bg-zinc-900/60 text-zinc-500 border-zinc-800 hover:text-zinc-300"
                    }`}
                  >
                    {r === "today" ? "Today" : r === "7days" ? "7 days" : "30 days"}
                  </button>
                ))}
              </div>
            </div>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mt-4">
              {(["food", "wood", "stone", "gold"] as const).map((r) => {
                const win = inv?.resources_gathered?.[invRange];
                const val = win ? (win[r] as number) : 0;
                const trend = win?.trend || [];
                const maxT = Math.max(1, ...trend.map((t) => (t[r] as number) || 0));
                return (
                  <div key={r} className="rounded-xl bg-zinc-950/60 border border-zinc-800/80 p-4">
                    <div className={`text-[11px] font-semibold uppercase tracking-wider ${RESOURCE_COLORS[r]}`}>{r}</div>
                    <div className="mt-1 text-2xl font-bold text-white">{fmtBig(val)}</div>
                    <div className="mt-2 flex items-end gap-1 h-8">
                      {trend.slice(-14).map((t, i) => (
                        <div
                          key={i}
                          className="flex-1 rounded-t bg-emerald-500/40"
                          style={{ height: `${Math.max(4, ((t[r] as number) || 0) / maxT * 100)}%` }}
                          title={`${t.day}: ${fmtBig((t[r] as number) || 0)}`}
                        />
                      ))}
                      {trend.length === 0 && <span className="text-[10px] text-zinc-600">No data yet</span>}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* In cities now */}
          <div className="card p-5">
            <h3 className="text-sm font-bold text-white">In cities now</h3>
            <div className="grid grid-cols-2 lg:grid-cols-5 gap-4 mt-3">
              {(["food", "wood", "stone", "gold", "gems"] as const).map((r) => (
                <div key={r} className="rounded-xl bg-zinc-950/60 border border-zinc-800/80 p-4">
                  <div className={`text-[11px] font-semibold uppercase tracking-wider ${RESOURCE_COLORS[r]}`}>{r}</div>
                  <div className="mt-1 text-xl font-bold text-white">{fmtBig(inv?.in_cities_now?.[r] ?? 0)}</div>
                </div>
              ))}
            </div>
            {!inv && <p className="text-xs text-zinc-500 mt-3">Waiting for the next Opcode 1002 city sync…</p>}
          </div>

          {/* Per-character breakdown */}
          <div className="card p-5 overflow-x-auto">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-bold text-white">Per-character breakdown</h3>
              <button
                onClick={() => setGroupByKingdom((v) => !v)}
                className={`px-3 py-1 rounded-lg text-[11px] font-bold uppercase border transition-all ${
                  groupByKingdom
                    ? "bg-[#8b9bff]/15 text-[#8b9bff] border-[#8b9bff]/40"
                    : "bg-zinc-900/60 text-zinc-500 border-zinc-800 hover:text-zinc-300"
                }`}
              >
                Group by kingdom
              </button>
            </div>
            {groupByKingdom && inv?.characters_by_kingdom ? (
              <div className="space-y-3">
                {Object.entries(inv.characters_by_kingdom).map(([kd, chars]) => (
                  <details key={kd} open className="rounded-xl bg-zinc-950/60 border border-zinc-800/80 overflow-hidden">
                    <summary className="px-4 py-2.5 cursor-pointer text-xs font-bold text-[#8b9bff] uppercase tracking-wide">
                      Kingdom {kd} — {chars.length} governor{chars.length === 1 ? "" : "s"} · {fmtBig(chars.reduce((s, c) => s + c.total, 0))} RSS
                    </summary>
                    <div className="px-4 pb-3"><InvTable chars={chars} /></div>
                  </details>
                ))}
              </div>
            ) : inv && inv.characters.length > 0 ? (
              <InvTable chars={inv.characters} />
            ) : (
              <p className="text-xs text-zinc-500">No characters tracked yet — the first visit syncs city state.</p>
            )}
          </div>
        </div>
      )}

      {/* HISTORY */}
      {tab === "history" && (
        <div className="card overflow-hidden">
          <div className="px-5 py-4 border-b border-[#25252e]"><h3 className="text-sm font-bold text-white">Recent runs</h3></div>
          {runs.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-[10px] uppercase tracking-wider text-zinc-500 border-b border-[#25252e]">
                    <th className="px-4 py-2.5">Started</th>
                    <th className="px-4 py-2.5">Account</th>
                    <th className="px-4 py-2.5">Length</th>
                    <th className="px-4 py-2.5">Characters</th>
                    <th className="px-4 py-2.5">Food</th>
                    <th className="px-4 py-2.5">Wood</th>
                    <th className="px-4 py-2.5">Stone</th>
                    <th className="px-4 py-2.5">Gold</th>
                    <th className="px-4 py-2.5"></th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((r) => (
                    <tr key={r.run_id} className="border-b border-[#1d1d26]/60 hover:bg-zinc-900/40">
                      <td className="px-4 py-2.5 text-zinc-300 whitespace-nowrap">{(r.started || "").slice(0, 19).replace("T", " ")}</td>
                      <td className="px-4 py-2.5 text-zinc-400 max-w-40 truncate" title={r.account}>{r.account}</td>
                      <td className="px-4 py-2.5 text-zinc-300">{r.length_minutes}m</td>
                      <td className="px-4 py-2.5 text-zinc-300">{r.characters}</td>
                      <td className={`px-4 py-2.5 font-semibold ${RESOURCE_COLORS.food}`}>{fmtBig(r.food)}</td>
                      <td className={`px-4 py-2.5 font-semibold ${RESOURCE_COLORS.wood}`}>{fmtBig(r.wood)}</td>
                      <td className={`px-4 py-2.5 font-semibold ${RESOURCE_COLORS.stone}`}>{fmtBig(r.stone)}</td>
                      <td className={`px-4 py-2.5 font-semibold ${RESOURCE_COLORS.gold}`}>{fmtBig(r.gold)}</td>
                      <td className="px-4 py-2.5">
                        <button
                          onClick={async () => {
                            const s = await getRunSummary(id, r.run_id);
                            if (s) {
                              setRunSummary(s);
                              setSummaryOpen(true);
                            }
                          }}
                          className="px-2.5 py-1 rounded-lg bg-[#8b9bff]/10 text-[#8b9bff] border border-[#8b9bff]/30 text-[10px] font-bold uppercase hover:bg-[#8b9bff]/20"
                        >
                          View summary
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="px-5 py-8 text-center text-xs text-zinc-500">No runs recorded yet — history fills after the first sweep.</div>
          )}
        </div>
      )}

      {/* RUN SUMMARY MODAL */}
      {summaryOpen && runSummary && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4" onClick={() => setSummaryOpen(false)}>
          <div className="card w-full max-w-2xl max-h-[85vh] overflow-y-auto p-6" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-start justify-between gap-4">
              <div>
                <h3 className="text-lg font-bold text-white">Farm run summary</h3>
                <p className="text-xs text-zinc-500 mt-1">
                  Run {runSummary.run_id?.slice(-8)} · {runSummary.length_minutes}m · governors {runSummary.characters_ratio}
                </p>
              </div>
              <button onClick={() => setSummaryOpen(false)} className="btn-ghost px-2 py-1 text-xs">✕</button>
            </div>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mt-4">
              {(["food", "wood", "stone", "gold"] as const).map((r) => (
                <div key={r} className="rounded-xl bg-zinc-950/60 border border-zinc-800/80 p-3">
                  <div className={`text-[10px] font-semibold uppercase tracking-wider ${RESOURCE_COLORS[r]}`}>{r} this run</div>
                  <div className="mt-1 text-lg font-bold text-white">{fmtBig((runSummary.totals as any)[r] ?? 0)}</div>
                </div>
              ))}
            </div>
            <div className="mt-4 space-y-3">
              {runSummary.characters.map((c) => (
                <div key={c.id} className="rounded-xl bg-zinc-950/60 border border-zinc-800/80 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="text-sm font-bold text-white">{c.name || `Governor ${c.id}`}</div>
                    <div className="text-[11px] text-zinc-500">CH{c.city_hall} · {fmtBig(c.power)} power · visit {fmtDuration(c.visit_duration_seconds)}</div>
                  </div>
                  <div className="grid grid-cols-4 gap-2 mt-2 text-center">
                    {(["food", "wood", "stone", "gold"] as const).map((r) => (
                      <div key={r} className="rounded-lg bg-zinc-900/70 p-2">
                        <div className={`text-[9px] uppercase tracking-wide ${RESOURCE_COLORS[r]}`}>{r}</div>
                        <div className="text-xs font-bold text-white mt-0.5">+{fmtBig((c as any)[r] ?? 0)}</div>
                      </div>
                    ))}
                  </div>
                  {(() => {
                    if (!c.details) return null;
                    try {
                      const d = typeof c.details === "string" ? JSON.parse(c.details) : c.details;
                      const gatherers: string[] = Array.isArray(d?.gatherers) ? d.gatherers : [];
                      const actions: string[] = Array.isArray(d?.actions) ? d.actions : [];
                      if (gatherers.length === 0 && actions.length === 0) return null;
                      return (
                        <div className="mt-3 pt-3 border-t border-zinc-800/80 space-y-2 text-left">
                          {gatherers.length > 0 && (
                            <div>
                              <div className="text-[10px] font-bold uppercase tracking-wider text-emerald-400">Marches & Gatherers</div>
                              <ul className="mt-1 space-y-0.5 text-[11px] text-zinc-300">
                                {gatherers.map((g, idx) => (
                                  <li key={idx} className="flex items-center gap-1.5">
                                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 shrink-0" />
                                    <span>{g}</span>
                                  </li>
                                ))}
                              </ul>
                            </div>
                          )}
                          {actions.length > 0 && (
                            <div>
                              <div className="text-[10px] font-bold uppercase tracking-wider text-indigo-400">Actions Completed</div>
                              <ul className="mt-1 space-y-0.5 text-[11px] text-zinc-400">
                                {actions.map((a, idx) => (
                                  <li key={idx} className="flex items-center gap-1.5">
                                    <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 shrink-0" />
                                    <span>{a}</span>
                                  </li>
                                ))}
                              </ul>
                            </div>
                          )}
                        </div>
                      );
                    } catch {
                      return null;
                    }
                  })()}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* CONFIG */}
      {tab === "config" && (
        <div className="space-y-5">
          <div className="card p-5 md:p-6">
            <div className="grid md:grid-cols-2 gap-5">
              <div>
                <h3 className="text-sm font-bold text-white">Configuration</h3>
                <p className="text-xs text-zinc-500 mt-1">Choose a category or search for a setting. Account changes save automatically.</p>
                <p className="text-xs text-[#8b9bff] mt-1">Changes take effect the next time the bot starts.</p>
                {engineNote && <p className="text-[11px] text-zinc-500 mt-1">{engineNote}</p>}
              </div>
              <div className="space-y-3">
                <div>
                  <label className="block text-[11px] font-semibold uppercase tracking-wider text-zinc-500 mb-1">Account</label>
                  <select value={selectedEmail} onChange={(e) => pickEmail(e.target.value)} className="input-dark w-full px-3 py-2 text-xs">
                    {emailOptions.length === 0 && <option value="">No accounts linked</option>}
                    {emailOptions.map((a) => (
                      <option key={a.email} value={a.email}>{a.email}</option>
                    ))}
                  </select>
                </div>
                <div className="relative">
                  <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-zinc-600" />
                  <input value={governorQuery} onChange={(e) => setGovernorQuery(e.target.value)} placeholder="Find account by governor name" className="input-dark w-full pl-9 pr-3 py-2 text-xs" />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold uppercase tracking-wider text-zinc-500 mb-1">Apply changes to</label>
                  <select value={scope} onChange={(e) => setScope(e.target.value as "one" | "all")} className="input-dark w-full px-3 py-2 text-xs">
                    <option value="one">This email only</option>
                    <option value="all">All emails on this bot</option>
                  </select>
                </div>
                <div className="relative">
                  <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-zinc-600" />
                  <input value={settingQuery} onChange={(e) => setSettingQuery(e.target.value)} placeholder="Search settings" className="input-dark w-full pl-9 pr-3 py-2 text-xs" />
                </div>
              </div>
            </div>
          </div>
          <div className="grid lg:grid-cols-[220px_1fr] gap-5 items-start">
          <div className="card p-2 space-y-1">
            {CONFIG_CATS.map((c) => (
              <button
                key={c}
                onClick={() => setCfgCat(c)}
                className={`w-full text-left px-3 py-2.5 rounded-lg text-xs font-semibold transition-colors ${
                  cfgCat === c ? "bg-[#5865F2]/15 text-white border border-[#5865F2]/40" : "text-zinc-400 hover:bg-[#1a1a22] border border-transparent"
                }`}
              >
                {c}
              </button>
            ))}
          </div>
          <div className="card overflow-hidden">
            <div className="px-5 py-3 border-b border-[#25252e] flex items-center gap-2">
              <h3 className="text-sm font-bold text-white">{cfgCat}</h3>
              {saved && <span className="text-[11px] text-[#10B981] font-semibold flex items-center gap-1"><Check className="w-3 h-3" /> Saved</span>}
            </div>
            {cfgCat === "General" && (
              <div>
                <div className="px-5 pt-4 flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h4 className="text-sm font-bold text-white">Run Frequency</h4>
                    <p className="text-xs text-zinc-500 mt-0.5">Choose how often the bot completes a full pass through your characters.</p>
                  </div>
                  <button
                    type="button"
                    onClick={handleRunNow}
                    disabled={triggeringNow}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-400 border border-emerald-500/40 text-xs font-semibold transition-all shadow-sm"
                    title="Run full pass immediately without waiting for interval"
                  >
                    <Play className="w-3.5 h-3.5 fill-current" />
                    {triggeringNow ? "Starting…" : "Run pass now"}
                  </button>
                </div>
                <Row q={settingQuery} title="Interval" desc="How often the bot starts a full pass."
                  control={
                    <div className="flex flex-wrap items-center gap-2">
                      <select
                        value={isCustomInterval ? "custom" : interval}
                        onChange={(e) => {
                          const val = e.target.value;
                          if (val === "custom") {
                            setIsCustomInterval(true);
                          } else {
                            setIsCustomInterval(false);
                            const h = parseFloat(val);
                            const m = Math.round(h * 60);
                            setCustomMinutes(String(m));
                            saveGeneral({ run_interval_hours: val, run_interval_minutes: String(m) }, val, undefined);
                          }
                        }}
                        className="input-dark px-3 py-1.5 text-xs font-medium"
                      >
                        <option value="3">Every 3 hours</option>
                        <option value="4">Every 4 hours</option>
                        <option value="6">Every 6 hours</option>
                        <option value="8">Every 8 hours</option>
                        <option value="12">Every 12 hours</option>
                        <option value="24">Every 24 hours</option>
                        <option value="custom">Custom...</option>
                      </select>
                      {isCustomInterval && (
                        <div className="flex items-center gap-1.5 bg-[#1b1b22] px-2 py-1 rounded border border-[#25252e]">
                          <span className="text-xs text-zinc-400">Every</span>
                          <input
                            type="number"
                            min="1"
                            max="1440"
                            value={customMinutes}
                            onChange={(e) => setCustomMinutes(e.target.value)}
                            placeholder="10"
                            className="input-dark w-16 px-2 py-1 text-xs text-center font-bold text-emerald-400 border border-emerald-500/40 rounded focus:outline-none"
                          />
                          <span className="text-xs text-zinc-400">min</span>
                          <button
                            type="button"
                            onClick={() => {
                              const mins = Math.max(1, parseInt(customMinutes) || 10);
                              const hrs = (mins / 60).toFixed(4);
                              saveGeneral({ run_interval_minutes: String(mins), run_interval_hours: hrs }, hrs, undefined);
                              setGenMsg(`✓ Saved: Bot scheduled to start every ${mins} minute${mins === 1 ? "" : "s"}.`);
                            }}
                            className="px-2.5 py-1 bg-[#5865F2] hover:bg-[#4752c4] text-white rounded text-xs font-semibold shadow-sm transition-colors"
                          >
                            Set
                          </button>
                        </div>
                      )}
                    </div>
                  }
                />
                <div className="px-5 pt-4">
                  <h4 className="text-sm font-bold text-white">Instance Settings</h4>
                  <p className="text-xs text-zinc-500 mt-0.5">Settings shared by every account on this {bot.product === "gem-bot" ? "Gem Bot" : "Farm Bot"}.</p>
                </div>
                <Row q={settingQuery} title="Discord notifications" desc="Send a summary to your Discord DMs after each run."
                  control={<Toggle on={discordNotify} onClick={() => saveGeneral({ discord_notifications: String(!discordNotify) }, undefined, !discordNotify)} />} />
                {genMsg && <p className="px-5 pb-4 text-[11px] text-zinc-400">{genMsg}</p>}
              </div>
            )}
            {cfgCat === "Gathering" && (
              <div>
                {(["food", "wood", "stone", "gold"] as const).map((r) => (
                  <Row q={settingQuery} key={r} icon={`/images/res/${r}.webp`} title={r[0].toUpperCase() + r.slice(1)} desc={`${cfg.marches[r]} march${cfg.marches[r] === 1 ? "" : "es"} on ${r}`}
                    control={<Stepper value={cfg.marches[r]} onChange={(v) => persist({ marches: { ...cfg.marches, [r]: v } })} />} />
                ))}
                <Row q={settingQuery} title="Auto-Balance Lowest Resource" desc="Automatically routes ~65% of gathering marches to the resource type with lowest reserves in city. Resources set to 0 marches are strictly excluded."
                  control={<Toggle on={!!cfg.auto_balance_lowest_rss} onClick={() => persist({ auto_balance_lowest_rss: !cfg.auto_balance_lowest_rss })} />} />
                <Row q={settingQuery} title="Max node level" desc="Highest resource-node level the bot will gather."
                  control={<select value={cfg.maxNodeLevel} onChange={(e) => persist({ maxNodeLevel: e.target.value })} className="input-dark px-3 py-1.5 text-xs">
                    {["No cap", "6", "5", "4", "3", "2", "1"].map((o) => <option key={o}>{o}</option>)}
                  </select>} />
                <Row q={settingQuery} title="Only finishable nodes" desc="Only send a march to a node it can fully drain."
                  soon control={<Toggle on={cfg.finishable} onClick={() => persist({ finishable: !cfg.finishable })} />} />
                <Row q={settingQuery} title="Skip partially gathered nodes" desc="Only gather tiles with >=90% full capacity. Skip abandoned or depleted tiles."
                  control={<Toggle on={cfg.skipPartial} onClick={() => persist({ skipPartial: !cfg.skipPartial })} />} />
                <Row q={settingQuery} title="Avoid other alliance territories" desc="Gather only on your alliance territory or neutral land."
                  control={<Toggle on={cfg.avoidTerritory} onClick={() => persist({ avoidTerritory: !cfg.avoidTerritory })} />} />
                <div className="border-t border-[#25252e] px-5 pt-4 pb-1 flex flex-wrap items-center gap-2">
                  <h4 className="text-sm font-bold text-white">Gathering Commanders</h4>
                  <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 border border-amber-500/30 uppercase tracking-wider">Soon</span>
                </div>
                <div className="opacity-40 pointer-events-none grayscale px-5 pb-3 max-w-2xl">
                  <p className="text-xs text-zinc-500 py-2">Pin commanders to specific gather marches. Leave a row on Auto to let the bot choose.</p>
                  <div className="card p-3 mb-2 flex items-center gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-semibold text-white">Use loadout color instead</div>
                      <div className="text-xs text-zinc-500 mt-0.5">Take commanders from the march loadouts saved in game.</div>
                    </div>
                    <Toggle on={cmd.useLoadout} onClick={() => persist({ commanders: { ...cmd, useLoadout: !cmd.useLoadout } })} />
                  </div>
                  {cmd.marches.map((m, i) => (
                    <div key={i} className="card p-3 mb-2">
                      <div className="text-sm font-semibold text-white">March {i + 1}</div>
                      <div className="grid sm:grid-cols-2 gap-3 mt-2">
                        <select value={m.primary} onChange={(e) => setMarch(i, { primary: e.target.value })} className="input-dark px-3 py-2 text-xs"><option>Auto</option></select>
                        <select value={m.secondary} onChange={(e) => setMarch(i, { secondary: e.target.value })} className="input-dark px-3 py-2 text-xs"><option>Auto (best available)</option></select>
                      </div>
                      <label className="flex items-center gap-2 mt-2 text-xs text-zinc-400">
                        <input type="checkbox" checked={m.alliancePit} onChange={(e) => setMarch(i, { alliancePit: e.target.checked })} className="accent-[#5865F2]" /> Alliance pit
                      </label>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {cfgCat === "City" && (
              <div>
                <Row q={settingQuery} title="Collect city resources" desc="Collect resources from production buildings."
                  control={<Toggle on={cfg.collectCity} onClick={() => persist({ collectCity: !cfg.collectCity })} />} />
                <Row q={settingQuery} title="Produce blacksmith materials" desc="Keep basic crafting materials in production."
                  soon control={<Toggle on={cfg.blacksmith} onClick={() => persist({ blacksmith: !cfg.blacksmith })} />} />
                {(["infantry", "cavalry", "archery", "siege"] as const).map((u) => (
                  <Row q={settingQuery} key={u} title={`Train ${u}`} desc="Highest tier to train, or Off to skip."
                    control={<select value={cfg.train[u]} onChange={(e) => persist({ train: { ...cfg.train, [u]: e.target.value } })} className="input-dark px-3 py-1.5 text-xs">
                      {["Off", "T1", "T2", "T3", "T4", "T5"].map((o) => <option key={o}>{o}</option>)}
                    </select>} />
                ))}
                <div className="border-t border-[#25252e] px-5 pt-4 pb-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h4 className="text-[11px] font-bold tracking-wider text-zinc-400">BATTLE TRAINING</h4>
                    <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 border border-amber-500/30 uppercase tracking-wider">Pro only</span>
                    <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 border border-amber-500/30 uppercase tracking-wider">Soon</span>
                  </div>
                  <div className="mt-2 p-4 rounded-lg border border-[#25252e] bg-[#141418] text-xs text-zinc-400">
                    Battle training is a Pro feature. Upgrade to Pro to mass-train battle troops toward a ready-troop target or through a per-governor speedup budget.
                  </div>
                  <div className="opacity-40 pointer-events-none grayscale">
                    <Row q={settingQuery} title="Battle training mode" desc="Target trains each governor up to a healthy troop total. Turn this off to resume the normal queue."
                      control={<select value={cfg.battleTrainingMode} onChange={(e) => persist({ battleTrainingMode: e.target.value })} className="input-dark px-3 py-1.5 text-xs">
                        {["Off", "Target total", "Speedup budget"].map((o) => <option key={o}>{o}</option>)}
                      </select>} />
                  </div>
                </div>
               </div>
             )}
            {cfgCat === "Combat" && (
              <div>
                <div className="px-5 pt-4 pb-3 flex flex-wrap items-center justify-between gap-3 border-b border-[#25252e]">
                  <div>
                    <h4 className="text-sm font-bold text-white flex items-center gap-2">
                      <Swords className="w-4 h-4 text-red-400" />
                      Barbarian Hunting (هجوم البربر)
                    </h4>
                    <p className="text-xs text-zinc-500 mt-0.5">Automated barbarian elimination across all march queues before gathering.</p>
                  </div>
                  <button
                    type="button"
                    onClick={handleCombatNow}
                    disabled={triggeringCombat}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-600/20 hover:bg-red-600/30 text-red-400 border border-red-500/40 text-xs font-semibold transition-all shadow-sm"
                    title="Dispatch barbarian hunt immediately"
                  >
                    <Swords className="w-3.5 h-3.5" />
                    {triggeringCombat ? "Dispatching…" : "Attack barbarians now (هجوم الآن)"}
                  </button>
                </div>
                <Row
                  q={settingQuery}
                  title="Attack barbarians"
                  desc="Burn Action Points on barbarians"
                  control={
                    <Toggle
                      on={cfg.barbs}
                      onClick={() => persist({ barbs: !cfg.barbs })}
                    />
                  }
                />

                <div className="flex items-center gap-4 p-4 border-b border-[#25252e]">
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold text-white">Highest barb level to attack</div>
                    <div className="text-xs text-zinc-500 mt-0.5">
                      The bot kills the strongest barbarians it can, climbing up to this level. Lower it if your troops (e.g. T3) can&apos;t beat high-level barbs. Your City Hall also auto-caps attacks a couple levels below your CH, so if this is set higher, the bot lowers it to fit instead of skipping barbs altogether.
                    </div>
                  </div>
                  <select
                    value={cfg.highestBarbLevel || "L7"}
                    onChange={(e) => persist({ highestBarbLevel: e.target.value })}
                    className="input-dark px-3 py-1.5 text-xs w-36 shrink-0"
                  >
                    {BARB_LEVEL_OPTIONS.map((lvl) => (
                      <option key={lvl} value={lvl}>
                        {lvl === "Max Unlocked" ? "Max Unlocked (أعلى مستوى)" : lvl}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="flex items-center gap-4 p-4 border-b border-[#25252e]">
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold text-white">Skip barbs below</div>
                    <div className="text-xs text-zinc-500 mt-0.5">
                      Optional floor so the bot doesn&apos;t spend Action Points on weak barbs. Leave at &ldquo;None&rdquo; to take whatever it can. This is a floor, not a target: setting it high will <i>not</i> make the bot attack higher levels (use &ldquo;Highest barb level&rdquo; above for that).
                    </div>
                  </div>
                  <select
                    value={cfg.skipBarbsBelow || "None"}
                    onChange={(e) => persist({ skipBarbsBelow: e.target.value })}
                    className="input-dark px-3 py-1.5 text-xs w-28 shrink-0"
                  >
                    {SKIP_BARB_LEVEL_OPTIONS.map((lvl) => (
                      <option key={lvl} value={lvl}>{lvl}</option>
                    ))}
                  </select>
                </div>

                <div className="flex items-center gap-4 p-4 border-b border-[#25252e]">
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold text-white">Barb commander</div>
                    <div className="text-xs text-zinc-500 mt-0.5">
                      Pin which commander leads barb attacks, plus the secondary that rides along. Falls back to your highest-level idle commander when the chosen one isn&apos;t owned or available. The secondary only attaches when the primary is level 20+ and a commander is spare: one commander cannot lead a march and assist another at the same time.
                    </div>
                  </div>
                  <div className="flex flex-col gap-2 shrink-0 w-48">
                    <select
                      value={cfg.barbPrimaryCommander || "Auto"}
                      onChange={(e) => persist({ barbPrimaryCommander: e.target.value })}
                      className="input-dark px-3 py-1.5 text-xs w-full"
                    >
                      {COMMANDER_OPTIONS.map((cmd) => (
                        <option key={cmd} value={cmd}>{cmd}</option>
                      ))}
                    </select>
                    <select
                      value={cfg.barbSecondaryCommander || "Auto (best available)"}
                      onChange={(e) => persist({ barbSecondaryCommander: e.target.value })}
                      className="input-dark px-3 py-1.5 text-xs w-full"
                    >
                      {SECONDARY_COMMANDER_OPTIONS.map((cmd) => (
                        <option key={cmd} value={cmd}>{cmd}</option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="flex items-center gap-4 p-4 border-b border-[#25252e]">
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold text-white flex items-center gap-2">
                      Combat rounds (عدد اللفات)
                      <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-blue-500/15 text-blue-400 border border-blue-500/30">
                        New
                      </span>
                    </div>
                    <div className="text-xs text-zinc-500 mt-0.5">
                      Number of consecutive barbarian hunt loops per visit. In each round, all available march queues go out, eliminate barbarians, return to city, and repeat up to this count (e.g. 10 rounds).
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <input
                      type="number"
                      min={1}
                      max={50}
                      value={cfg.combatRounds ?? 1}
                      onChange={(e) => persist({ combatRounds: Math.max(1, Math.min(50, Number(e.target.value) || 1)) })}
                      className="input-dark w-24 px-3 py-1.5 text-xs text-center"
                    />
                    <span className="text-xs text-zinc-400">rounds</span>
                  </div>
                </div>

                <Row
                  q={settingQuery}
                  title="Dispatch all available march queues"
                  desc="Deploy every available march queue in the account simultaneously (all 3, 4, or 5 queues at once)."
                  control={
                    <Toggle
                      on={cfg.dispatchAllMarches !== false}
                      onClick={() => persist({ dispatchAllMarches: cfg.dispatchAllMarches === false })}
                    />
                  }
                />

                <div className="border-t border-[#25252e] px-5 pt-4 pb-1 flex flex-wrap items-center gap-2">
                  <h4 className="text-[11px] font-bold tracking-wider text-zinc-400">HEALING</h4>
                </div>
                <div>
                  <Row
                    q={settingQuery}
                    title="Heal troops"
                    desc="Heal wounded troops on every visit. If resources are low, heals fewer at a time so you don't go broke."
                    control={<Toggle on={cfg.healTroops} onClick={() => persist({ healTroops: !cfg.healTroops })} />}
                  />
                  <div className="flex items-center gap-4 p-4 border-b border-[#25252e] last:border-0">
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-semibold text-white">Heal this many at a time</div>
                      <div className="text-xs text-zinc-500 mt-0.5">
                        Your alliance can give a heal 30 helps, and 30 helps finish a batch of about 2,500 troops instantly, so 2,500 at a time beats one huge heal that takes days. Set a number and the bot asks the alliance for help on each batch. 0 = heal the whole hospital in one go.
                      </div>
                    </div>
                    <input
                      type="number"
                      value={cfg.healBatch}
                      onChange={(e) => persist({ healBatch: Number(e.target.value) })}
                      className="input-dark w-28 px-3 py-1.5 text-xs"
                    />
                  </div>
                </div>
              </div>
            )}
            {cfgCat === "Alliance" && (
              <div>
                <Row q={settingQuery} title="Donate to tech" desc="Donate to alliance tech research."
                  control={<Toggle on={cfg.donateTech} onClick={() => persist({ donateTech: !cfg.donateTech })} />} />
                <Row q={settingQuery} title="Help alliance members" desc="Click the Help All button."
                  control={<Toggle on={cfg.allianceHelp} onClick={() => persist({ allianceHelp: !cfg.allianceHelp })} />} />
                <Row q={settingQuery} title="Gather alliance resource pit" desc="Send a march to the alliance resource pit."
                  control={<Toggle on={cfg.alliancePit} onClick={() => persist({ alliancePit: !cfg.alliancePit })} />} />
                <Row q={settingQuery} title="Claim alliance gifts" desc="Open waiting alliance gift boxes."
                  control={<Toggle on={cfg.allianceGifts} onClick={() => persist({ allianceGifts: !cfg.allianceGifts })} />} />
                <Row q={settingQuery} title="Claim territory resources" desc="Collect accumulated resources from alliance territory forts/sanctuaries."
                  control={<Toggle on={cfg.claimTerritoryRss} onClick={() => persist({ claimTerritoryRss: !cfg.claimTerritoryRss })} />} />
              </div>
            )}
            {cfgCat === "Daily Claims" && (
              <div>
                <Row q={settingQuery} title="Daily VIP Claim" desc="Claim daily VIP points and free chest package."
                  control={<Toggle on={cfg.dailyVipClaim} onClick={() => persist({ dailyVipClaim: !cfg.dailyVipClaim })} />} />
                <Row q={settingQuery} title="City Resource Harvest" desc="Auto-collect production from farms, lumber mills, quarries, and gold mines inside the castle."
                  control={<Toggle on={cfg.cityHarvest} onClick={() => persist({ cityHarvest: !cfg.cityHarvest })} />} />
                <Row q={settingQuery} title="Kingdom Chronicle (الجريدة)" desc="Check and claim completed Chronicle chapters and milestones."
                  control={<Toggle on={cfg.chronicleClaim} onClick={() => persist({ chronicleClaim: !cfg.chronicleClaim })} />} />
                <Row q={settingQuery} title="Daily Quests" desc="Claim completed daily quest rewards."
                  control={<Toggle on={cfg.claimDailyQuests} onClick={() => persist({ claimDailyQuests: !cfg.claimDailyQuests })} />} />
                <Row q={settingQuery} title="Daily Quest Activity Chests" desc="Open activity milestone chests (20, 40, 60, 80, 100 points)."
                  control={<Toggle on={cfg.claimDailyQuestChests} onClick={() => persist({ claimDailyQuestChests: !cfg.claimDailyQuestChests })} />} />
                <Row q={settingQuery} title="Side & Main Quests" desc="Claim rewards from standard building/train/research quests."
                  control={<Toggle on={cfg.claimSideQuests} onClick={() => persist({ claimSideQuests: !cfg.claimSideQuests })} />} />
                <Row q={settingQuery} title="Auto Scout" desc="Run auto-scout in the camp building."
                  control={<Toggle on={cfg.autoScout} onClick={() => persist({ autoScout: !cfg.autoScout })} />} />
              </div>
            )}
            {cfgCat === "Account Progression" && (
              <div className="p-5">
                {bot.tier !== "pro" ? (
                  <div className="p-4 rounded-lg border border-amber-500/30 bg-amber-500/5 text-xs text-zinc-300 flex gap-2">
                    <Lock className="w-4 h-4 text-amber-400 shrink-0" />
                    <span>Account progression is a <b>Pro</b> feature (buildings, research, commanders). Upgrade this bot to unlock it.</span>
                  </div>
                ) : (
                  <p className="text-xs text-zinc-500">Progression automation is enabled for this bot.</p>
                )}
              </div>
            )}
          </div>
        </div>
        </div>
      )}

      {/* UPGRADE */}
      {tab === "upgrade" && (
        <div className="space-y-4">
          <div className="card p-5 flex flex-wrap items-center gap-4">
            <div className="flex-1 min-w-[200px]">
              <h3 className="text-sm font-bold text-white">Upgrade to Pro</h3>
              <p className="text-xs text-zinc-500">Unlock account progression for all {bot.slots} characters on this license.</p>
            </div>
            <button onClick={() => router.push(`/checkout?item=${bot.product}`)} className="btn-primary px-5 py-2.5 text-xs font-bold">Continue to checkout →</button>
          </div>
          <div className="card p-5 flex flex-wrap items-center gap-4">
            <div className="flex-1 min-w-[200px]">
              <h3 className="text-sm font-bold text-white">Add character slots</h3>
              <p className="text-xs text-zinc-500">Licensed for {bot.slots} slots. Add more any time.</p>
            </div>
            <button onClick={() => router.push(`/checkout?item=${bot.product}`)} className="btn-primary px-5 py-2.5 text-xs font-bold">Continue to checkout →</button>
          </div>
        </div>
      )}

      {/* RSS */}
      {tab === "rss" && (
        <div className="space-y-4 max-w-3xl">
          <div className="card p-5 space-y-4">
            <h3 className="text-sm font-bold text-white">Recipient</h3>
            <div>
              <label className="block text-[11px] font-medium text-zinc-500 mb-1">Governor ID</label>
              <input placeholder="e.g. 165584533" className="input-dark w-full px-3 py-2 text-xs" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-[11px] font-medium text-zinc-500 mb-1">Tile X</label>
                <input placeholder="X" className="input-dark w-full px-3 py-2 text-xs" />
              </div>
              <div>
                <label className="block text-[11px] font-medium text-zinc-500 mb-1">Tile Y</label>
                <input placeholder="Y" className="input-dark w-full px-3 py-2 text-xs" />
              </div>
            </div>
          </div>
          <div className="card p-5">
            <h3 className="text-sm font-bold text-white">Farms to send from</h3>
            <p className="text-xs text-zinc-500 mt-1">No farms linked yet — add accounts first.</p>
          </div>
          <button disabled className="btn-primary px-6 py-2.5 text-sm opacity-50 cursor-not-allowed">Start Transfer</button>
        </div>
      )}

      {/* Add account modal */}
      {showAdd && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70" onClick={() => { setShowAdd(false); closeCaptchaPopup(); setCaptchaCreds(null); }}>
          <div className="card p-6 w-full max-w-md space-y-4" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-sm font-bold text-white">Add a Rise of Kingdoms account</h3>
            <p className="text-xs text-zinc-500">Sign in with the Lilith account of your farms (Lilith accounts only).</p>
            <div>
              <label className="block text-[11px] font-medium text-zinc-500 mb-1">Email</label>
              <input value={newEmail} onChange={(e) => setNewEmail(e.target.value)} placeholder="farm@example.com" className="input-dark w-full px-3 py-2 text-sm" />
            </div>
            <div>
              <label className="block text-[11px] font-medium text-zinc-500 mb-1">Password</label>
              <input type="password" value={newPass} onChange={(e) => setNewPass(e.target.value)} placeholder="••••••••" className="input-dark w-full px-3 py-2 text-sm" />
              <p className="text-[10px] text-zinc-600 mt-1">Sent once to the backend server for login. Never stored in website files.</p>
            </div>
            {syncPhase !== "idle" && (
              <div className={`p-3 rounded-lg border text-xs ${
                syncPhase === "done" || syncPhase === "added" ? "bg-[#10B981]/10 border-[#10B981]/30 text-zinc-200"
                : syncPhase === "error" ? "bg-red-500/10 border-red-500/30 text-zinc-200"
                : "bg-[#5865F2]/10 border-[#5865F2]/30 text-zinc-200"
              }`}>
                <p className="font-semibold">
                  {syncPhase === "busy" ? "Syncing…" : syncPhase === "done" ? "Synced — pick characters" : syncPhase === "added" ? "Linked" : syncPhase === "captcha" ? "Verification — auto-continuing once solved" : "Failed"}
                </p>
                <p className="text-zinc-400 mt-0.5">{syncMsg}</p>
                {syncPhase === "done" && syncChars.length > 0 && (
                  <ul className="mt-2 space-y-1.5">
                    {syncChars.map((c) => {
                      const on = picked.includes(c.role_id);
                      return (
                        <li key={c.role_id}>
                          <button onClick={() => togglePick(c.role_id)} className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg border text-left transition-colors ${on ? "border-[#10B981]/50 bg-[#10B981]/5" : "border-[#25252e] hover:border-[#35353f]"}`}>
                            <span className={`w-4 h-4 rounded border flex items-center justify-center shrink-0 ${on ? "bg-[#10B981] border-[#10B981]" : "border-zinc-600"}`}>
                              {on && <Check className="w-3 h-3 text-white" />}
                            </span>
                            <GovAvatar name={c.name} src={c.avatar_url || ""} />
                            <span className="text-zinc-200 font-medium">{c.name}</span>
                            <span className="text-zinc-500 ml-auto">{c.city_level ? `CH ${c.city_level} · ` : ""}Kingdom #{c.kingdom_id}</span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                )}
                {syncPhase === "captcha" && (
                  <div className="mt-2 space-y-2">
                    {popupBlocked ? (
                      captchaUrl && (
                        <button onClick={() => openCaptchaPopup(captchaUrl)} className="btn-primary inline-block px-4 py-2 text-xs font-bold">
                          Open verification window →
                        </button>
                      )
                    ) : (
                      <p className="text-[11px] text-zinc-400">
                        A small verification window is open — solve the slider there.
                      </p>
                    )}
                    <div className="flex flex-wrap gap-2">
                      {captchaUrl && (
                        <button onClick={() => openCaptchaPopup(captchaUrl)} className="text-[11px] text-cyan-400 hover:underline">
                          Reopen window
                        </button>
                      )}
                      <button onClick={checkCaptchaNow} className="text-[11px] text-emerald-400 hover:underline font-semibold">
                        I solved it — continue
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}
            <div className="flex gap-2">
              {syncPhase === "added" ? (
                <button onClick={() => { setShowAdd(false); setNewEmail(""); }} className="btn-primary flex-1 py-2.5 text-sm">Done</button>
              ) : syncPhase === "done" ? (
                <button onClick={confirmPick} disabled={picked.length === 0} className="btn-primary flex-1 py-2.5 text-sm disabled:opacity-50">
                  Add {picked.length} character{picked.length === 1 ? "" : "s"}
                </button>
              ) : (
                <button onClick={submitAccount} disabled={!newEmail.trim() || !newPass || syncPhase === "busy"} className="btn-primary flex-1 py-2.5 text-sm disabled:opacity-50">
                  {syncPhase === "busy" ? "Syncing…" : "Continue"}
                </button>
              )}
              <button onClick={() => { setShowAdd(false); closeCaptchaPopup(); setCaptchaCreds(null); setNewPass(""); }} className="btn-ghost px-5 py-2.5 text-sm">Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
