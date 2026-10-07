"use client";

import React, { createContext, useContext, useEffect, useState } from "react";
import { supabase } from "@/lib/supabaseClient";
import type { User, Session } from "@supabase/supabase-js";

export interface GhostBotContextType {
  user: User | null;
  session: Session | null;
  profile: any;
  bots: any[];
  accounts: any[];
  isLoading: boolean;
  refreshData: () => Promise<void>;
  loading?: boolean;
  refreshUserData?: () => Promise<void>;
  clearStore?: () => void;
}

const GhostBotContext = createContext<GhostBotContextType>({
  user: null,
  session: null,
  profile: null,
  bots: [],
  accounts: [],
  isLoading: true,
  refreshData: async () => {},
});

export const SupabaseProvider = ({ children }: { children: React.ReactNode }) => {
  const [user, setUser] = useState<User | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [profile, setProfile] = useState<any>(null);
  const [bots, setBots] = useState<any[]>([]);
  const [accounts, setAccounts] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const hydrateUserData = async (userId: string, currentUser?: User) => {
    try {
      // 1. Fetch Profile + Bot Instances + Game Accounts + Characters concurrently
      const [profileRes, botsRes, accountsRes, charactersRes] = await Promise.all([
        supabase.from("profiles").select("*").eq("id", userId).maybeSingle(),
        supabase
          .from("bot_instances")
          .select("*")
          .eq("user_id", userId)
          .order("created_at", { ascending: true }),
        supabase.from("game_accounts").select("*").eq("user_id", userId),
        supabase.from("game_characters").select("*").eq("user_id", userId),
      ]);

      // Fallback profile details directly from OAuth metadata if DB trigger is delayed
      const meta = currentUser?.user_metadata || {};
      const resolvedProfile = profileRes.data || {
        id: userId,
        username:
          meta.custom_claims?.global_name ||
          meta.full_name ||
          meta.name ||
          "Commander",
        avatar_url: meta.avatar_url || meta.picture || "/ghostbot-logo.png",
        role: "user",
      };

      const rawAccs = accountsRes.data || [];
      const rawChars = charactersRes.data || [];

      // Map characters into account items with 0 initial stats until gathered from game
      const enrichedAccounts = rawAccs.flatMap((acc: any) => {
        const charsForAcc = rawChars.filter((c: any) => c.account_id === acc.id);
        if (charsForAcc.length === 0) {
          return [{
            ...acc,
            governor_name: acc.email?.split("@")[0] || "Governor",
            kingdom: String(acc.kingdom_id || "3057"),
            city_hall_level: 25,
            power: 0,
            status: acc.is_enabled ? "متصل وجاهز" : "معطل",
            food: "0",
            wood: "0",
            stone: "0",
            gold: "0",
            gems: "0",
            total_rss: "0",
          }];
        }
        return charsForAcc.map((c: any) => ({
          id: `char-${c.id}`,
          role_id: c.role_id,
          email: acc.email,
          governor_name: c.name || `Governor #${c.role_id}`,
          kingdom: String(c.kingdom_id || "3057"),
          city_hall_level: c.city_level || 1,
          power: c.power || 0,
          status: c.is_enabled ? "متصل وجاهز" : "معطل",
          instance_id: c.instance_id || acc.instance_id,
          food: "0",
          wood: "0",
          stone: "0",
          gold: "0",
          gems: "0",
          total_rss: "0",
          enabled: c.is_enabled,
        }));
      });

      let resolvedBots = botsRes.data || [];
      
      // If user has 0 bots, leave as empty array (0 rooms) for a true multi-tenant default state
      if (resolvedBots.length === 0) {
        try {
          const { getBots } = await import("@/lib/store");
          const localBots = getBots();
          if (localBots && localBots.length > 0) {
            resolvedBots = localBots.map((lb) => ({
              id: lb.id,
              bot_id: lb.bot_id || lb.id,
              name: lb.label,
              product: lb.product,
              tier: lb.tier || "pro",
              slots: lb.slots || 5,
              status: "active",
              config: {},
              expires_at: lb.expiresAt || new Date(Date.now() + 30 * 86400000).toISOString(),
            }));
          }
        } catch {
          resolvedBots = [];
        }
      }

      setProfile(resolvedProfile);
      setBots(resolvedBots);
      setAccounts(enrichedAccounts);
    } catch (err) {
      console.error("[HYDRATION_ERROR]", err);
    } finally {
      setIsLoading(false);
    }
  };

  const clearUnauthenticatedState = () => {
    setUser(null);
    setSession(null);
    setProfile(null);
    setBots([]);
    setAccounts([]);
    setIsLoading(false);
  };

  useEffect(() => {
    let mounted = true;

    // 1. Immediate active session check on mount
    supabase.auth.getSession().then(async (res: any) => {
      const currentSession = res?.data?.session;
      if (!mounted) return;
      if (currentSession?.user && !currentSession.user.is_anonymous) {
        setUser(currentSession.user);
        setSession(currentSession);
        await hydrateUserData(currentSession.user.id, currentSession.user);
      } else {
        clearUnauthenticatedState();
      }
    }).catch(async () => {
      clearUnauthenticatedState();
    });

    // 2. Listen to all Supabase auth lifecycle events
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange(async (event: any, currentSession: any) => {
      if (!mounted) return;

      if (currentSession?.user) {
        setUser(currentSession.user);
        setSession(currentSession);
        await hydrateUserData(currentSession.user.id, currentSession.user);
      } else if (event === "SIGNED_OUT") {
        setUser(null);
        setSession(null);
        setProfile(null);
        setBots([]);
        setAccounts([]);
        setIsLoading(false);
      }
    });

    return () => {
      mounted = false;
      subscription.unsubscribe();
    };
  }, []);

  // 3. Realtime subscription to bot_instances and game_accounts
  useEffect(() => {
    if (!user?.id) return;

    const channel = supabase
      .channel(`realtime-user-fleet-${user.id}`)
      .on(
        "postgres_changes",
        {
          event: "*",
          schema: "public",
          table: "bot_instances",
          filter: `user_id=eq.${user.id}`,
        },
        () => {
          hydrateUserData(user.id, user);
        }
      )
      .on(
        "postgres_changes",
        {
          event: "*",
          schema: "public",
          table: "game_accounts",
          filter: `user_id=eq.${user.id}`,
        },
        () => {
          hydrateUserData(user.id, user);
        }
      )
      .on(
        "postgres_changes",
        {
          event: "*",
          schema: "public",
          table: "game_characters",
          filter: `user_id=eq.${user.id}`,
        },
        () => {
          hydrateUserData(user.id, user);
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [user?.id]);

  const refreshData = async () => {
    if (user?.id) {
      await hydrateUserData(user.id, user);
    }
  };

  const contextValue: GhostBotContextType = {
    user,
    session,
    profile,
    bots,
    accounts,
    isLoading,
    refreshData,
    loading: isLoading,
    refreshUserData: refreshData,
    clearStore: () => {
      setUser(null);
      setSession(null);
      setProfile(null);
      setBots([]);
      setAccounts([]);
      setIsLoading(false);
    },
  };

  return (
    <GhostBotContext.Provider value={contextValue}>
      {isLoading ? (
        // Sleek Cyber Skeleton Loader to prevent UI flicker
        <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-[#04080e] text-[#00e5ff]">
          <div className="relative flex items-center justify-center w-24 h-24 mb-6">
            <div className="absolute inset-0 rounded-full border-2 border-[#00e5ff]/20 animate-ping" />
            <div className="w-16 h-16 rounded-2xl bg-[#07131f] border border-[#00e5ff] shadow-[0_0_25px_rgba(0,229,255,0.4)] flex items-center justify-center">
              <span className="text-2xl animate-pulse">⚡</span>
            </div>
          </div>
          <div className="text-sm font-mono tracking-widest uppercase text-[#00e5ff]/80">
            جاري استرجاع بيانات السحابة الآمنة...
          </div>
          <div className="text-xs text-[#88a0b8] mt-2 font-mono">
            Securing GhostBot Multi-Tenant Tunnel
          </div>
        </div>
      ) : (
        children
      )}
    </GhostBotContext.Provider>
  );
};

export const useGhostBot = () => useContext(GhostBotContext);
export const useSupabaseStore = () => useContext(GhostBotContext);
export default SupabaseProvider;
