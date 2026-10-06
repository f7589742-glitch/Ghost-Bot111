"""
app/services/commander_manager.py
Smart Tiered Commander Allocation Engine for 4-March Gathering.

Enforces two-phase commander allocation:
- Phase 1: Assign Primary commanders across all 4 marches FIRST (prioritizing gatherers,
           falling back to highest-level combat/support commanders when gatherers < 4).
- Phase 2: Assign Secondary commanders SECOND for marches whose Primary is level >= 20
           (using remaining gatherers when 5-11 gatherers are owned, or remaining
           non-gatherers when only 1-4 gatherers are owned).
"""

import logging
from typing import List, Dict, Any, Optional, Tuple, Set

logger = logging.getLogger("commander_manager")

# Canonical gathering commander string tokens (case-insensitive match)
GATHER_COMMANDERS: Set[str] = {
    "constance", "sarka", "gaius", "gaius marius", "matilda", "matilda of flanders",
    "seondeok", "queen seondeok", "cleopatra", "cleopatra vii", "ishida", "ishida mitsunari",
    "joan", "joan of arc", "centurion", "tamar", "tamar of georgia", "shajar", "shajar al-durr"
}

# Canonical RoK integer hero IDs for gathering commanders
GATHER_HERO_IDS: Set[int] = {
    38,  # Sarka
    33,  # Constance
    24,  # Centurion
    34,  # Gaius Marius
    15,  # Joan of Arc
    29,  # Cleopatra VII
    25,  # Seondeok
    26,  # Ishida Mitsunari
    59,  # Matilda of Flanders
    60,  # Tamar of Georgia
    121, # Shajar al-Durr
}

HERO_ID_TO_NAME: Dict[int, str] = {
    38: "Sarka",
    33: "Constance",
    24: "Centurion",
    34: "Gaius Marius",
    15: "Joan of Arc",
    29: "Cleopatra VII",
    25: "Seondeok",
    26: "Ishida Mitsunari",
    59: "Matilda of Flanders",
    60: "Tamar of Georgia",
    121: "Shajar al-Durr",
    6: "Lohar",
    14: "Boudica",
    22: "Aethelflaed",
    3: "Sun Tzu",
    8: "Scipio Africanus",
    10: "Belisarius",
    11: "Baibars",
    5: "Pelagius",
    12: "Osman I",
    9: "Hermann",
    7: "Eulji Mundeok",
    13: "Kusunoki Masashige",
    36: "Lancelot",
    35: "Tomoe Gozen",
    1: "City Keeper",
    2: "Cao Cao",
    4: "Minamoto no Yoshitsune",
    20: "Richard I",
    21: "Charles Martel",
}


def is_gatherer(cmd_data: Dict[str, Any]) -> bool:
    """
    Returns True if the commander dictionary represents a gathering commander
    by hero_id, id, name, role, or tags.
    """
    if not isinstance(cmd_data, dict):
        return False

    # Check integer hero_id / id
    raw_id = cmd_data.get("hero_id") or cmd_data.get("id")
    if isinstance(raw_id, int) and raw_id in GATHER_HERO_IDS:
        return True
    if isinstance(raw_id, str) and raw_id.isdigit() and int(raw_id) in GATHER_HERO_IDS:
        return True

    # Check string name / id / role / tags
    name_str = str(cmd_data.get("name") or HERO_ID_TO_NAME.get(raw_id if isinstance(raw_id, int) else -1, "")).lower()
    id_str = str(cmd_data.get("id") or "").lower()
    role_str = str(cmd_data.get("role") or "").lower()
    tags_list = [str(t).lower() for t in (cmd_data.get("tags") or [])]

    if role_str in ("gather", "gatherer", "gathering") or "gather" in tags_list or "gathering" in tags_list:
        return True

    for g_key in GATHER_COMMANDERS:
        if g_key in name_str or g_key in id_str:
            return True

    return False


def _normalize_commander(cmd: Dict[str, Any]) -> Dict[str, Any]:
    """Normalizes commander fields so both unit tests and live socket rosters have consistent keys."""
    out = dict(cmd)
    hid = out.get("hero_id") or out.get("id")
    if isinstance(hid, int):
        out["hero_id"] = hid
        out.setdefault("id", hid)
        out.setdefault("name", HERO_ID_TO_NAME.get(hid, f"Commander #{hid}"))
    else:
        out.setdefault("id", str(hid or out.get("name") or "unknown"))
        out.setdefault("hero_id", out["id"])
        out.setdefault("name", str(out.get("name") or out["id"]))
    out["level"] = int(out.get("level") or 1)
    out["star"] = int(out.get("star") or (3 if out["level"] >= 20 else 1))
    return out


def allocate_gathering_commanders(
    unlocked_commanders: Optional[List[Dict[str, Any]]] = None,
    target_marches: int = 4,
    **kwargs
) -> List[Dict[str, Any]]:
    """
    Distributes unlocked commanders across `target_marches` (default 4) using a strict
    two-phase algorithm:
      Phase 1: Fill PRIMARY slots for all 4 marches first (prioritizing Gatherers, then Others).
      Phase 2: Fill SECONDARY slots for marches whose Primary is Level >= 20
               (prioritizing remaining Gatherers, then remaining Others).

    Scenarios handled automatically:
      - Scenario A (8-11 gatherers): All 4 marches get Gatherer Primary + Gatherer Secondary.
      - Scenario B (4 gatherers): All 4 marches get Gatherer Primary + Non-Gatherer Secondary.
      - Scenario C (1-2 gatherers): Marches 1-2 get Gatherer Primary, Marches 3-4 get Non-Gatherer
        Primary, and remaining Non-Gatherers fill the Secondary slots across all 4 marches.
    """
    roster_input = unlocked_commanders if unlocked_commanders is not None else (kwargs.get("roster") or [])
    busy_set = set(kwargs.get("busy_commanders") or set())
    garrison_set = set(kwargs.get("wall_garrison") or set())
    failed_set = set(kwargs.get("failed_heroes") or set())

    # In RoK, wall garrison heroes defend the city but are 100% free to march and gather
    excluded_ids = busy_set | failed_set

    normalized_pool: List[Dict[str, Any]] = []
    seen_keys = set()
    for raw_c in roster_input:
        if not isinstance(raw_c, dict):
            continue
        if raw_c.get("in_use", False) or raw_c.get("busy", False):
            continue
        c = _normalize_commander(raw_c)
        cid = c.get("hero_id") if c.get("hero_id") is not None else c.get("id")
        if cid in excluded_ids or cid in seen_keys:
            continue
        seen_keys.add(cid)
        normalized_pool.append(c)

    # Sort descending by level (and power/star if present)
    def _sort_key(c: Dict[str, Any]):
        return (int(c.get("level", 1)), int(c.get("power", 0)), int(c.get("star", 1)))

    gatherers = sorted([c for c in normalized_pool if is_gatherer(c)], key=_sort_key, reverse=True)
    others = sorted([c for c in normalized_pool if not is_gatherer(c)], key=_sort_key, reverse=True)

    marches: List[Dict[str, Any]] = []

    # =========================================================================
    # PHASE 1: Secure PRIMARY commander for ALL target_marches (4 marches) first
    # =========================================================================
    for i in range(int(target_marches)):
        primary = None
        if gatherers:
            primary = gatherers.pop(0)
        elif others:
            primary = others.pop(0)

        if primary is not None:
            marches.append({
                "march_index": i + 1,
                "primary": primary,
                "secondary": None
            })

    # =========================================================================
    # PHASE 2: Assign SECONDARY commander ONLY after all 4 primaries are locked
    # =========================================================================
    for m in marches:
        prim = m["primary"]
        can_take_secondary = int(prim.get("level", 1)) >= 20 or int(prim.get("star", 1)) >= 3
        if can_take_secondary:
            if gatherers:
                # 8-11 Gatherers case: remaining gatherers become secondary
                m["secondary"] = gatherers.pop(0)
            elif others:
                # Prefer level <= 10 non-gatherers (combat heroes) for secondary
                low_lvl_idx = next((idx for idx, c in enumerate(others) if int(c.get("level", 1) or 1) <= 10), None)
                if low_lvl_idx is not None:
                    m["secondary"] = others.pop(low_lvl_idx)
                else:
                    m["secondary"] = others.pop(0)

    logger.info(
        f"[COMMANDER_MANAGER] Allocated {len(marches)}/{target_marches} gathering marches: "
        + ", ".join(
            f"M{m['march_index']}=[{m['primary']['name']} (L{m['primary']['level']}) + "
            f"{m['secondary']['name'] + ' (L' + str(m['secondary']['level']) + ')' if m['secondary'] else 'SOLO'}]"
            for m in marches
        )
    )
    return marches


def allocate_gathering_commanders_tuples(
    roster: List[Dict[str, Any]],
    target_queues: int = 4,
    busy_commanders: Optional[Set[int]] = None,
    wall_garrison: Optional[Set[int]] = None,
    failed_heroes: Optional[Set[int]] = None,
    fallback_hero_ids: Optional[List[int]] = None,
) -> List[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]]:
    """
    Adapter used by `smart_gather_search.py` returning `(primary_dict, secondary_dict)` pairs
    while strictly preserving the 4-march two-phase allocation order.
    """
    busy_commanders = busy_commanders or set()
    wall_garrison = wall_garrison or set()
    failed_heroes = failed_heroes or set()

    effective_roster = list(roster or [])
    existing_ids = {int(r.get("hero_id") or r.get("id") or 0) for r in effective_roster if isinstance(r, dict)}

    # Supplement with fallback_hero_ids if roster has fewer than target_queues * 2 heroes
    if len(effective_roster) < max(4, target_queues):
        for fid in (fallback_hero_ids or [38, 33, 24, 34, 15, 6, 14, 3, 8]):
            if fid not in existing_ids and fid not in busy_commanders and fid not in wall_garrison and fid not in failed_heroes:
                effective_roster.append({
                    "hero_id": int(fid),
                    "id": int(fid),
                    "name": HERO_ID_TO_NAME.get(int(fid), f"Commander #{fid}"),
                    "level": 30,
                    "star": 3,
                })
                existing_ids.add(int(fid))

    marches = allocate_gathering_commanders(
        unlocked_commanders=effective_roster,
        target_marches=max(4, int(target_queues)),
        busy_commanders=busy_commanders,
        wall_garrison=wall_garrison,
        failed_heroes=failed_heroes,
    )

    pairs: List[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]] = []
    for m in marches:
        pairs.append((m["primary"], m["secondary"]))
    return pairs
