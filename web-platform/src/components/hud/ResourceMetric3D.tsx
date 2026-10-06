"use client";

import React from "react";
import Image from "next/image";
import TiltCard3D from "./TiltCard3D";
import { ITEM_FOOD_BASE64, ITEM_WOOD_BASE64, ITEM_STONE_BASE64, ITEM_GOLD_BASE64, ITEM_GEM_BASE64 } from "@/lib/gameIconsBase64";

interface ResourceMetric3DProps {
  type: "food" | "wood" | "stone" | "gold" | "gem";
  label: string;
  amount: string | number;
  ratePerHour?: string;
  statusText?: string;
}

export default function ResourceMetric3D({
  type,
  label,
  amount,
  ratePerHour,
  statusText = "Node Flow Optimal",
}: ResourceMetric3DProps) {
  const images = {
    food: ITEM_FOOD_BASE64,
    wood: ITEM_WOOD_BASE64,
    stone: ITEM_STONE_BASE64,
    gold: ITEM_GOLD_BASE64,
    gem: ITEM_GEM_BASE64,
  }[type];

  const glowColor = type === "food" || type === "wood" ? "emerald" : type === "gem" ? "cyan" : "gold";

  return (
    <TiltCard3D glowColor={glowColor} className="p-4 overflow-hidden">
      {/* Ambient background bloom glow */}
      <div
        className={`absolute -right-6 -top-6 w-24 h-24 rounded-full blur-2xl pointer-events-none opacity-25 ${
          glowColor === "emerald" ? "bg-emerald-500" : glowColor === "cyan" ? "bg-cyan-500" : "bg-amber-500"
        }`}
      />

      <div className="flex items-start justify-between">
        <div>
          <span className="text-xs uppercase tracking-wider text-zinc-400 font-semibold flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
            {label}
          </span>
          <div className="mt-2 text-2xl font-bold tracking-tight text-white flex items-baseline gap-1.5">
            {amount}
            <span className="text-xs text-zinc-400 font-normal uppercase">Total</span>
          </div>
        </div>

        {/* 3D-Styled Metallic Floating Badge */}
        <div className="relative w-12 h-12 flex items-center justify-center rounded-xl bg-gradient-to-br from-zinc-800/80 via-zinc-900/90 to-black/80 border border-zinc-700/50 shadow-inner p-2">
          <div className="absolute inset-0 rounded-xl bg-white/5 backdrop-blur-sm" />
          <Image
            src={images}
            alt={label}
            width={34}
            height={34}
            className="object-contain relative z-10 drop-shadow-[0_4px_8px_rgba(0,0,0,0.6)]"
          />
        </div>
      </div>

      {/* Telemetry sub-row */}
      <div className="mt-3 pt-3 border-t border-zinc-800/60 flex items-center justify-between text-xs">
        <span className="text-zinc-400">{statusText}</span>
        {ratePerHour && (
          <span className="text-emerald-400 font-semibold flex items-center gap-1">
            ▲ {ratePerHour}
          </span>
        )}
      </div>
    </TiltCard3D>
  );
}