/**
 * Gathering commander registry for manual march pairs.
 * heroId = live numeric commander ID from the game wire protocol
 * (Opcode 367 catalogue, see app/services/smart_gather_search.py
 * COMMANDER_NAMES). Entries with heroId null have no known wire ID yet
 * and are always shown locked ("غير مدعوم بعد").
 * Icons live in public/assets/commanders/.
 */
export interface GatheringCommander {
  id: string;
  heroId: number | null;
  name: string;
  icon: string;
  rarity: "advanced" | "elite" | "epic" | "legendary";
  /** Shown under locked tiles when heroId is null. */
  pendingNote?: string;
}

export const COMMANDER_ICON_BASE = "/assets/commanders";

// heroId = PROVEN live wire ID (official detail screen matched 1:1 with
// Opcode 367 id/level/star). Entries with heroId null are honestly locked:
// either not recruited (Casimir/Pepin) or wire ID still ambiguous
// (Centurion = 7/24, Ishida = 62/105 - same level+stars, unresolvable
// from screenshots; a wrong guess would dispatch the wrong hero).
export const GATHERING_COMMANDERS: GatheringCommander[] = [
  { id: "joan_of_arc", heroId: 15, name: "جوان دارك (Joan of Arc)", icon: "joan_of_arc.png", rarity: "epic" },
  { id: "tamar", heroId: 134, name: "تامار (Tamar)", icon: "tamar.png", rarity: "epic" },
  { id: "cleopatra", heroId: null, name: "كليوباترا (Cleopatra)", icon: "cleopatra.png", rarity: "legendary", pendingNote: "المعرف غير مؤكد" },
  { id: "seondeok", heroId: 102, name: "سوندوك (Seondeok)", icon: "seondeok.png", rarity: "legendary" },
  { id: "matilda", heroId: 572, name: "ماتيلدا (Matilda)", icon: "matilda.png", rarity: "epic" },
  { id: "ishida_mitsunari", heroId: 32, name: "إيشيدا (Ishida Mitsunari)", icon: "ishida-mitsunari-icon.webp", rarity: "legendary" },
  { id: "constance", heroId: 33, name: "كونستانس (Constance)", icon: "constance-icon.webp", rarity: "elite" },
  { id: "sarka", heroId: 38, name: "ساركا (Sarka)", icon: "Sarka.png", rarity: "elite" },
  { id: "gaius_marius", heroId: 34, name: "غايوس ماريوس (Gaius Marius)", icon: "gaius-marius-icon.webp", rarity: "elite" },
  { id: "centurion", heroId: 24, name: "سنتوريون (Centurion)", icon: "Centurion.webp", rarity: "advanced" },
  { id: "casimir", heroId: null, name: "كازيمير (Casimir)", icon: "Casimir-Icon.png", rarity: "legendary" },
  { id: "pepin", heroId: null, name: "بيبن (Pepin)", icon: "Pepin-Icon.png", rarity: "legendary" },
  { id: "wak_chanil_ajaw", heroId: null, name: "واك شانيل (Wak-Chanil-Ajaw)", icon: "Wak-Chanil-Ajaw-Icon-1.webp", rarity: "epic" },
];

export const heroIdByCommanderId: Record<string, number | null> = Object.fromEntries(
  GATHERING_COMMANDERS.map((c) => [c.id, c.heroId])
);

export const commanderByHeroId: Record<number, GatheringCommander> = Object.fromEntries(
  GATHERING_COMMANDERS.filter((c) => c.heroId !== null).map((c) => [c.heroId as number, c])
);

export type MarchPair = { primary: number | null; secondary: number | null };

export type CommanderPairs = {
  food: MarchPair[];
  wood: MarchPair[];
  stone: MarchPair[];
  gold: MarchPair[];
};

export const emptyPairs = (): CommanderPairs => ({ food: [], wood: [], stone: [], gold: [] });

/** Resize each resource list to its march count, preserving picks. */
export function syncPairsWithCounts(
  pairs: CommanderPairs | undefined,
  counts: Record<string, number>
): CommanderPairs {
  const out = emptyPairs();
  (["food", "wood", "stone", "gold"] as const).forEach((res) => {
    const n = Math.max(0, Math.min(5, Number(counts[res]) || 0));
    const cur = (pairs && Array.isArray((pairs as any)[res]) ? (pairs as any)[res] : []) as any[];
    for (let i = 0; i < n; i++) {
      const e = cur[i];
      out[res][i] =
        e && typeof e === "object"
          ? { primary: typeof e.primary === "number" ? e.primary : null, secondary: typeof e.secondary === "number" ? e.secondary : null }
          : { primary: null, secondary: null };
    }
  });
  return out;
}
