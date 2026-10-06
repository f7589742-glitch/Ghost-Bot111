"use client";

import React, { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import TacticalSidebar from "./hud/TacticalSidebar";
import { getAllBots, bootOwner } from "@/lib/cloud";
import { type OwnedBot } from "@/lib/store";
import { useGhostBot } from "@/components/SupabaseProvider";

import { useLanguage } from "@/context/LanguageContext";

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { bots: sbBots } = useGhostBot();
  const [bots, setBots] = useState<OwnedBot[]>([]);
  const [clock, setClock] = useState("");
  const { lang, toggleLang, t } = useLanguage();

  useEffect(() => {
    bootOwner().then(() => {
      getAllBots().then((b) => {
        setBots(b);
      });
    });
  }, [pathname]);

  useEffect(() => {
    function updateClock() {
      const now = new Date();
      setClock(now.toUTCString().replace("GMT", "UTC"));
    }
    updateClock();
    const interval = setInterval(updateClock, 1000);
    return () => clearInterval(interval);
  }, []);

  if (pathname === "/login" || pathname.startsWith("/auth")) {
    return <>{children}</>;
  }

  const activeBots = (sbBots && Array.isArray(sbBots) && sbBots.length > 0) ? sbBots : bots;

  return (
    <div className="app-shell">
      <TacticalSidebar bots={activeBots} />
      <main className="workspace">
        <div className="workspace-inner">
          {/* Top Workspace HUD with UTC clock and language switcher */}
          <div className="workspace-top-hud h-12 px-4 sm:px-5 mb-4 rounded-xl bg-[#07132a]/60 border border-[#00e5ff]/20 flex items-center justify-between">
            <div className="workspace-hud-left flex items-center gap-3 font-mono text-xs">
              <span className="hud-status-node text-[#00e699] font-bold flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-[#00e699] animate-pulse" />
                {t("ghostbot_core", "GHOSTBOT CORE")}
              </span>
              <span className="text-[#00e5ff]/30">|</span>
              <span className="hud-clock-mono text-[#8fa7c7]">{clock || "UTC CLOCK"}</span>
            </div>
            <div className="workspace-hud-right flex items-center gap-3">
              <button
                className="hud-lang-toggle px-3.5 py-1.5 rounded-full bg-[#00e5ff]/10 border border-[#00e5ff]/30 text-[#00e5ff] text-xs font-bold hover:bg-[#00e5ff]/20 transition-all flex items-center gap-2"
                onClick={toggleLang}
                title={lang === "ar" ? "Switch to English" : "التبديل إلى العربية"}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="10" />
                  <line x1="2" y1="12" x2="22" y2="12" />
                  <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
                </svg>
                <span>{t("lang_toggle_label", lang === "ar" ? "English" : "العربية")}</span>
              </button>
            </div>
          </div>

          {children}
        </div>
      </main>
    </div>
  );
}

export default AppShell;