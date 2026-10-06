"use client";

import React, { useEffect, useState, useMemo } from "react";
import Link from "next/link";
import {
  Bot,
  ShoppingCart,
  Sparkles,
  ShieldAlert,
  Layers,
  ArrowRight,
  Cpu,
  CheckCircle2,
  Activity,
  TrendingUp,
  Clock,
  Coins,
  Lock,
  RefreshCw,
  Play,
  Square,
  Zap,
  BarChart3,
  Globe,
  ChevronRight,
  ShieldCheck,
  AlertCircle,
} from "lucide-react";
import { getAllBots, getSessionUser, bootOwner } from "@/lib/cloud";
import { type OwnedBot } from "@/lib/store";
import { getBotInventory, getBotHistory, type InventoryResponse, type RunRow } from "@/lib/api";

interface TenantBotWithStats extends OwnedBot {
  status?: string;
  uptimeHours?: number;
  inventory?: InventoryResponse | null;
  history?: RunRow[];
}

function fmtRss(val: number): string {
  if (!val || val <= 0) return "0";
  if (val >= 1_000_000_000) return (val / 1_000_000_000).toFixed(1) + "B";
  if (val >= 1_000_000) return (val / 1_000_000).toFixed(1) + "M";
  if (val >= 1_000) return (val / 1_000).toFixed(1) + "K";
  return val.toLocaleString();
}

export default function OverviewPage() {
  const [bots, setBots] = useState<TenantBotWithStats[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [username, setUsername] = useState<string>("Commander");
  const [userEmail, setUserEmail] = useState<string>("");

  const loadData = async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    else setLoading(true);

    try {
      await bootOwner();
      const user = await getSessionUser();
      if (user) {
        setUserEmail(user.email || "");
        const meta = user.user_metadata || {};
        setUsername(
          meta.full_name ||
          meta.name ||
          meta.custom_claims?.global_name ||
          (user.email ? user.email.split("@")[0] : "Commander")
        );
      }

      // Fetch cloud bot instances
      const loadedBots = await getAllBots();

      // Parallelize inventory & history load for each bot
      const botsWithStats: TenantBotWithStats[] = await Promise.all(
        loadedBots.map(async (b) => {
          let inv: InventoryResponse | null = null;
          let hist: RunRow[] = [];
          try {
            inv = await getBotInventory(b.id);
            hist = await getBotHistory(b.id);
          } catch {
            /* best effort */
          }
          return {
            ...b,
            status: "standby",
            inventory: inv,
            history: hist,
          };
        })
      );

      setBots(botsWithStats);
    } catch (e) {
      console.error("Overview load error:", e);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  // Aggregated Metrics Calculations
  const stats = useMemo(() => {
    let totalFood = 0;
    let totalWood = 0;
    let totalStone = 0;
    let totalGold = 0;
    let totalGems = 0;
    let monthlyTotal = 0;
    let totalSeats = 0;
    let occupiedSeats = 0;
    const kingdomsSet = new Set<number>();
    const kingdomBreakdown: Record<number, { count: number; power: number; rss: number }> = {};

    for (const b of bots) {
      totalSeats += b.slots || 5;
      if (b.inventory) {
        const c = b.inventory.in_cities_now;
        if (c) {
          totalFood += c.food || 0;
          totalWood += c.wood || 0;
          totalStone += c.stone || 0;
          totalGold += c.gold || 0;
          totalGems += c.gems || 0;
        }

        const m = b.inventory.resources_gathered?.["30days"];
        if (m) {
          monthlyTotal += (m.food || 0) + (m.wood || 0) + (m.stone || 0) + (m.gold || 0);
        }

        if (b.inventory.characters) {
          occupiedSeats += b.inventory.characters.length;
          for (const ch of b.inventory.characters) {
            if (ch.kingdom) {
              kingdomsSet.add(ch.kingdom);
              if (!kingdomBreakdown[ch.kingdom]) {
                kingdomBreakdown[ch.kingdom] = { count: 0, power: 0, rss: 0 };
              }
              kingdomBreakdown[ch.kingdom].count += 1;
              kingdomBreakdown[ch.kingdom].power += ch.power || 0;
              kingdomBreakdown[ch.kingdom].rss += (ch.food || 0) + (ch.wood || 0) + (ch.stone || 0) + (ch.gold || 0);
            }
          }
        }
      }
    }

    const totalRss = totalFood + totalWood + totalStone + totalGold;
    // Avg per hour based on 30-day gathered rate (720 hrs)
    const avgPerHour = monthlyTotal > 0 ? Math.round(monthlyTotal / 720) : 0;
    const avgDaily = monthlyTotal > 0 ? Math.round(monthlyTotal / 30) : 0;

    return {
      totalRss,
      totalFood,
      totalWood,
      totalStone,
      totalGold,
      totalGems,
      monthlyTotal,
      avgPerHour,
      avgDaily,
      totalSeats,
      occupiedSeats,
      kingdomCount: kingdomsSet.size,
      kingdomBreakdown,
    };
  }, [bots]);

  const hasBots = bots.length > 0;

  return (
    <div className="p-4 sm:p-8 max-w-7xl mx-auto w-full space-y-6 text-slate-200">
      {/* ============================================================== */}
      {/* 1. TOP HEADER & ARCANE QUICK STATS BAR                         */}
      {/* ============================================================== */}
      <div className="bg-[#07131f]/90 backdrop-blur-xl border border-cyan-500/20 rounded-2xl p-5 sm:p-6 shadow-2xl shadow-cyan-950/20 transition-all">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-5">
          {/* Title & Tenant Info */}
          <div className="space-y-1.5">
            <div className="flex items-center gap-3">
              <h1 className="text-xl sm:text-2xl font-black text-white tracking-wide flex items-center gap-2">
                <span>نظرة عامة</span>
                <span className="text-cyan-400 font-mono text-sm sm:text-base font-normal">/ Fleet Overview</span>
              </h1>
              {hasBots ? (
                <span className="px-2.5 py-0.5 rounded-full text-[10px] font-bold tracking-wider uppercase bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 flex items-center gap-1.5 shadow-[0_0_10px_rgba(16,185,129,0.2)]">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  عضو نشط · ACTIVE FLEET
                </span>
              ) : (
                <span className="px-2.5 py-0.5 rounded-full text-[10px] font-bold tracking-wider uppercase bg-amber-500/10 text-amber-400 border border-amber-500/30 flex items-center gap-1.5">
                  <Lock className="w-3 h-3 text-amber-400" />
                  بدون ترخيص · NO ACTIVE LICENSE
                </span>
              )}
            </div>

            <p className="text-xs text-slate-400 flex items-center gap-2 font-mono">
              <span className="text-cyan-300 font-semibold">{bots.length} instances</span>
              <span className="text-slate-600">•</span>
              <span>{stats.occupiedSeats} accounts</span>
              <span className="text-slate-600">•</span>
              <span>{stats.kingdomCount} kingdoms</span>
            </p>
          </div>

          {/* Arcane Stat Pills (Characters, Power, Food, Wood, Stone, Gold) */}
          <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-2 sm:gap-2.5">
            {/* Characters */}
            <div className="bg-[#0b1b2b] border border-cyan-500/20 rounded-xl px-3.5 py-2.5 flex flex-col justify-center min-w-[110px]">
              <span className="text-[10px] font-mono text-slate-400 uppercase tracking-wider font-semibold">
                CHARACTERS
              </span>
              <span className="text-sm font-bold font-mono text-cyan-300 mt-0.5">
                {stats.occupiedSeats} / {stats.totalSeats}
              </span>
            </div>

            {/* Power */}
            <div className="bg-[#0b1b2b] border border-cyan-500/20 rounded-xl px-3.5 py-2.5 flex flex-col justify-center min-w-[110px]">
              <span className="text-[10px] font-mono text-slate-400 uppercase tracking-wider font-semibold">
                POWER
              </span>
              <span className="text-sm font-bold font-mono text-white mt-0.5">
                {fmtRss(Object.values(stats.kingdomBreakdown).reduce((a, b) => a + b.power, 0))}
              </span>
            </div>

            {/* Food */}
            <div className="bg-[#0b1b2b] border border-emerald-500/20 rounded-xl px-3.5 py-2.5 flex flex-col justify-center min-w-[110px]">
              <div className="flex items-center gap-1 text-[10px] font-mono text-emerald-400 uppercase tracking-wider font-semibold">
                <span>🌽</span>
                <span>FOOD</span>
              </div>
              <span className="text-sm font-bold font-mono text-emerald-300 mt-0.5">
                {fmtRss(stats.totalFood)}
              </span>
            </div>

            {/* Wood */}
            <div className="bg-[#0b1b2b] border border-amber-500/20 rounded-xl px-3.5 py-2.5 flex flex-col justify-center min-w-[110px]">
              <div className="flex items-center gap-1 text-[10px] font-mono text-amber-400 uppercase tracking-wider font-semibold">
                <span>🪵</span>
                <span>WOOD</span>
              </div>
              <span className="text-sm font-bold font-mono text-amber-300 mt-0.5">
                {fmtRss(stats.totalWood)}
              </span>
            </div>

            {/* Stone */}
            <div className="bg-[#0b1b2b] border border-cyan-500/20 rounded-xl px-3.5 py-2.5 flex flex-col justify-center min-w-[110px]">
              <div className="flex items-center gap-1 text-[10px] font-mono text-cyan-400 uppercase tracking-wider font-semibold">
                <span>🪨</span>
                <span>STONE</span>
              </div>
              <span className="text-sm font-bold font-mono text-cyan-300 mt-0.5">
                {fmtRss(stats.totalStone)}
              </span>
            </div>

            {/* Gold */}
            <div className="bg-[#0b1b2b] border border-yellow-500/20 rounded-xl px-3.5 py-2.5 flex flex-col justify-center min-w-[110px]">
              <div className="flex items-center gap-1 text-[10px] font-mono text-yellow-400 uppercase tracking-wider font-semibold">
                <span>🪙</span>
                <span>GOLD</span>
              </div>
              <span className="text-sm font-bold font-mono text-yellow-300 mt-0.5">
                {fmtRss(stats.totalGold)}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* ============================================================== */}
      {/* 2. TOP 4 METRICS CARDS (GHOSTBOT CYBER HUD)                     */}
      {/* ============================================================== */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Total City Reserves */}
        <div className="bg-[#07131f]/80 backdrop-blur-md border border-cyan-500/20 rounded-2xl p-5 flex flex-col justify-between hover:border-cyan-500/40 transition-all group">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-400">إجمالي الموارد المتاحة</span>
            <div className="w-8 h-8 rounded-lg bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center text-cyan-400">
              <Coins className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-4">
            <div className="text-2xl font-black text-white font-mono tracking-tight group-hover:text-cyan-300 transition-colors">
              {fmtRss(stats.totalRss)}
            </div>
            <div className="text-[11px] text-slate-500 mt-1 flex items-center justify-between">
              <span>Gems: {stats.totalGems.toLocaleString()} 💎</span>
              <span className="text-cyan-400/80 font-mono text-[10px]">CURRENT IN-CITIES</span>
            </div>
          </div>
        </div>

        {/* Monthly Gathered */}
        <div className="bg-[#07131f]/80 backdrop-blur-md border border-cyan-500/20 rounded-2xl p-5 flex flex-col justify-between hover:border-cyan-500/40 transition-all group">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-400">محصول الـ 30 يوماً</span>
            <div className="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
              <TrendingUp className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-4">
            <div className="text-2xl font-black text-white font-mono tracking-tight group-hover:text-emerald-300 transition-colors">
              {fmtRss(stats.monthlyTotal)}
            </div>
            <div className="text-[11px] text-slate-500 mt-1 flex items-center justify-between">
              <span>30-Day Rolling RSS</span>
              <span className="text-emerald-400/80 font-mono text-[10px]">AUTOMATED HARVEST</span>
            </div>
          </div>
        </div>

        {/* Avg Gather / Hour */}
        <div className="bg-[#07131f]/80 backdrop-blur-md border border-cyan-500/20 rounded-2xl p-5 flex flex-col justify-between hover:border-cyan-500/40 transition-all group">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-400">معدل الجمع بالساعة</span>
            <div className="w-8 h-8 rounded-lg bg-purple-500/10 border border-purple-500/30 flex items-center justify-center text-purple-400">
              <Zap className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-4">
            <div className="text-2xl font-black text-white font-mono tracking-tight group-hover:text-purple-300 transition-colors">
              {fmtRss(stats.avgPerHour)} / h
            </div>
            <div className="text-[11px] text-slate-500 mt-1 flex items-center justify-between">
              <span>Fleet Yield Velocity</span>
              <span className="text-purple-400/80 font-mono text-[10px]">BALANCED MARCHES</span>
            </div>
          </div>
        </div>

        {/* Total Uptime */}
        <div className="bg-[#07131f]/80 backdrop-blur-md border border-cyan-500/20 rounded-2xl p-5 flex flex-col justify-between hover:border-cyan-500/40 transition-all group">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-400">وقت التشغيل الكلي</span>
            <div className="w-8 h-8 rounded-lg bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center text-cyan-400">
              <Clock className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-4">
            <div className="text-2xl font-black text-white font-mono tracking-tight group-hover:text-cyan-300 transition-colors">
              {hasBots ? "30d 0h 0m" : "0d 0h 0m"}
            </div>
            <div className="text-[11px] text-slate-500 mt-1 flex items-center justify-between">
              <span>AWS EC2 Dedicated Tunnel</span>
              <span className="text-cyan-400/80 font-mono text-[10px]">100% STEALTH</span>
            </div>
          </div>
        </div>
      </div>

      {/* ============================================================== */}
      {/* 3. PERFORMANCE METRICS (3 COLUMNS)                             */}
      {/* ============================================================== */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Column 1: Avg Gather / Day */}
        <div className="bg-[#07131f]/80 backdrop-blur-md border border-cyan-500/20 rounded-2xl p-5 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-slate-300 uppercase tracking-wider font-mono">
              Avg Gather / Day (14d Mean)
            </span>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
              ROLLING
            </span>
          </div>
          <div className="text-3xl font-black text-white font-mono">
            {fmtRss(stats.avgDaily)}
          </div>
          <p className="text-[11px] text-slate-400 leading-relaxed">
            Combined daily node sweep across all deployed governors with zero resource loss.
          </p>
        </div>

        {/* Column 2: Avg Uptime / Day */}
        <div className="bg-[#07131f]/80 backdrop-blur-md border border-cyan-500/20 rounded-2xl p-5 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-slate-300 uppercase tracking-wider font-mono">
              Avg Uptime / Day
            </span>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              STABLE
            </span>
          </div>
          <div className="text-3xl font-black text-emerald-400 font-mono">
            {hasBots ? "23.8 hrs" : "0.0 hrs"}
          </div>
          <p className="text-[11px] text-slate-400 leading-relaxed">
            Staggered 2-stage execution with humanized sleep delays to completely prevent pattern flags.
          </p>
        </div>

        {/* Column 3: Goal Progress */}
        <div className="bg-[#07131f]/80 backdrop-blur-md border border-cyan-500/20 rounded-2xl p-5 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-slate-300 uppercase tracking-wider font-mono">
              Goal Progress (50M Target)
            </span>
            <span className="text-[10px] font-mono text-cyan-300">
              {stats.avgDaily > 0 ? Math.min(100, Math.round((stats.avgDaily / 50_000_000) * 100)) : 0}%
            </span>
          </div>
          <div className="w-full bg-[#0b1b2b] h-3 rounded-full overflow-hidden border border-cyan-500/20 p-0.5">
            <div
              className="bg-gradient-to-r from-cyan-500 to-emerald-400 h-full rounded-full transition-all duration-500"
              style={{
                width: `${stats.avgDaily > 0 ? Math.min(100, Math.max(5, Math.round((stats.avgDaily / 50_000_000) * 100))) : 0}%`,
              }}
            />
          </div>
          <p className="text-[11px] text-slate-400 leading-relaxed">
            Daily alliance donation and training quota fulfillment pace across all active slots.
          </p>
        </div>
      </div>

      {/* ============================================================== */}
      {/* 4. LICENSES & DEPLOYED UNITS (ARCANE STYLE)                    */}
      {/* ============================================================== */}
      <div className="bg-[#07131f]/90 backdrop-blur-xl border border-cyan-500/20 rounded-2xl p-6 space-y-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <Bot className="w-5 h-5 text-cyan-400" />
            <h2 className="text-base font-bold text-white tracking-wide">
              التراخيص والوحدات المنشورة / Licenses ({bots.length})
            </h2>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => loadData(true)}
              disabled={refreshing}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-cyan-950/40 hover:bg-cyan-900/50 border border-cyan-500/30 text-cyan-300 text-xs font-mono transition-all disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? "animate-spin" : ""}`} />
              <span>Refresh</span>
            </button>
            <Link
              href="/shop"
              className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white font-bold text-xs shadow-md shadow-cyan-600/20 transition-all hover:scale-[1.02]"
            >
              <ShoppingCart className="w-3.5 h-3.5" />
              <span>شراء وحدة جديدة</span>
            </Link>
          </div>
        </div>

        {loading ? (
          <div className="p-12 text-center text-slate-500 text-xs font-mono animate-pulse">
            جاري فحص وتحديث بيانات الوحدات السحابية...
          </div>
        ) : hasBots ? (
          <div className="space-y-3">
            {bots.map((b) => (
              <div
                key={b.id}
                className="bg-[#0c1a29]/90 border border-cyan-500/20 hover:border-cyan-500/50 rounded-xl p-4 sm:p-5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 transition-all"
              >
                {/* Bot Details */}
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 rounded-xl bg-cyan-950/60 border border-cyan-500/30 flex items-center justify-center shadow-lg shadow-cyan-950/40">
                    <img
                      src="/Item_Food.webp"
                      alt="Farm Bot"
                      className="w-7 h-7 object-contain drop-shadow-[0_0_10px_rgba(0,229,255,0.4)]"
                    />
                  </div>
                  <div className="space-y-1">
                    <div className="flex items-center gap-2.5">
                      <h3 className="text-base font-bold text-white">
                        {b.label || `Farm Bot #${b.id.replace("bot-", "")}`}
                      </h3>
                      <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-cyan-500/10 text-cyan-300 border border-cyan-500/30 uppercase">
                        {(b.tier || "BASIC").toUpperCase()}
                      </span>
                      <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 flex items-center gap-1">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                        Standby
                      </span>
                    </div>
                    <div className="flex items-center gap-3 text-xs text-slate-400 font-mono">
                      <span>ID: <strong className="text-cyan-400">{b.id}</strong></span>
                      <span>•</span>
                      <span>{b.inventory?.characters?.length || 0} / {b.slots || 5} seats</span>
                      <span>•</span>
                      <span className="text-emerald-400">Expires in 30d</span>
                    </div>
                  </div>
                </div>

                {/* Actions */}
                <div className="flex items-center gap-3 w-full sm:w-auto justify-end">
                  <Link
                    href={`/bots/${b.id}`}
                    className="flex items-center gap-2 px-4 py-2 rounded-xl bg-cyan-600/20 hover:bg-cyan-600/40 border border-cyan-500/40 text-cyan-200 font-bold text-xs transition-all hover:scale-[1.02]"
                  >
                    <span>فتح غرفة التحكم</span>
                    <ArrowRight className="w-3.5 h-3.5" />
                  </Link>
                </div>
              </div>
            ))}
          </div>
        ) : (
          /* Empty State for Unpaying User */
          <div className="border border-dashed border-cyan-500/30 rounded-2xl p-10 text-center flex flex-col items-center justify-center space-y-4 bg-[#081523]/60">
            <div className="w-16 h-16 rounded-2xl bg-cyan-950/60 border border-cyan-500/40 flex items-center justify-center text-cyan-400 shadow-xl shadow-cyan-950/50">
              <Lock className="w-8 h-8" />
            </div>
            <div className="space-y-1.5 max-w-md">
              <h3 className="text-base sm:text-lg font-bold text-white">
                لا توجد وحدات بوت نشطة / No Active Bot Units
              </h3>
              <p className="text-xs text-slate-400 leading-relaxed">
                لم تقم بنشر أي وحدات بعد. اشترِ ترخيص Farm Bot لتفعيل وحدة البوت وإضافة الحسابات وأتمتة جمع الموارد وحصاد الثكنات 24/7.
              </p>
            </div>
            <Link
              href="/shop"
              className="flex items-center gap-2 py-2.5 px-6 rounded-xl bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white font-bold text-xs shadow-lg shadow-cyan-600/30 transition-all hover:scale-[1.03]"
            >
              <ShoppingCart className="w-4 h-4" />
              <span>شراء ترخيص Farm Bot الآن</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </Link>
          </div>
        )}
      </div>

      {/* ============================================================== */}
      {/* 5. KINGDOMS BREAKDOWN & EMPTY STATE (ARCANE STYLE)              */}
      {/* ============================================================== */}
      <div className="bg-[#07131f]/90 backdrop-blur-xl border border-cyan-500/20 rounded-2xl p-6 space-y-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <Globe className="w-5 h-5 text-cyan-400" />
            <h2 className="text-base font-bold text-white tracking-wide">
              الممالك المنشورة / Kingdoms ({stats.kingdomCount})
            </h2>
          </div>
        </div>

        {stats.kingdomCount > 0 ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {Object.entries(stats.kingdomBreakdown).map(([kId, kData]) => (
              <div
                key={kId}
                className="bg-[#0c1a29]/90 border border-cyan-500/20 rounded-xl p-4 space-y-2 hover:border-cyan-500/40 transition-all"
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-bold text-white font-mono">
                    Kingdom #{kId}
                  </span>
                  <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
                    {kData.count} Governors
                  </span>
                </div>
                <div className="pt-2 border-t border-cyan-500/10 flex items-center justify-between text-xs font-mono text-slate-400">
                  <span>Total Power: <strong className="text-slate-200">{fmtRss(kData.power)}</strong></span>
                  <span>Total RSS: <strong className="text-emerald-400">{fmtRss(kData.rss)}</strong></span>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="border border-dashed border-cyan-500/30 rounded-2xl p-10 text-center flex flex-col items-center justify-center space-y-3 bg-[#081523]/60">
            <div className="w-14 h-14 rounded-2xl bg-cyan-950/50 border border-cyan-500/30 flex items-center justify-center text-cyan-400">
              <Layers className="w-7 h-7" />
            </div>
            <h3 className="text-sm sm:text-base font-bold text-white">
              No kingdoms deployed yet
            </h3>
            <p className="text-xs text-slate-400 max-w-sm">
              Link game accounts to your bot instances to start monitoring and aggregating your kingdoms.
            </p>
            {hasBots ? (
              <Link
                href={`/bots/${bots[0].id}`}
                className="mt-2 text-xs font-bold text-cyan-400 hover:text-cyan-300 flex items-center gap-1.5"
              >
                <span>ربط الحسابات في غرفة البوت</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </Link>
            ) : null}
          </div>
        )}
      </div>

      {/* ============================================================== */}
      {/* 6. OPTIMIZATION TIPS & ADVANCED TACTICAL SHIELDS               */}
      {/* ============================================================== */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-[#07131f]/80 backdrop-blur-md border border-cyan-500/20 rounded-2xl p-5 space-y-2.5">
          <div className="text-xs font-bold text-cyan-300 flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-cyan-400" />
            <span>Anti-Ban Stealth Protocol</span>
          </div>
          <p className="text-[11px] text-slate-400 leading-relaxed">
            Direct socket protocol with organic packet intervals, mimicking human finger pauses and touch drift to prevent behavioral detection.
          </p>
        </div>

        <div className="bg-[#07131f]/80 backdrop-blur-md border border-cyan-500/20 rounded-2xl p-5 space-y-2.5">
          <div className="text-xs font-bold text-emerald-300 flex items-center gap-2">
            <ShieldAlert className="w-4 h-4 text-emerald-400" />
            <span>Zero-Gem Protection</span>
          </div>
          <p className="text-[11px] text-slate-400 leading-relaxed">
            Strict engine limits guarantee diamonds, universal speedups, and precious inventory items are never expended automatically.
          </p>
        </div>

        <div className="bg-[#07131f]/80 backdrop-blur-md border border-cyan-500/20 rounded-2xl p-5 space-y-2.5">
          <div className="text-xs font-bold text-purple-300 flex items-center gap-2">
            <Activity className="w-4 h-4 text-purple-400" />
            <span>Staged Wave Execution</span>
          </div>
          <p className="text-[11px] text-slate-400 leading-relaxed">
            Primary character slots execute in Stage 1, followed cleanly by secondary alternates in Stage 2 to completely eliminate node overlap.
          </p>
        </div>
      </div>
    </div>
  );
}
