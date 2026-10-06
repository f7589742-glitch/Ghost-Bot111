"use client";

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Inbox as InboxIcon, Loader2, MailOpen } from "lucide-react";
import TiltCard3D from "@/components/hud/TiltCard3D";
import { linkifyHtml } from "@/lib/format";

interface Announcement {
  id: number;
  title: string;
  body: string;
  image_url?: string | null;
  created_at: string;
}

const SEEN_KEY = "zb_inbox_seen";

export default function InboxPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [items, setItems] = useState<Announcement[]>([]);
  const [seenMax, setSeenMax] = useState<number>(0);
  const [err, setErr] = useState("");

  useEffect(() => {
    try {
      setSeenMax(Number(localStorage.getItem(SEEN_KEY) || 0));
    } catch {
      /* private mode */
    }
    (async () => {
      try {
        const res = await fetch("/api/announcements");
        const data = await res.json();
        if (res.status === 401) {
          router.replace("/login?redirectTo=/inbox");
          return;
        }
        if (!data.success) throw new Error(data.error || "Failed to load inbox.");
        const list: Announcement[] = data.announcements || [];
        setItems(list);
        // Mark everything currently visible as read after a short view delay
        if (list.length > 0) {
          const maxId = Math.max(...list.map((a) => a.id));
          setTimeout(() => {
            try {
              localStorage.setItem(SEEN_KEY, String(maxId));
            } catch {
              /* ignore */
            }
          }, 2000);
        }
      } catch (e: any) {
        setErr(e?.message || "Failed to load inbox.");
      } finally {
        setLoading(false);
      }
    })();
  }, [router]);

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-cyan-400 animate-ping" />
          <span className="text-xs font-semibold tracking-wider text-cyan-400 uppercase">
            Owner Updates · Read Only
          </span>
        </div>
        <h1 className="text-3xl font-extrabold tracking-tight text-white mt-1 flex items-center gap-2">
          <InboxIcon className="w-7 h-7 text-cyan-400" />
          Inbox
        </h1>
        <p className="text-sm text-zinc-400 mt-1">
          Announcements from the ZeroBot team. Reading only — no replies.
        </p>
      </div>

      {loading ? (
        <p className="text-xs text-zinc-500 flex items-center gap-2">
          <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading messages...
        </p>
      ) : err ? (
        <TiltCard3D glowColor="gold" className="p-6">
          <p className="text-xs text-rose-400">{err}</p>
        </TiltCard3D>
      ) : items.length === 0 ? (
        <TiltCard3D glowColor="default" className="p-8 text-center">
          <MailOpen className="w-8 h-8 text-zinc-600 mx-auto mb-3" />
          <p className="text-sm font-semibold text-white">Inbox is empty</p>
          <p className="text-xs text-zinc-500 mt-1">New owner updates will appear here.</p>
        </TiltCard3D>
      ) : (
        <div className="space-y-3">
          {items.map((a) => {
            const isNew = a.id > seenMax;
            return (
              <TiltCard3D key={a.id} glowColor={isNew ? "cyan" : "default"} className="p-5">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2 min-w-0">
                    <div className="text-sm font-bold text-white truncate">{a.title}</div>
                    {isNew && (
                      <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 uppercase shrink-0">
                        New
                      </span>
                    )}
                  </div>
                  <div className="text-[11px] text-zinc-500 shrink-0">
                    {new Date(a.created_at).toLocaleString()}
                  </div>
                </div>
                <div
                  className="text-xs text-zinc-300 mt-2 leading-relaxed break-words [&_a]:text-cyan-300"
                  dangerouslySetInnerHTML={{ __html: linkifyHtml(a.body) }}
                />
                {a.image_url && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={a.image_url}
                    alt=""
                    className="mt-3 rounded-lg border border-zinc-800 max-h-72 w-full object-cover"
                  />
                )}
              </TiltCard3D>
            );
          })}
        </div>
      )}
    </div>
  );
}
