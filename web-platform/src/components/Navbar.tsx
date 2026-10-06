"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Shield, Activity, Cpu, Sparkles, LogIn, LayoutDashboard } from "lucide-react";

export function Navbar() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-50 w-full border-b border-cyan-500/15 glass-panel bg-slate-950/80 backdrop-blur-xl">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        
        {/* Logo */}
        <Link href="/" className="flex items-center gap-3 group">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-cyan-500 to-emerald-400 p-[1px] shadow-lg shadow-cyan-500/20 group-hover:shadow-cyan-500/40 transition-all">
            <div className="w-full h-full bg-[#090d1a] rounded-xl flex items-center justify-center">
              <Cpu className="w-5 h-5 text-cyan-400 group-hover:rotate-12 transition-transform duration-300" />
            </div>
          </div>
          <div>
            <span className="text-lg font-black tracking-wider text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 via-teal-300 to-emerald-400">
              ROK MASTER
            </span>
            <span className="ml-1.5 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-widest text-cyan-300 bg-cyan-950/70 border border-cyan-500/30 rounded">
              SaaS v2
            </span>
          </div>
        </Link>

        {/* Navigation Links */}
        <nav className="hidden md:flex items-center gap-8 text-sm font-medium">
          <Link
            href="/"
            className={`transition-colors hover:text-cyan-400 ${
              pathname === "/" ? "text-cyan-400 font-semibold" : "text-slate-400"
            }`}
          >
            Overview
          </Link>
          <Link
            href="/#features"
            className="text-slate-400 hover:text-cyan-400 transition-colors"
          >
            Capabilities
          </Link>
          <Link
            href="/#pricing"
            className="text-slate-400 hover:text-cyan-400 transition-colors"
          >
            Pricing
          </Link>
          <Link
            href="/leaderboard"
            className={`transition-colors hover:text-cyan-400 ${
              pathname === "/leaderboard" ? "text-cyan-400 font-semibold" : "text-slate-400"
            }`}
          >
            Leaderboard
          </Link>
          <Link
            href="/shop"
            className={`transition-colors hover:text-cyan-400 ${
              pathname === "/shop" ? "text-cyan-400 font-semibold" : "text-slate-400"
            }`}
          >
            Fleet Store
          </Link>
        </nav>

        {/* Right CTA / Auth */}
        <div className="flex items-center gap-3">
          <Link
            href="/dashboard"
            className="flex items-center gap-2 px-4 py-2 text-xs font-semibold rounded-xl bg-cyan-950/60 border border-cyan-500/30 text-cyan-300 hover:bg-cyan-900/60 hover:border-cyan-400/50 transition-all shadow-sm"
          >
            <LayoutDashboard className="w-3.5 h-3.5 text-cyan-400" />
            <span>Dashboard</span>
          </Link>

          <Link
            href="/login"
            className="flex items-center gap-2 px-4 py-2 text-xs font-bold rounded-xl bg-gradient-to-r from-cyan-500 to-emerald-500 text-slate-950 hover:opacity-95 shadow-md shadow-cyan-500/20 hover:shadow-cyan-500/40 transition-all"
          >
            <LogIn className="w-3.5 h-3.5" />
            <span>Connect</span>
          </Link>
        </div>

      </div>
    </header>
  );
}
