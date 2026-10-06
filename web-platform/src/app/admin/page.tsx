"use client";

import React, { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { 
  Users, 
  Power, 
  CreditCard, 
  Megaphone, 
  ShieldAlert, 
  Trash2, 
  Ban, 
  CheckCircle, 
  AlertTriangle, 
  RefreshCw, 
  Loader2, 
  ImagePlus, 
  Send, 
  X,
  Bot,
  Layers,
  Activity,
  DollarSign,
  Search,
  Sparkles,
  Copy,
  Check,
  Server,
  Radio,
  ExternalLink,
  ShieldCheck,
  ChevronDown,
  ChevronUp
} from "lucide-react";
import { linkifyHtml } from "@/lib/format";
import { ITEM_FOOD_BASE64, ITEM_GEM_BASE64, ITEM_GOLD_BASE64 } from "@/lib/gameIconsBase64";

interface UserProfileRecord {
  id: string;
  username: string;
  discord_id: string;
  avatar_url: string;
  role: string;
  is_banned: boolean;
  created_at: string;
  rooms: Array<{
    id: string;
    bot_id: string;
    name: string;
    status: string;
    slots: number;
    created_at: string;
  }>;
  rooms_count: number;
  accounts_count: number;
  characters_count: number;
  orders_count: number;
}

interface OrderRecord {
  id: string;
  invoice_number: string;
  user_id: string;
  buyer_name: string;
  discord_id: string;
  avatar_url: string;
  product_name: string;
  tier: string;
  slots: number;
  amount: string;
  currency: string;
  payment_method: string;
  billing_cycle: string;
  status: string;
  created_at: string;
  expires_at: string;
}

interface Announcement {
  id: number;
  title: string;
  body: string;
  image_url?: string | null;
  created_at: string;
}

export default function AdminConsolePage() {
  const router = useRouter();
  const [currentTab, setCurrentTab] = useState<"users" | "server" | "orders" | "broadcast">("users");

  // Status & Auth
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);
  const [role, setRole] = useState("admin");

  // Global Data
  const [stats, setStats] = useState<any>({
    total_users: 0,
    total_rooms: 0,
    total_accounts: 0,
    total_characters: 0,
    total_orders: 0,
    total_revenue: "0.00",
  });
  const [usersList, setUsersList] = useState<UserProfileRecord[]>([]);
  const [ordersList, setOrdersList] = useState<OrderRecord[]>([]);

  // Search & UI Filters
  const [searchQuery, setSearchQuery] = useState("");
  const [orderSearch, setOrderSearch] = useState("");
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [expandedRooms, setExpandedRooms] = useState<Record<string, boolean>>({});

  // Maintenance State
  const [maintenanceEnabled, setMaintenanceEnabled] = useState(false);
  const [maintenanceMsg, setMaintenanceMsg] = useState("لقد تم إطفاء السيرفر للصيانة من قبل الإدارة");
  const [savingMaint, setSavingMaint] = useState(false);
  const [maintFeedback, setMaintFeedback] = useState("");

  // Broadcast State
  const imgRef = useRef<HTMLInputElement | null>(null);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [imageUrl, setImageUrl] = useState("");
  const [uploading, setUploading] = useState(false);
  const [sending, setSending] = useState(false);
  const [announcements, setAnnouncements] = useState<Announcement[]>([]);
  const [broadcastMsg, setBroadcastMsg] = useState("");
  const [broadcastErr, setBroadcastErr] = useState("");

  // Feedback notifications
  const [toastMsg, setToastMsg] = useState("");

  const showToast = (txt: string) => {
    setToastMsg(txt);
    setTimeout(() => setToastMsg(""), 4000);
  };

  const copyToClipboard = (text: string, id: string) => {
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      navigator.clipboard.writeText(text);
      setCopiedId(id);
      setTimeout(() => setCopiedId(null), 2000);
      showToast("تم نسخ المعرف للحافظة ✓");
    }
  };

  const toggleExpandRoom = (userId: string) => {
    setExpandedRooms((prev) => ({
      ...prev,
      [userId]: !prev[userId],
    }));
  };

  async function checkAuthAndLoad() {
    setLoading(true);
    try {
      const st = await fetch("/api/admin/status");
      const sd = await st.json().catch(() => ({}));
      if (st.status === 401) {
        router.replace("/login?redirectTo=/admin");
        return;
      }
      if (!sd.isAdmin && !sd.isOwner) {
        setForbidden(true);
        return;
      }
      setRole(sd.role || "admin");
      setForbidden(false);

      // Concurrently load Users, Orders, Maintenance & Broadcasts
      await Promise.all([
        loadUsersData(),
        loadOrdersData(),
        loadMaintenanceData(),
        loadAnnouncements(),
      ]);
    } catch (e: any) {
      console.error("Admin load error:", e);
    } finally {
      setLoading(false);
    }
  }

  async function loadUsersData() {
    try {
      const res = await fetch("/api/admin/users");
      if (res.ok) {
        const data = await res.json();
        if (data.success) {
          setStats(data.stats || {});
          setUsersList(data.users || []);
        }
      }
    } catch (e) {
      console.error("Failed to fetch users", e);
    }
  }

  async function loadOrdersData() {
    try {
      const res = await fetch("/api/admin/orders");
      if (res.ok) {
        const data = await res.json();
        if (data.success) {
          setOrdersList(data.orders || []);
        }
      }
    } catch (e) {
      console.error("Failed to fetch orders", e);
    }
  }

  async function loadMaintenanceData() {
    try {
      const res = await fetch("/api/admin/maintenance");
      if (res.ok) {
        const data = await res.json();
        setMaintenanceEnabled(Boolean(data.maintenance));
        if (data.message) setMaintenanceMsg(data.message);
      }
    } catch (e) {
      console.error("Failed to fetch maintenance state", e);
    }
  }

  async function loadAnnouncements() {
    try {
      const res = await fetch("/api/announcements");
      if (res.ok) {
        const data = await res.json();
        setAnnouncements(data.announcements || []);
      }
    } catch (e) {
      console.error("Failed to fetch announcements", e);
    }
  }

  useEffect(() => {
    checkAuthAndLoad();
  }, []);

  // Action: Delete a Bot Room
  async function handleDeleteRoom(userId: string, roomId: string, roomName: string) {
    const confirmDel = window.confirm(`هل أنت متأكد من رغبتك بحذف الغرفة "${roomName}" وتصفير حساباتها ومزارعها نهائياً؟`);
    if (!confirmDel) return;

    try {
      const res = await fetch("/api/admin/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "delete_room",
          target_user_id: userId,
          room_id: roomId,
        }),
      });
      const data = await res.json();
      if (res.ok && data.success) {
        showToast(`تم حذف الغرفة "${roomName}" وتصفيرها بنجاح.`);
        loadUsersData();
      } else {
        alert(data.error || "فشل حذف الغرفة.");
      }
    } catch (e: any) {
      alert("حدث خطأ أثناء الاتصال: " + e.message);
    }
  }

  // Action: Ban or Unban User
  async function handleToggleBan(userId: string, currentBanned: boolean, username: string) {
    const actionLabel = currentBanned ? "فك حظر" : "حظر";
    const confirmBan = window.confirm(`هل أنت متأكد من ${actionLabel} المستخدم "${username}"؟`);
    if (!confirmBan) return;

    try {
      const res = await fetch("/api/admin/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "toggle_ban",
          target_user_id: userId,
          ban_status: !currentBanned,
        }),
      });
      const data = await res.json();
      if (res.ok && data.success) {
        showToast(`تم ${actionLabel} المستخدم "${username}" بنجاح.`);
        loadUsersData();
      } else {
        alert(data.error || `فشل ${actionLabel} المستخدم.`);
      }
    } catch (e: any) {
      alert("حدث خطأ أثناء الاتصال: " + e.message);
    }
  }

  // Action: Toggle Maintenance Mode
  async function handleSaveMaintenance(newVal: boolean) {
    setSavingMaint(true);
    setMaintFeedback("");
    try {
      const res = await fetch("/api/admin/maintenance", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          enabled: newVal,
          message: maintenanceMsg,
        }),
      });
      const data = await res.json();
      if (res.ok && data.success) {
        setMaintenanceEnabled(newVal);
        const stateWord = newVal ? "إطفاء السيرفر للصيانة 🛑" : "تشغيل السيرفر بالكامل 🟢";
        setMaintFeedback(`تم ${stateWord} بنجاح.`);
        showToast(`تم تحديث حالة السيرفر: ${newVal ? "متوقف للصيانة" : "يعمل الآن"}`);
      } else {
        setMaintFeedback(data.error || "فشل حفظ الإعدادات");
      }
    } catch (e: any) {
      setMaintFeedback("خطأ في الاتصال: " + e.message);
    } finally {
      setSavingMaint(false);
    }
  }

  // Upload Broadcast Image
  async function handleImageFile(file: File) {
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch("/api/admin/upload", {
        method: "POST",
        body: fd,
      });
      const data = await res.json();
      if (res.ok && data.url) {
        setImageUrl(data.url);
      } else {
        alert(data.error || "فشل رفع الصورة");
      }
    } catch (e: any) {
      alert("خطأ أثناء الرفع: " + e.message);
    } finally {
      setUploading(false);
    }
  }

  // Send Broadcast
  async function handleSendBroadcast() {
    if (!title.trim() || !body.trim()) return;
    setSending(true);
    setBroadcastMsg("");
    setBroadcastErr("");
    try {
      const res = await fetch("/api/admin/broadcast", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: title.trim(),
          body: body.trim(),
          image_url: imageUrl || null,
        }),
      });
      const data = await res.json();
      if (res.ok && data.success) {
        setBroadcastMsg("تم إرسال الإشعار لجميع المشتركين بنجاح ✓");
        setTitle("");
        setBody("");
        setImageUrl("");
        loadAnnouncements();
      } else {
        setBroadcastErr(data.error || "فشل إرسال الإشعار");
      }
    } catch (e: any) {
      setBroadcastErr("خطأ في الاتصال: " + e.message);
    } finally {
      setSending(false);
    }
  }

  // Filtered Lists
  const filteredUsers = usersList.filter((u) => {
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase();
    return (
      u.username?.toLowerCase().includes(q) ||
      u.discord_id?.toLowerCase().includes(q) ||
      u.id?.toLowerCase().includes(q)
    );
  });

  const filteredOrders = ordersList.filter((o) => {
    if (!orderSearch.trim()) return true;
    const q = orderSearch.toLowerCase();
    return (
      o.invoice_number?.toLowerCase().includes(q) ||
      o.buyer_name?.toLowerCase().includes(q) ||
      o.discord_id?.toLowerCase().includes(q) ||
      o.user_id?.toLowerCase().includes(q) ||
      o.payment_method?.toLowerCase().includes(q)
    );
  });

  const getTabLabel = (tab: string) => {
    switch (tab) {
      case "users": return "المستخدمين والغرف";
      case "server": return "التحكم بالسيرفر";
      case "orders": return "طلبات المشتركين";
      case "broadcast": return "بريد الإعلانات";
      default: return tab;
    }
  };

  if (loading) {
    return (
      <div className="admin-loading-screen" dir="rtl">
        <div className="admin-spinner">
          <Loader2 className="w-10 h-10 animate-spin text-cyan-400" />
        </div>
        <div className="admin-loading-text">جاري التحقق من صلاحيات الأونر والاتصال المركزي...</div>
      </div>
    );
  }

  if (forbidden) {
    return (
      <div className="admin-forbidden-screen" dir="rtl">
        <div className="forbidden-box">
          <ShieldAlert className="w-12 h-12 text-rose-500 mx-auto mb-4" />
          <h1 className="text-2xl font-black text-white">منطقة محظورة — خاصة بمالك المنصة فقط (Owners Only)</h1>
          <p className="text-sm text-slate-400 mt-2">
            حسابك لا يمتلك الصلاحيات الإدارية لدخول هذه الغرفة. تم تأمين النظام بالكامل.
          </p>
          <div className="mt-6">
            <Link href="/dashboard" className="btn-action-outline">
              ← العودة للوحة العمليات
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="admin-dashboard-page" dir="rtl">
      
      {/* Toast Notification */}
      {toastMsg && (
        <div className="admin-toast">
          <Sparkles className="w-4 h-4 text-cyan-300" />
          <span>{toastMsg}</span>
        </div>
      )}

      {/* =========================================================================
          TOP SYSTEM HEADER
         ========================================================================= */}
      <header className="admin-header">
        <div className="header-main">
          <div className="system-badge">
            <span className="status-dot pulsing"></span>
            <span>SYSTEM OWNER COMMAND</span>
            <span className="badge-divider">•</span>
            <span className="server-state-pill">
              {maintenanceEnabled ? "السيرفر: متوقف للصيانة" : "السيرفر: نشط للجميع"}
            </span>
          </div>
          <h1>مركز قيادة الأونر والتحكم الشامل</h1>
          <p className="header-desc">إدارة المشتركين، مراقبة المزارع، فواتير الشراء، ومفاتيح السيرفر المباشرة.</p>
        </div>

        <div className="header-quick-actions">
          <button className="btn-action-outline" onClick={checkAuthAndLoad}>
            <RefreshCw className="w-4 h-4 text-cyan-400" />
            <span>تحديث البيانات الحية</span>
          </button>
          <Link href="/dashboard" className="btn-action-primary">
            <span>لوحة العمليات</span>
            <ExternalLink className="w-3.5 h-3.5" />
          </Link>
        </div>
      </header>

      {/* =========================================================================
          STAT METRICS ROW
         ========================================================================= */}
      <section className="metrics-grid">
        <div className="metric-card highlight-green">
          <div className="metric-icon">
            <img src={ITEM_GOLD_BASE64} alt="Gold" className="w-8 h-8 object-contain" />
          </div>
          <div className="metric-details">
            <span className="metric-label">إجمالي المبيعات المحققة</span>
            <span className="metric-value font-en">${Number(stats.total_revenue || 0).toFixed(2)}</span>
            <span className="metric-sub">{stats.total_orders || 0} عملية شراء واشتراك</span>
          </div>
        </div>

        <div className="metric-card">
          <div className="metric-icon">👥</div>
          <div className="metric-details">
            <span className="metric-label">إجمالي المشتركين</span>
            <span className="metric-value font-en">{stats.total_users || 0}</span>
            <span className="metric-sub">حسابات مسجلة بالمنصة</span>
          </div>
        </div>

        <div className="metric-card">
          <div className="metric-icon">☁️</div>
          <div className="metric-details">
            <span className="metric-label">الغرف السحابية النشطة</span>
            <span className="metric-value font-en">{stats.total_rooms || 0}</span>
            <span className="metric-sub">وحدات بوت تعمل للمستخدمين</span>
          </div>
        </div>

        <div className="metric-card">
          <div className="metric-icon">
            <img src={ITEM_FOOD_BASE64} alt="Farms" className="w-8 h-8 object-contain" />
          </div>
          <div className="metric-details">
            <span className="metric-label">إجمالي المزارع المربوطة</span>
            <span className="metric-value font-en">{stats.total_characters || 0}</span>
            <span className="metric-sub">شخصيات ومزارع نشطة</span>
          </div>
        </div>
      </section>

      {/* =========================================================================
          NAVIGATION & FILTER TOOLBAR
         ========================================================================= */}
      <section className="toolbar-section">
        <div className="tab-pills">
          {(["users", "server", "orders", "broadcast"] as const).map((tab) => (
            <button
              key={tab}
              className={`tab-btn ${currentTab === tab ? "active" : ""}`}
              onClick={() => setCurrentTab(tab)}
            >
              <span>{getTabLabel(tab)}</span>
              {tab === "users" && <span className="tab-counter">{usersList.length}</span>}
              {tab === "orders" && <span className="tab-counter">{ordersList.length}</span>}
              {tab === "server" && (
                <span className={`tab-dot ${maintenanceEnabled ? "dot-red" : "dot-green"}`}></span>
              )}
            </button>
          ))}
        </div>

        {currentTab === "users" && (
          <div className="search-box">
            <Search className="icon-search" />
            <input 
              type="text" 
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="بحث باسم المستخدم، الـ Discord ID، أو UID..." 
            />
            {searchQuery && (
              <button className="search-clear" onClick={() => setSearchQuery("")}>
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        )}

        {currentTab === "orders" && (
          <div className="search-box">
            <Search className="icon-search" />
            <input 
              type="text" 
              value={orderSearch}
              onChange={(e) => setOrderSearch(e.target.value)}
              placeholder="بحث برقم الفاتورة، اسم المشتري، أو UID..." 
            />
            {orderSearch && (
              <button className="search-clear" onClick={() => setOrderSearch("")}>
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        )}
      </section>

      {/* =========================================================================
          TAB 1: USERS & SUBSCRIBERS MANAGEMENT TABLE
         ========================================================================= */}
      {currentTab === "users" && (
        <section className="table-container">
          <table className="admin-data-table">
            <thead>
              <tr>
                <th>المستخدم</th>
                <th>معرفات النظام</th>
                <th className="col-center">الحسابات المرتبطة</th>
                <th className="col-center">المزارع النشطة</th>
                <th className="col-center">الغرف السحابية</th>
                <th>الحالة</th>
                <th>الإجراءات</th>
              </tr>
            </thead>
            <tbody>
              {filteredUsers.length === 0 ? (
                <tr>
                  <td colSpan={7} className="col-empty">
                    لا يوجد مستخدمون يطابقون معايير البحث الحالية
                  </td>
                </tr>
              ) : (
                filteredUsers.map((user) => {
                  const isOwnerItem = user.role === "owner" || user.discord_id === "775687774417321994";
                  const hasRooms = user.rooms && user.rooms.length > 0;
                  const isExpanded = Boolean(expandedRooms[user.id]);

                  return (
                    <React.Fragment key={user.id}>
                      <tr className={isOwnerItem ? "owner-row" : user.is_banned ? "banned-row" : ""}>
                        
                        {/* User Identity */}
                        <td className="col-user">
                          <img 
                            src={user.avatar_url || "https://cdn.discordapp.com/embed/avatars/0.png"} 
                            className="user-avatar" 
                            alt="" 
                          />
                          <div className="user-info">
                            <span className="user-name">{user.username}</span>
                            {isOwnerItem && <span className="badge-owner">OWNER</span>}
                          </div>
                        </td>
                        
                        {/* System IDs (LTR with copy functionality) */}
                        <td className="col-ids font-en">
                          <button
                            type="button"
                            className="id-tag-btn"
                            onClick={() => copyToClipboard(user.id, `uid-${user.id}`)}
                            title="انقر لنسخ المعرف UID"
                          >
                            <span className="id-tag-label">UID:</span>
                            <span>{user.id.slice(0, 10)}...</span>
                            {copiedId === `uid-${user.id}` ? (
                              <Check className="w-3 h-3 text-emerald-400" />
                            ) : (
                              <Copy className="w-3 h-3 text-slate-500" />
                            )}
                          </button>

                          {user.discord_id && user.discord_id !== "N/A" && (
                            <button
                              type="button"
                              className="id-tag-btn discord-tag"
                              onClick={() => copyToClipboard(user.discord_id, `disc-${user.id}`)}
                              title="انقر لنسخ معرف الديسكورد"
                            >
                              <span className="id-tag-label">Discord:</span>
                              <span>{user.discord_id}</span>
                              {copiedId === `disc-${user.id}` ? (
                                <Check className="w-3 h-3 text-emerald-400" />
                              ) : (
                                <Copy className="w-3 h-3 text-indigo-400" />
                              )}
                            </button>
                          )}
                        </td>

                        {/* Linked Accounts */}
                        <td className="col-center font-en">{user.accounts_count || 0}</td>

                        {/* Active Farms */}
                        <td className="col-center font-en font-bold text-emerald-400">
                          {user.characters_count || 0}
                        </td>

                        {/* Cloud Rooms (Interactive button to view/manage rooms) */}
                        <td className="col-center font-en">
                          {hasRooms ? (
                            <button
                              type="button"
                              onClick={() => toggleExpandRoom(user.id)}
                              className="room-expand-badge"
                              title="عرض وإدارة الغرف السحابية"
                            >
                              <span>{user.rooms_count || user.rooms.length}</span>
                              {isExpanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                            </button>
                          ) : (
                            <span className="text-slate-500">0</span>
                          )}
                        </td>

                        {/* Status */}
                        <td>
                          <span className={`status-badge ${user.is_banned ? "banned" : "active"}`}>
                            {user.is_banned ? "محظور" : "نشط"}
                          </span>
                        </td>

                        {/* Actions */}
                        <td className="col-actions">
                          {!isOwnerItem ? (
                            <button 
                              className={`btn-tbl-action ${user.is_banned ? "btn-unban" : "btn-ban"}`}
                              onClick={() => handleToggleBan(user.id, user.is_banned, user.username)}
                            >
                              {user.is_banned ? "إلغاء الحظر" : "حظر الحساب"}
                            </button>
                          ) : (
                            <span className="protected-tag">
                              <ShieldCheck className="w-3.5 h-3.5 text-amber-400" />
                              <span>حساب محمي</span>
                            </span>
                          )}
                        </td>
                      </tr>

                      {/* Expandable Bot Rooms Sub-row */}
                      {isExpanded && hasRooms && (
                        <tr className="rooms-sub-row">
                          <td colSpan={7}>
                            <div className="rooms-drawer">
                              <div className="rooms-drawer-header">
                                <Bot className="w-4 h-4 text-cyan-400" />
                                <span>الغرف السحابية التابعة لـ {user.username} ({user.rooms.length} غرف):</span>
                              </div>
                              <div className="rooms-drawer-grid">
                                {user.rooms.map((r) => {
                                  const isGem = r.name?.toLowerCase().includes("gem") || r.name?.includes("جواهر");
                                  return (
                                    <div key={r.id} className="room-sub-card">
                                      <div className="room-sub-main">
                                        <img 
                                          src={isGem ? ITEM_GEM_BASE64 : ITEM_FOOD_BASE64} 
                                          alt="" 
                                          className="room-sub-icon" 
                                        />
                                        <div>
                                          <div className="room-sub-name">{r.name}</div>
                                          <div className="room-sub-meta font-en">
                                            ID #{r.bot_id} • {r.slots} slots • {r.status || "ready"}
                                          </div>
                                        </div>
                                      </div>
                                      {!isOwnerItem && (
                                        <button
                                          type="button"
                                          onClick={() => handleDeleteRoom(user.id, r.id, r.name)}
                                          className="btn-room-del"
                                          title="حذف وتصفير الغرفة نهائياً"
                                        >
                                          <Trash2 className="w-3.5 h-3.5" />
                                          <span>حذف</span>
                                        </button>
                                      )}
                                    </div>
                                  );
                                })}
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })
              )}
            </tbody>
          </table>
        </section>
      )}

      {/* =========================================================================
          TAB 2: BACKEND SERVER MAINTENANCE CONTROLS
         ========================================================================= */}
      {currentTab === "server" && (
        <section className="server-ctrl-section">
          <div className="server-ctrl-card">
            <div className="server-ctrl-head">
              <div className={`power-icon-wrap ${maintenanceEnabled ? "power-off" : "power-on"}`}>
                <Power className="w-6 h-6" />
              </div>
              <div>
                <h2>مفتاح السيرفر الخلفي المركزي</h2>
                <p>إيقاف أو تشغيل وصول المستخدمين ومحرك البوت السحابي بالكامل.</p>
              </div>
            </div>

            {/* Current State Indicator */}
            <div className={`server-state-banner ${maintenanceEnabled ? "banner-offline" : "banner-online"}`}>
              <div className="state-badge-circle">{maintenanceEnabled ? "🛑" : "🟢"}</div>
              <div>
                <div className="state-title">
                  الحالة: {maintenanceEnabled ? "مطفأ للصيانة (MAINTENANCE OFFLINE)" : "يعمل بكامل كفاءته (ONLINE)"}
                </div>
                <div className="state-desc">
                  {maintenanceEnabled 
                    ? "السيرفر مغلق حالياً على جميع المشتركين وتظهر لهم رسالة الصيانة فوراً عند محاولة تشغيل البوت."
                    : "السيرفر متاح ومفتوح لجميع المشتركين وتعمل دورات الحصاد والنقل بصورة طبيعية."}
                </div>
              </div>
            </div>

            {/* Presets */}
            <div className="presets-wrap">
              <label>رسائل الصيانة الجاهزة:</label>
              <div className="presets-btns">
                {[
                  "لقد تم إطفاء السيرفر للصيانة من قبل الإدارة",
                  "جاري تحديث السيرفرات وإضافة مزايا الحصاد الذكي الجديدة، نعود قريباً",
                  "صيانة دورية لتحديث خوادم اللعبة وتأمين الحسابات"
                ].map((txt) => (
                  <button
                    key={txt}
                    type="button"
                    onClick={() => setMaintenanceMsg(txt)}
                    className="preset-btn"
                  >
                    {txt}
                  </button>
                ))}
              </div>
            </div>

            {/* Custom Message */}
            <div className="msg-field-wrap">
              <label>نص رسالة الصيانة المعروضة للمستخدمين:</label>
              <textarea
                value={maintenanceMsg}
                onChange={(e) => setMaintenanceMsg(e.target.value)}
                rows={3}
                className="server-textarea"
                placeholder="اكتب رسالة الصيانة هنا..."
              />
            </div>

            {/* Big Action Buttons */}
            <div className="server-actions-grid">
              <button
                type="button"
                onClick={() => handleSaveMaintenance(false)}
                disabled={savingMaint || !maintenanceEnabled}
                className="btn-server-on"
              >
                <CheckCircle className="w-5 h-5" />
                <span>تشغيل السيرفر للجميع (ONLINE)</span>
              </button>

              <button
                type="button"
                onClick={() => handleSaveMaintenance(true)}
                disabled={savingMaint || maintenanceEnabled}
                className="btn-server-off"
              >
                <Power className="w-5 h-5" />
                <span>إطفاء السيرفر للصيانة فوراً (OFFLINE)</span>
              </button>
            </div>

            {maintFeedback && (
              <p className="server-feedback-msg">{maintFeedback}</p>
            )}
          </div>
        </section>
      )}

      {/* =========================================================================
          TAB 3: ORDERS & PURCHASES LEDGER TABLE
         ========================================================================= */}
      {currentTab === "orders" && (
        <section className="table-container">
          <table className="admin-data-table">
            <thead>
              <tr>
                <th>رقم الفاتورة</th>
                <th>المشتري</th>
                <th>معرف المستخدم (UID)</th>
                <th>المنتج / الباقة</th>
                <th className="col-center">السعة (المزارع)</th>
                <th>وسيلة الدفع</th>
                <th className="col-center">المبلغ</th>
                <th>تاريخ الشراء</th>
                <th>الحالة</th>
              </tr>
            </thead>
            <tbody>
              {filteredOrders.length === 0 ? (
                <tr>
                  <td colSpan={9} className="col-empty">
                    لا توجد فواتير تطابق معايير البحث
                  </td>
                </tr>
              ) : (
                filteredOrders.map((ord) => (
                  <tr key={ord.id}>
                    <td className="font-en font-bold text-cyan-400">{ord.invoice_number}</td>
                    
                    <td className="col-user">
                      <img 
                        src={ord.avatar_url || "https://cdn.discordapp.com/embed/avatars/0.png"} 
                        className="user-avatar" 
                        alt="" 
                      />
                      <div className="user-info">
                        <span className="user-name">{ord.buyer_name}</span>
                        <span className="id-tag font-en">{ord.discord_id}</span>
                      </div>
                    </td>

                    <td className="font-en">
                      <button
                        type="button"
                        onClick={() => copyToClipboard(ord.user_id, `ord-${ord.id}`)}
                        className="id-tag-btn"
                        title="نسخ المعرف"
                      >
                        <span>{ord.user_id.slice(0, 10)}...</span>
                        {copiedId === `ord-${ord.id}` ? (
                          <Check className="w-3 h-3 text-emerald-400" />
                        ) : (
                          <Copy className="w-3 h-3 text-slate-500" />
                        )}
                      </button>
                    </td>

                    <td>
                      <span className="font-bold text-white">{ord.product_name}</span>
                      <span className="tier-tag font-en mr-1.5">{ord.tier.toUpperCase()}</span>
                    </td>

                    <td className="col-center font-en font-bold text-amber-300">
                      {ord.slots} مزارع
                    </td>

                    <td>
                      <span className="pay-method-badge">{ord.payment_method}</span>
                    </td>

                    <td className="col-center font-en font-black text-emerald-400 text-sm">
                      ${ord.amount}
                    </td>

                    <td className="font-en text-slate-400 text-xs">
                      {new Date(ord.created_at).toLocaleDateString("ar-EG")}
                    </td>

                    <td>
                      <span className="status-badge active uppercase font-en">
                        {ord.status}
                      </span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </section>
      )}

      {/* =========================================================================
          TAB 4: BROADCAST MAIL
         ========================================================================= */}
      {currentTab === "broadcast" && (
        <section className="broadcast-grid">
          <div className="broadcast-card">
            <h2>إرسال إشعار جماعي لجميع المشتركين</h2>
            <p className="broadcast-desc">يظهر الإشعار في صندوق الوارد لجميع المستخدمين داخل الموقع فوراً.</p>

            <div className="broadcast-form">
              <div className="form-group">
                <label>عنوان الإشعار:</label>
                <input
                  type="text"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="مثال: تم إطلاق تحديث الحصاد الذكي السحابي v2.5"
                  maxLength={120}
                  className="broadcast-input"
                />
              </div>

              <div className="form-group">
                <label>نص الرسالة:</label>
                <textarea
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  placeholder="اكتب تفاصيل التحديث أو التعليمات هنا..."
                  rows={6}
                  maxLength={4000}
                  className="broadcast-textarea"
                />
              </div>

              <div className="form-group">
                <label>مرفق صورة (اختياري):</label>
                {imageUrl ? (
                  <div className="img-preview-wrap">
                    <img src={imageUrl} alt="preview" className="img-preview" />
                    <button type="button" onClick={() => setImageUrl("")} className="btn-img-remove">
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                ) : (
                  <div>
                    <button
                      type="button"
                      onClick={() => imgRef.current?.click()}
                      disabled={uploading}
                      className="btn-upload"
                    >
                      {uploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <ImagePlus className="w-4 h-4 text-cyan-400" />}
                      <span>{uploading ? "جاري الرفع..." : "إرفاق صورة"}</span>
                    </button>
                    <input
                      ref={imgRef}
                      type="file"
                      accept="image/*"
                      className="hidden"
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) handleImageFile(f);
                        e.target.value = "";
                      }}
                    />
                  </div>
                )}
              </div>

              <button
                type="button"
                onClick={handleSendBroadcast}
                disabled={sending || !title.trim() || !body.trim()}
                className="btn-send-broadcast"
              >
                {sending ? <Loader2 className="w-4 h-4 animate-spin text-black" /> : <Send className="w-4 h-4 text-black" />}
                <span>إرسال لجميع المشتركين فوراً</span>
              </button>

              {broadcastMsg && <p className="msg-ok">{broadcastMsg}</p>}
              {broadcastErr && <p className="msg-err">{broadcastErr}</p>}
            </div>
          </div>

          {/* Past Announcements Feed */}
          <div className="broadcast-feed-card">
            <h3>سجل الإعلانات المرسلة سابقاً:</h3>
            {announcements.length === 0 ? (
              <p className="feed-empty">لا توجد إعلانات سابقة مسجلة.</p>
            ) : (
              <div className="feed-list">
                {announcements.map((a) => (
                  <div key={a.id} className="feed-item">
                    <div className="feed-item-top">
                      <span className="feed-title">{a.title}</span>
                      <span className="feed-date font-en">{new Date(a.created_at).toLocaleDateString("ar-EG")}</span>
                    </div>
                    <div 
                      className="feed-body" 
                      dangerouslySetInnerHTML={{ __html: linkifyHtml(a.body) }}
                    />
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>
      )}

      {/* =========================================================================
          PROFESSIONAL STYLING OVERHAUL (CSS / RTL NORMALIZATION)
         ========================================================================= */}
      <style jsx>{`
        .admin-dashboard-page {
          padding: 28px 36px;
          background-color: #070913;
          color: #cfd4e8;
          min-height: 100vh;
          font-family: 'Segoe UI', Tahoma, Arial, sans-serif;
          max-width: 1740px;
          margin: 0 auto;
        }

        .font-en {
          direction: ltr !important;
          display: inline-block;
          font-family: 'Consolas', 'Roboto Mono', 'JetBrains Mono', monospace;
        }

        /* Header */
        .admin-header {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          margin-bottom: 28px;
          border-bottom: 1px solid rgba(255, 255, 255, 0.08);
          padding-bottom: 22px;
          flex-wrap: wrap;
          gap: 16px;
        }

        .system-badge {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          background: rgba(234, 179, 8, 0.12);
          color: #facc15;
          border: 1px solid rgba(234, 179, 8, 0.3);
          padding: 4px 12px;
          border-radius: 20px;
          font-size: 0.75rem;
          font-weight: bold;
          letter-spacing: 0.5px;
          margin-bottom: 8px;
        }

        .status-dot.pulsing {
          width: 8px;
          height: 8px;
          background: #22c55e;
          border-radius: 50%;
          box-shadow: 0 0 8px #22c55e;
        }

        .badge-divider {
          opacity: 0.4;
        }

        .server-state-pill {
          font-size: 0.7rem;
          color: #94a3b8;
          font-weight: 600;
        }

        .admin-header h1 {
          font-size: 1.85rem;
          font-weight: 900;
          color: #ffffff;
          margin: 4px 0;
          letter-spacing: -0.5px;
        }

        .header-desc {
          font-size: 0.85rem;
          color: #8c96b5;
          margin-top: 2px;
        }

        .header-quick-actions {
          display: flex;
          align-items: center;
          gap: 12px;
        }

        .btn-action-outline {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          background: rgba(255, 255, 255, 0.04);
          border: 1px solid rgba(255, 255, 255, 0.15);
          color: #e2e8f0;
          padding: 9px 16px;
          border-radius: 10px;
          font-size: 0.82rem;
          font-weight: 700;
          cursor: pointer;
          transition: all 0.2s ease;
        }

        .btn-action-outline:hover {
          background: rgba(255, 255, 255, 0.08);
          border-color: #00e5ff;
          color: #ffffff;
        }

        .btn-action-primary {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          background: linear-gradient(135deg, #0284c7, #2563eb);
          color: #ffffff;
          padding: 9px 18px;
          border-radius: 10px;
          font-size: 0.82rem;
          font-weight: 800;
          text-decoration: none;
          box-shadow: 0 4px 14px rgba(37, 99, 235, 0.3);
          transition: all 0.2s ease;
        }

        .btn-action-primary:hover {
          opacity: 0.95;
          transform: translateY(-1px);
        }

        /* Metrics Grid */
        .metrics-grid {
          display: grid;
          grid-template-columns: repeat(4, 1fr);
          gap: 16px;
          margin-bottom: 28px;
        }

        @media (max-width: 1024px) {
          .metrics-grid {
            grid-template-columns: repeat(2, 1fr);
          }
        }

        @media (max-width: 640px) {
          .metrics-grid {
            grid-template-columns: 1fr;
          }
        }

        .metric-card {
          background: #0f1322;
          border: 1px solid #1e2640;
          border-radius: 14px;
          padding: 18px 20px;
          display: flex;
          align-items: center;
          gap: 16px;
          transition: all 0.2s ease;
        }

        .metric-card:hover {
          border-color: rgba(0, 229, 255, 0.3);
          transform: translateY(-1px);
        }

        .metric-card.highlight-green {
          border-color: rgba(34, 197, 94, 0.35);
          background: linear-gradient(135deg, #0f1322, #0d1e18);
        }

        .metric-icon {
          font-size: 1.8rem;
          background: rgba(255, 255, 255, 0.04);
          padding: 12px;
          border-radius: 12px;
          display: flex;
          align-items: center;
          justify-content: center;
          width: 52px;
          height: 52px;
          flex-shrink: 0;
          border: 1px solid rgba(255, 255, 255, 0.06);
        }

        .metric-details {
          display: flex;
          flex-direction: column;
          min-width: 0;
        }

        .metric-label {
          font-size: 0.82rem;
          color: #8c96b5;
          font-weight: 600;
        }

        .metric-value {
          font-size: 1.7rem;
          font-weight: 900;
          color: #ffffff;
          margin: 2px 0;
        }

        .metric-sub {
          font-size: 0.75rem;
          color: #64748b;
          font-weight: 500;
        }

        /* Toolbar & Filter */
        .toolbar-section {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 20px;
          gap: 20px;
          flex-wrap: wrap;
        }

        .tab-pills {
          display: flex;
          background: #0f1322;
          border: 1px solid #1e2640;
          border-radius: 10px;
          padding: 4px;
          gap: 4px;
        }

        .tab-btn {
          background: transparent;
          border: none;
          color: #94a3b8;
          padding: 8px 16px;
          border-radius: 8px;
          cursor: pointer;
          font-weight: 700;
          font-size: 0.88rem;
          display: inline-flex;
          align-items: center;
          gap: 8px;
          transition: all 0.2s ease;
        }

        .tab-btn:hover {
          color: #ffffff;
          background: rgba(255, 255, 255, 0.04);
        }

        .tab-btn.active {
          background: #2563eb;
          color: #ffffff;
          box-shadow: 0 2px 8px rgba(37, 99, 235, 0.35);
        }

        .tab-counter {
          font-size: 0.72rem;
          background: rgba(0, 0, 0, 0.3);
          padding: 1px 6px;
          border-radius: 12px;
          font-family: monospace;
        }

        .tab-dot {
          width: 6px;
          height: 6px;
          border-radius: 50%;
        }

        .dot-green { background: #22c55e; box-shadow: 0 0 6px #22c55e; }
        .dot-red { background: #ef4444; box-shadow: 0 0 6px #ef4444; }

        .search-box {
          position: relative;
          flex: 1;
          max-width: 440px;
          min-width: 260px;
        }

        :global(.icon-search) {
          position: absolute;
          right: 14px;
          top: 50%;
          transform: translateY(-50%);
          width: 16px;
          height: 16px;
          color: #64748b;
          pointer-events: none;
        }

        .search-box input {
          width: 100%;
          background: #0f1322;
          border: 1px solid #1e2640;
          padding: 10px 40px 10px 36px;
          border-radius: 10px;
          color: #ffffff;
          outline: none;
          font-size: 0.88rem;
          transition: all 0.2s ease;
        }

        .search-box input:focus {
          border-color: #3b82f6;
          box-shadow: 0 0 12px rgba(59, 130, 246, 0.25);
        }

        .search-clear {
          position: absolute;
          left: 12px;
          top: 50%;
          transform: translateY(-50%);
          background: none;
          border: none;
          color: #64748b;
          cursor: pointer;
        }

        .search-clear:hover {
          color: #ffffff;
        }

        /* Data Table */
        .table-container {
          background: #0f1322;
          border: 1px solid #1e2640;
          border-radius: 14px;
          overflow: hidden;
          box-shadow: 0 10px 30px rgba(0, 0, 0, 0.4);
        }

        .admin-data-table {
          width: 100%;
          border-collapse: collapse;
          text-align: right;
          font-size: 0.88rem;
        }

        .admin-data-table th {
          background: #141a2e;
          color: #94a3b8;
          padding: 14px 18px;
          font-weight: 700;
          border-bottom: 1px solid #1e2640;
          white-space: nowrap;
        }

        .admin-data-table td {
          padding: 14px 18px;
          border-bottom: 1px solid #171f38;
          vertical-align: middle;
        }

        .col-center { 
          text-align: center; 
        }

        .col-empty {
          text-align: center;
          padding: 48px;
          color: #64748b;
          font-weight: 600;
        }

        .col-user {
          display: flex;
          align-items: center;
          gap: 12px;
        }

        .user-avatar {
          width: 40px;
          height: 40px;
          border-radius: 50%;
          border: 1px solid #2d3748;
          object-fit: cover;
          flex-shrink: 0;
        }

        .user-info {
          display: flex;
          align-items: center;
          gap: 8px;
          flex-wrap: wrap;
        }

        .user-name {
          font-weight: 800;
          color: #ffffff;
          font-size: 0.92rem;
        }

        .badge-owner {
          background: #ca8a04;
          color: #ffffff;
          font-size: 0.7rem;
          padding: 2px 8px;
          border-radius: 6px;
          font-weight: 900;
          letter-spacing: 0.5px;
        }

        .col-ids {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }

        .id-tag-btn {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          background: rgba(0, 0, 0, 0.35);
          border: 1px solid rgba(255, 255, 255, 0.08);
          border-radius: 6px;
          padding: 2px 8px;
          font-size: 0.78rem;
          color: #94a3b8;
          cursor: pointer;
          width: fit-content;
          transition: all 0.15s ease;
        }

        .id-tag-btn:hover {
          color: #ffffff;
          border-color: rgba(255, 255, 255, 0.2);
        }

        .discord-tag {
          background: rgba(88, 101, 242, 0.12);
          border-color: rgba(88, 101, 242, 0.3);
          color: #c7d2fe;
        }

        .id-tag-label {
          color: #64748b;
          font-weight: 700;
        }

        .room-expand-badge {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          background: rgba(0, 229, 255, 0.1);
          border: 1px solid rgba(0, 229, 255, 0.25);
          color: #00e5ff;
          padding: 3px 10px;
          border-radius: 8px;
          font-size: 0.8rem;
          font-weight: 800;
          cursor: pointer;
          transition: all 0.2s ease;
        }

        .room-expand-badge:hover {
          background: rgba(0, 229, 255, 0.2);
          border-color: #00e5ff;
        }

        .status-badge {
          padding: 4px 12px;
          border-radius: 14px;
          font-size: 0.78rem;
          font-weight: 700;
          display: inline-block;
          text-align: center;
        }

        .status-badge.active { 
          background: rgba(34, 197, 94, 0.15); 
          color: #4ade80; 
          border: 1px solid rgba(34, 197, 94, 0.3);
        }

        .status-badge.banned { 
          background: rgba(239, 68, 68, 0.15); 
          color: #f87171; 
          border: 1px solid rgba(239, 68, 68, 0.3);
        }

        .btn-tbl-action {
          padding: 6px 14px;
          border-radius: 8px;
          border: none;
          font-size: 0.8rem;
          cursor: pointer;
          font-weight: 800;
          transition: all 0.2s ease;
        }

        .btn-ban { 
          background: #dc2626; 
          color: #ffffff; 
        }

        .btn-ban:hover { 
          background: #b91c1c; 
        }

        .btn-unban { 
          background: #16a34a; 
          color: #ffffff; 
        }

        .btn-unban:hover { 
          background: #15803d; 
        }

        .protected-tag { 
          color: #facc15; 
          font-size: 0.78rem; 
          font-weight: 800;
          display: inline-flex;
          align-items: center;
          gap: 4px;
        }

        .tier-tag {
          font-size: 0.72rem;
          background: rgba(0, 229, 255, 0.12);
          color: #00e5ff;
          border: 1px solid rgba(0, 229, 255, 0.25);
          padding: 2px 6px;
          border-radius: 6px;
          font-weight: 800;
        }

        .pay-method-badge {
          font-size: 0.78rem;
          background: rgba(255, 255, 255, 0.05);
          border: 1px solid rgba(255, 255, 255, 0.1);
          padding: 4px 10px;
          border-radius: 8px;
          color: #cbd5e1;
        }

        /* Rooms Sub Drawer */
        .rooms-sub-row td {
          background: #090c17;
          padding: 16px 24px;
          border-bottom: 2px solid #1e2640;
        }

        .rooms-drawer-header {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 0.8rem;
          font-weight: 800;
          color: #94a3b8;
          margin-bottom: 12px;
        }

        .rooms-drawer-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
          gap: 12px;
        }

        .room-sub-card {
          background: #11172a;
          border: 1px solid #1e293b;
          border-radius: 10px;
          padding: 10px 14px;
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 10px;
        }

        .room-sub-main {
          display: flex;
          align-items: center;
          gap: 10px;
          min-width: 0;
        }

        .room-sub-icon {
          width: 24px;
          height: 24px;
          object-fit: contain;
          flex-shrink: 0;
        }

        .room-sub-name {
          font-size: 0.82rem;
          font-weight: 800;
          color: #ffffff;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .room-sub-meta {
          font-size: 0.72rem;
          color: #64748b;
        }

        .btn-room-del {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          background: rgba(239, 68, 68, 0.15);
          border: 1px solid rgba(239, 68, 68, 0.3);
          color: #f87171;
          padding: 4px 8px;
          border-radius: 6px;
          font-size: 0.72rem;
          font-weight: 800;
          cursor: pointer;
          transition: all 0.2s ease;
        }

        .btn-room-del:hover {
          background: #ef4444;
          color: #ffffff;
        }

        /* Server Maintenance Section */
        .server-ctrl-section {
          max-width: 820px;
          margin: 0 auto;
        }

        .server-ctrl-card {
          background: #0f1322;
          border: 1px solid #1e2640;
          border-radius: 16px;
          padding: 28px 32px;
          display: flex;
          flex-direction: column;
          gap: 20px;
        }

        .server-ctrl-head {
          display: flex;
          align-items: center;
          gap: 16px;
        }

        .power-icon-wrap {
          width: 52px;
          height: 52px;
          border-radius: 14px;
          display: flex;
          align-items: center;
          justify-content: center;
        }

        .power-on {
          background: rgba(34, 197, 94, 0.15);
          border: 1px solid rgba(34, 197, 94, 0.35);
          color: #4ade80;
        }

        .power-off {
          background: rgba(239, 68, 68, 0.15);
          border: 1px solid rgba(239, 68, 68, 0.35);
          color: #f87171;
        }

        .server-ctrl-head h2 {
          font-size: 1.3rem;
          font-weight: 900;
          color: #ffffff;
        }

        .server-ctrl-head p {
          font-size: 0.82rem;
          color: #8c96b5;
          margin-top: 2px;
        }

        .server-state-banner {
          display: flex;
          align-items: center;
          gap: 16px;
          padding: 18px 22px;
          border-radius: 14px;
          border: 1px solid;
        }

        .banner-online {
          background: linear-gradient(135deg, rgba(16, 185, 129, 0.1), rgba(15, 23, 42, 0.6));
          border-color: rgba(34, 197, 94, 0.4);
        }

        .banner-offline {
          background: linear-gradient(135deg, rgba(239, 68, 68, 0.1), rgba(15, 23, 42, 0.6));
          border-color: rgba(239, 68, 68, 0.4);
        }

        .state-badge-circle {
          font-size: 2rem;
        }

        .state-title {
          font-size: 1.05rem;
          font-weight: 900;
          color: #ffffff;
        }

        .state-desc {
          font-size: 0.82rem;
          color: #94a3b8;
          margin-top: 2px;
        }

        .presets-wrap label, .msg-field-wrap label {
          font-size: 0.8rem;
          font-weight: 700;
          color: #94a3b8;
          display: block;
          margin-bottom: 8px;
        }

        .presets-btns {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }

        .preset-btn {
          background: rgba(255, 255, 255, 0.04);
          border: 1px solid rgba(255, 255, 255, 0.1);
          color: #cbd5e1;
          padding: 6px 12px;
          border-radius: 8px;
          font-size: 0.78rem;
          cursor: pointer;
          transition: all 0.15s ease;
        }

        .preset-btn:hover {
          background: rgba(255, 255, 255, 0.08);
          color: #ffffff;
          border-color: #3b82f6;
        }

        .server-textarea {
          width: 100%;
          background: #090c17;
          border: 1px solid #1e2640;
          border-radius: 12px;
          padding: 12px 16px;
          color: #ffffff;
          font-size: 0.88rem;
          outline: none;
          resize: none;
          font-family: inherit;
        }

        .server-textarea:focus {
          border-color: #3b82f6;
        }

        .server-actions-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 16px;
          padding-top: 8px;
        }

        .btn-server-on {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 10px;
          padding: 14px 20px;
          border-radius: 12px;
          background: linear-gradient(135deg, #059669, #0d9488);
          color: #ffffff;
          font-size: 0.88rem;
          font-weight: 900;
          border: none;
          cursor: pointer;
          box-shadow: 0 4px 14px rgba(5, 150, 105, 0.35);
          transition: all 0.2s ease;
        }

        .btn-server-on:hover:not(:disabled) {
          opacity: 0.95;
          transform: translateY(-1px);
        }

        .btn-server-off {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 10px;
          padding: 14px 20px;
          border-radius: 12px;
          background: linear-gradient(135deg, #dc2626, #b91c1c);
          color: #ffffff;
          font-size: 0.88rem;
          font-weight: 900;
          border: none;
          cursor: pointer;
          box-shadow: 0 4px 14px rgba(220, 38, 38, 0.35);
          transition: all 0.2s ease;
        }

        .btn-server-off:hover:not(:disabled) {
          opacity: 0.95;
          transform: translateY(-1px);
        }

        .btn-server-on:disabled, .btn-server-off:disabled {
          opacity: 0.4;
          cursor: not-allowed;
          box-shadow: none;
        }

        .server-feedback-msg {
          text-align: center;
          font-size: 0.85rem;
          font-weight: 800;
          color: #00e5ff;
        }

        /* Broadcast Section */
        .broadcast-grid {
          display: grid;
          grid-template-columns: 2fr 1fr;
          gap: 20px;
        }

        @media (max-width: 1024px) {
          .broadcast-grid {
            grid-template-columns: 1fr;
          }
        }

        .broadcast-card, .broadcast-feed-card {
          background: #0f1322;
          border: 1px solid #1e2640;
          border-radius: 16px;
          padding: 24px 28px;
        }

        .broadcast-card h2, .broadcast-feed-card h3 {
          font-size: 1.15rem;
          font-weight: 900;
          color: #ffffff;
        }

        .broadcast-desc {
          font-size: 0.82rem;
          color: #8c96b5;
          margin-top: 2px;
          margin-bottom: 20px;
        }

        .broadcast-form {
          display: flex;
          flex-direction: column;
          gap: 16px;
        }

        .form-group label {
          font-size: 0.8rem;
          font-weight: 700;
          color: #94a3b8;
          display: block;
          margin-bottom: 6px;
        }

        .broadcast-input, .broadcast-textarea {
          width: 100%;
          background: #090c17;
          border: 1px solid #1e2640;
          border-radius: 10px;
          padding: 10px 14px;
          color: #ffffff;
          font-size: 0.88rem;
          outline: none;
          font-family: inherit;
        }

        .broadcast-input:focus, .broadcast-textarea:focus {
          border-color: #3b82f6;
        }

        .btn-upload {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          background: rgba(255, 255, 255, 0.05);
          border: 1px solid rgba(255, 255, 255, 0.12);
          color: #e2e8f0;
          padding: 8px 16px;
          border-radius: 8px;
          font-size: 0.8rem;
          font-weight: 700;
          cursor: pointer;
        }

        .img-preview-wrap {
          position: relative;
          max-width: 240px;
          border-radius: 10px;
          overflow: hidden;
          border: 1px solid #1e2640;
        }

        .img-preview {
          width: 100%;
          height: auto;
          display: block;
        }

        .btn-img-remove {
          position: absolute;
          top: 6px;
          left: 6px;
          background: rgba(0, 0, 0, 0.8);
          border: 1px solid rgba(255, 255, 255, 0.2);
          color: #ffffff;
          border-radius: 6px;
          padding: 4px;
          cursor: pointer;
        }

        .btn-send-broadcast {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          gap: 8px;
          background: linear-gradient(135deg, #00e5ff, #3b82f6);
          color: #000000;
          padding: 12px 24px;
          border-radius: 10px;
          font-size: 0.85rem;
          font-weight: 900;
          border: none;
          cursor: pointer;
          box-shadow: 0 4px 14px rgba(0, 229, 255, 0.35);
          transition: all 0.2s ease;
        }

        .btn-send-broadcast:hover:not(:disabled) {
          opacity: 0.95;
          transform: translateY(-1px);
        }

        .btn-send-broadcast:disabled {
          opacity: 0.4;
          cursor: not-allowed;
        }

        .msg-ok { color: #4ade80; font-size: 0.82rem; font-weight: 700; }
        .msg-err { color: #f87171; font-size: 0.82rem; font-weight: 700; }

        .feed-empty { font-size: 0.82rem; color: #64748b; margin-top: 14px; }
        .feed-list { display: flex; flex-direction: column; gap: 10px; margin-top: 14px; max-height: 520px; overflow-y: auto; }
        .feed-item { background: #090c17; border: 1px solid #1e2640; border-radius: 10px; padding: 12px 14px; }
        .feed-item-top { display: flex; justify-content: space-between; align-items: center; font-size: 0.82rem; font-weight: 800; color: #ffffff; }
        .feed-date { font-size: 0.72rem; color: #64748b; }
        .feed-body { font-size: 0.78rem; color: #94a3b8; margin-top: 6px; line-height: 1.5; }

        /* Loading / Forbidden */
        .admin-loading-screen, .admin-forbidden-screen {
          min-height: 75vh;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          gap: 16px;
        }

        .admin-loading-text { font-size: 0.88rem; color: #94a3b8; font-weight: 700; }
        .forbidden-box { background: #0f1322; border: 1px solid rgba(239, 68, 68, 0.4); border-radius: 16px; padding: 36px 40px; text-align: center; max-width: 520px; }

        /* Toast */
        .admin-toast {
          position: fixed;
          top: 24px;
          left: 50%;
          transform: translateX(-50%);
          z-index: 9999;
          background: #0f172a;
          border: 1px solid #00e5ff;
          color: #00e5ff;
          padding: 10px 20px;
          border-radius: 14px;
          font-size: 0.85rem;
          font-weight: 800;
          box-shadow: 0 4px 20px rgba(0, 229, 255, 0.35);
          display: flex;
          align-items: center;
          gap: 8px;
        }
      `}</style>

    </div>
  );
}
