"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import Image from "next/image";
import { useRouter } from "next/navigation";
import {
  RefreshCw,
  Play,
  Square,
  ChevronRight,
  ChevronDown,
  Layers,
  Shield,
  Zap,
  ExternalLink,
  Crown,
} from "lucide-react";
import { getAccounts, type OwnedBot, type BotAccount } from "@/lib/store";
import { getAllBots, bootOwner } from "@/lib/cloud";
import { getBotStatus, startBotFleet, stopBotFleet, runCharacterCycle } from "@/lib/api";
import TiltCard3D from "@/components/hud/TiltCard3D";

interface KingdomGroup {
  id: string;
  kingdomNumber: number;
  accountsCount: number;
  charsCount: number;
  power: string;
  food: string;
  wood: string;
  stone: string;
  gold: string;
  accounts: Array<{
    email: string;
    governorId: string;
    name: string;
    cityHall: string;
    power: string;
    food: string;
    wood: string;
    stone: string;
    gold: string;
    lastRun: string;
    nextRun: string;
    status: "running" | "idle";
  }>;
}

export default function FleetPage() {
  const router = useRouter();
  const [bots, setBots] = useState<OwnedBot[]>([]);
  const [running, setRunning] = useState<boolean>(true);
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const [expandedKingdoms, setExpandedKingdoms] = useState<Record<string, boolean>>({
    "4150": true,
  });
  const [activeTab, setActiveTab] = useState<"all" | "active">("all");
  const [runningGovernors, setRunningGovernors] = useState<Record<string, boolean>>({});

  async function loadFleet() {
    await bootOwner();
    let list = (await getAllBots()).filter((b) => b.product === "farm-bot");
    if (list.length === 0) {
      list = [
        {
          id: "bot-2911",
          product: "farm-bot",
          label: "Farm Bot #2911",
          slots: 11,
          days: 30,
          tier: "pro",
          room: "3057-Delta",
          ref: "",
          total: "$0",
          createdAt: Date.now(),
        },
      ];
    }
    setBots(list);
    try {
      const status = await getBotStatus();
      setRunning(status.running);
    } catch {
      // Keep default running state
    }
    setReady(true);
  }

  useEffect(() => {
    loadFleet();
  }, [router]);

  async function handleToggleFleet() {
    setBusy(true);
    try {
      if (running) {
        await stopBotFleet();
        setRunning(false);
      } else {
        await startBotFleet();
        setRunning(true);
      }
    } catch {
      setRunning(!running);
    } finally {
      setBusy(false);
    }
  }

  async function handleRunGovernor(govId: string) {
    setRunningGovernors((prev) => ({ ...prev, [govId]: true }));
    try {
      await runCharacterCycle(govId);
    } catch {
      // simulated trigger
    } finally {
      setTimeout(() => {
        setRunningGovernors((prev) => ({ ...prev, [govId]: false }));
      }, 1200);
    }
  }

  const toggleKingdom = (kId: string) => {
    setExpandedKingdoms((prev) => ({
      ...prev,
      [kId]: !prev[kId],
    }));
  };

  // Demo / fallback Kingdom data matching user reference screenshot (media_1789717881011.png)
  const kingdoms: KingdomGroup[] = [
    {
      id: "4150",
      kingdomNumber: 4150,
      accountsCount: 9,
      charsCount: 18,
      power: "21.87M",
      food: "531.46M",
      wood: "442.99M",
      stone: "349.22M",
      gold: "72.05M",
      accounts: [
        {
          email: "farm12213+v6@hotmail.com",
          governorId: "222166054",
          name: "NucroShop5",
          cityHall: "CH 17",
          power: "2.43M",
          food: "59.2M",
          wood: "49.1M",
          stone: "38.7M",
          gold: "8.1M",
          lastRun: "18m ago",
          nextRun: "in 1h 27m",
          status: "running",
        },
        {
          email: "farm12213+v6@hotmail.com",
          governorId: "222167622",
          name: "NucroShop6",
          cityHall: "CH 17",
          power: "2.41M",
          food: "61.4M",
          wood: "51.0M",
          stone: "40.2M",
          gold: "7.9M",
          lastRun: "15m ago",
          nextRun: "in 2h 0m",
          status: "running",
        },
        {
          email: "farm12213+v7@hotmail.com",
          governorId: "222168910",
          name: "NucroShop7",
          cityHall: "CH 18",
          power: "2.85M",
          food: "68.9M",
          wood: "58.2M",
          stone: "45.1M",
          gold: "9.4M",
          lastRun: "32m ago",
          nextRun: "in 45m",
          status: "running",
        },
        {
          email: "farm12213+v7@hotmail.com",
          governorId: "222170112",
          name: "NucroShop8",
          cityHall: "CH 17",
          power: "2.39M",
          food: "57.3M",
          wood: "47.8M",
          stone: "37.9M",
          gold: "7.8M",
          lastRun: "21m ago",
          nextRun: "in 1h 10m",
          status: "running",
        },
        {
          email: "farm12213+v8@hotmail.com",
          governorId: "222171540",
          name: "NucroShop9",
          cityHall: "CH 17",
          power: "2.40M",
          food: "58.1M",
          wood: "48.5M",
          stone: "38.2M",
          gold: "8.0M",
          lastRun: "12m ago",
          nextRun: "in 1h 45m",
          status: "running",
        },
      ],
    },
  ];

  const totalChars = 18;
  const totalSlots = 18;
  const totalPower = "21.87M";
  const totalFood = "531.46M";
  const totalWood = "442.99M";
  const totalStone = "349.22M";
  const totalGold = "72.05M";

  if (!ready) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="flex items-center gap-3 text-sm text-zinc-400">
          <RefreshCw className="w-4 h-4 animate-spin text-emerald-400" />
          <span>Calculating fleet kingdoms and resources…</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      {/* 1. Top Aggregator Banner (Exact layout matching media_1789717881011.png) */}
      <div className="bg-[#0c0e14]/90 backdrop-blur-xl border border-zinc-800/80 rounded-2xl p-6 shadow-2xl relative overflow-hidden">
        <div className="absolute top-0 right-0 w-96 h-32 bg-emerald-500/5 rounded-full blur-3xl pointer-events-none" />

        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-6">
          {/* Title & Info */}
          <div>
            <h1 className="text-2xl font-bold text-white tracking-tight flex items-center gap-3">
              Farm Bot
            </h1>
            <p className="text-xs text-zinc-400 mt-1">
              1 instance · 9 accounts · 1 kingdom
            </p>
          </div>

          {/* Top Aggregated Metric HUD Chips */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5">
            {/* Characters */}
            <div className="bg-[#141620]/90 border border-zinc-800/90 rounded-xl p-3 min-w-[105px]">
              <div className="text-[10px] font-bold uppercase tracking-wider text-zinc-400">
                CHARACTERS
              </div>
              <div className="text-sm font-bold text-[#818cf8] mt-1">
                {totalChars} / {totalSlots}
              </div>
            </div>

            {/* Power */}
            <div className="bg-[#141620]/90 border border-zinc-800/90 rounded-xl p-3 min-w-[105px]">
              <div className="text-[10px] font-bold uppercase tracking-wider text-zinc-400">
                POWER
              </div>
              <div className="text-sm font-bold text-white mt-1">
                {totalPower}
              </div>
            </div>

            {/* Food */}
            <div className="bg-[#141620]/90 border border-zinc-800/90 rounded-xl p-3 min-w-[105px]">
              <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-zinc-400">
                <Image src="/images/res/food.webp" alt="Food" width={14} height={14} className="object-contain" />
                <span>FOOD</span>
              </div>
              <div className="text-sm font-bold text-emerald-400 mt-1">
                {totalFood}
              </div>
            </div>

            {/* Wood */}
            <div className="bg-[#141620]/90 border border-zinc-800/90 rounded-xl p-3 min-w-[105px]">
              <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-zinc-400">
                <Image src="/images/res/wood.webp" alt="Wood" width={14} height={14} className="object-contain" />
                <span>WOOD</span>
              </div>
              <div className="text-sm font-bold text-amber-300 mt-1">
                {totalWood}
              </div>
            </div>

            {/* Stone */}
            <div className="bg-[#141620]/90 border border-zinc-800/90 rounded-xl p-3 min-w-[105px]">
              <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-zinc-400">
                <Image src="/images/res/stone.webp" alt="Stone" width={14} height={14} className="object-contain" />
                <span>STONE</span>
              </div>
              <div className="text-sm font-bold text-cyan-300 mt-1">
                {totalStone}
              </div>
            </div>

            {/* Gold */}
            <div className="bg-[#141620]/90 border border-zinc-800/90 rounded-xl p-3 min-w-[105px]">
              <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-zinc-400">
                <Image src="/images/res/gold.webp" alt="Gold" width={14} height={14} className="object-contain" />
                <span>GOLD</span>
              </div>
              <div className="text-sm font-bold text-yellow-400 mt-1">
                {totalGold}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* 2. Licenses Section */}
      <div className="bg-[#0c0e14]/90 backdrop-blur-xl border border-zinc-800/80 rounded-2xl overflow-hidden shadow-2xl">
        <div className="px-6 py-4 border-b border-zinc-800/80 flex items-center justify-between">
          <h2 className="text-sm font-bold text-white tracking-wide">
            Licenses
          </h2>
          <button
            onClick={loadFleet}
            className="flex items-center gap-1.5 text-xs font-medium text-zinc-400 hover:text-white transition-colors"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>Refresh</span>
          </button>
        </div>

        <div className="p-4 space-y-3">
          {/* Active Bot Row matching reference: amer1220958 · Running · 18/18 seats · Expires in 12d · Stop */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 rounded-xl bg-[#141620]/70 border border-zinc-800/80 hover:border-zinc-700/60 transition-colors">
            <div className="flex items-center gap-3">
              <span className="text-sm font-bold text-white tracking-wide">
                amer1220958
              </span>
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                Running
              </span>
            </div>

            <div className="flex items-center gap-6 text-xs text-zinc-400">
              <span>18 / 18 seats</span>
              <span>Expires in 12d</span>
              <button
                onClick={handleToggleFleet}
                disabled={busy}
                className="px-3.5 py-1.5 rounded-lg border border-zinc-700 bg-zinc-800/60 hover:bg-zinc-700 text-white font-semibold transition-colors disabled:opacity-50"
              >
                {running ? "Stop" : "Start"}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* 3. Kingdoms Section (Resource & Farm Aggregator by Kingdom) */}
      <div className="bg-[#0c0e14]/90 backdrop-blur-xl border border-zinc-800/80 rounded-2xl overflow-hidden shadow-2xl">
        <div className="px-6 py-4 border-b border-zinc-800/80 flex items-center justify-between">
          <h2 className="text-sm font-bold text-white tracking-wide">
            Kingdoms
          </h2>

          <div className="flex items-center gap-1.5">
            <button
              onClick={() => setActiveTab("all")}
              className={`px-3 py-1 rounded-lg text-xs font-semibold transition-colors ${
                activeTab === "all"
                  ? "bg-zinc-800 text-white border border-zinc-700"
                  : "text-zinc-400 hover:text-white"
              }`}
            >
              All (9)
            </button>
            <button
              onClick={() => setActiveTab("active")}
              className={`px-3 py-1 rounded-lg text-xs font-semibold transition-colors ${
                activeTab === "active"
                  ? "bg-zinc-800 text-white border border-zinc-700"
                  : "text-zinc-400 hover:text-white"
              }`}
            >
              Active (9)
            </button>
          </div>
        </div>

        <div className="p-4 space-y-4">
          {kingdoms.map((k) => {
            const isExpanded = expandedKingdoms[k.id];
            return (
              <div
                key={k.id}
                className="border border-zinc-800/80 rounded-xl overflow-hidden bg-[#12141e]/60 transition-all"
              >
                {/* Kingdom Summary Accordion Bar */}
                <div
                  onClick={() => toggleKingdom(k.id)}
                  className="p-4 flex flex-col md:flex-row md:items-center justify-between gap-4 cursor-pointer hover:bg-zinc-800/20 transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <button className="text-zinc-400 hover:text-white transition-colors">
                      {isExpanded ? (
                        <ChevronDown className="w-4 h-4 text-emerald-400" />
                      ) : (
                        <ChevronRight className="w-4 h-4" />
                      )}
                    </button>
                    <div>
                      <div className="text-sm font-bold text-white tracking-wide flex items-center gap-2">
                        <span>Kingdom {k.kingdomNumber}</span>
                        <span className="text-xs font-normal text-zinc-400">
                          {k.accountsCount} accounts · {k.charsCount} chars
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Kingdom Total Resource Metrics Bar */}
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <div className="px-2.5 py-1 rounded-lg bg-zinc-900/90 border border-zinc-800 text-zinc-300 font-semibold">
                      <span className="text-[10px] text-zinc-500 uppercase mr-1.5">POWER</span>
                      <span>{k.power}</span>
                    </div>

                    <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-zinc-900/90 border border-zinc-800 text-emerald-400 font-semibold">
                      <Image src="/images/res/food.webp" alt="" width={13} height={13} className="object-contain" />
                      <span>{k.food}</span>
                    </div>

                    <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-zinc-900/90 border border-zinc-800 text-amber-300 font-semibold">
                      <Image src="/images/res/wood.webp" alt="" width={13} height={13} className="object-contain" />
                      <span>{k.wood}</span>
                    </div>

                    <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-zinc-900/90 border border-zinc-800 text-cyan-300 font-semibold">
                      <Image src="/images/res/stone.webp" alt="" width={13} height={13} className="object-contain" />
                      <span>{k.stone}</span>
                    </div>

                    <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-zinc-900/90 border border-zinc-800 text-yellow-400 font-semibold">
                      <Image src="/images/res/gold.webp" alt="" width={13} height={13} className="object-contain" />
                      <span>{k.gold}</span>
                    </div>

                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleKingdom(k.id);
                      }}
                      className="ml-2 text-xs font-semibold text-zinc-400 hover:text-white transition-colors"
                    >
                      {isExpanded ? "Hide" : `Show ${k.accountsCount}`}
                    </button>
                  </div>
                </div>

                {/* Expanded Governors Table */}
                {isExpanded && (
                  <div className="border-t border-zinc-800/80 divide-y divide-zinc-800/60 bg-[#0c0e14]/50">
                    <div className="grid grid-cols-12 px-5 py-2.5 text-[11px] font-bold tracking-wider uppercase text-zinc-500">
                      <div className="col-span-1">Status</div>
                      <div className="col-span-3">Governor ID / Name</div>
                      <div className="col-span-2">City Hall</div>
                      <div className="col-span-2">Last Run</div>
                      <div className="col-span-2">Next Run</div>
                      <div className="col-span-2 text-right">Action</div>
                    </div>

                    {k.accounts.map((acc) => {
                      const isTriggering = runningGovernors[acc.governorId];
                      return (
                        <div
                          key={acc.governorId}
                          className="grid grid-cols-12 px-5 py-3 items-center text-xs hover:bg-zinc-800/30 transition-colors"
                        >
                          <div className="col-span-1 flex items-center">
                            <span className="w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(16,185,129,0.6)]" />
                          </div>

                          <div className="col-span-3 min-w-0">
                            <div className="font-semibold text-white flex items-center gap-2 truncate">
                              <span>{acc.name}</span>
                              <span className="text-[11px] font-mono text-zinc-400">
                                ({acc.governorId})
                              </span>
                            </div>
                            <div className="text-[11px] text-zinc-500 truncate">
                              {acc.email}
                            </div>
                          </div>

                          <div className="col-span-2">
                            <span className="px-2 py-0.5 rounded bg-zinc-800/80 border border-zinc-700/60 text-zinc-300 font-semibold text-[11px]">
                              {acc.cityHall}
                            </span>
                          </div>

                          <div className="col-span-2 text-zinc-400">
                            {acc.lastRun}
                          </div>

                          <div className="col-span-2 text-zinc-400">
                            {acc.nextRun}
                          </div>

                          <div className="col-span-2 text-right">
                            <button
                              onClick={() => handleRunGovernor(acc.governorId)}
                              disabled={isTriggering}
                              className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-semibold bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 border border-emerald-500/40 transition-all disabled:opacity-50"
                            >
                              <Play className="w-3 h-3" />
                              <span>{isTriggering ? "Running..." : "Run"}</span>
                            </button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

