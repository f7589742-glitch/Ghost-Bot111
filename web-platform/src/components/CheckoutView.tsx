'use client';

import React, { useState } from 'react';
import { Check, ShieldCheck, ChevronRight, ArrowLeft, Plus, Zap, Shield, Sparkles, Layers } from 'lucide-react';
import { PayPalIcon, BinanceIcon, BitcoinIcon, EthereumIcon, UsdtIcon } from './PayIcons';
import { saveBot } from '@/lib/store';
import { createCloudBot, getSessionUser } from '@/lib/cloud';
import { createClient } from '@/lib/supabase/client';
import TiltCard3D from './hud/TiltCard3D';

interface Props {
  itemId: string;
  itemName: string;
  initialReferral?: string;
}

// Zeroed: no legacy instances carried over — user creates fresh ones below.
interface FleetInstance {
  id: string;
  label: string;
  detail: string;
  rooms: string[];
}
const EXISTING_INSTANCES: FleetInstance[] = [];

// Volume discount matrix (per-char rate by slot count, Standard tier)
const VOLUME_TIERS = [
  { min: 1, label: '1+ chars', std: 2.0 },
  { min: 10, label: '10+ chars', std: 1.6 },
  { min: 50, label: '50+ chars', std: 1.4 },
  { min: 100, label: '100+ chars', std: 1.2 },
];
const PRO_MULTIPLIER = 1.75;

function volumeStd(count: number): number {
  let rate = VOLUME_TIERS[0].std;
  for (const t of VOLUME_TIERS) {
    if (count >= t.min) rate = t.std;
  }
  return rate;
}

const PAY_METHODS = [
  { id: 'PayPal', sub: 'Balance · Card via PayPal', Icon: PayPalIcon },
  { id: 'Binance Pay', sub: 'BTC · ETH · USDT', Icon: BinanceIcon },
  { id: 'Bitcoin', sub: 'BTC network', Icon: BitcoinIcon },
  { id: 'Ethereum', sub: 'ERC-20 network', Icon: EthereumIcon },
  { id: 'USDT', sub: 'ERC-20 / TRC-20', Icon: UsdtIcon },
];

export default function CheckoutView({ itemId, itemName, initialReferral = '' }: Props) {
  const [currentStep, setCurrentStep] = useState<number>(1);
  const [maxStep, setMaxStep] = useState<number>(1);
  const [orderId, setOrderId] = useState<string | null>(null);
  const [orderErr, setOrderErr] = useState<string>("");

  async function placeOrder() {
    setOrderErr("");
    // Zero-ghost policy: no order without an active Discord session.
    // The order is linked to the Supabase user via createCloudBot.
    const user = await getSessionUser();
    if (!user) {
      setOrderErr("Discord login is required to place an order.");
      return;
    }

    try {
      const provRes = await fetch("/api/bots/provision", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          product: itemId === "gem-bot" ? "gem-bot" : "farm-bot",
          tier,
          slots: characterCount,
          duration: billingDays,
          pay_method: "PayPal / Cards",
          amount: String(totalPrice),
          custom_name: effectiveRoom.trim() || undefined,
        }),
      });
      const provData = await provRes.json();
      if (!provRes.ok || !provData.success) {
        setOrderErr(provData.error || "Failed to provision global bot unit");
        return;
      }

      const botSlug = provData.bot_id;
      const bot = {
        id: provData.bot.id,
        bot_id: botSlug,
        product: (itemId === 'gem-bot' ? 'gem-bot' : 'farm-bot') as 'farm-bot' | 'gem-bot',
        label: provData.name,
        tier,
        slots: characterCount,
        days: billingDays,
        room: botSlug,
        ref: referralCode.trim(),
        total: totalPrice,
        createdAt: Date.now(),
      };
      saveBot(bot);
      setOrderId(botSlug);
      setPlaced(true);
    } catch (e: any) {
      setOrderErr(e?.message || "Order placement failed");
    }
  }

  const [tier, setTier] = useState<'basic' | 'pro'>('basic');
  const [characterCount, setCharacterCount] = useState<number>(5);
  const [billingDays, setBillingDays] = useState<number>(30);

  const [promoCode, setPromoCode] = useState<string>('');
  const [referralCode, setReferralCode] = useState<string>(initialReferral);
  const [promoApplied, setPromoApplied] = useState<boolean>(false);

  // Step 2: assignment (starts empty — no legacy data)
  const [assignTarget, setAssignTarget] = useState<string>('new');
  const [newRoomName, setNewRoomName] = useState<string>('');

  // Step 3: payment
  const [payMethod, setPayMethod] = useState<string>(PAY_METHODS[0].id);
  const [agreed, setAgreed] = useState<boolean>(false);
  const [placed, setPlaced] = useState<boolean>(false);

  const stdRate = volumeStd(characterCount);
  const baseRatePerChar = tier === 'basic' ? stdRate : stdRate * PRO_MULTIPLIER;
  const rawSubtotal = characterCount * baseRatePerChar;
  const daysMultiplier = billingDays === 90 ? 2.55 : 1.0;
  const totalPrice = (rawSubtotal * daysMultiplier).toFixed(2);

  const activeInstance = EXISTING_INSTANCES.find((i) => i.id === assignTarget);
  const effectiveRoom = newRoomName;

  function goStep(n: number) {
    if (placed) return;
    if (n <= maxStep) setCurrentStep(n);
  }

  function continueTo(n: number) {
    setMaxStep((m) => Math.max(m, n));
    setCurrentStep(n);
  }

  return (
    <div className="w-full space-y-8">
      {/* Tactical Breadcrumb Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-6 border-b border-[#1f293d]/80">
        <div>
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-emerald-400 animate-ping" />
            <span className="text-xs font-semibold tracking-wider text-emerald-400 uppercase">
              TERMINAL ARMORY · FLEET PROVISIONING
            </span>
          </div>
          <h1 className="text-3xl font-extrabold tracking-tight text-white mt-1">
            Configure &amp; Checkout
          </h1>
          <p className="text-sm text-zinc-400 mt-1">
            Step {currentStep} of 3: {currentStep === 1 ? `${itemName} Configuration` : currentStep === 2 ? 'Instance Assignment' : 'Payment Authorization'}
          </p>
        </div>

        <button
          onClick={() => (currentStep > 1 ? setCurrentStep(currentStep - 1) : window.history.back())}
          className="btn-ghost flex items-center gap-2 text-xs font-semibold px-4 py-2.5 self-start sm:self-center"
        >
          <ArrowLeft className="w-4 h-4 text-zinc-400" />
          <span>Back</span>
        </button>
      </div>

      {/* Step indicator with high-tech tactical glowing styling */}
      <div className="grid grid-cols-3 gap-3 sm:gap-4">
        {[
          { step: 1, label: 'Configure', desc: 'Tier & Capacity' },
          { step: 2, label: 'Assign Instances', desc: 'Room Deployment' },
          { step: 3, label: 'Payment', desc: 'Secure Settlement' },
        ].map((item) => {
          const isCurrent = currentStep === item.step;
          const isUnlocked = item.step <= maxStep;
          const isDone = item.step < currentStep;

          return (
            <div
              key={item.step}
              onClick={() => goStep(item.step)}
              title={isUnlocked ? item.label : 'Complete the current step first'}
              className={`p-3 sm:p-4 rounded-xl border transition-all duration-200 flex items-center gap-3 ${
                isCurrent
                  ? 'bg-gradient-to-r from-emerald-500/15 via-emerald-500/5 to-transparent border-emerald-500/50 shadow-[0_0_20px_rgba(16,185,129,0.18)] cursor-pointer'
                  : isDone
                    ? 'bg-[#0a0e17]/80 border-emerald-500/30 text-zinc-300 hover:border-emerald-500/50 cursor-pointer'
                    : isUnlocked
                      ? 'bg-[#0a0e17]/60 border-[#1f293d]/80 text-zinc-400 hover:border-zinc-700 cursor-pointer'
                      : 'bg-[#0a0e17]/40 border-[#1f293d]/40 text-zinc-600 opacity-50 cursor-not-allowed'
              }`}
            >
              <div
                className={`w-7 h-7 sm:w-8 sm:h-8 rounded-lg flex items-center justify-center text-xs font-bold shrink-0 transition-all ${
                  isCurrent
                    ? 'bg-emerald-500 text-slate-950 shadow-[0_0_12px_rgba(16,185,129,0.5)]'
                    : isDone
                      ? 'bg-emerald-950/80 border border-emerald-500/40 text-emerald-400'
                      : 'bg-zinc-800/80 border border-zinc-700/50 text-zinc-400'
                }`}
              >
                {isDone ? <Check className="w-4 h-4 stroke-[3]" /> : item.step}
              </div>
              <div className="min-w-0">
                <div className={`text-xs sm:text-sm font-semibold truncate ${isCurrent ? 'text-white' : 'text-zinc-300'}`}>
                  {item.label}
                </div>
                <div className="text-[11px] text-zinc-500 hidden sm:block truncate">
                  {item.desc}
                </div>
              </div>
            </div>
          );
        })}
      </div>

        {currentStep === 1 && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 items-start">
          {/* Main Config Column */}
          <div className="lg:col-span-2 space-y-6">
            <TiltCard3D glowColor="emerald" className="p-6 space-y-6">
              <div>
                <h3 className="text-base font-bold text-white flex items-center gap-2">
                  <Zap className="w-4 h-4 text-emerald-400" />
                  License Profile
                </h3>
                <p className="text-xs text-zinc-400 mt-1">
                  Select bot execution tier, capacity quotas, and duration.
                </p>
              </div>

              {/* Tier Cards */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div
                  onClick={() => setTier('basic')}
                  className={`p-4 rounded-xl border cursor-pointer transition-all duration-200 relative ${
                    tier === 'basic'
                      ? 'bg-emerald-500/10 border-emerald-500/60 shadow-[0_0_20px_rgba(16,185,129,0.15)]'
                      : 'bg-[#06080d]/80 border-[#1f293d] hover:border-zinc-700'
                  }`}
                >
                  <div className="flex justify-between items-center mb-2">
                    <span className="text-sm font-bold text-white">Standard Fleet</span>
                    <span className="text-xs text-emerald-400 font-semibold px-2 py-0.5 rounded-full bg-emerald-500/15 border border-emerald-500/30">
                      from $2.00/char
                    </span>
                  </div>
                  <p className="text-xs text-zinc-400 leading-relaxed">
                    Automated gathering, troop training in all 4 barracks, and daily routine claims.
                  </p>
                  {tier === 'basic' && (
                    <span className="absolute top-2 right-2 w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_8px_#10b981]" />
                  )}
                </div>

                <div
                  onClick={() => setTier('pro')}
                  className={`p-4 rounded-xl border cursor-pointer transition-all duration-200 relative ${
                    tier === 'pro'
                      ? 'bg-amber-500/10 border-amber-500/60 shadow-[0_0_20px_rgba(245,158,11,0.15)]'
                      : 'bg-[#06080d]/80 border-[#1f293d] hover:border-zinc-700'
                  }`}
                >
                  <div className="flex justify-between items-center mb-2">
                    <span className="text-sm font-bold text-white">Autonomous Pro</span>
                    <span className="text-xs text-amber-400 font-semibold px-2 py-0.5 rounded-full bg-amber-500/15 border border-amber-500/30">
                      from $3.50/char
                    </span>
                  </div>
                  <p className="text-xs text-zinc-400 leading-relaxed">
                    Everything in Standard, plus account progression, smart healing, and event automation.
                  </p>
                  {tier === 'pro' && (
                    <span className="absolute top-2 right-2 w-2 h-2 rounded-full bg-amber-400 shadow-[0_0_8px_#f59e0b]" />
                  )}
                </div>
              </div>

              {/* Slot Counter */}
              <div className="space-y-3 pt-3 border-t border-[#1f293d]/80">
                <div className="flex justify-between items-center">
                  <span className="text-xs font-semibold text-white">Managed Characters</span>
                  <span className="text-xs text-zinc-400">
                    Current Rate:{' '}
                    <span className="text-emerald-400 font-bold">${baseRatePerChar.toFixed(2)}</span> / slot
                  </span>
                </div>
                <div className="flex items-center gap-3 bg-[#06080d]/90 border border-[#1f293d] p-3 rounded-xl">
                  <span className="flex-1 text-xs text-zinc-300 pl-1 font-medium">
                    Concurrent slots requested: <strong className="text-white">{characterCount}</strong>
                  </span>
                  <button
                    onClick={() => setCharacterCount((c) => Math.max(1, c - 1))}
                    className="w-9 h-9 rounded-lg border border-zinc-700 bg-zinc-800/80 hover:bg-zinc-700 text-white font-bold text-sm flex items-center justify-center transition"
                  >
                    -
                  </button>
                  <span className="w-10 text-center text-base font-bold text-emerald-400">
                    {characterCount}
                  </span>
                  <button
                    onClick={() => setCharacterCount((c) => Math.min(100, c + 1))}
                    className="w-9 h-9 rounded-lg border border-zinc-700 bg-zinc-800/80 hover:bg-zinc-700 text-white font-bold text-sm flex items-center justify-center transition"
                  >
                    +
                  </button>
                </div>
              </div>

              {/* Volume Discount Strip */}
              <div className="pt-3 border-t border-[#1f293d]/80">
                <div className="flex items-center justify-between mb-2.5">
                  <span className="text-xs font-semibold text-white">Volume Tier Scaling</span>
                  <span className="text-[11px] text-zinc-500">Auto-applies based on character count</span>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  {VOLUME_TIERS.map((t) => {
                    const active =
                      characterCount >= t.min &&
                      (VOLUME_TIERS[VOLUME_TIERS.indexOf(t) + 1]?.min ?? 101) > characterCount;
                    const rate = tier === 'basic' ? t.std : t.std * PRO_MULTIPLIER;
                    return (
                      <div
                        key={t.label}
                        className={`p-3 rounded-xl border transition-all ${
                          active
                            ? 'bg-emerald-500/15 border-emerald-500/60 shadow-[0_0_15px_rgba(16,185,129,0.15)]'
                            : 'bg-[#06080d]/60 border-[#1f293d]'
                        }`}
                      >
                        <span className="block text-xs font-bold text-white">{t.label}</span>
                        <span
                          className={`block text-xs mt-1 font-semibold ${
                            active ? 'text-emerald-300' : 'text-zinc-500'
                          }`}
                        >
                          ${rate.toFixed(2)} / char
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Duration Options */}
              <div className="grid grid-cols-2 gap-4 pt-3 border-t border-[#1f293d]/80">
                <div
                  onClick={() => setBillingDays(30)}
                  className={`p-4 rounded-xl border cursor-pointer text-center transition-all ${
                    billingDays === 30
                      ? 'bg-emerald-500/15 border-emerald-500/60 text-white shadow-[0_0_15px_rgba(16,185,129,0.15)]'
                      : 'bg-[#06080d]/80 border-[#1f293d] text-zinc-400 hover:border-zinc-700'
                  }`}
                >
                  <span className="block text-xs font-bold">30 Days</span>
                  <span className="block text-xs text-zinc-500 mt-1">Standard monthly deployment</span>
                </div>
                <div
                  onClick={() => setBillingDays(90)}
                  className={`p-4 rounded-xl border cursor-pointer text-center transition-all ${
                    billingDays === 90
                      ? 'bg-emerald-500/15 border-emerald-500/60 text-white shadow-[0_0_15px_rgba(16,185,129,0.15)]'
                      : 'bg-[#06080d]/80 border-[#1f293d] text-zinc-400 hover:border-zinc-700'
                  }`}
                >
                  <div className="flex items-center justify-center gap-1.5">
                    <span className="text-xs font-bold">90 Days</span>
                    <span className="text-[10px] bg-amber-500/20 text-amber-300 border border-amber-500/30 px-1.5 py-0.5 rounded font-bold">
                      SAVE 15%
                    </span>
                  </div>
                  <span className="block text-xs text-zinc-500 mt-1">Extended quarterly campaign</span>
                </div>
              </div>
            </TiltCard3D>

            {/* What's Included */}
            <div className="card p-6">
              <h3 className="text-sm font-bold text-white mb-4 flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-emerald-400" />
                Included In This Tier
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6 text-xs">
                <div className="space-y-2.5">
                  <span className="text-xs font-semibold text-zinc-400 uppercase tracking-wider block border-b border-[#1f293d] pb-1.5">
                    Gathering &amp; Training
                  </span>
                  {[
                    'Automatic resource gathering, day and night',
                    'Full march dispatch across all queues',
                    'Troop training in all four barracks',
                    'Completed troops collected automatically',
                  ].map((f) => (
                    <div key={f} className="flex items-center gap-2 text-zinc-300">
                      <Check className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                      <span>{f}</span>
                    </div>
                  ))}
                </div>
                <div className="space-y-2.5">
                  <span className="text-xs font-semibold text-zinc-400 uppercase tracking-wider block border-b border-[#1f293d] pb-1.5">
                    Alliance &amp; Daily Routine
                  </span>
                  {[
                    'Alliance help sent on schedule',
                    'Technology donations to recommended research',
                    'Daily city collection and routine tasks',
                    'Runs in the cloud — zero emulator burden',
                  ].map((f) => (
                    <div key={f} className="flex items-center gap-2 text-zinc-300">
                      <Check className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                      <span>{f}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Sticky Order Summary Column */}
          <TiltCard3D glowColor="emerald" className="p-6 space-y-6 lg:sticky lg:top-6">
            <h3 className="text-sm font-bold text-white border-b border-[#1f293d] pb-3 flex items-center justify-between">
              <span>Order Summary</span>
              <span className="text-xs font-normal text-emerald-400">Live Quota</span>
            </h3>

            <div className="space-y-3 text-xs">
              <div className="flex justify-between text-zinc-400">
                <span>Item</span>
                <span className="text-white font-medium">{itemName}</span>
              </div>
              <div className="flex justify-between text-zinc-400">
                <span>Plan Tier</span>
                <span className="text-white font-medium">
                  {tier === 'basic' ? 'Standard Fleet' : 'Autonomous Pro'}
                </span>
              </div>
              <div className="flex justify-between text-zinc-400">
                <span>Character Limit</span>
                <span className="text-white font-medium">{characterCount} accounts</span>
              </div>
              <div className="flex justify-between text-zinc-400">
                <span>Rate</span>
                <span className="text-white font-medium">${baseRatePerChar.toFixed(2)} / char</span>
              </div>
              <div className="flex justify-between text-zinc-400">
                <span>Duration</span>
                <span className="text-white font-medium">{billingDays} Days</span>
              </div>
            </div>

            {/* Promos & Referrals */}
            <div className="space-y-3 pt-3 border-t border-[#1f293d]">
              <div>
                <label className="block text-xs font-medium text-zinc-400 mb-1.5">Promo Code</label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={promoCode}
                    onChange={(e) => setPromoCode(e.target.value)}
                    placeholder="Enter promo code"
                    className="input-dark flex-1 px-3 py-2 text-xs"
                  />
                  <button
                    onClick={() => setPromoApplied(promoCode.trim().length > 0)}
                    className="btn-ghost text-xs px-3.5 py-2"
                  >
                    Apply
                  </button>
                </div>
                {promoApplied && (
                  <p className="text-xs text-emerald-400 mt-1 flex items-center gap-1">
                    <Check className="w-3 h-3" /> Promo code validated.
                  </p>
                )}
              </div>

              <div>
                <label className="block text-xs font-medium text-zinc-400 mb-1.5">Referral Code</label>
                <input
                  type="text"
                  value={referralCode}
                  onChange={(e) => setReferralCode(e.target.value)}
                  placeholder="Partner referral ID (Optional)"
                  className="input-dark w-full px-3 py-2 text-xs"
                />
                <span className="text-[11px] text-zinc-500 mt-1 block">
                  Grants active runtime bonus upon node deployment.
                </span>
              </div>
            </div>

            {/* Total Due & Action */}
            <div className="pt-4 border-t border-[#1f293d] space-y-4">
              <div className="flex justify-between items-baseline">
                <span className="text-xs text-zinc-400 font-medium">Total Due</span>
                <span className="text-3xl font-black text-white tracking-tight">
                  ${totalPrice}
                </span>
              </div>

              <button
                onClick={() => continueTo(2)}
                className="btn-primary w-full py-3.5 text-xs font-bold flex items-center justify-center gap-2 shadow-[0_0_25px_rgba(16,185,129,0.3)]"
              >
                <span>Continue to Assignment</span>
                <ChevronRight className="w-4 h-4" />
              </button>

              <div className="flex items-center justify-center gap-2 text-xs text-zinc-500 pt-1">
                <ShieldCheck className="w-4 h-4 text-emerald-400" />
                <span>Encrypted 256-bit War Room Session</span>
              </div>
            </div>
          </TiltCard3D>
        </div>
      )}

      {/* STEP 2: ASSIGN INSTANCES */}
      {currentStep === 2 && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 items-start">
          <div className="lg:col-span-2 space-y-6">
            <TiltCard3D glowColor="emerald" className="p-6 space-y-5">
              <div>
                <h3 className="text-base font-bold text-white flex items-center gap-2">
                  <Layers className="w-4 h-4 text-emerald-400" />
                  Apply To Instance
                </h3>
                <p className="text-xs text-zinc-400 mt-1">
                  Choose an existing bot instance or create a brand new fleet worker.
                </p>
              </div>

              {EXISTING_INSTANCES.length === 0 && (
                <div className="p-5 rounded-xl border border-dashed border-[#1f293d] bg-[#06080d]/50 text-center">
                  <p className="text-xs font-semibold text-zinc-300">No active instances yet</p>
                  <p className="text-xs text-zinc-500 mt-1">
                    This account has no provisioned bot workers. Create your first instance below.
                  </p>
                </div>
              )}

              {EXISTING_INSTANCES.map((inst) => (
                <div
                  key={inst.id}
                  onClick={() => setAssignTarget(inst.id)}
                  className={`p-4 rounded-xl border cursor-pointer transition-all duration-200 flex items-center gap-3 ${
                    assignTarget === inst.id
                      ? 'bg-emerald-500/10 border-emerald-500/60 shadow-[0_0_20px_rgba(16,185,129,0.15)]'
                      : 'bg-[#06080d]/80 border-[#1f293d] hover:border-zinc-700'
                  }`}
                >
                  <div className="flex-1">
                    <div className="text-sm font-bold text-white">{inst.label}</div>
                    <div className="text-xs text-zinc-400 mt-0.5">{inst.detail}</div>
                  </div>
                  {assignTarget === inst.id && <Check className="w-5 h-5 text-emerald-400" />}
                </div>
              ))}

              <div
                onClick={() => setAssignTarget('new')}
                className={`p-4 rounded-xl border cursor-pointer transition-all duration-200 flex items-center gap-3.5 ${
                  assignTarget === 'new'
                    ? 'bg-emerald-500/10 border-emerald-500/60 shadow-[0_0_20px_rgba(16,185,129,0.15)]'
                    : 'bg-[#06080d]/80 border-dashed border-[#1f293d] hover:border-zinc-700'
                }`}
              >
                <div className="w-10 h-10 rounded-lg bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center shrink-0">
                  <Plus className="w-5 h-5 text-emerald-400" />
                </div>
                <div className="flex-1">
                  <div className="text-sm font-bold text-white">New Dedicated Instance</div>
                  <div className="text-xs text-zinc-400 mt-0.5">Spin up a fresh cloud bot worker</div>
                </div>
                {assignTarget === 'new' && <Check className="w-5 h-5 text-emerald-400" />}
              </div>
            </TiltCard3D>

            <TiltCard3D glowColor="emerald" className="p-6 space-y-4">
              <div>
                <h3 className="text-base font-bold text-white">Farm Room Identifier</h3>
                <p className="text-xs text-zinc-400 mt-1">
                  Name the fleet operational room for these {characterCount} bot farms.
                </p>
              </div>
              <input
                type="text"
                value={newRoomName}
                onChange={(e) => setNewRoomName(e.target.value)}
                placeholder="Room name (e.g. Main Room / Sector Delta)"
                className="input-dark w-full px-4 py-3 text-sm"
              />
            </TiltCard3D>
          </div>

          {/* Sticky Assignment Summary */}
          <TiltCard3D glowColor="emerald" className="p-6 space-y-5 lg:sticky lg:top-6">
            <h3 className="text-sm font-bold text-white border-b border-[#1f293d] pb-3">
              Instance Assignment
            </h3>

            <div className="space-y-3 text-xs">
              <div className="flex justify-between text-zinc-400">
                <span>Item</span>
                <span className="text-white font-medium">
                  {itemName} × {characterCount} slots
                </span>
              </div>
              <div className="flex justify-between text-zinc-400">
                <span>Target Node</span>
                <span className="text-white font-medium">
                  {assignTarget === 'new' ? 'New Dedicated Instance' : activeInstance?.label}
                </span>
              </div>
              <div className="flex justify-between text-zinc-400">
                <span>Assigned Room</span>
                <span className="text-emerald-400 font-semibold">{effectiveRoom.trim() || '—'}</span>
              </div>
              <div className="flex justify-between text-zinc-400 pt-2 border-t border-[#1f293d]">
                <span>Total Due</span>
                <span className="text-2xl font-black text-white">${totalPrice}</span>
              </div>
            </div>

            <button
              onClick={() => continueTo(3)}
              disabled={!effectiveRoom.trim()}
              title={!effectiveRoom.trim() ? 'Enter a room name first' : 'Continue to Payment'}
              className="btn-primary w-full py-3.5 text-xs font-bold flex items-center justify-center gap-2 disabled:opacity-40"
            >
              <span>Continue to Payment</span>
              <ChevronRight className="w-4 h-4" />
            </button>
          </TiltCard3D>
        </div>
      )}

      {/* STEP 3: PAYMENT & CONFIRMATION */}
      {currentStep === 3 && !placed && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 items-start">
          <div className="lg:col-span-2 space-y-6">
            <TiltCard3D glowColor="emerald" className="p-6 space-y-6">
              <div>
                <h3 className="text-base font-bold text-white flex items-center gap-2">
                  <Shield className="w-4 h-4 text-emerald-400" />
                  Payment Gateway
                </h3>
                <p className="text-xs text-zinc-400 mt-1">
                  14-day guaranteed refund period applies. Instant activation upon clearance.
                </p>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
                {PAY_METHODS.map((m) => {
                  const Icon = m.Icon;
                  const selected = payMethod === m.id;
                  return (
                    <button
                      key={m.id}
                      onClick={() => setPayMethod(m.id)}
                      className={`p-4 rounded-xl border text-left transition-all duration-200 flex items-center gap-3.5 ${
                        selected
                          ? 'bg-emerald-500/15 border-emerald-500/60 shadow-[0_0_20px_rgba(16,185,129,0.18)]'
                          : 'bg-[#06080d]/80 border-[#1f293d] hover:border-zinc-700'
                      }`}
                    >
                      <Icon />
                      <span className="min-w-0 flex-1">
                        <span className={`block text-xs font-bold ${selected ? 'text-white' : 'text-zinc-300'}`}>
                          {m.id}
                        </span>
                        <span className="block text-xs text-zinc-400 mt-0.5 truncate">{m.sub}</span>
                      </span>
                      {selected && <Check className="w-4 h-4 text-emerald-400 ml-auto shrink-0" />}
                    </button>
                  );
                })}
              </div>

              <label className="flex items-start gap-3 text-xs text-zinc-400 cursor-pointer pt-2 border-t border-[#1f293d]">
                <input
                  type="checkbox"
                  checked={agreed}
                  onChange={(e) => setAgreed(e.target.checked)}
                  className="w-4 h-4 mt-0.5 accent-emerald-500 rounded cursor-pointer"
                />
                <span>
                  I agree to the Terms of Service, Autonomous Fleet Policy, and 14-day Refund Guarantee.
                </span>
              </label>
            </TiltCard3D>
          </div>

          {/* Sticky Final Review */}
          <TiltCard3D glowColor="emerald" className="p-6 space-y-5 lg:sticky lg:top-6">
            <h3 className="text-sm font-bold text-white border-b border-[#1f293d] pb-3">
              Final Review
            </h3>

            <div className="space-y-3 text-xs">
              <div className="flex justify-between text-zinc-400">
                <span>Item</span>
                <span className="text-white font-medium">
                  {itemName} · {tier === 'basic' ? 'Standard' : 'Pro'} · {billingDays}d
                </span>
              </div>
              <div className="flex justify-between text-zinc-400">
                <span>Slots</span>
                <span className="text-white font-medium">{characterCount}</span>
              </div>
              <div className="flex justify-between text-zinc-400">
                <span>Assign to</span>
                <span className="text-white font-medium text-right">
                  {assignTarget === 'new' ? 'New instance' : activeInstance?.label} · {effectiveRoom.trim() || '—'}
                </span>
              </div>
              <div className="flex justify-between text-zinc-400">
                <span>Payment Method</span>
                <span className="text-emerald-400 font-semibold">{payMethod}</span>
              </div>

              <div className="pt-3 border-t border-[#1f293d] flex justify-between items-baseline">
                <span className="text-xs text-zinc-400 font-medium">Total Due</span>
                <span className="text-3xl font-black text-white tracking-tight">${totalPrice}</span>
              </div>
            </div>

            <button
              onClick={placeOrder}
              disabled={!agreed}
              className="btn-primary w-full py-3.5 text-xs font-bold disabled:opacity-40 shadow-[0_0_25px_rgba(16,185,129,0.3)]"
            >
              Place Order &amp; Launch
            </button>

            {orderErr && (
              <p className="text-xs text-rose-400 bg-rose-500/10 border border-rose-500/30 p-2.5 rounded-lg">
                {orderErr}
              </p>
            )}
          </TiltCard3D>
        </div>
      )}

      {/* ORDER RECEIVED / SUCCESS STATE */}
      {currentStep === 3 && placed && (
        <TiltCard3D glowColor="emerald" className="p-10 text-center space-y-4 max-w-xl mx-auto">
          <div className="relative w-16 h-16 mx-auto rounded-full bg-emerald-500/15 border border-emerald-500/40 flex items-center justify-center shadow-[0_0_30px_rgba(16,185,129,0.3)]">
            <span className="absolute inline-flex h-full w-full rounded-full animate-ping bg-emerald-400/20" />
            <Check className="w-8 h-8 text-emerald-400 stroke-[2.5]" />
          </div>

          <h3 className="text-2xl font-black text-white tracking-tight">Order Dispatched to Fleet</h3>
          <p className="text-sm text-zinc-400 leading-relaxed max-w-md mx-auto">
            {itemName} · {characterCount} slots · {billingDays} days —{' '}
            <span className="text-emerald-400 font-bold">${totalPrice}</span> via {payMethod}.
            Our orchestration engine is provisioning your cloud worker instance.
          </p>

          {orderId && (
            <div className="pt-4">
              <button
                onClick={() => (window.location.href = `/bots/${orderId}`)}
                className="btn-primary px-8 py-3 text-sm font-bold shadow-[0_0_25px_rgba(16,185,129,0.3)]"
              >
                Open Bot HUD →
              </button>
            </div>
          )}
        </TiltCard3D>
      )}
    </div>
  );
}
