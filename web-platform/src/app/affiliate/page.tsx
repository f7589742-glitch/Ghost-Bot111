"use client";

import React, { useState } from "react";
import { Copy, Check, Wallet } from "lucide-react";

export default function AffiliatePage() {
  const [copied, setCopied] = useState(false);
  const refLink = "https://aegisfleet.cloud/ref/MALEK11332";

  function copy() {
    navigator.clipboard.writeText(refLink).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-white">Affiliate Hub</h1>
        <p className="text-sm text-zinc-500">Referrals, commissions and payout requests.</p>
      </div>

      {/* Zeroed stat boxes */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: "Pending Payout", value: "$0.00" },
          { label: "Paid Out", value: "$0.00" },
          { label: "Referred Volume", value: "$0.00" },
          { label: "Commission Tier", value: "20%" },
        ].map((s) => (
          <div key={s.label} className="card p-4">
            <div className="text-xs text-zinc-500 font-medium">{s.label}</div>
            <div className="mt-1.5 text-2xl font-bold text-white">{s.value}</div>
          </div>
        ))}
      </div>

      {/* Referral link */}
      <div className="card p-5">
        <h2 className="text-sm font-bold text-white mb-1">Referral Link</h2>
        <p className="text-xs text-zinc-500 mb-3">Share your link — earn 20% lifetime commission on every order.</p>
        <div className="flex gap-2">
          <input readOnly value={refLink} className="input-dark flex-1 px-3 py-2 text-sm" />
          <button onClick={copy} className="btn-primary flex items-center gap-2 px-4 py-2 text-sm">
            {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
      </div>

      {/* Payout request — zeroed */}
      <div className="card p-5">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2 text-sm text-zinc-300">
            <Wallet className="w-4 h-4 text-zinc-500" />
            Minimum payout threshold: <span className="font-bold text-white">$20.00</span>
          </div>
          <div className="ml-auto text-xs text-zinc-500">Current balance: $0.00 — $20.00 to go</div>
        </div>
        <div className="mt-3 h-2 rounded-full bg-[#0b0b0e] border border-[#25252e] overflow-hidden">
          <div className="h-full bg-[#5865F2] rounded-full" style={{ width: "0%" }} />
        </div>
        <button disabled className="btn-ghost mt-4 px-4 py-2 text-sm opacity-50 cursor-not-allowed">
          Request Payout (locked)
        </button>
      </div>

      {/* Empty history */}
      <div className="card overflow-hidden">
        <div className="px-5 py-4 border-b border-[#25252e]">
          <h2 className="text-sm font-bold text-white">Payout History</h2>
        </div>
        <div className="px-5 py-8 text-center">
          <p className="text-sm text-zinc-500">No payouts yet.</p>
          <p className="text-xs text-zinc-600 mt-1">Your referral earnings will appear here.</p>
        </div>
      </div>
    </div>
  );
}
