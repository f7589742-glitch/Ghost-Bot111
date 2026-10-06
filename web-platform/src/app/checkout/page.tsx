"use client";

import React, { Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import CheckoutView from "@/components/CheckoutView";

const ITEM_NAMES: Record<string, string> = {
  "farm-bot": "Farm Bot",
  "gem-bot": "Gem Bot",
};

function CheckoutRouter() {
  const params = useSearchParams();
  const router = useRouter();
  const item = params.get("item") ?? params.get("plan") ?? "farm-bot";
  const ref = params.get("ref") ?? params.get("code") ?? "";

  if (!(item in ITEM_NAMES)) {
    return (
      <div className="card p-10 text-center space-y-3">
        <h3 className="text-lg font-bold text-white">Coming soon</h3>
        <p className="text-sm text-zinc-500">
          This product is not available for purchase yet. We will enable it soon.
        </p>
        <button onClick={() => router.push("/shop")} className="btn-primary px-5 py-2.5 text-sm">
          Back to Store
        </button>
      </div>
    );
  }
  return <CheckoutView itemId={item} itemName={ITEM_NAMES[item]} initialReferral={ref} />;
}

export default function CheckoutPage() {
  return (
    <Suspense fallback={<div className="text-sm text-zinc-500">Loading checkout…</div>}>
      <CheckoutRouter />
    </Suspense>
  );
}
