"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { Trash2, Radio, Shield, Compass, Swords, Cpu, RefreshCw, Filter } from "lucide-react";
import { getRecentActivity, getBotStatus } from "@/lib/api";
import TiltCard3D from "@/components/hud/TiltCard3D";

type FilterType = "all" | "gather" | "combat" | "alliance" | "system";

export default function ActivityPage() {
  const [lines, setLines] = useState<string[]>([]);
  const [filter, setFilter] = useState<FilterType>("all");
  const [paused, setPaused] = useState(false);
  const [running, setRunning] = useState<boolean | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    // Sequential polling: next request is scheduled only after the current
    // one settles — no stacked pending fetches in the connection pool.
    let timeoutId: ReturnType<typeof setTimeout> | undefined;
    let cancelled = false;
    const controller = new AbortController();

    const load = async () => {
      try {
        if (!paused) {
          const fresh = await getRecentActivity(undefined, controller.signal);
          if (alive && fresh.length && !controller.signal.aborted) setLines(fresh.slice(-200));
          const s = await getBotStatus();
          if (alive && !controller.signal.aborted) setRunning(s.running);
        }
      } finally {
        if (!cancelled) timeoutId = setTimeout(load, 5000);
      }
    };
    load();
    return () => {
      alive = false;
      cancelled = true;
      controller.abort();
      if (timeoutId !== undefined) clearTimeout(timeoutId);
    };
  }, [paused]);

  useEffect(() => {
    if (!paused) {
      boxRef.current?.scrollTo({ top: boxRef.current.scrollHeight, behavior: "smooth" });
    }
  }, [lines, paused]);

  const filteredLines = useMemo(() => lines.filter((l) => {
    if (filter === "all") return true;
    const low = l.toLowerCase();
    if (filter === "gather") return low.includes("gather") || low.includes("food") || low.includes("wood") || low.includes("stone") || low.includes("tile") || low.includes("node");
    if (filter === "combat") return low.includes("barb") || low.includes("combat") || low.includes("fight") || low.includes("attack");
    if (filter === "alliance") return low.includes("alliance") || low.includes("tech") || low.includes("donate") || low.includes("help") || low.includes("gift");
    if (filter === "system") return low.includes("scheduler") || low.includes("started") || low.includes("stopped") || low.includes("switch");
    return true;
  }), [lines, filter]);

  function getEventMeta(line: string) {
    const low = line.toLowerCase();
    if (low.includes("combat") || low.includes("barb")) {
      return { icon: Swords, color: "text-rose-400", tag: "COMBAT", border: "border-rose-500/20 bg-rose-500/5" };
    }
    if (low.includes("gather") || low.includes("food") || low.includes("wood") || low.includes("stone")) {
      return { icon: Compass, color: "text-emerald-400", tag: "GATHER", border: "border-emerald-500/20 bg-emerald-500/5" };
    }
    if (low.includes("alliance") || low.includes("tech") || low.includes("donate")) {
      return { icon: Shield, color: "text-amber-400", tag: "ALLIANCE", border: "border-amber-500/20 bg-amber-500/5" };
    }
    return { icon: Cpu, color: "text-cyan-400", tag: "ENGINE", border: "border-cyan-500/20 bg-cyan-500/5" };
  }

  return (
    <div className="w-full space-y-6 font-sans">
      {/* 1. Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-6 border-b border-zinc-800/80">
        <div>
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-cyan-400 animate-ping" />
            <span className="text-[10px] font-mono tracking-widest text-cyan-400 uppercase">
              WIRE PROTOCOL · REALTIME TELEMETRY
            </span>
          </div>
          <h1 className="text-3xl font-extrabold font-mono tracking-tight text-white mt-1">
            MISSION TELEMETRY CONSOLE
          </h1>
          <p className="text-xs text-zinc-400 font-mono mt-1">
            Real-time event stream directly from AWS EC2 headless fleet engine.
          </p>
        </div>

        <div className="flex items-center gap-2 font-mono text-xs">
          <button
            onClick={() => setPaused(!paused)}
            className={`px-3.5 py-1.5 rounded-lg border font-semibold transition-all ${
              paused
                ? "bg-amber-500/20 border-amber-500/40 text-amber-300"
                : "bg-emerald-500/20 border-emerald-500/40 text-emerald-300"
            }`}
          >
            {paused ? "STREAM PAUSED" : "LIVE RADAR ACTIVE"}
          </button>
          <button
            onClick={() => setLines([])}
            className="p-2 rounded-lg border border-zinc-800 bg-zinc-900/60 hover:bg-zinc-800 text-zinc-400 hover:text-white"
            title="Clear Stream"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* 2. Top Metric Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <TiltCard3D glowColor="cyan" className="p-4">
          <span className="text-[10px] font-mono text-zinc-400 uppercase tracking-widest">GATEWAY LINK</span>
          <div className="text-lg font-bold font-mono text-white mt-1">AWS eu-north-1</div>
          <div className="text-[11px] font-mono text-emerald-400 mt-1">● 16.171.9.216 ONLINE</div>
        </TiltCard3D>
        <TiltCard3D glowColor="emerald" className="p-4">
          <span className="text-[10px] font-mono text-zinc-400 uppercase tracking-widest">PACKETS LOGGED</span>
          <div className="text-lg font-bold font-mono text-white mt-1">{lines.length} Frames</div>
          <div className="text-[11px] font-mono text-zinc-500 mt-1">Buffered in session</div>
        </TiltCard3D>
        <TiltCard3D glowColor="gold" className="p-4">
          <span className="text-[10px] font-mono text-zinc-400 uppercase tracking-widest">FLEET ENGINE</span>
          <div className="text-lg font-bold font-mono text-white mt-1">{running ? "RUNNING" : "STANDBY"}</div>
          <div className="text-[11px] font-mono text-amber-400 mt-1">Autonomous Loop Active</div>
        </TiltCard3D>
        <TiltCard3D glowColor="default" className="p-4">
          <span className="text-[10px] font-mono text-zinc-400 uppercase tracking-widest">SECURITY STATUS</span>
          <div className="text-lg font-bold font-mono text-white mt-1">STEALTH 444</div>
          <div className="text-[11px] font-mono text-emerald-400 mt-1">Protected Transport</div>
        </TiltCard3D>
      </div>

      {/* 3. Filter Navigation Chips */}
      <div className="flex flex-wrap items-center gap-2 font-mono text-xs">
        <span className="text-zinc-500 flex items-center gap-1 mr-2 text-[11px]">
          <Filter className="w-3.5 h-3.5" /> FILTER:
        </span>
        {(["all", "gather", "combat", "alliance", "system"] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-3 py-1.5 rounded-lg uppercase tracking-wider text-[11px] font-bold border transition-all ${
              filter === f
                ? "bg-emerald-500/20 border-emerald-500/40 text-emerald-300 shadow-[0_0_12px_rgba(16,185,129,0.2)]"
                : "border-zinc-800 bg-zinc-900/40 text-zinc-400 hover:text-white"
            }`}
          >
            {f}
          </button>
        ))}
      </div>

      {/* 4. Stream Console Terminal */}
      <TiltCard3D glowColor="cyan" className="p-0 overflow-hidden bg-black/85">
        <div className="px-5 py-3 border-b border-zinc-800/80 bg-zinc-950/60 flex items-center justify-between font-mono text-xs">
          <div className="flex items-center gap-2">
            <Radio className="w-4 h-4 text-emerald-400 animate-pulse" />
            <span className="text-zinc-300 font-bold uppercase tracking-wider">
              TELEMETRY EVENT STREAM
            </span>
          </div>
          <span className="text-[10px] text-zinc-500">
            SHOWING {filteredLines.length} OF {lines.length} EVENTS
          </span>
        </div>

        <div
          ref={boxRef}
          className="p-4 h-[460px] overflow-y-auto font-mono text-xs space-y-2 bg-[#06080d]/90"
        >
          {filteredLines.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-zinc-600 space-y-2">
              <RefreshCw className="w-6 h-6 animate-spin text-zinc-700" />
              <p>Awaiting game telemetry frames from the fleet engine...</p>
              <p className="text-[10px]">Start fleet or trigger pulse cycle from Dashboard to inspect live packets.</p>
            </div>
          ) : (
            filteredLines.map((l, i) => {
              const meta = getEventMeta(l);
              const Icon = meta.icon;
              return (
                <div
                  key={i}
                  className={`flex items-start gap-3 p-2.5 rounded-lg border ${meta.border}`}
                >
                  <div className={`p-1 rounded bg-black/40 ${meta.color} shrink-0 mt-0.5`}>
                    <Icon className="w-3.5 h-3.5" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className={`text-[9px] font-bold uppercase px-1.5 py-0.2 rounded border ${meta.color} border-current/30`}>
                        {meta.tag}
                      </span>
                    </div>
                    <p className="text-zinc-200 text-[11px] leading-relaxed break-all font-mono">
                      {l}
                    </p>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </TiltCard3D>
    </div>
  );
}