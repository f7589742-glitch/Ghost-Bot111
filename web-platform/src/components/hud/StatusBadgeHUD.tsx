"use client";

import React from "react";

export type BotState = "running" | "stopped" | "checking" | "combat" | "gathering" | "idle";

interface StatusBadgeHUDProps {
  status: BotState | boolean | null;
  label?: string;
  size?: "sm" | "md" | "lg";
}

export default function StatusBadgeHUD({ status, label, size = "md" }: StatusBadgeHUDProps) {
  let normalized: BotState = "idle";
  if (typeof status === "boolean") {
    normalized = status ? "running" : "stopped";
  } else if (status) {
    normalized = status;
  }

  const configs = {
    running: {
      color: "text-emerald-400",
      bg: "bg-emerald-500/10",
      border: "border-emerald-500/30",
      dot: "bg-emerald-400",
      ping: "bg-emerald-400/40",
      defaultLabel: "OPERATIONAL",
    },
    stopped: {
      color: "text-amber-400",
      bg: "bg-amber-500/10",
      border: "border-amber-500/30",
      dot: "bg-amber-400",
      ping: "bg-amber-400/30",
      defaultLabel: "STANDBY",
    },
    checking: {
      color: "text-cyan-400",
      bg: "bg-cyan-500/10",
      border: "border-cyan-500/30",
      dot: "bg-cyan-400",
      ping: "bg-cyan-400/40",
      defaultLabel: "SCANNING",
    },
    combat: {
      color: "text-rose-400",
      bg: "bg-rose-500/10",
      border: "border-rose-500/30",
      dot: "bg-rose-400",
      ping: "bg-rose-400/40",
      defaultLabel: "COMBAT ENGAGED",
    },
    gathering: {
      color: "text-yellow-400",
      bg: "bg-yellow-500/10",
      border: "border-yellow-500/30",
      dot: "bg-yellow-400",
      ping: "bg-yellow-400/40",
      defaultLabel: "GATHERING",
    },
    idle: {
      color: "text-zinc-400",
      bg: "bg-zinc-800/40",
      border: "border-zinc-700/40",
      dot: "bg-zinc-400",
      ping: "bg-zinc-400/20",
      defaultLabel: "IDLE",
    },
  }[normalized];

  const sizeClasses = {
    sm: "px-2 py-0.5 text-[10px]",
    md: "px-2.5 py-1 text-xs",
    lg: "px-3.5 py-1.5 text-sm",
  }[size];

  return (
    <div
      className={`inline-flex items-center gap-2 rounded-full border backdrop-blur-md font-semibold tracking-wide uppercase ${configs.bg} ${configs.border} ${configs.color} ${sizeClasses}`}
    >
      <span className="relative flex h-2 w-2">
        <span className={`absolute inline-flex h-full w-full rounded-full animate-radar ${configs.ping}`} />
        <span className={`relative inline-flex rounded-full h-2 w-2 ${configs.dot}`} />
      </span>
      <span>{label || configs.defaultLabel}</span>
    </div>
  );
}