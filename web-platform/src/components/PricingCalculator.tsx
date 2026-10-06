"use client";

import React, { useState } from "react";
import { Check, Zap, Sparkles, ShieldCheck } from "lucide-react";
import Link from "next/link";

export function PricingCalculator() {
  const [characterCount, setCharacterCount] = useState(5);
  const [duration, setDuration] = useState<30 | 90>(30);

  // Price calculation formula
  // Base price per character: $1.80/month for 30 days, $1.40/month for 90 days (22% discount)
  const ratePerChar = duration === 30 ? 1.8 : 1.4;
  const totalPrice = (characterCount * ratePerChar * (duration / 30)).toFixed(2);
  const dailyRate = (Number(totalPrice) / duration).toFixed(2);

  return (
    <div id="pricing" className="max-w-4xl mx-auto p-8 rounded-3xl glass-panel border border-cyan-500/20 relative overflow-hidden">
      <div className="absolute -top-24 -right-24 w-60 h-60 bg-cyan-500/10 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute -bottom-24 -left-24 w-60 h-60 bg-emerald-500/10 rounded-full blur-3xl pointer-events-none" />

      <div className="text-center max-w-xl mx-auto mb-10">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 mb-3">
          <Sparkles className="w-3.5 h-3.5" />
          <span>Transparent Fleet Pricing</span>
        </div>
        <h3 className="text-2xl sm:text-3xl font-black text-white">
          Configure Your Fleet Scale
        </h3>
        <p className="text-slate-400 text-sm mt-2">
          Pay only for the active characters you deploy. Scale up or pause at any second.
        </p>
      </div>

      <div className="grid md:grid-cols-2 gap-8 items-center">
        {/* Sliders & Controls */}
        <div className="space-y-6">
          <div>
            <div className="flex justify-between items-center mb-3">
              <label className="text-sm font-semibold text-slate-200">
                Number of Characters
              </label>
              <span className="text-lg font-black text-cyan-400 bg-cyan-950/60 px-3 py-1 rounded-xl border border-cyan-500/30">
                {characterCount} Chars
              </span>
            </div>
            <input
              type="range"
              min={1}
              max={30}
              step={1}
              value={characterCount}
              onChange={(e) => setCharacterCount(Number(e.target.value))}
              className="w-full h-2 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-cyan-400"
            />
            <div className="flex justify-between text-[11px] text-slate-500 mt-1 font-mono">
              <span>1 Character</span>
              <span>15 Characters</span>
              <span>30 Characters</span>
            </div>
          </div>

          <div>
            <label className="block text-sm font-semibold text-slate-200 mb-2">
              Billing Duration
            </label>
            <div className="grid grid-cols-2 gap-3">
              <button
                onClick={() => setDuration(30)}
                className={`py-3 px-4 rounded-xl text-xs font-bold transition-all border ${
                  duration === 30
                    ? "bg-cyan-950/80 border-cyan-400 text-cyan-300 shadow-md shadow-cyan-500/20"
                    : "bg-slate-900/60 border-slate-800 text-slate-400 hover:border-slate-700"
                }`}
              >
                30 Days (Standard)
              </button>
              <button
                onClick={() => setDuration(90)}
                className={`py-3 px-4 rounded-xl text-xs font-bold transition-all border relative overflow-hidden ${
                  duration === 90
                    ? "bg-emerald-950/80 border-emerald-400 text-emerald-300 shadow-md shadow-emerald-500/20"
                    : "bg-slate-900/60 border-slate-800 text-slate-400 hover:border-slate-700"
                }`}
              >
                <span className="absolute -top-2 right-1 text-[8px] bg-emerald-500 text-slate-950 px-1.5 py-0.5 rounded-full font-black">
                  SAVE 22%
                </span>
                90 Days (Quarterly)
              </button>
            </div>
          </div>

          <div className="space-y-2 pt-2 border-t border-slate-800/80">
            <div className="flex items-center gap-2 text-xs text-slate-300">
              <Check className="w-4 h-4 text-emerald-400" />
              <span>100% Headless Cloud Architecture (0% CPU load)</span>
            </div>
            <div className="flex items-center gap-2 text-xs text-slate-300">
              <Check className="w-4 h-4 text-emerald-400" />
              <span>Full Autonomous Alliance Help & Tech Donation</span>
            </div>
            <div className="flex items-center gap-2 text-xs text-slate-300">
              <Check className="w-4 h-4 text-emerald-400" />
              <span>Instant Cloud Reconnect & Zero-Gem Protection</span>
            </div>
          </div>
        </div>

        {/* Pricing Summary Box */}
        <div className="bg-gradient-to-b from-[#10192e] to-[#0b101f] border border-cyan-500/30 rounded-2xl p-6 text-center space-y-5 shadow-2xl relative">
          <div className="inline-block px-3 py-1 rounded-full text-[10px] font-bold tracking-wider uppercase bg-cyan-500/10 border border-cyan-500/30 text-cyan-300">
            Estimated Total
          </div>

          <div>
            <div className="text-4xl sm:text-5xl font-black text-white tracking-tight">
              ${totalPrice}
            </div>
            <div className="text-xs text-slate-400 mt-1 font-mono">
              Just ~${dailyRate} / day across {characterCount} active characters
            </div>
          </div>

          <div className="pt-2">
            <Link
              href={`/shop?chars=${characterCount}&duration=${duration}`}
              className="w-full flex items-center justify-center gap-2 py-3.5 px-6 rounded-xl bg-gradient-to-r from-cyan-400 to-emerald-400 text-slate-950 font-black text-sm hover:opacity-95 shadow-lg shadow-cyan-500/25 transition-all"
            >
              <Zap className="w-4 h-4" />
              <span>Deploy Fleet Plan</span>
            </Link>
          </div>

          <div className="flex items-center justify-center gap-2 text-[11px] text-slate-500">
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-500" />
            <span>Instant Cloud Provisioning via AWS eu-north-1</span>
          </div>
        </div>
      </div>
    </div>
  );
}
