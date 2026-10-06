"use client";

export interface OrderRecord {
  id: string; // e.g. "GB-89214"
  bot_id: string; // "farm-bot-1"
  name: string; // "Rey's Farm Bot #1"
  product: "farm-bot" | "gem-bot";
  tier: "basic" | "pro";
  slots: number; // 5
  duration: number; // 30 or 90
  amount: string; // "10.00"
  pay_method: string; // "USDT (TRC20)", "PayPal & Cards", "Binance Pay", etc.
  created_at: string;
  expires_at: string;
  status: "active" | "expired";
}

const ORDERS_KEY_PREFIX = "ghostbot_orders_v2__";

export function getStoredOrders(userId: string = "guest"): OrderRecord[] {
  if (typeof window === "undefined") return [];
  const key = ORDERS_KEY_PREFIX + (userId || "guest");
  try {
    const raw = localStorage.getItem(key);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) {
        return parsed;
      }
    }
  } catch (e) {
    console.error("Failed to read orders:", e);
  }

  return [];
}

export function saveNewOrder(order: OrderRecord, userId: string = "guest"): OrderRecord[] {
  if (typeof window === "undefined") return [];
  const key = ORDERS_KEY_PREFIX + (userId || "guest");
  const existing = getStoredOrders(userId);
  const updated = [order, ...existing.filter((o) => o.id !== order.id)];
  try {
    localStorage.setItem(key, JSON.stringify(updated));
  } catch (e) {
    console.error("Failed to save order:", e);
  }
  return updated;
}
