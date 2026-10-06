"use client";

import React, { useState } from "react";
import { Star } from "lucide-react";

export default function LeaderboardPage() {
  const [tab, setTab] = useState<"month" | "all">("month");
  const [hidden, setHidden] = useState(false);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-white">Leaderboard</h1>
        <p className="text-sm text-zinc-500">Top resource gatherers by total units harvested.</p>
      </div>

      <div className="card p-5">
        <div className="flex flex-wrap items-center gap-3 mb-5">
          <div className="flex rounded-lg bg-[#0b0b0e] border border-[#25252e] p-1">
            {(["month", "all"] as const).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`px-4 py-1.5 rounded-md text-xs font-semibold transition-colors ${
                  tab === t ? "bg-[#5865F2] text-white" : "text-zinc-400 hover:text-white"
                }`}
              >
                {t === "month" ? "This Month" : "All-Time"}
              </button>
            ))}
          </div>
          <label className="ml-auto flex items-center gap-2 text-xs text-zinc-400 cursor-pointer">
            <button
              role="switch"
              aria-checked={hidden}
              onClick={() => setHidden(!hidden)}
              className={`w-9 h-5 rounded-full p-0.5 transition-colors ${hidden ? "bg-[#5865F2]" : "bg-[#25252e]"}`}
            >
              <span className={`block w-4 h-4 rounded-full bg-white transition-transform ${hidden ? "translate-x-4" : ""}`} />
            </button>
            Hide My Display Name
          </label>
        </div>

        {/* Zeroed board */}
        <div className="py-10 text-center">
          <p className="text-sm font-semibold text-white">No rankings yet</p>
          <p className="text-xs text-zinc-500 mt-1">
            {tab === "month" ? "This month" : "All-time"} standings will appear once fleets start gathering.
          </p>
        </div>
      </div>

      {/* Empty community rating */}
      <div className="card p-5">
        <div className="flex flex-wrap items-center gap-3">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">Community Rating</div>
            <div className="mt-1.5 flex items-center gap-2">
              <span className="text-2xl font-bold text-white">0.0</span>
              <span className="flex gap-0.5">
                {[0, 1, 2, 3, 4].map((i) => (
                  <Star key={i} className="w-4 h-4 text-zinc-700" />
                ))}
              </span>
              <span className="text-xs text-zinc-500 uppercase">0 reviews</span>
            </div>
            <p className="mt-1 text-xs text-zinc-500">No reviews yet — ratings open after the first orders.</p>
          </div>
          <button disabled className="ml-auto btn-ghost px-4 py-2 text-xs opacity-50 cursor-not-allowed">
            View reviews
          </button>
        </div>
      </div>
    </div>
  );
}
