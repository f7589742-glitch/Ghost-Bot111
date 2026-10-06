"use client";

import React from "react";

export default function GhostBotSvgSprite() {
  return (
<svg width="0" height="0" style={{ position: "absolute", pointerEvents: "none" }}>
    <defs>
      <linearGradient id="ghostBodyGrad" x1="15%" y1="5%" x2="85%" y2="95%">
        <stop offset="0%" stopColor="#f2feff"/>
        <stop offset="45%" stopColor="#64f0ff"/>
        <stop offset="100%" stopColor="#00a8cc"/>
      </linearGradient>
      <linearGradient id="cyberGoldGrad" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stopColor="#fff3b0"/>
        <stop offset="50%" stopColor="#facc15"/>
        <stop offset="100%" stopColor="#d97706"/>
      </linearGradient>
      <linearGradient id="cyberCyanGrad" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stopColor="#a5f3fc"/>
        <stop offset="50%" stopColor="#00e5ff"/>
        <stop offset="100%" stopColor="#0284c7"/>
      </linearGradient>
      <linearGradient id="reactorGlowGrad" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stopColor="#00e5ff"/>
        <stop offset="50%" stopColor="#00f2fe"/>
        <stop offset="100%" stopColor="#00e699"/>
      </linearGradient>
      <radialGradient id="haloAura" cx="50%" cy="50%" r="50%">
        <stop offset="0%" stopColor="rgba(0, 229, 255, 0.45)"/>
        <stop offset="100%" stopColor="rgba(0, 229, 255, 0)"/>
      </radialGradient>

      {/* GhostBot Mascot */}
      <symbol id="ghostbot-mascot" viewBox="0 0 100 100">
        <circle cx="50" cy="52" r="42" fill="url(#haloAura)"/>
        <line x1="51" y1="20" x2="49" y2="10" stroke="#00e5ff" strokeWidth="3.2" strokeLinecap="round"/>
        <circle cx="48.5" cy="8.5" r="4.5" fill="#c4fcff" stroke="#00e5ff" strokeWidth="2"/>
        <path d="M52 19 C34 19 25 31 24 47 C22 54 15 58 14 62 C14 65 20 66 24 64 C23 71 17 75 12 77 C18 83 29 83 35 79 C39 84 46 85 51 81 C56 85 64 84 67 77 C71 75 74 68 74 61 C78 63 83 62 84 58 C84 54 78 49 76 44 C75 29 67 19 52 19 Z"
              fill="url(#ghostBodyGrad)" stroke="#05162e" strokeWidth="3.2" strokeLinejoin="round"/>
        <rect x="33" y="28" width="37" height="24" rx="11" fill="#05142b" stroke="#00e5ff" strokeWidth="1.8"/>
        <path d="M40 39 C41.5 35.5, 45.5 35.5, 47 39" fill="none" stroke="#62f2ff" strokeWidth="2.8" strokeLinecap="round"/>
        <path d="M56 39 C57.5 35.5, 61.5 35.5, 63 39" fill="none" stroke="#62f2ff" strokeWidth="2.8" strokeLinecap="round"/>
        <path d="M47.5 44 C49.5 47.2, 53.5 47.2, 55.5 44" fill="none" stroke="#62f2ff" strokeWidth="2.6" strokeLinecap="round"/>
        <g className="gear-rotator">
          <circle cx="47" cy="66" r="6.5" fill="#05142b" stroke="#00e5ff" strokeWidth="2"/>
          <circle cx="47" cy="66" r="2.6" fill="#62f2ff"/>
        </g>
      </symbol>

      {/* Custom Cyber Mail (Updates Inbox) & Cyber Bell (Notifications) Icons */}
      <symbol id="icon-cyber-mail" viewBox="0 0 24 24">
        <rect x="2.5" y="4.5" width="19" height="15" rx="3" fill="rgba(0,229,255,0.15)" stroke="#00e5ff" strokeWidth="1.8"/>
        <polyline points="3 6 12 13 21 6" fill="none" stroke="#a5f3fc" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
        <circle cx="18.5" cy="6.5" r="2.5" fill="#facc15" stroke="#05142b" strokeWidth="1"/>
      </symbol>

      <symbol id="icon-cyber-bell" viewBox="0 0 24 24">
        <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" fill="rgba(0,229,255,0.16)" stroke="#00e5ff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
        <path d="M13.73 21a2 2 0 0 1-3.46 0" stroke="#facc15" strokeWidth="2" strokeLinecap="round"/>
        <path d="M19.5 4.5C20.8 5.8 21.5 7.5 21.5 9" fill="none" stroke="#62f2ff" strokeWidth="1.4" strokeLinecap="round"/>
        <path d="M4.5 4.5C3.2 5.8 2.5 7.5 2.5 9" fill="none" stroke="#62f2ff" strokeWidth="1.4" strokeLinecap="round"/>
      </symbol>

      {/* Avatar & Commander Emblems */}
      <symbol id="icon-crown-royal" viewBox="0 0 24 24">
        <path d="M3 18h18v2H3v-2zm0-2l2-9 5 4 2-6 2 6 5-4 2 9H3z" fill="url(#cyberGoldGrad)" stroke="#00e5ff" strokeWidth="1.2" strokeLinejoin="round"/>
        <circle cx="12" cy="3" r="1.5" fill="#00e5ff"/>
        <circle cx="5" cy="5.5" r="1.2" fill="#00e5ff"/>
        <circle cx="19" cy="5.5" r="1.2" fill="#00e5ff"/>
      </symbol>

      <symbol id="icon-blades-tactical" viewBox="0 0 24 24">
        <path d="M14.5 17.5L3 6V3h3l11.5 11.5-3 3z" fill="url(#cyberCyanGrad)" stroke="#e2f8ff" strokeWidth="1.2"/>
        <path d="M13 19l6-6M16 16l4 4M19 21l2-2" stroke="#00e5ff" strokeWidth="2" strokeLinecap="round"/>
        <path d="M9.5 17.5L21 6V3h-3L6.5 14.5l3 3z" fill="none" stroke="#facc15" strokeWidth="1.6"/>
        <path d="M11 19l-6-6M8 16l-4 4M5 21l-2-2" stroke="#facc15" strokeWidth="2" strokeLinecap="round"/>
      </symbol>

      <symbol id="icon-aegis-shield" viewBox="0 0 24 24">
        <path d="M12 2L4 5.5v6.2c0 5.4 3.4 9.9 8 11.3 4.6-1.4 8-5.9 8-11.3V5.5L12 2z" fill="rgba(0,229,255,0.18)" stroke="#00e5ff" strokeWidth="1.8" strokeLinejoin="round"/>
        <path d="M12 6.5l4 2v3.5c0 2.9-1.7 5.4-4 6.4-2.3-1-4-3.5-4-6.4V8.5l4-2z" fill="url(#cyberCyanGrad)"/>
      </symbol>

      {/* UI Utility & Action Icons */}
      <symbol id="icon-edit-pen" viewBox="0 0 24 24">
        <path d="M12 20h9" stroke="#00e5ff" strokeWidth="2" strokeLinecap="round"/>
        <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" fill="rgba(0,229,255,0.18)" stroke="#00e5ff" strokeWidth="1.8" strokeLinejoin="round"/>
      </symbol>

      <symbol id="icon-globe-cyber" viewBox="0 0 24 24">
        <circle cx="12" cy="12" r="9.5" fill="none" stroke="#00e5ff" strokeWidth="1.8"/>
        <ellipse cx="12" cy="12" rx="4.2" ry="9.5" fill="none" stroke="#00e5ff" strokeWidth="1.5"/>
        <line x1="2.5" y1="12" x2="21.5" y2="12" stroke="#00e5ff" strokeWidth="1.5"/>
        <line x1="4.5" y1="7.5" x2="19.5" y2="7.5" stroke="#00e5ff" strokeWidth="1.1" strokeOpacity="0.7"/>
        <line x1="4.5" y1="16.5" x2="19.5" y2="16.5" stroke="#00e5ff" strokeWidth="1.1" strokeOpacity="0.7"/>
      </symbol>

      <symbol id="icon-lighting-prism" viewBox="0 0 24 24">
        <circle cx="12" cy="12" r="4.5" fill="url(#cyberCyanGrad)" stroke="#fff" strokeWidth="1.2"/>
        <path d="M12 2v3M12 19v3M4.93 4.93l2.12 2.12M16.95 16.95l2.12 2.12M2 12h3M19 12h3M4.93 19.07l2.12-2.12M16.95 7.05l2.12-2.12" stroke="#00e5ff" strokeWidth="2" strokeLinecap="round"/>
      </symbol>

      <symbol id="icon-power-play" viewBox="0 0 24 24">
        <polygon points="6 4 20 12 6 20 6 4" fill="currentColor" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round"/>
      </symbol>

      <symbol id="icon-plus-node" viewBox="0 0 24 24">
        <rect x="3" y="3" width="18" height="18" rx="5" fill="rgba(0,229,255,0.12)" stroke="currentColor" strokeWidth="1.8"/>
        <line x1="12" y1="7.5" x2="12" y2="16.5" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"/>
        <line x1="7.5" y1="12" x2="16.5" y2="12" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"/>
      </symbol>

      <symbol id="icon-rss-crate" viewBox="0 0 24 24">
        <path d="M21 8.5l-9-5-9 5v7l9 5 9-5v-7z" fill="rgba(0,229,255,0.15)" stroke="#00e5ff" strokeWidth="1.8" strokeLinejoin="round"/>
        <polyline points="3.3 8.7 12 13.5 20.7 8.7" fill="none" stroke="#00e5ff" strokeWidth="1.6"/>
        <line x1="12" y1="20.5" x2="12" y2="13.5" stroke="#00e5ff" strokeWidth="1.6"/>
      </symbol>

      <symbol id="icon-commander-badge" viewBox="0 0 24 24">
        <circle cx="12" cy="8" r="4" fill="rgba(0,229,255,0.22)" stroke="#00e5ff" strokeWidth="1.8"/>
        <path d="M4.5 20c1.5-3.8 4.3-5.5 7.5-5.5s6 1.7 7.5 5.5" fill="none" stroke="#00e5ff" strokeWidth="1.8" strokeLinecap="round"/>
      </symbol>

      <symbol id="icon-search-radar" viewBox="0 0 24 24">
        <circle cx="11" cy="11" r="7" fill="rgba(0,229,255,0.1)" stroke="#00e5ff" strokeWidth="2"/>
        <circle cx="11" cy="11" r="2.5" fill="#00e5ff"/>
        <line x1="16.2" y1="16.2" x2="21" y2="21" stroke="#00e5ff" strokeWidth="2.2" strokeLinecap="round"/>
      </symbol>

      <symbol id="icon-close-x" viewBox="0 0 24 24">
        <line x1="18" y1="6" x2="6" y2="18" stroke="#00e5ff" strokeWidth="2.2" strokeLinecap="round"/>
        <line x1="6" y1="6" x2="18" y2="18" stroke="#00e5ff" strokeWidth="2.2" strokeLinecap="round"/>
      </symbol>

      <symbol id="icon-analytics-chart" viewBox="0 0 24 24">
        <rect x="3" y="13" width="4" height="8" rx="1" fill="#00e5ff"/>
        <rect x="10" y="8" width="4" height="13" rx="1" fill="#62f2ff"/>
        <rect x="17" y="4" width="4" height="17" rx="1" fill="#facc15"/>
      </symbol>

      <symbol id="icon-doc-report" viewBox="0 0 24 24">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" fill="rgba(0,229,255,0.14)" stroke="#00e5ff" strokeWidth="1.8"/>
        <polyline points="14 2 14 8 20 8" fill="none" stroke="#00e5ff" strokeWidth="1.8"/>
        <line x1="8" y1="13" x2="16" y2="13" stroke="#00e5ff" strokeWidth="1.8" strokeLinecap="round"/>
        <line x1="8" y1="17" x2="13" y2="17" stroke="#00e5ff" strokeWidth="1.8" strokeLinecap="round"/>
      </symbol>

      {/* Custom Kingdom Resource Icons */}
      <symbol id="icon-res-food" viewBox="0 0 24 24">
        <path d="M12 2v20M12 6c-3 0-5 2.2-5 5 3 0 5-2.2 5-5zm0 5c-3 0-5 2.2-5 5 3 0 5-2.2 5-5zm0-5c3 0 5 2.2 5 5-3 0-5-2.2-5-5zm0 5c3 0 5 2.2 5 5-3 0-5-2.2-5-5z" fill="#facc15" stroke="#fde047" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
      </symbol>

      <symbol id="icon-res-wood" viewBox="0 0 24 24">
        <polygon points="12 2 4 12 9 12 5 18 19 18 15 12 20 12 12 2" fill="rgba(0,230,153,0.3)" stroke="#00e699" strokeWidth="1.8" strokeLinejoin="round"/>
        <line x1="12" y1="18" x2="12" y2="22" stroke="#00e699" strokeWidth="2.4" strokeLinecap="round"/>
      </symbol>

      <symbol id="icon-res-stone" viewBox="0 0 24 24">
        <polygon points="12 3 4 9 6 20 18 20 20 9 12 3" fill="rgba(203,232,255,0.28)" stroke="#cbe8ff" strokeWidth="1.8" strokeLinejoin="round"/>
        <polyline points="4 9 12 13 20 9" fill="none" stroke="#cbe8ff" strokeWidth="1.5"/>
        <line x1="12" y1="13" x2="12" y2="20" stroke="#cbe8ff" strokeWidth="1.5"/>
      </symbol>

      <symbol id="icon-res-gold" viewBox="0 0 24 24">
        <circle cx="12" cy="12" r="9" fill="rgba(255,170,43,0.25)" stroke="#ffaa2b" strokeWidth="2"/>
        <polygon points="12 6.5 14.2 10.2 18.2 11 15 14 15.8 18 12 16 8.2 18 9 14 5.8 11 9.8 10.2 12 6.5" fill="#ffaa2b"/>
      </symbol>

      <symbol id="icon-res-gems" viewBox="0 0 24 24">
        <polygon points="6 3 18 3 22 9 12 21 2 9 6 3" fill="rgba(192,132,252,0.3)" stroke="#c084fc" strokeWidth="1.8" strokeLinejoin="round"/>
        <polyline points="2 9 22 9" stroke="#e9d5ff" strokeWidth="1.4"/>
        <polyline points="6 3 12 9 18 3" fill="none" stroke="#e9d5ff" strokeWidth="1.4"/>
        <polyline points="12 9 12 21" stroke="#e9d5ff" strokeWidth="1.4"/>
      </symbol>
    
      {/* Professional Vector Game & Tactical Icons */}
      <symbol id="icon-crop-wheat" viewBox="0 0 24 24">
        <path d="M12 2v20M8 5c2 0 4 1.5 4 4-2 0-4-1.5-4-4zm8 0c-2 0-4 1.5-4 4 2 0 4-1.5 4-4zm-8 6c2 0 4 1.5 4 4-2 0-4-1.5-4-4zm8 0c-2 0-4 1.5-4 4 2 0 4-1.5 4-4z" fill="none" stroke="#facc15" strokeWidth="1.8" strokeLinecap="round"/>
      </symbol>
      <symbol id="icon-castle-fort" viewBox="0 0 24 24">
        <path d="M3 21h18M4 21V9l3-3v3l2-2v2l3-3 3 3v-2l2 2v-3l3 3v12M9 21v-5a3 3 0 0 1 6 0v5" fill="none" stroke="#00e5ff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
      </symbol>
      <symbol id="icon-swords-crossed" viewBox="0 0 24 24">
        <path d="M14.5 17.5L3 6V3h3l11.5 11.5-3 3z" fill="rgba(0,229,255,0.2)" stroke="#00e5ff" strokeWidth="1.6"/>
        <path d="M9.5 17.5L21 6V3h-3L6.5 14.5l3 3z" fill="none" stroke="#62f2ff" strokeWidth="1.6"/>
      </symbol>
      <symbol id="icon-shield-crest" viewBox="0 0 24 24">
        <path d="M12 2L4 5v6c0 5.5 3.8 10.7 8 12 4.2-1.3 8-6.5 8-12V5l-8-3z" fill="rgba(0,229,255,0.18)" stroke="#00e5ff" strokeWidth="1.8" strokeLinejoin="round"/>
      </symbol>
      <symbol id="icon-horse-cavalry" viewBox="0 0 24 24">
        <path d="M19 8c-1.5-3-4-5-7-5-4 0-7 3.5-7 8 0 3 1.5 5.5 3.5 7L7 22h10l-1.5-4c2-1.5 3.5-4 3.5-7 0-1-.3-2-.8-3h.8z" fill="none" stroke="#00e699" strokeWidth="1.8" strokeLinejoin="round"/>
      </symbol>
      <symbol id="icon-bow-archer" viewBox="0 0 24 24">
        <path d="M5 2c6 0 14 8 14 10s-8 10-14 10V2zM5 12h14M16 9l3 3-3 3" fill="none" stroke="#ffaa2b" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
      </symbol>
      <symbol id="icon-catapult-siege" viewBox="0 0 24 24">
        <circle cx="7" cy="18" r="3" fill="none" stroke="#c084fc" strokeWidth="1.8"/>
        <circle cx="17" cy="18" r="3" fill="none" stroke="#c084fc" strokeWidth="1.8"/>
        <path d="M4 18h16M7 15l7-9 6 3M12 9v6" fill="none" stroke="#c084fc" strokeWidth="1.8" strokeLinecap="round"/>
      </symbol>
      <symbol id="icon-treasure-chest" viewBox="0 0 24 24">
        <rect x="3" y="10" width="18" height="11" rx="2" fill="rgba(250,204,21,0.15)" stroke="#facc15" strokeWidth="1.8"/>
        <path d="M3 10a9 9 0 0 1 18 0M10 13h4v3h-4z" fill="none" stroke="#facc15" strokeWidth="1.8"/>
      </symbol>
      <symbol id="icon-crown-vip" viewBox="0 0 24 24">
        <path d="M3 18h18l-2-12-5 5-2-7-2 7-5-5-2 12z" fill="rgba(250,204,21,0.2)" stroke="#facc15" strokeWidth="1.8" strokeLinejoin="round"/>
        <circle cx="12" cy="4" r="1.5" fill="#facc15"/>
        <circle cx="4" cy="7" r="1.5" fill="#facc15"/>
        <circle cx="20" cy="7" r="1.5" fill="#facc15"/>
      </symbol>
      <symbol id="icon-handshake-alliance" viewBox="0 0 24 24">
        <path d="M11 15h2l4-4-2-2-4 4-2-2-4 4 2 2 4-2zM3 11l4-4 2 2M21 11l-4-4-2 2" fill="none" stroke="#00e5ff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
      </symbol>
      <symbol id="icon-hospital-cross" viewBox="0 0 24 24">
        <rect x="3" y="3" width="18" height="18" rx="4" fill="rgba(239,68,68,0.15)" stroke="#f87171" strokeWidth="1.8"/>
        <path d="M12 7v10M7 12h10" stroke="#f87171" strokeWidth="2.2" strokeLinecap="round"/>
      </symbol>
      <symbol id="icon-balance-scale" viewBox="0 0 24 24">
        <path d="M12 3v18M3 8l9-3 9 3M6 8l-3 7h6l-3-7zm12 0l-3 7h6l-3-7zM8 21h8" fill="none" stroke="#00e5ff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
      </symbol>
      <symbol id="icon-lightning-bolt" viewBox="0 0 24 24">
        <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" fill="rgba(250,204,21,0.25)" stroke="#facc15" strokeWidth="1.8" strokeLinejoin="round"/>
      </symbol>
      <symbol id="icon-hammer-builder" viewBox="0 0 24 24">
        <path d="M15 4l5 5-3 3-5-5 3-3zM13.5 7.5L5 16l3 3 8.5-8.5" fill="none" stroke="#ffaa2b" strokeWidth="1.8" strokeLinejoin="round"/>
      </symbol>
      <symbol id="icon-flask-science" viewBox="0 0 24 24">
        <path d="M9 3h6M10 3v5l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3" fill="rgba(168,85,247,0.18)" stroke="#c084fc" strokeWidth="1.8" strokeLinejoin="round"/>
        <path d="M7 16h10" stroke="#c084fc" strokeWidth="1.5"/>
      </symbol>
      <symbol id="icon-monument-temple" viewBox="0 0 24 24">
        <path d="M3 21h18M4 18h16M5 18V9M9 18V9M15 18V9M19 18V9M2 9l10-6 10 6" fill="none" stroke="#00e5ff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
      </symbol>
      <symbol id="icon-anvil-forge" viewBox="0 0 24 24">
        <path d="M4 7h16l-3 4H7L4 7zM7 11v6l-3 4h16l-3-4v-6" fill="rgba(0,229,255,0.15)" stroke="#00e5ff" strokeWidth="1.8" strokeLinejoin="round"/>
      </symbol>
      <symbol id="icon-radar-dashboard" viewBox="0 0 24 24">
        <rect x="3" y="3" width="7" height="7" rx="1.5" fill="rgba(0,229,255,0.18)" stroke="#00e5ff" strokeWidth="1.8"/>
        <rect x="14" y="3" width="7" height="7" rx="1.5" fill="rgba(0,229,255,0.18)" stroke="#00e5ff" strokeWidth="1.8"/>
        <rect x="14" y="14" width="7" height="7" rx="1.5" fill="rgba(0,229,255,0.18)" stroke="#00e5ff" strokeWidth="1.8"/>
        <rect x="3" y="14" width="7" height="7" rx="1.5" fill="rgba(0,229,255,0.18)" stroke="#00e5ff" strokeWidth="1.8"/>
      </symbol>
      <symbol id="icon-store-cart" viewBox="0 0 24 24">
        <circle cx="9" cy="20" r="1.5" fill="#00e5ff"/>
        <circle cx="18" cy="20" r="1.5" fill="#00e5ff"/>
        <path d="M1 2h3l2.6 12.5a2 2 0 0 0 2 1.5h9.8a2 2 0 0 0 2-1.5L22 6H5.2" fill="none" stroke="#00e5ff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
      </symbol>
      <symbol id="icon-trophy-tier" viewBox="0 0 24 24">
        <path d="M6 3h12v6a6 6 0 0 1-12 0V3zM6 6H3a3 3 0 0 0 3 3M18 6h3a3 3 0 0 1-3 3M12 15v3M8 21h8" fill="rgba(250,204,21,0.2)" stroke="#facc15" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
      </symbol>

      <symbol id="icon-shield-tactical" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
      </symbol>
      <symbol id="icon-swords-cross" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <polyline points="14.5 17.5 3 6 3 3 6 3 17.5 14.5"/>
        <line x1="13" y1="19" x2="19" y2="13"/>
        <line x1="16" y1="16" x2="20" y2="20"/>
        <line x1="19" y1="21" x2="21" y2="19"/>
        <polyline points="14.5 6.5 18 3 21 3 21 6 17.5 9.5"/>
        <line x1="5" y1="14" x2="9" y2="18"/>
        <line x1="7" y1="17" x2="3" y2="21"/>
        <line x1="4" y1="20" x2="7" y2="21"/>
      </symbol>
      <symbol id="icon-harvest-grain" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M2 22L12 12"/>
        <path d="M12 2a5 5 0 0 0-5 5v5a5 5 0 0 0 10 0V7a5 5 0 0 0-5-5z"/>
        <path d="M7 12a5 5 0 0 0 10 0"/>
      </symbol>

    </defs>
  </svg>
  );
}
