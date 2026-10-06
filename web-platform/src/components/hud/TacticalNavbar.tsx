"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { Play, Square, Activity, ShieldCheck } from "lucide-react";
import { type OwnedBot } from "@/lib/store";
import { useGhostBot } from "@/components/SupabaseProvider";

interface TacticalNavbarProps {
  running: boolean | null;
  busy: boolean;
  onToggleFleet: () => void;
  bots?: OwnedBot[];
}

export default function TacticalNavbar({ running, busy, onToggleFleet }: TacticalNavbarProps) {
  const { user, profile } = useGhostBot();
  const [time, setTime] = useState("");

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setTime(now.toUTCString().replace("GMT", "UTC"));
    };
    updateTime();
    const timer = setInterval(updateTime, 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <header className="sticky top-0 z-40 w-full border-b border-[#00e5ff]/20 bg-[#040a17]/90 backdrop-blur-xl">
      <div className="flex h-16 items-center justify-between px-4 sm:px-6 lg:px-8">
        {/* Brand: GhostBot Mascot & Glowing Wordmark */}
        <div className="flex items-center gap-4">
          <Link href="/dashboard" className="flex items-center gap-3 group">
            <div className="relative w-10 h-10 rounded-xl bg-[#07131f] border border-[#00e5ff]/40 flex items-center justify-center p-1.5 shadow-[0_0_20px_rgba(0,229,255,0.25)]">
              <svg className="w-7 h-7 text-[#00e5ff]">
                <use href="#ghostbot-mascot" />
              </svg>
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-base font-black tracking-wider text-white">
                  Ghost<span className="text-[#00e5ff] drop-shadow-[0_0_10px_rgba(0,229,255,0.8)]">Bot</span>
                </span>
                <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-[#00e5ff]/15 text-[#00e5ff] border border-[#00e5ff]/30 tracking-widest">
                  CYBER CORE
                </span>
              </div>
              <p className="text-[11px] text-[#92b2d6]">YOUR INTELLIGENT AI COMPANION</p>
            </div>
          </Link>

          {/* Telemetry Clock & Latency */}
          <div className="hidden md:flex items-center gap-3 pr-4 border-r border-[#00e5ff]/15 text-xs text-[#92b2d6]">
            <div className="flex items-center gap-1.5">
              <Activity className="w-3.5 h-3.5 text-[#00e5ff]" />
              <span>AWS EC2:</span>
              <span className="text-[#00e5ff] font-semibold">22ms (Frankfurt)</span>
            </div>
            <div className="w-1 h-1 rounded-full bg-[#00e5ff]/40" />
            <div className="text-[#92b2d6] font-mono text-[11px]">{time || "SYNCING..."}</div>
          </div>
        </div>

        {/* Global Fleet Controls & Status */}
        <div className="flex items-center gap-3 sm:gap-4">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[#07131f] border border-[#00e5ff]/25 text-xs">
            <span className={`w-2 h-2 rounded-full ${running ? "bg-[#00e5ff] animate-ping" : "bg-amber-400"}`} />
            <span className="text-white font-bold text-[11px]">
              {running ? "أسطول نشط · ACTIVE" : "في الانتظار · STANDBY"}
            </span>
          </div>

          <button
            onClick={onToggleFleet}
            disabled={busy || running === null}
            className={`flex items-center gap-2 px-4 py-2 text-xs font-bold tracking-wide uppercase rounded-xl border transition-all duration-200 ${
              running
                ? "bg-amber-500/15 border-amber-500/40 text-amber-300 hover:bg-amber-500/25 hover:shadow-[0_0_20px_rgba(245,158,11,0.25)]"
                : "bg-[#00e5ff]/20 border-[#00e5ff]/50 text-[#00e5ff] hover:bg-[#00e5ff]/30 hover:shadow-[0_0_25px_rgba(0,229,255,0.35)]"
            } ${busy ? "opacity-50 cursor-wait" : ""}`}
          >
            {running ? <Square className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
            <span>{busy ? "جارٍ الإرسال..." : running ? "إيقاف الأسطول" : "تشغيل الأسطول"}</span>
          </button>

          {/* User Profile Mini Pill */}
          <Link
            href="/profile"
            className="flex items-center gap-2.5 px-3 py-1.5 rounded-xl bg-[#07131f] border border-[#00e5ff]/30 hover:border-[#00e5ff] transition-all"
          >
            <img
              src={profile?.avatar_url || user?.user_metadata?.avatar_url || "/ghostbot-logo.png"}
              alt="Avatar"
              className="w-7 h-7 rounded-full object-cover border border-[#00e5ff]/50"
              onError={(e) => { (e.target as any).src = "/ghostbot-logo.png"; }}
            />
            <span className="text-xs font-bold text-white hidden sm:inline">
              {profile?.username || user?.user_metadata?.custom_claims?.global_name || "Commander"}
            </span>
          </Link>
        </div>
      </div>
    </header>
  );
}