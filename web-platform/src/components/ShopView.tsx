"use client";

import React, { useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { Star, ShieldCheck, Zap, Sparkles, ShoppingCart, Tag, CheckCircle2, ChevronRight } from "lucide-react";
import TiltCard3D from "./hud/TiltCard3D";

import { ITEM_GEM_BASE64, ITEM_FOOD_BASE64 } from "@/lib/gameIconsBase64";

interface BotProduct {
  id: string;
  title: string;
  subtitle: string;
  description: string;
  priceStart: string;
  badge?: string;
  badgeType?: "active" | "notice";
  imageSrc: string;
  available: boolean;
  features: string[];
}

export default function ShopView() {
  const [referralCode, setReferralCode] = useState("");
  const [isReferralApplied, setIsReferralApplied] = useState(false);

  const products: BotProduct[] = [
    {
      id: "gem-bot",
      title: "Gem Bot",
      subtitle: "جمع الجواهر الذكي 24/7",
      description: "Collect gems 24/7, run barb fort rallies solo or paired with a friend, and keep your farms fed.",
      priceStart: "$10.00",
      badge: "UPDATED",
      badgeType: "active",
      imageSrc: ITEM_GEM_BASE64,
      available: true,
      features: [
        "جمع الجواهر الذكي على مدار الساعة",
        "حشد حصون البرابرة تلقائياً",
        "تغذية مزارعك باستمرار دون انقطاع",
        "انسحاب ذكي عند رصد أي خطر",
      ],
    },
    {
      id: "farm-bot",
      title: "Farm Bot",
      subtitle: "تشغيل مزارعك 24/7",
      description: "Run your farm accounts 24/7. Pricing scales per character.",
      priceStart: "$6.00",
      badge: "POPULAR",
      badgeType: "active",
      imageSrc: ITEM_FOOD_BASE64,
      available: true,
      features: [
        "تشغيل وإدارة حساباتك تلقائياً 24/7",
        "جمع القمح والأخشاب والحجر والذهب",
        "تدريب الجيوش التلقائي لجميع الثكنات",
        "تجنب أراضي التحالفات المعادية",
        "استلام الهدايا والتبرع للتحالف",
      ],
    },
  ];

  const handleApplyReferral = () => {
    if (referralCode.trim()) {
      setIsReferralApplied(true);
    }
  };

  return (
    <div className="w-full space-y-8">
      {/* 1. Armory Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-6 border-b border-zinc-800/80">
        <div>
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-amber-400 animate-ping" />
            <span className="text-xs font-semibold tracking-wider text-amber-400 uppercase">
              TACTICAL PROCUREMENT · ARMORY BAYS
            </span>
          </div>
          <h1 className="text-3xl font-extrabold tracking-tight text-white mt-1">
            BOT INSTANCES &amp; LICENSES
          </h1>
          <p className="text-sm text-zinc-400 mt-1">
            Deploy autonomous headless worker nodes directly to your AWS EC2 cloud fleet.
          </p>
        </div>

        <div className="flex items-center gap-3 text-xs font-medium">
          <div className="px-3.5 py-2 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-emerald-400" />
            <span>INSTANT CLOUD PROVISIONING</span>
          </div>
        </div>
      </div>

      {/* 2. Top Info: Community Rating & Voucher / Partner Input */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Verified Rating Card */}
        <TiltCard3D glowColor="emerald" className="p-5 flex flex-col justify-between">
          <div className="flex items-start justify-between">
            <div>
              <span className="text-xs font-semibold tracking-wider text-zinc-400 uppercase">
                COMMUNITY TELEMETRY
              </span>
              <div className="mt-2 flex items-baseline gap-2">
                <span className="text-3xl font-extrabold text-white">5.0</span>
                <span className="flex gap-1">
                  {[0, 1, 2, 3, 4].map((i) => (
                    <Star key={i} className="w-4 h-4 fill-amber-400 text-amber-400" />
                  ))}
                </span>
              </div>
            </div>
            <span className="text-xs font-semibold px-2.5 py-1 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 uppercase">
              100% RELIABLE
            </span>
          </div>
          <div className="mt-4 pt-3 border-t border-zinc-800/60 flex items-center justify-between text-xs text-zinc-400">
            <span>Verified Operator Feedback</span>
            <span className="text-emerald-400 font-semibold">Zero Ban History</span>
          </div>
        </TiltCard3D>

        {/* Voucher / Partner Code Card */}
        <TiltCard3D glowColor="gold" className="lg:col-span-2 p-5 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-2 text-xs font-semibold tracking-wider uppercase text-zinc-400">
              <span className="flex items-center gap-1.5">
                <Tag className="w-3.5 h-3.5 text-amber-400" />
                VOUCHER / ALLIANCE PARTNER PROTOCOL
              </span>
              {isReferralApplied && (
                <span className="text-emerald-400 font-bold flex items-center gap-1">
                  <CheckCircle2 className="w-3.5 h-3.5" /> APPLIED
                </span>
              )}
            </div>
            <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3 mt-3">
              <div className="relative flex-1">
                <input
                  type="text"
                  value={referralCode}
                  onChange={(e) => {
                    setReferralCode(e.target.value);
                    setIsReferralApplied(false);
                  }}
                  placeholder="Enter partner / discount code (Optional)"
                  className="input-dark w-full px-4 py-2.5 text-xs"
                />
              </div>
              <button
                onClick={handleApplyReferral}
                className="px-6 py-2.5 rounded-lg bg-amber-500/15 border border-amber-500/40 text-amber-300 hover:bg-amber-500/25 text-xs font-bold tracking-wide transition-all hover:shadow-[0_0_20px_rgba(245,158,11,0.25)]"
              >
                {isReferralApplied ? "VALIDATED ✓" : "APPLY VOUCHER"}
              </button>
            </div>
          </div>

          <p className="text-xs text-zinc-400 mt-3">
            {isReferralApplied
              ? "Partner token active. Extra slot allocations linked to this checkout session."
              : "Enter an officer referral token to unlock bonus telemetry cycles and discount rates."}
          </p>
        </TiltCard3D>
      </div>

      {/* 3. High-Tech Product Armory Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {products.map((bot) => {
          const isFeatured = bot.id === "farm-bot";
          return (
            <TiltCard3D
              key={bot.id}
              glowColor={isFeatured ? "emerald" : "default"}
              className={`p-6 flex flex-col justify-between relative overflow-hidden ${
                !bot.available ? "opacity-75" : ""
              }`}
            >
              {/* Background Glow */}
              {isFeatured && (
                <div className="absolute -top-12 -right-12 w-36 h-36 rounded-full bg-emerald-500/15 blur-3xl pointer-events-none" />
              )}

              <div>
                {/* Badge & Icon Header */}
                <div className="flex items-start justify-between mb-5">
                  <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-zinc-800/80 via-zinc-900/90 to-black/80 border border-zinc-700/60 p-2.5 flex items-center justify-center relative shadow-inner">
                    <Image
                      src={bot.imageSrc}
                      alt={bot.title}
                      width={48}
                      height={48}
                      className="object-contain relative z-10 drop-shadow-[0_0_10px_rgba(0,229,255,0.4)]"
                    />
                  </div>

                  <span
                    className={`text-xs font-semibold px-2.5 py-1 rounded-full border uppercase tracking-wide ${
                      bot.badgeType === "active"
                        ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/40 shadow-[0_0_12px_rgba(16,185,129,0.25)]"
                        : "bg-zinc-800/50 text-zinc-500 border-zinc-700/40"
                    }`}
                  >
                    {bot.badge}
                  </span>
                </div>

                {/* Title & Subtitle */}
                <div className="mb-3">
                  <span className="text-xs font-semibold text-zinc-400 uppercase tracking-wider block">
                    {bot.subtitle}
                  </span>
                  <h3 className="text-xl font-extrabold text-white mt-0.5 tracking-wide">
                    {bot.title}
                  </h3>
                </div>

                <p className="text-xs leading-relaxed text-zinc-400 min-h-[54px] mb-5">
                  {bot.description}
                </p>

                {/* Feature Bullet Points */}
                <div className="space-y-2 py-4 border-t border-zinc-800/80 text-xs text-zinc-300">
                  {bot.features.map((feat, idx) => (
                    <div key={idx} className="flex items-center gap-2">
                      <span className={`w-1.5 h-1.5 rounded-full ${bot.available ? "bg-emerald-400" : "bg-zinc-600"}`} />
                      <span>{feat}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Price & Action Button */}
              <div className="pt-5 mt-4 border-t border-zinc-800/80 flex items-center justify-between">
                <div>
                  <span className="block text-xs text-zinc-500 uppercase tracking-wider">
                    LICENSE TIER
                  </span>
                  <div className="flex items-baseline gap-1 mt-0.5">
                    <span className="text-2xl font-black text-white">{bot.priceStart}</span>
                    <span className="text-xs text-zinc-500 font-normal">/ month</span>
                  </div>
                </div>

                {bot.available ? (
                  <Link
                    href={`/checkout?plan=${bot.id}&code=${encodeURIComponent(referralCode)}`}
                    className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-400 hover:to-teal-500 text-black font-bold text-xs tracking-wide uppercase transition-all shadow-[0_0_20px_rgba(16,185,129,0.3)] hover:shadow-[0_0_30px_rgba(16,185,129,0.5)]"
                  >
                    <span>ACQUIRE</span>
                    <ChevronRight className="w-4 h-4" />
                  </Link>
                ) : (
                  <button
                    disabled
                    className="px-4 py-2.5 rounded-xl bg-zinc-900 border border-zinc-800 text-zinc-500 text-xs font-semibold uppercase cursor-not-allowed opacity-60"
                  >
                    IN DEVELOPMENT
                  </button>
                )}
              </div>
            </TiltCard3D>
          );
        })}
      </div>
    </div>
  );
}