"use client";

import React, { useEffect, useState, useRef, useMemo } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useGhostBot } from "@/components/SupabaseProvider";
import { useLanguage } from "@/context/LanguageContext";
import {
  getSavedRecipients,
  startRssTransfer,
  getTransferStatus,
  stopTransferJob,
  getFleetGrouped,
  getBotInventory,
} from "@/lib/api";
import { ITEM_FOOD_BASE64, ITEM_WOOD_BASE64, ITEM_STONE_BASE64, ITEM_GOLD_BASE64 } from "@/lib/gameIconsBase64";

const RSS_META = {
  food: { name: "FOOD", labelAr: "قمح", icon: ITEM_FOOD_BASE64, color: "#facc15", fillGrad: "linear-gradient(90deg, #ca8a04, #facc15)" },
  wood: { name: "WOOD", labelAr: "خشب", icon: ITEM_WOOD_BASE64, color: "#22c55e", fillGrad: "linear-gradient(90deg, #15803d, #22c55e)" },
  stone: { name: "STONE", labelAr: "حجر", icon: ITEM_STONE_BASE64, color: "#38bdf8", fillGrad: "linear-gradient(90deg, #0284c7, #38bdf8)" },
  gold: { name: "GOLD", labelAr: "ذهب", icon: ITEM_GOLD_BASE64, color: "#f97316", fillGrad: "linear-gradient(90deg, #c2410c, #f97316)" },
};

interface AccountTelemetry {
  email: string;
  status: "RUNNING" | "COMPLETED";
}

interface WorkerTelemetry {
  role_id: string;
  name: string;
  email?: string;
  stage_msg: string;
  market_lvl: number;
  tax_rate: number;
  sent_amount: number;
  sent_rss?: Record<string, number>;
  status: "WAITING" | "RUNNING" | "DRAINED" | "SKIPPED" | "FAILED";
}

interface ActiveJobTelemetry {
  job_id: string;
  target_role_id: string;
  target_name?: string;
  x: number;
  y: number;
  status: "RUNNING" | "COMPLETED" | "PARTIAL" | "CANCELLED" | "FAILED";
  requested: Record<string, number>;
  delivered: Record<string, number>;
  accounts?: AccountTelemetry[];
  workers: WorkerTelemetry[];
}

export default function RSSTransferPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, bots, accounts: userAccounts } = useGhostBot();
  const { lang } = useLanguage();
  const isAr = lang === "ar";

  const queryBotId = searchParams?.get("bot") || searchParams?.get("bot_id") || "";
  const queryUserId = searchParams?.get("user_id") || user?.id || "";

  const [activeBotId, setActiveBotId] = useState<string>(queryBotId);
  const [activeUserId, setActiveUserId] = useState<string>(queryUserId);

  useEffect(() => {
    if (queryBotId) setActiveBotId(queryBotId);
    else if (bots && bots.length > 0 && !activeBotId) {
      setActiveBotId(bots[0].bot_id || bots[0].id || "bot-1");
    }
  }, [queryBotId, bots]);

  useEffect(() => {
    if (user?.id && !activeUserId) setActiveUserId(user.id);
  }, [user, activeUserId]);

  const activeBot = useMemo(() => {
    return (bots || []).find((b: any) => b.id === activeBotId || b.bot_id === activeBotId) || (bots && bots.length > 0 ? bots[0] : null);
  }, [bots, activeBotId]);

  const handleBotChange = (newBotId: string) => {
    setActiveBotId(newBotId);
    hasInitializedSelection.current = false;
    router.replace(`/transfer?bot=${encodeURIComponent(newBotId)}&user_id=${encodeURIComponent(activeUserId || user?.id || "")}`);
  };

  // Order State
  const [order, setOrder] = useState({
    target_role_id: "",
    x: 419,
    y: 513,
    requested_rss: { food: 0, wood: 0, stone: 0, gold: 0 } as Record<string, number>,
    selected_farm_roles: [] as string[],
  });

  const [availableFarms, setAvailableFarms] = useState<any[]>([]);
  const [savedRecipients, setSavedRecipients] = useState<any[]>([]);
  const [activeJob, setActiveJob] = useState<ActiveJobTelemetry | null>(null);
  const [isLaunching, setIsLaunching] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");

  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const hasInitializedSelection = useRef(false);

  // Formatting Helpers
  const formatShort = (val: number | undefined | null) => {
    if (!val) return "0";
    if (val >= 1_000_000_000) return (val / 1_000_000_000).toFixed(1) + "B";
    if (val >= 1_000_000) return (val / 1_000_000).toFixed(1) + "M";
    if (val >= 1_000) return (val / 1_000).toFixed(0) + "K";
    return val.toLocaleString();
  };

  const formatMetric = (val: number | undefined | null) => {
    if (!val) return "0.00M";
    return (val / 1_000_000).toFixed(2) + "M";
  };

  const getPercentage = (cur: number | undefined, total: number | undefined) => {
    if (!total || total <= 0) return 0;
    return Math.min(100, Math.max(0, Math.round(((cur || 0) / total) * 100)));
  };

  const getGrossFormatted = (net: number | undefined | null) => {
    if (!net || net <= 0) return "0";
    return Math.ceil(net / (1 - 0.19)).toLocaleString();
  };

  // Load Saved Recipients
  useEffect(() => {
    async function loadMeta() {
      try {
        const rec = await getSavedRecipients().catch(() => ({ recipients: [] }));
        if (rec?.recipients) setSavedRecipients(rec.recipients);
      } catch (err) {
        console.error("Failed to load recipients", err);
      }
    }
    loadMeta();
  }, []);

  // Fetch Available Farms with STRICT room tenancy & selection initialization
  const fetchFarms = async () => {
    try {
      const matched = (bots || []).find((b: any) => b.id === activeBotId || b.bot_id === activeBotId);
      const bId = matched?.bot_id || activeBotId || "bot-1";
      const uId = activeUserId || user?.id || "";
      const [grouped, inv] = await Promise.all([
        getFleetGrouped(bId, uId).catch(() => null),
        getBotInventory(bId !== "all" ? bId : "bot-1", undefined, undefined, uId).catch(() => null),
      ]);

      const farmMap = new Map<string, any>();

      (grouped?.accounts || []).forEach((acc: any) => {
        const accEmail = acc.email || "";
        (acc.characters || []).forEach((ch: any) => {
          const rId = String(ch.role_id || ch.id || "").trim();
          if (!rId || rId === "undefined" || rId === "null" || !/^\d+$/.test(rId)) return;
          const cityLvl = ch.city_level || ch.city_hall || 17;
          const isEnabled = ch.enabled !== false && ch.is_enabled !== false;

          farmMap.set(rId, {
            role_id: rId,
            name: ch.name || `Farm_${rId}`,
            email: accEmail,
            alliance_tag: ch.alliance_tag || "",
            power: ch.power || 0,
            city_level: cityLvl,
            enabled: isEnabled,
            tax_rate: cityLvl >= 25 ? 8 : cityLvl === 16 ? 20 : 19,
            resources: {
              food: Number(ch.food) || 0,
              wood: Number(ch.wood) || 0,
              stone: Number(ch.stone) || 0,
              gold: Number(ch.gold) || 0,
            },
          });
        });
      });

      // Augment/cross-verify with user accounts from Supabase context for this room
      const matchedInstanceId = matched?.id;
      (userAccounts || []).forEach((sa: any) => {
        if (matchedInstanceId && sa.instance_id && sa.instance_id !== matchedInstanceId) return;
        const rId = String(sa.role_id || "").trim();
        if (!rId || !/^\d+$/.test(rId)) return;
        if (!farmMap.has(rId)) {
          const cityLvl = sa.city_hall_level || 17;
          farmMap.set(rId, {
            role_id: rId,
            name: sa.governor_name || `Farm_${rId}`,
            email: sa.email || "",
            alliance_tag: "",
            power: sa.power || 0,
            city_level: cityLvl,
            enabled: sa.enabled !== false && sa.is_enabled !== false,
            tax_rate: cityLvl >= 25 ? 8 : cityLvl === 16 ? 20 : 19,
            resources: {
              food: Number(sa.food) || 0,
              wood: Number(sa.wood) || 0,
              stone: Number(sa.stone) || 0,
              gold: Number(sa.gold) || 0,
            },
          });
        }
      });

      (inv?.characters || []).forEach((ci: any) => {
        const rId = String(ci.role_id || ci.governor_id || "").trim();
        if (!rId || !farmMap.has(rId)) return;
        const ex = farmMap.get(rId);
        ex.resources.food = Number(ci.food) || ex.resources.food;
        ex.resources.wood = Number(ci.wood) || ex.resources.wood;
        ex.resources.stone = Number(ci.stone) || ex.resources.stone;
        ex.resources.gold = Number(ci.gold) || ex.resources.gold;
        if (ci.name) ex.name = ci.name;
        if (ci.city_hall) ex.city_level = ci.city_hall;
      });

      const farmList = Array.from(farmMap.values());
      setAvailableFarms(farmList);

      // Initialize default selection ONLY ONCE per room mount, selecting only ENABLED farms!
      if (farmList.length > 0 && !hasInitializedSelection.current) {
        hasInitializedSelection.current = true;
        const enabledFarmRoles = farmList.filter((f) => f.enabled !== false).map((f) => f.role_id);
        setOrder((prev) => ({
          ...prev,
          selected_farm_roles: enabledFarmRoles,
        }));
      }
    } catch (err) {
      console.error("Failed to load farms", err);
    }
  };

  useEffect(() => {
    fetchFarms();
  }, [activeBotId, activeUserId, bots]);

  // Selection Helpers
  const isFarmSelected = (id: string) => order.selected_farm_roles.includes(id);

  const toggleFarm = (id: string) => {
    setOrder((prev) => {
      const idx = prev.selected_farm_roles.indexOf(id);
      const next = [...prev.selected_farm_roles];
      if (idx > -1) next.splice(idx, 1);
      else next.push(id);
      return { ...prev, selected_farm_roles: next };
    });
  };

  const selectAllFarms = (status: boolean) => {
    setOrder((prev) => ({
      ...prev,
      selected_farm_roles: status ? availableFarms.map((f) => f.role_id) : [],
    }));
  };

  const setMaxAvailable = (res: "food" | "wood" | "stone" | "gold") => {
    const totalAvail = availableFarms
      .filter((f) => isFarmSelected(f.role_id))
      .reduce((sum, f) => sum + (f.resources?.[res] || 0), 0);
    const netCalculated = Math.max(0, Math.floor(totalAvail * 0.81));
    setOrder((prev) => ({
      ...prev,
      requested_rss: { ...prev.requested_rss, [res]: netCalculated },
    }));
  };

  // Launch Execution
  const startExecution = async () => {
    setErrorMsg("");
    if (!order.target_role_id.trim()) {
      setErrorMsg(isAr ? "يرجى إدخال معرّف الحساب المستلم (Recipient Governor ID)." : "Please enter recipient Governor ID.");
      return;
    }

    // STRICT: Only pass strictly selected farms that actually exist in availableFarms
    const strictlySelectedRoles = order.selected_farm_roles.filter((id) =>
      availableFarms.some((f) => f.role_id === id)
    );

    if (strictlySelectedRoles.length === 0) {
      setErrorMsg(isAr ? "يرجى تحديد مزرعة واحدة على الأقل للإرسال." : "Please select at least one farm to send from.");
      return;
    }

    const totalRss = Object.values(order.requested_rss).reduce((a, b) => a + b, 0);
    if (totalRss <= 0) {
      setErrorMsg(isAr ? "يرجى تحديد كمية الموارد المطلوبة للنقل." : "Please specify resource amounts to transfer.");
      return;
    }

    setIsLaunching(true);
    try {
      const payload = {
        target_role_id: order.target_role_id.trim(),
        target_name: `Target_${order.target_role_id.trim()}`,
        x: Number(order.x),
        y: Number(order.y),
        requested_rss: order.requested_rss,
        selected_farm_roles: strictlySelectedRoles,
        bot_id: activeBot?.bot_id || activeBotId || "bot-1",
        user_id: activeUserId || user?.id,
        transfer_mode: "total_net" as const,
      };

      const res = await startRssTransfer(payload);
      if (res && res.success && res.job_id) {
        // Collect accounts
        const accSet = new Set<string>();
        const initialWorkers: WorkerTelemetry[] = strictlySelectedRoles.map((rId) => {
          const farm = availableFarms.find((f) => f.role_id === rId);
          const email = farm?.email || `Account_${rId}`;
          accSet.add(email);
          const lvl = farm?.city_level || 17;
          return {
            role_id: rId,
            name: farm?.name || `Farm_${rId}`,
            email: email,
            stage_msg: "Waiting for march recall...",
            market_lvl: lvl,
            tax_rate: farm?.tax_rate || (lvl === 16 ? 20 : 19),
            sent_amount: 0,
            sent_rss: { food: 0, wood: 0, stone: 0, gold: 0 },
            status: "WAITING",
          };
        });

        const initialJob: ActiveJobTelemetry = {
          job_id: res.job_id,
          target_role_id: order.target_role_id,
          x: order.x,
          y: order.y,
          status: "RUNNING",
          requested: order.requested_rss,
          delivered: { food: 0, wood: 0, stone: 0, gold: 0 },
          accounts: Array.from(accSet).map((em) => ({ email: em, status: "RUNNING" })),
          workers: initialWorkers,
        };
        setActiveJob(initialJob);
        startPollingTelemetry(res.job_id);
      } else {
        throw new Error(res?.detail || res?.message || (isAr ? "فشل بدء مهمة النقل." : "Failed to initialize transfer."));
      }
    } catch (err: any) {
      setErrorMsg(err?.message || (isAr ? "فشل بدء مهمة النقل." : "Failed to start transfer job."));
      setIsLaunching(false);
    }
  };

  // Telemetry Polling (Pure telemetry, zero raw logs)
  const startPollingTelemetry = (jobId: string) => {
    if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);

    pollIntervalRef.current = setInterval(async () => {
      try {
        const data = await getTransferStatus(jobId);
        if (data) {
          setActiveJob((prev) => {
            if (!prev) return data;
            return {
              ...prev,
              job_id: data.job_id || prev.job_id,
              status: data.status || prev.status,
              target_role_id: data.target_role_id || prev.target_role_id,
              x: data.x !== undefined ? data.x : prev.x,
              y: data.y !== undefined ? data.y : prev.y,
              requested: data.requested || prev.requested,
              delivered: data.delivered || prev.delivered,
              accounts: data.accounts && data.accounts.length > 0 ? data.accounts : prev.accounts,
              workers: data.workers && data.workers.length > 0 ? data.workers : prev.workers,
            };
          });

          if (data.status && data.status !== "RUNNING") {
            if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
          }
        }
      } catch (e) {
        console.error("Telemetry poll error:", e);
      }
    }, 1200);
  };

  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    };
  }, []);

  const cancelJob = async () => {
    if (!activeJob) return;
    try {
      await stopTransferJob(activeJob.job_id);
      setActiveJob((prev) => (prev ? { ...prev, status: "CANCELLED" } : null));
    } catch (err) {
      console.error("Cancel failed:", err);
    }
  };

  const resetToNewJob = () => {
    if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    setActiveJob(null);
    setIsLaunching(false);
    fetchFarms();
  };

  const finishedFarmsCount = useMemo(() => {
    if (!activeJob) return 0;
    return (activeJob.workers || []).filter((w) => w.status === "DRAINED" || w.status === "SKIPPED" || w.status === "FAILED").length;
  }, [activeJob]);

  // Compute deficit summary if finished partially
  const deficitSummary = useMemo(() => {
    if (!activeJob || (activeJob.status !== "PARTIAL" && activeJob.status !== "COMPLETED")) return null;
    const deficits: { res: string; name: string; needed: number; delivered: number; missing: number }[] = [];
    (["food", "wood", "stone", "gold"] as const).forEach((r) => {
      const req = activeJob.requested?.[r] || 0;
      const deliv = activeJob.delivered?.[r] || 0;
      if (req > deliv) {
        deficits.push({
          res: r,
          name: RSS_META[r].name,
          needed: req,
          delivered: deliv,
          missing: req - deliv,
        });
      }
    });
    return deficits;
  }, [activeJob]);

  return (
    <div className="glass-ai-transfer-container">
      {/* Top Glass AI Bar */}
      <header className="glass-nav">
        <div className="brand-group">
          <div className="pulse-icon-box">
            <span className="pulse-glow"></span>
            <span className="icon">⚡</span>
          </div>
          <div>
            <h2 className="title-text">RSS Transfer Hub</h2>
            <p className="subtitle-text">Glass AI · Concurrent Caravan Dispatcher & Live Telemetry</p>
          </div>
        </div>
        <Link href={`/dashboard?tab=live&bot=${encodeURIComponent(activeBotId)}`} className="glass-btn-nav">
          ← {isAr ? "لوحة التحكم" : "Dashboard"}
        </Link>
      </header>

      {/* ROOM & TENANCY IDENTITY HUD CARD */}
      <section className="glass-tenancy-hud">
        <div className="hud-col room-col">
          <div className="hud-badge-icon">🏛️</div>
          <div className="hud-meta">
            <span className="hud-label-small">{isAr ? "غرفة التحكم النشطة (Active Bot Room)" : "Active Bot Room"}</span>
            <div className="hud-room-action-row">
              {bots && bots.length > 1 ? (
                <select
                  value={activeBot?.bot_id || activeBotId}
                  onChange={(e) => handleBotChange(e.target.value)}
                  className="hud-room-select"
                >
                  {bots.map((b: any) => (
                    <option key={b.id || b.bot_id} value={b.bot_id || b.id}>
                      {b.name || `Bot Unit #${b.bot_id || b.id}`} ({b.bot_id || b.id})
                    </option>
                  ))}
                </select>
              ) : (
                <span className="hud-val-bold">{activeBot?.name || activeBot?.bot_id || activeBotId || (isAr ? "غرفة غير محددة" : "Default Room")}</span>
              )}
              <span className="hud-pill-tag cyan">
                ID: {activeBot?.bot_id || activeBotId || "bot-1"}
              </span>
            </div>
          </div>
        </div>

        <div className="hud-divider"></div>

        <div className="hud-col user-col">
          <div className="hud-badge-icon">👤</div>
          <div className="hud-meta">
            <span className="hud-label-small">{isAr ? "معرّف حساب الموقع (User Account ID)" : "User Account ID"}</span>
            <div className="hud-id-row">
              <span className="hud-val-mono">{activeUserId || user?.id || "Unknown"}</span>
              <span className="hud-pill-tag user">{user?.email || "Authenticated"}</span>
            </div>
          </div>
        </div>

        <div className="hud-divider"></div>

        <div className="hud-col isolation-col">
          <div className="hud-isolation-box">
            <span className="hud-pulse-dot green"></span>
            <span className="hud-isolation-text">
              {isAr ? "عزل سحابي تام: تظهر وتُنقل مزارع هذه الغرفة حصراً" : "Zero-Leak Room Isolation Active"}
            </span>
          </div>
        </div>
      </section>

      {/* Configuration View (When No Transfer is Active) */}
      {!activeJob ? (
        <div className="config-grid-layout">
          {errorMsg && (
            <div className="glass-error-toast">
              <span className="toast-icon">⚠️</span>
              <span>{errorMsg}</span>
            </div>
          )}

          {/* Section 1: Recipient Identity */}
          <section className="glass-panel">
            <div className="panel-header">
              <div className="panel-title">{isAr ? "بيانات الحساب المستلم" : "Recipient Details"}</div>
              <span className="panel-badge-hud">STEP 1</span>
            </div>
            <p className="panel-desc">
              {isAr
                ? "أدخل معرّف الحاكم المستلم (Governor ID) وإحداثيات القلعة. يتم حفظ الوجهات تلقائياً."
                : "Enter recipient Governor ID and kingdom coordinates. Saved destinations sync automatically."}
            </p>

            {savedRecipients.length > 0 && (
              <div style={{ marginBottom: "16px" }}>
                <select
                  className="glass-select"
                  onChange={(e) => {
                    const sel = savedRecipients[Number(e.target.value)];
                    if (sel) {
                      setOrder((prev) => ({
                        ...prev,
                        target_role_id: String(sel.role_id),
                        x: Number(sel.x) || prev.x,
                        y: Number(sel.y) || prev.y,
                      }));
                    }
                  }}
                  defaultValue=""
                >
                  <option value="" disabled>
                    {isAr ? "-- اختيار سريع من الوجهات المحفوظة --" : "-- Quick select saved recipient --"}
                  </option>
                  {savedRecipients.map((rec, idx) => (
                    <option key={rec.role_id || idx} value={idx}>
                      {rec.name || `Target_${rec.role_id}`} (#{rec.role_id} • X:{rec.x}, Y:{rec.y})
                    </option>
                  ))}
                </select>
              </div>
            )}

            <div className="coords-row">
              <div className="input-field-wrap grow">
                <label className="field-lbl">{isAr ? "معرف الحاكم المستلم" : "Governor ID"}</label>
                <input
                  type="text"
                  value={order.target_role_id}
                  onChange={(e) => setOrder({ ...order, target_role_id: e.target.value })}
                  placeholder="227652418"
                  className="glass-input"
                />
              </div>
              <div className="input-field-wrap">
                <label className="field-lbl">X</label>
                <input
                  type="number"
                  value={order.x}
                  onChange={(e) => setOrder({ ...order, x: Number(e.target.value) })}
                  placeholder="419"
                  className="glass-input num-sm"
                />
              </div>
              <div className="input-field-wrap">
                <label className="field-lbl">Y</label>
                <input
                  type="number"
                  value={order.y}
                  onChange={(e) => setOrder({ ...order, y: Number(e.target.value) })}
                  placeholder="513"
                  className="glass-input num-sm"
                />
              </div>
            </div>
          </section>

          {/* Section 2: Resource Demand Inputs */}
          <section className="glass-panel">
            <div className="panel-header">
              <div className="panel-title">{isAr ? "الموارد والكميات الصافية المطلوبة" : "Resources & Net Quantities"}</div>
              <span className="panel-badge-hud">STEP 2</span>
            </div>
            <p className="panel-desc">
              {isAr
                ? "يتم احتساب ضريبة السوق وخصمها فوق هذه الكميات لضمان وصول المبلغ الصافي كاملاً للمستلم."
                : "Trading post taxes are dynamically calculated and deducted on top of these net amounts."}
            </p>

            <div className="rss-cards-grid">
              {(["food", "wood", "stone", "gold"] as const).map((res) => (
                <div key={res} className="rss-glass-card">
                  <div className="rss-card-left">
                    <img src={RSS_META[res].icon} alt={res} className="rss-big-img" />
                    <div>
                      <div className="rss-card-title">{RSS_META[res].name}</div>
                      <div className="rss-card-sub">{isAr ? RSS_META[res].labelAr : res}</div>
                    </div>
                  </div>
                  <div className="rss-card-middle">
                    <input
                      type="number"
                      value={order.requested_rss[res] || ""}
                      onChange={(e) =>
                        setOrder({
                          ...order,
                          requested_rss: { ...order.requested_rss, [res]: Math.max(0, Number(e.target.value)) },
                        })
                      }
                      placeholder="0"
                      className="glass-input-rss"
                    />
                    <span className="gross-tag">
                      {isAr ? "المخصوم المتوقع:" : "Est Gross:"} {getGrossFormatted(order.requested_rss[res])}
                    </span>
                  </div>
                  <button className="glass-btn-max" onClick={() => setMaxAvailable(res)}>
                    MAX
                  </button>
                </div>
              ))}
            </div>
          </section>

          {/* Section 3: Farm Dispatch Selection */}
          <section className="glass-panel">
            <div className="panel-header">
              <div className="panel-title">
                {isAr ? "المزارع المشاركة في النقل" : "Dispatch Farms"} ({order.selected_farm_roles.length}/{availableFarms.length})
              </div>
              <div className="panel-actions">
                <button className="glass-btn-subtle" onClick={() => selectAllFarms(true)}>
                  {isAr ? "تحديد الكل" : "Select All"}
                </button>
                <span className="action-sep">/</span>
                <button className="glass-btn-subtle" onClick={() => selectAllFarms(false)}>
                  {isAr ? "إلغاء التحديد" : "None"}
                </button>
              </div>
            </div>
            <p className="panel-desc">
              {isAr
                ? "حدد المزارع المشاركة. تعمل الحسابات المختلفة بالتوازي التام، وتوزع الحصة بذكاء دون إرهاق المزارع."
                : "Select participating farms. Different accounts run concurrently with smart pool balance."}
            </p>

            <div className="farms-glass-list">
              {availableFarms.length === 0 ? (
                <div className="empty-notice">{isAr ? "لا توجد مزارع مسجلة حالياً." : "No farms discovered."}</div>
              ) : (
                availableFarms.map((farm) => {
                  const isSelected = isFarmSelected(farm.role_id);
                  const isFleetDisabled = farm.enabled === false;

                  return (
                    <div
                      key={farm.role_id}
                      className={`farm-row-item ${isSelected ? "selected" : ""} ${isFleetDisabled ? "fleet-disabled" : ""}`}
                      onClick={() => toggleFarm(farm.role_id)}
                    >
                      <div className="farm-check-col">
                        <span className={`glass-chk ${isSelected ? "checked" : ""}`}></span>
                      </div>
                      <div className="farm-name-col">
                        <div className="name-line">
                          <span className="f-name">{farm.name}</span>
                          {isFleetDisabled && (
                            <span className="fleet-badge-warn">
                              {isAr ? "معطل بالأسطول" : "Disabled in Fleet"}
                            </span>
                          )}
                        </div>
                        <div className="meta-line">
                          [{farm.alliance_tag || "No Ally"}] · TP {farm.city_level || 17} ({farm.tax_rate || 19}% tax) · {farm.email}
                        </div>
                      </div>
                      <div className="farm-rss-tags">
                        <span className="rss-tag">
                          <img src="/images/Item_Food.webp" className="mini-icon" alt="food" /> {formatShort(farm.resources?.food)}
                        </span>
                        <span className="rss-tag">
                          <img src="/images/Item_Wood.webp" className="mini-icon" alt="wood" /> {formatShort(farm.resources?.wood)}
                        </span>
                        <span className="rss-tag">
                          <img src="/images/Item_Stone.webp" className="mini-icon" alt="stone" /> {formatShort(farm.resources?.stone)}
                        </span>
                        <span className="rss-tag">
                          <img src="/images/Item_Gold.webp" className="mini-icon" alt="gold" /> {formatShort(farm.resources?.gold)}
                        </span>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </section>

          {/* Action Launch Bar */}
          <div className="launch-dock">
            <button
              className="glass-btn-launch"
              disabled={isLaunching || order.selected_farm_roles.length === 0}
              onClick={startExecution}
            >
              <span className="btn-glow-pulse"></span>
              {isLaunching
                ? isAr ? "جاري تهيئة منظومة النقل المتزامن..." : "Initializing Transfer Pipeline..."
                : isAr ? "🚀 بدء إرسال الموارد فوراً (Start Transfer)" : "🚀 Start Transfer Execution"}
            </button>
          </div>
        </div>
      ) : (
        /* =========================================================================
           ACTIVE JOB MONITOR LAYOUT (High-End Glass AI Matching User's Request)
           ========================================================================= */
        <div className="monitor-glass-layout">
          {/* Active Job Order Summary & Tenancy Header Strip */}
          <section className="order-summary-hud">
            <div className="order-summary-left">
              <div className="order-id-badge">
                <span className="order-id-title">{isAr ? `مهمة الإمداد #${activeJob.job_id}` : `Transfer Job #${activeJob.job_id}`}</span>
                <span className={`status-pill ${activeJob.status.toLowerCase()}`}>
                  {activeJob.status === "RUNNING" ? (isAr ? "⚡ قيد النقل المتزامن" : "RUNNING") : activeJob.status}
                </span>
              </div>
              <div className="order-target-line">
                <span>{isAr ? "المستلم:" : "Target:"} <strong>{activeJob.target_name || activeJob.target_role_id}</strong> (#{activeJob.target_role_id})</span>
                <span className="target-coords">X:{activeJob.x}, Y:{activeJob.y}</span>
              </div>
              <div className="order-tenancy-tags">
                <span className="tag-item">🏛️ {isAr ? "الغرفة:" : "Room:"} <strong>{activeBot?.name || activeBot?.bot_id || activeBotId}</strong> ({activeBot?.bot_id || activeBotId})</span>
                <span className="tag-item">👤 {isAr ? "حساب الموقع:" : "User ID:"} <code>{activeUserId || user?.id}</code></span>
              </div>
            </div>

            <div className="order-summary-right">
              {activeJob.status === "RUNNING" && (
                <button className="glass-btn-cancel-top" onClick={cancelJob}>
                  🛑 {isAr ? "إلغاء فوري آمن" : "Cancel Job"}
                </button>
              )}
            </div>
          </section>

          {/* Hydraulic Real-Time Resource Progress Bars with WebP Icons */}
          <div className="hydraulic-panel">
            <div className="hydraulic-panel-title">
              <span>HYDRAULIC RESOURCE DISPATCH GAUGES</span>
              <span className="live-pulse-badge">LIVE TELEMETRY</span>
            </div>

            {(["food", "wood", "stone", "gold"] as const).map((res) => {
              const req = activeJob.requested?.[res] || 0;
              if (req <= 0) return null;
              const deliv = activeJob.delivered?.[res] || 0;
              const pct = getPercentage(deliv, req);

              return (
                <div key={res} className="hydraulic-tube-group">
                  <div className="tube-meta-row">
                    <div className="tube-res-brand">
                      <img src={RSS_META[res].icon} alt={res} className="tube-res-icon" />
                      <span className="tube-res-name">{RSS_META[res].name}</span>
                    </div>
                    <div className="tube-amounts">
                      <span className="tube-metric-cur">{formatMetric(deliv)}</span>
                      <span className="tube-metric-sep">/</span>
                      <span className="tube-metric-tot">{formatMetric(req)}</span>
                      <span className="tube-metric-tag">{isAr ? "تم التسليم" : "received"} ({pct}%)</span>
                    </div>
                  </div>
                  <div className="hydraulic-glass-pipe">
                    <div
                      className={`hydraulic-flow ${res}`}
                      style={{
                        width: `${pct}%`,
                        background: RSS_META[res].fillGrad,
                      }}
                    >
                      <span className="flow-shimmer"></span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* ACCOUNTS TELEMETRY ROW */}
          {activeJob.accounts && activeJob.accounts.length > 0 && (
            <div className="glass-panel accounts-box">
              <div className="panel-header-sm">
                <span className="hud-label">ACCOUNTS TELEMETRY</span>
                <span className="hud-badge">{activeJob.accounts.length} ACCOUNTS CONNECTED</span>
              </div>
              <div className="accounts-glass-list">
                {activeJob.accounts.map((acc, i) => (
                  <div key={i} className="account-glass-row">
                    <div className="acc-left">
                      <span className="acc-pulse-dot" data-status={acc.status.toLowerCase()}></span>
                      <span className="acc-email-text">{acc.email}</span>
                    </div>
                    <span className={`glass-status-chip ${acc.status.toLowerCase()}`}>{acc.status}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* FARMS LEDGER SECTION */}
          <div className="glass-panel farms-monitor-box">
            <div className="panel-header-sm">
              <span className="hud-label">
                FARMS DISPATCH LEDGER ({finishedFarmsCount}/{activeJob.workers?.length || 0} FINISHED)
              </span>
              <span className="hud-badge">ZERO OVERHEAD MONITOR</span>
            </div>

            <div className="workers-glass-list">
              {(activeJob.workers || []).map((worker) => {
                const sentRss = worker.sent_rss || {};
                const hasSentAny = Object.values(sentRss).some((v) => v > 0);

                return (
                  <div key={worker.role_id} className="worker-glass-card" data-status={worker.status.toLowerCase()}>
                    <div className="worker-info-col">
                      <div className="worker-title-row">
                        <span className="worker-name-text">{worker.name}</span>
                        <span className="worker-role-id">#{worker.role_id}</span>
                      </div>

                      {/* Real-time Per-Farm Delivered Resource Pills */}
                      {hasSentAny && (
                        <div className="worker-sent-pills">
                          {(["food", "wood", "stone", "gold"] as const).map((r) => {
                            const amt = sentRss[r] || 0;
                            if (amt <= 0) return null;
                            return (
                              <span key={r} className="sent-pill-tag">
                                <img src={RSS_META[r].icon} className="sent-icon" alt={r} />
                                <span className="sent-amt">{formatMetric(amt)}</span>
                                <span className="sent-sub">{isAr ? "مستلم" : "received"}</span>
                              </span>
                            );
                          })}
                        </div>
                      )}

                      {/* Real-Time Stage Description */}
                      <div className="worker-stage-msg">
                        {worker.stage_msg}
                      </div>
                    </div>

                    <div className="worker-telemetry-col">
                      <div className="worker-tp-spec">
                        TP {worker.market_lvl || 17} · {worker.tax_rate || 19}% tax
                      </div>
                      <div className={`worker-status-badge ${worker.status.toLowerCase()}`}>
                        {worker.status === "WAITING" && "⏳ WAITING"}
                        {worker.status === "RUNNING" && "⚡ RUNNING"}
                        {worker.status === "DRAINED" && "✅ DRAINED"}
                        {worker.status === "SKIPPED" && "⏭️ SKIPPED"}
                        {worker.status === "FAILED" && "❌ FAILED"}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Job Result Banner (Deficit / Success Details) */}
          {activeJob.status === "PARTIAL" && deficitSummary && (
            <div className="glass-summary-card deficit">
              <div className="summary-title">⚠️ {isAr ? "اكتمل النقل الجزئي مع وجود عجز في المزارع" : "Partial Transfer Completed (Deficit Notice)"}</div>
              <p className="summary-desc">
                {isAr
                  ? "تم تفريغ كافة الموارد المتوفرة بالمزارع المحددة بنجاح، لكن الرصيد كان أقل من المبلغ الإجمالي المطلوب:"
                  : "All available resources from selected farms were drained, but total farm balances were lower than requested:"}
              </p>
              <div className="deficit-tags-wrap">
                {deficitSummary.map((d) => (
                  <span key={d.res} className="deficit-tag">
                    <img src={RSS_META[d.res as keyof typeof RSS_META]?.icon} className="sent-icon" alt={d.res} />
                    <span>{d.name}: {isAr ? "متبقي عجز" : "Missing"} {formatMetric(d.missing)} ({isAr ? "وصل" : "Delivered"} {formatMetric(d.delivered)}/{formatMetric(d.needed)})</span>
                  </span>
                ))}
              </div>
            </div>
          )}

          {activeJob.status === "COMPLETED" && (
            <div className="glass-summary-card success">
              <div className="summary-title">🎉 {isAr ? "اكتمل النقل بنجاح تام 100%!" : "100% Net Transfer Completed!"}</div>
              <p className="summary-desc">
                {isAr
                  ? "تم تسليم كامل الموارد المطلوبة للمستلم، وتأمين كافة الجيوش في القلاع."
                  : "All requested net resources have been safely delivered to the recipient governor."}
              </p>
            </div>
          )}

          {/* Footer Controls matching reference layout */}
          <div className="monitor-footer-dock">
            <button className="glass-btn-back" onClick={resetToNewJob}>
              ← {isAr ? "نقل جديد / عودة" : "Back / New Transfer"}
            </button>
            {activeJob.status === "RUNNING" && (
              <button className="glass-btn-cancel" onClick={cancelJob}>
                🛑 {isAr ? "إلغاء فوري آمن" : "Cancel Job"}
              </button>
            )}
          </div>
        </div>
      )}

      {/* High-End Glass AI CSS */}
      <style jsx>{`
        .glass-ai-transfer-container {
          min-height: 100vh;
          background: radial-gradient(ellipse at 50% 0%, #0c1c3f 0%, #050e24 45%, #030713 100%);
          color: #dbeafe;
          font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Cairo", sans-serif;
          padding: 32px 44px;
        }

        /* Top Navigation */
        .glass-nav {
          display: flex;
          justify-content: space-between;
          align-items: center;
          background: rgba(7, 18, 41, 0.65);
          backdrop-filter: blur(20px);
          -webkit-backdrop-filter: blur(20px);
          border: 1px solid rgba(0, 229, 255, 0.2);
          border-radius: 16px;
          padding: 16px 28px;
          margin-bottom: 28px;
          box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
        }
        .brand-group {
          display: flex;
          align-items: center;
          gap: 16px;
        }
        .pulse-icon-box {
          position: relative;
          display: flex;
          align-items: center;
          justify-content: center;
          width: 44px;
          height: 44px;
          border-radius: 12px;
          background: rgba(0, 229, 255, 0.1);
          border: 1px solid rgba(0, 229, 255, 0.4);
        }
        .pulse-icon-box .icon {
          font-size: 1.6rem;
          color: #00e5ff;
          filter: drop-shadow(0 0 10px rgba(0, 229, 255, 0.8));
        }
        .title-text {
          margin: 0;
          font-size: 1.5rem;
          font-weight: 800;
          color: #ffffff;
          letter-spacing: -0.5px;
        }
        .subtitle-text {
          margin: 0;
          font-size: 0.8rem;
          color: #64748b;
          font-family: monospace;
        }
        .glass-btn-nav {
          color: #00e5ff;
          text-decoration: none;
          font-size: 0.9rem;
          font-weight: 700;
          padding: 10px 20px;
          border-radius: 10px;
          background: rgba(0, 229, 255, 0.08);
          border: 1px solid rgba(0, 229, 255, 0.25);
          transition: all 0.2s ease;
        }
        .glass-btn-nav:hover {
          background: rgba(0, 229, 255, 0.2);
          box-shadow: 0 0 16px rgba(0, 229, 255, 0.4);
          color: #ffffff;
        }

        /* Room & Tenancy HUD Strip */
        .glass-tenancy-hud {
          display: flex;
          align-items: center;
          justify-content: space-between;
          background: rgba(10, 24, 52, 0.7);
          backdrop-filter: blur(20px);
          -webkit-backdrop-filter: blur(20px);
          border: 1px solid rgba(0, 229, 255, 0.22);
          border-radius: 14px;
          padding: 14px 24px;
          margin-bottom: 24px;
          gap: 20px;
          box-shadow: 0 4px 20px rgba(0, 0, 0, 0.35);
        }
        .hud-col {
          display: flex;
          align-items: center;
          gap: 12px;
        }
        .hud-badge-icon {
          font-size: 1.4rem;
          display: flex;
          align-items: center;
          justify-content: center;
          width: 38px;
          height: 38px;
          border-radius: 10px;
          background: rgba(0, 229, 255, 0.08);
          border: 1px solid rgba(0, 229, 255, 0.2);
        }
        .hud-meta {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .hud-label-small {
          font-size: 0.72rem;
          color: #94a3b8;
          font-weight: 600;
          text-transform: uppercase;
          letter-spacing: 0.5px;
        }
        .hud-room-action-row, .hud-id-row {
          display: flex;
          align-items: center;
          gap: 10px;
        }
        .hud-room-select {
          background: rgba(5, 15, 34, 0.85);
          border: 1px solid rgba(0, 229, 255, 0.4);
          color: #ffffff;
          padding: 6px 14px;
          border-radius: 8px;
          font-size: 0.85rem;
          font-weight: 700;
          outline: none;
          cursor: pointer;
        }
        .hud-room-select option {
          background: #050e24;
          color: #ffffff;
        }
        .hud-val-bold {
          font-size: 0.95rem;
          font-weight: 800;
          color: #ffffff;
        }
        .hud-val-mono {
          font-family: monospace;
          font-size: 0.82rem;
          color: #38bdf8;
          background: rgba(56, 189, 248, 0.1);
          padding: 3px 8px;
          border-radius: 6px;
          border: 1px solid rgba(56, 189, 248, 0.25);
        }
        .hud-pill-tag {
          font-size: 0.72rem;
          font-weight: 800;
          padding: 3px 8px;
          border-radius: 6px;
          font-family: monospace;
        }
        .hud-pill-tag.cyan {
          background: rgba(0, 229, 255, 0.15);
          color: #00e5ff;
          border: 1px solid rgba(0, 229, 255, 0.4);
        }
        .hud-pill-tag.user {
          background: rgba(168, 85, 247, 0.15);
          color: #c084fc;
          border: 1px solid rgba(168, 85, 247, 0.4);
        }
        .hud-divider {
          width: 1px;
          height: 36px;
          background: rgba(255, 255, 255, 0.1);
        }
        .hud-isolation-box {
          display: flex;
          align-items: center;
          gap: 8px;
          background: rgba(16, 185, 129, 0.1);
          border: 1px solid rgba(16, 185, 129, 0.3);
          padding: 6px 14px;
          border-radius: 8px;
        }
        .hud-pulse-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
        }
        .hud-pulse-dot.green {
          background: #10b981;
          box-shadow: 0 0 8px #10b981;
        }
        .hud-isolation-text {
          font-size: 0.75rem;
          font-weight: 700;
          color: #6ee7b7;
        }

        /* Order Summary HUD in Active Monitor */
        .order-summary-hud {
          display: flex;
          justify-content: space-between;
          align-items: center;
          background: rgba(8, 20, 44, 0.7);
          backdrop-filter: blur(20px);
          border: 1px solid rgba(0, 229, 255, 0.25);
          border-radius: 14px;
          padding: 16px 24px;
          margin-bottom: 20px;
        }
        .order-summary-left {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        .order-id-badge {
          display: flex;
          align-items: center;
          gap: 12px;
        }
        .order-id-title {
          font-size: 1.1rem;
          font-weight: 800;
          color: #ffffff;
        }
        .status-pill {
          font-size: 0.75rem;
          font-weight: 800;
          padding: 3px 10px;
          border-radius: 6px;
          text-transform: uppercase;
        }
        .status-pill.running {
          background: rgba(0, 229, 255, 0.15);
          border: 1px solid #00e5ff;
          color: #00e5ff;
        }
        .status-pill.completed {
          background: rgba(16, 185, 129, 0.15);
          border: 1px solid #10b981;
          color: #10b981;
        }
        .status-pill.partial {
          background: rgba(245, 158, 11, 0.15);
          border: 1px solid #f59e0b;
          color: #f59e0b;
        }
        .status-pill.cancelled {
          background: rgba(239, 68, 68, 0.15);
          border: 1px solid #ef4444;
          color: #ef4444;
        }
        .order-target-line {
          font-size: 0.88rem;
          color: #cbd5e1;
          display: flex;
          gap: 10px;
          align-items: center;
        }
        .target-coords {
          font-family: monospace;
          background: rgba(255, 255, 255, 0.06);
          padding: 2px 6px;
          border-radius: 4px;
          color: #38bdf8;
        }
        .order-tenancy-tags {
          display: flex;
          gap: 14px;
          align-items: center;
          font-size: 0.8rem;
          color: #94a3b8;
          margin-top: 2px;
        }
        .tag-item strong {
          color: #00e5ff;
        }
        .tag-item code {
          color: #c084fc;
        }
        .glass-btn-cancel-top {
          background: rgba(239, 68, 68, 0.15);
          border: 1px solid #ef4444;
          color: #fca5a5;
          padding: 10px 18px;
          border-radius: 10px;
          font-weight: 700;
          font-size: 0.85rem;
          cursor: pointer;
          transition: all 0.2s ease;
        }
        .glass-btn-cancel-top:hover {
          background: rgba(239, 68, 68, 0.3);
          box-shadow: 0 0 16px rgba(239, 68, 68, 0.4);
        }

        /* Config Grid */
        .config-grid-layout {
          max-width: 1080px;
          margin: 0 auto;
          display: flex;
          flex-direction: column;
          gap: 24px;
        }
        .glass-error-toast {
          display: flex;
          align-items: center;
          gap: 12px;
          background: rgba(220, 38, 38, 0.15);
          border: 1px solid #ef4444;
          color: #fca5a5;
          padding: 14px 20px;
          border-radius: 12px;
          font-size: 0.95rem;
          backdrop-filter: blur(16px);
        }

        .glass-panel {
          background: rgba(8, 20, 44, 0.65);
          backdrop-filter: blur(24px);
          -webkit-backdrop-filter: blur(24px);
          border: 1px solid rgba(0, 229, 255, 0.18);
          border-radius: 16px;
          padding: 24px 28px;
          box-shadow: 0 10px 35px -5px rgba(0, 0, 0, 0.45);
        }
        .panel-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 6px;
        }
        .panel-title {
          font-size: 1.15rem;
          font-weight: 700;
          color: #ffffff;
        }
        .panel-badge-hud {
          background: rgba(0, 229, 255, 0.1);
          border: 1px solid rgba(0, 229, 255, 0.3);
          color: #00e5ff;
          font-size: 0.75rem;
          font-weight: 800;
          padding: 2px 8px;
          border-radius: 6px;
          font-family: monospace;
        }
        .panel-desc {
          font-size: 0.85rem;
          color: #64748b;
          margin-bottom: 18px;
        }
        .panel-actions {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .glass-btn-subtle {
          background: transparent;
          border: none;
          color: #38bdf8;
          font-size: 0.85rem;
          font-weight: 600;
          cursor: pointer;
          transition: color 0.2s;
        }
        .glass-btn-subtle:hover {
          color: #00e5ff;
        }
        .action-sep {
          color: #1e3a5f;
        }

        /* Inputs */
        .glass-select {
          width: 100%;
          max-width: 580px;
          background: #061127;
          border: 1px solid rgba(0, 229, 255, 0.25);
          color: #38bdf8;
          padding: 10px 16px;
          border-radius: 10px;
          font-size: 0.9rem;
          outline: none;
          cursor: pointer;
        }
        .coords-row {
          display: flex;
          gap: 16px;
          align-items: flex-end;
          flex-wrap: wrap;
        }
        .input-field-wrap {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        .input-field-wrap.grow {
          flex: 1;
          min-width: 280px;
        }
        .field-lbl {
          font-size: 0.8rem;
          color: #94a3b8;
          font-weight: 600;
        }
        .glass-input {
          background: #061127;
          border: 1px solid rgba(0, 229, 255, 0.2);
          color: #ffffff;
          padding: 12px 16px;
          border-radius: 10px;
          font-size: 0.95rem;
          outline: none;
          transition: all 0.2s;
        }
        .glass-input:focus {
          border-color: #00e5ff;
          box-shadow: 0 0 12px rgba(0, 229, 255, 0.3);
        }
        .glass-input.num-sm {
          width: 100px;
        }

        /* Resource Grid */
        .rss-cards-grid {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        .rss-glass-card {
          display: flex;
          align-items: center;
          justify-content: space-between;
          background: rgba(6, 17, 39, 0.7);
          border: 1px solid rgba(0, 229, 255, 0.12);
          border-radius: 12px;
          padding: 14px 20px;
          transition: all 0.2s;
        }
        .rss-glass-card:hover {
          border-color: rgba(0, 229, 255, 0.3);
          background: rgba(7, 20, 48, 0.8);
        }
        .rss-card-left {
          display: flex;
          align-items: center;
          gap: 14px;
          width: 160px;
        }
        .rss-big-img {
          width: 38px;
          height: 38px;
          object-fit: contain;
          filter: drop-shadow(0 2px 6px rgba(0, 0, 0, 0.6));
        }
        .rss-card-title {
          font-weight: 700;
          color: #ffffff;
          font-size: 1rem;
        }
        .rss-card-sub {
          font-size: 0.75rem;
          color: #64748b;
        }
        .rss-card-middle {
          display: flex;
          align-items: center;
          gap: 16px;
          flex: 1;
        }
        .glass-input-rss {
          background: #030814;
          border: 1px solid #1a3356;
          color: #ffffff;
          padding: 10px 16px;
          border-radius: 8px;
          font-size: 1rem;
          font-weight: 600;
          width: 260px;
          outline: none;
          font-family: monospace;
        }
        .glass-input-rss:focus {
          border-color: #00e5ff;
          box-shadow: 0 0 10px rgba(0, 229, 255, 0.25);
        }
        .gross-tag {
          font-size: 0.8rem;
          color: #38bdf8;
          font-family: monospace;
        }
        .glass-btn-max {
          background: rgba(0, 229, 255, 0.12);
          border: 1px solid rgba(0, 229, 255, 0.4);
          color: #00e5ff;
          padding: 8px 18px;
          border-radius: 20px;
          font-size: 0.8rem;
          font-weight: 700;
          cursor: pointer;
          transition: all 0.2s;
        }
        .glass-btn-max:hover {
          background: #00e5ff;
          color: #030713;
          box-shadow: 0 0 14px rgba(0, 229, 255, 0.6);
        }

        /* Farms List */
        .farms-glass-list {
          display: flex;
          flex-direction: column;
          gap: 10px;
          max-height: 340px;
          overflow-y: auto;
          padding-right: 6px;
        }
        .farm-row-item {
          display: flex;
          align-items: center;
          background: rgba(6, 17, 39, 0.6);
          border: 1px solid rgba(0, 229, 255, 0.1);
          padding: 12px 18px;
          border-radius: 10px;
          cursor: pointer;
          transition: all 0.2s ease;
        }
        .farm-row-item:hover {
          background: rgba(8, 22, 53, 0.8);
          border-color: rgba(0, 229, 255, 0.25);
        }
        .farm-row-item.selected {
          background: rgba(10, 28, 68, 0.85);
          border-color: #00e5ff;
          box-shadow: 0 0 16px rgba(0, 229, 255, 0.15);
        }
        .farm-row-item.fleet-disabled {
          opacity: 0.75;
          border-left: 3px solid #f59e0b;
        }
        .farm-check-col {
          margin-right: 14px;
        }
        .glass-chk {
          display: inline-block;
          width: 18px;
          height: 18px;
          border: 1px solid rgba(0, 229, 255, 0.5);
          border-radius: 5px;
          transition: all 0.2s;
        }
        .glass-chk.checked {
          background: #00e5ff;
          box-shadow: 0 0 10px rgba(0, 229, 255, 0.8);
        }
        .farm-name-col {
          display: flex;
          flex-direction: column;
          width: 290px;
        }
        .name-line {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .f-name {
          font-weight: 700;
          color: #ffffff;
          font-size: 0.95rem;
        }
        .fleet-badge-warn {
          background: rgba(245, 158, 11, 0.2);
          border: 1px solid #d97706;
          color: #fbbf24;
          font-size: 0.65rem;
          font-weight: 700;
          padding: 1px 6px;
          border-radius: 4px;
        }
        .meta-line {
          font-size: 0.75rem;
          color: #64748b;
        }
        .farm-rss-tags {
          display: flex;
          gap: 10px;
          margin-left: auto;
        }
        .rss-tag {
          background: rgba(3, 8, 20, 0.8);
          border: 1px solid rgba(30, 58, 95, 0.6);
          padding: 4px 10px;
          border-radius: 6px;
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 0.8rem;
          color: #cbd5e1;
          font-family: monospace;
        }
        .mini-icon {
          width: 16px;
          height: 16px;
          object-fit: contain;
        }

        /* Launch Button */
        .launch-dock {
          margin-top: 10px;
        }
        .glass-btn-launch {
          width: 100%;
          padding: 18px;
          background: linear-gradient(135deg, #0284c7 0%, #0369a1 50%, #00e5ff 100%);
          border: 1px solid #38bdf8;
          border-radius: 12px;
          color: #ffffff;
          font-size: 1.15rem;
          font-weight: 800;
          cursor: pointer;
          box-shadow: 0 6px 28px rgba(0, 229, 255, 0.4);
          transition: all 0.25s ease;
          letter-spacing: 0.5px;
        }
        .glass-btn-launch:hover:not(:disabled) {
          transform: translateY(-2px);
          box-shadow: 0 10px 36px rgba(0, 229, 255, 0.7);
        }
        .glass-btn-launch:disabled {
          opacity: 0.45;
          cursor: not-allowed;
          box-shadow: none;
        }

        /* =========================================================================
           ACTIVE JOB MONITOR LAYOUT (Glass AI)
           ========================================================================= */
        .monitor-glass-layout {
          max-width: 1000px;
          margin: 0 auto;
          display: flex;
          flex-direction: column;
          gap: 24px;
        }

        /* Hydraulic Progress Gauges */
        .hydraulic-panel {
          background: rgba(8, 20, 44, 0.75);
          backdrop-filter: blur(24px);
          -webkit-backdrop-filter: blur(24px);
          border: 1px solid rgba(0, 229, 255, 0.22);
          border-radius: 16px;
          padding: 24px 28px;
          box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
        }
        .hydraulic-panel-title {
          display: flex;
          justify-content: space-between;
          align-items: center;
          font-size: 0.85rem;
          font-weight: 800;
          color: #64748b;
          letter-spacing: 1px;
          margin-bottom: 20px;
          font-family: monospace;
        }
        .live-pulse-badge {
          background: rgba(0, 229, 255, 0.15);
          border: 1px solid rgba(0, 229, 255, 0.4);
          color: #00e5ff;
          padding: 3px 10px;
          border-radius: 12px;
          font-size: 0.7rem;
        }
        .hydraulic-tube-group {
          display: flex;
          flex-direction: column;
          gap: 8px;
          margin-bottom: 20px;
        }
        .hydraulic-tube-group:last-child {
          margin-bottom: 0;
        }
        .tube-meta-row {
          display: flex;
          justify-content: space-between;
          align-items: center;
        }
        .tube-res-brand {
          display: flex;
          align-items: center;
          gap: 12px;
        }
        .tube-res-icon {
          width: 28px;
          height: 28px;
          object-fit: contain;
          filter: drop-shadow(0 2px 6px rgba(0, 0, 0, 0.5));
        }
        .tube-res-name {
          font-size: 1.05rem;
          font-weight: 800;
          color: #ffffff;
        }
        .tube-amounts {
          display: flex;
          align-items: baseline;
          gap: 6px;
          font-family: monospace;
        }
        .tube-metric-cur {
          font-size: 1.15rem;
          font-weight: 800;
          color: #00e5ff;
        }
        .tube-metric-sep {
          color: #475569;
        }
        .tube-metric-tot {
          color: #cbd5e1;
          font-weight: 600;
        }
        .tube-metric-tag {
          color: #64748b;
          font-size: 0.8rem;
          margin-left: 6px;
        }

        .hydraulic-glass-pipe {
          width: 100%;
          height: 14px;
          background: rgba(3, 7, 18, 0.9);
          border-radius: 8px;
          overflow: hidden;
          border: 1px solid rgba(0, 229, 255, 0.15);
          box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.8);
        }
        .hydraulic-flow {
          height: 100%;
          border-radius: 8px;
          position: relative;
          transition: width 0.4s ease-out;
        }
        .flow-shimmer {
          position: absolute;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.3), transparent);
          animation: shimmerFlow 2.5s infinite;
        }
        @keyframes shimmerFlow {
          0% { transform: translateX(-100%); }
          100% { transform: translateX(100%); }
        }

        /* Accounts Box */
        .panel-header-sm {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 14px;
        }
        .hud-label {
          font-size: 0.85rem;
          font-weight: 800;
          color: #64748b;
          letter-spacing: 0.8px;
          font-family: monospace;
        }
        .hud-badge {
          font-size: 0.75rem;
          color: #38bdf8;
          font-family: monospace;
        }
        .accounts-glass-list {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .account-glass-row {
          display: flex;
          justify-content: space-between;
          align-items: center;
          background: rgba(6, 17, 39, 0.6);
          border: 1px solid rgba(0, 229, 255, 0.1);
          padding: 10px 16px;
          border-radius: 8px;
        }
        .acc-left {
          display: flex;
          align-items: center;
          gap: 12px;
        }
        .acc-pulse-dot {
          width: 10px;
          height: 10px;
          border-radius: 50%;
        }
        .acc-pulse-dot[data-status="running"] {
          background: #00e5ff;
          box-shadow: 0 0 10px #00e5ff;
        }
        .acc-pulse-dot[data-status="completed"] {
          background: #22c55e;
          box-shadow: 0 0 8px #22c55e;
        }
        .acc-email-text {
          font-size: 0.95rem;
          font-weight: 600;
          color: #f1f5f9;
          font-family: monospace;
        }
        .glass-status-chip {
          padding: 3px 12px;
          border-radius: 12px;
          font-size: 0.75rem;
          font-weight: 700;
          font-family: monospace;
        }
        .glass-status-chip.running {
          background: rgba(0, 229, 255, 0.15);
          color: #00e5ff;
          border: 1px solid rgba(0, 229, 255, 0.4);
        }
        .glass-status-chip.completed {
          background: rgba(34, 197, 94, 0.15);
          color: #4ade80;
          border: 1px solid rgba(34, 197, 94, 0.4);
        }

        /* Farms Ledger */
        .workers-glass-list {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        .worker-glass-card {
          display: flex;
          justify-content: space-between;
          align-items: center;
          background: rgba(6, 17, 39, 0.7);
          border: 1px solid rgba(0, 229, 255, 0.12);
          padding: 14px 20px;
          border-radius: 12px;
          transition: all 0.2s;
        }
        .worker-glass-card[data-status="running"] {
          border-color: #00e5ff;
          background: rgba(8, 26, 60, 0.85);
          box-shadow: 0 0 20px rgba(0, 229, 255, 0.15);
        }
        .worker-glass-card[data-status="drained"] {
          border-color: rgba(34, 197, 94, 0.4);
        }
        .worker-glass-card[data-status="failed"] {
          border-color: rgba(239, 68, 68, 0.4);
        }

        .worker-info-col {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        .worker-title-row {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .worker-name-text {
          font-weight: 800;
          color: #ffffff;
          font-size: 1.05rem;
        }
        .worker-role-id {
          font-size: 0.75rem;
          color: #64748b;
          font-family: monospace;
        }
        .worker-sent-pills {
          display: flex;
          gap: 10px;
          flex-wrap: wrap;
        }
        .sent-pill-tag {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          background: rgba(3, 8, 20, 0.8);
          border: 1px solid rgba(0, 229, 255, 0.2);
          padding: 3px 10px;
          border-radius: 6px;
          font-family: monospace;
          font-size: 0.85rem;
        }
        .sent-icon {
          width: 16px;
          height: 16px;
          object-fit: contain;
        }
        .sent-amt {
          color: #00e5ff;
          font-weight: 700;
        }
        .sent-sub {
          color: #64748b;
          font-size: 0.75rem;
        }
        .worker-stage-msg {
          font-size: 0.8rem;
          color: #94a3b8;
          font-family: monospace;
        }

        .worker-telemetry-col {
          display: flex;
          align-items: center;
          gap: 14px;
        }
        .worker-tp-spec {
          background: rgba(3, 8, 20, 0.7);
          border: 1px solid rgba(30, 58, 95, 0.6);
          color: #94a3b8;
          font-size: 0.85rem;
          padding: 6px 12px;
          border-radius: 8px;
          font-family: monospace;
        }
        .worker-status-badge {
          padding: 6px 16px;
          border-radius: 8px;
          font-size: 0.8rem;
          font-weight: 800;
          font-family: monospace;
          min-width: 90px;
          text-align: center;
          letter-spacing: 0.5px;
        }
        .worker-status-badge.waiting {
          background: rgba(245, 158, 11, 0.15);
          color: #fbbf24;
          border: 1px solid #d97706;
        }
        .worker-status-badge.running {
          background: rgba(0, 229, 255, 0.2);
          color: #00e5ff;
          border: 1px solid #00e5ff;
          box-shadow: 0 0 12px rgba(0, 229, 255, 0.5);
        }
        .worker-status-badge.drained {
          background: rgba(34, 197, 94, 0.15);
          color: #4ade80;
          border: 1px solid #22c55e;
        }
        .worker-status-badge.skipped {
          background: rgba(51, 65, 85, 0.4);
          color: #94a3b8;
          border: 1px solid #475569;
        }
        .worker-status-badge.failed {
          background: rgba(239, 68, 68, 0.2);
          color: #fca5a5;
          border: 1px solid #ef4444;
        }

        /* Summary Cards */
        .glass-summary-card {
          padding: 20px 24px;
          border-radius: 14px;
          backdrop-filter: blur(20px);
        }
        .glass-summary-card.deficit {
          background: rgba(245, 158, 11, 0.1);
          border: 1px solid rgba(245, 158, 11, 0.35);
        }
        .glass-summary-card.success {
          background: rgba(34, 197, 94, 0.1);
          border: 1px solid rgba(34, 197, 94, 0.35);
        }
        .summary-title {
          font-size: 1.1rem;
          font-weight: 800;
          color: #ffffff;
          margin-bottom: 6px;
        }
        .summary-desc {
          font-size: 0.9rem;
          color: #cbd5e1;
          margin-bottom: 12px;
        }
        .deficit-tags-wrap {
          display: flex;
          gap: 12px;
          flex-wrap: wrap;
        }
        .deficit-tag {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          background: rgba(3, 8, 20, 0.8);
          border: 1px solid rgba(245, 158, 11, 0.4);
          padding: 6px 12px;
          border-radius: 8px;
          font-family: monospace;
          color: #fde047;
          font-size: 0.85rem;
        }

        /* Footer Controls */
        .monitor-footer-dock {
          display: flex;
          gap: 16px;
          margin-top: 10px;
        }
        .glass-btn-back {
          background: rgba(0, 229, 255, 0.12);
          border: 1px solid rgba(0, 229, 255, 0.4);
          color: #00e5ff;
          padding: 12px 28px;
          border-radius: 10px;
          font-size: 0.95rem;
          font-weight: 700;
          cursor: pointer;
          transition: all 0.2s;
        }
        .glass-btn-back:hover {
          background: rgba(0, 229, 255, 0.25);
          box-shadow: 0 0 16px rgba(0, 229, 255, 0.4);
          color: #ffffff;
        }
        .glass-btn-cancel {
          background: rgba(239, 68, 68, 0.15);
          border: 1px solid rgba(239, 68, 68, 0.5);
          color: #fca5a5;
          padding: 12px 26px;
          border-radius: 10px;
          font-size: 0.95rem;
          font-weight: 700;
          cursor: pointer;
          transition: all 0.2s;
        }
        .glass-btn-cancel:hover {
          background: rgba(239, 68, 68, 0.35);
          box-shadow: 0 0 16px rgba(239, 68, 68, 0.5);
          color: #ffffff;
        }
      `}</style>
    </div>
  );
}
