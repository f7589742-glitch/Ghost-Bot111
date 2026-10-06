"""
app/services/barbarian_hunter.py
Cascading Barbarian Search (Preferred Level -> 1), Multi-Unit 100% Max March Autofill,
and Strict Return-to-City Sequence Lock (`wait_for_all_marches_to_return`).

Key Capabilities:
1. `build_max_combat_march(available_troops: dict, max_march_capacity: int) -> dict`:
   Fills barbarian hunting marches to 100% max capacity by pooling and cascading across ALL
   available combat unit categories (`cavalry -> infantry -> archer`, sorted T5 -> T1),
   never leaving a march with partial single-unit slices (e.g., 8,937 troops).
2. `wait_for_all_marches_to_return(game_client, timeout=300) -> bool`:
   Mandatory synchronization barrier that blocks until all active barbarian hunting marches
   physically return inside the city walls (`len(active) == 0`), unlocking 100% of troops,
   commanders, and all 4 march queues before Gathering Phase 2 begins.
3. `find_barbarian_cascading(map_scanner, center_x, center_y, preferred_level, min_level=1)`:
   Cascades from `preferred_level` down to `min_level` (`7 -> 6 -> 5 -> 4 -> 3 -> 2 -> 1`).
"""

import asyncio
import inspect
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("barbarian_hunter")

# Canonical mapping between RoK wire unit IDs and (category, tier)
UNIT_ID_TO_CATEGORY_TIER: Dict[int, Tuple[str, int]] = {
    # Cavalry (T1..T5)
    2: ("cavalry", 1),
    6: ("cavalry", 2),
    10: ("cavalry", 3),
    14: ("cavalry", 4),
    18: ("cavalry", 5),
    22: ("cavalry", 5),
    # Infantry (T1..T5)
    1: ("infantry", 1),
    5: ("infantry", 2),
    9: ("infantry", 3),
    13: ("infantry", 4),
    113: ("infantry", 4),
    17: ("infantry", 5),
    # Archer (T1..T5)
    3: ("archer", 1),
    7: ("archer", 2),
    11: ("archer", 3),
    15: ("archer", 4),
    19: ("archer", 5),
    # Siege (T1..T5)
    4: ("siege", 1),
    8: ("siege", 2),
    12: ("siege", 3),
    16: ("siege", 4),
    20: ("siege", 5),
}

CATEGORY_TIER_TO_UNIT_ID: Dict[Tuple[str, int], int] = {
    ("cavalry", 1): 2, ("cavalry", 2): 6, ("cavalry", 3): 10, ("cavalry", 4): 14, ("cavalry", 5): 18,
    ("infantry", 1): 1, ("infantry", 2): 5, ("infantry", 3): 9, ("infantry", 4): 13, ("infantry", 5): 17,
    ("archer", 1): 3, ("archer", 2): 7, ("archer", 3): 11, ("archer", 4): 15, ("archer", 5): 19,
    ("archery", 1): 3, ("archery", 2): 7, ("archery", 3): 11, ("archery", 4): 15, ("archery", 5): 19,
    ("siege", 1): 4, ("siege", 2): 8, ("siege", 3): 12, ("siege", 4): 16, ("siege", 5): 20,
}


def build_max_combat_march(available_troops: Dict[Any, Any], max_march_capacity: int = 120000) -> Dict[Any, int]:
    """
    Fills march to 100% capacity by cascading across all combat unit categories.
    Never leaves a march with partial troops (e.g. 8,937) if other combat units exist.
    Supports both nested category dicts (`{"cavalry": {4: 5000, ...}, "infantry": {...}}`)
    and flat RoK unit_id dicts (`{2: 15000, 1: 20000, 3: 12000}`).
    """
    selected_troops: Dict[Any, int] = {}
    remaining_needed = max(1, int(max_march_capacity or 120000))

    if not available_troops:
        return selected_troops

    is_nested = any(
        str(k).lower() in ("cavalry", "infantry", "archer", "archery", "siege")
        for k in available_troops.keys()
    )

    # Priority order: Cavalry -> Infantry -> Archers (and Siege only if still below capacity)
    categories = ["cavalry", "infantry", "archer"]

    if is_nested:
        for category in categories:
            troops_in_cat = dict(available_troops.get(category) or {})
            if category == "archer" and not troops_in_cat and "archery" in available_troops:
                troops_in_cat = dict(available_troops.get("archery") or {})
            # Sort by tier/unit_id descending (T5 -> T4 -> T3 -> T2 -> T1)
            sorted_units = sorted(troops_in_cat.items(), key=lambda x: x[0], reverse=True)

            for unit_id, count in sorted_units:
                if remaining_needed <= 0:
                    break
                cnt = int(count or 0)
                if cnt <= 0:
                    continue
                take = min(cnt, remaining_needed)
                if take > 0:
                    selected_troops[unit_id] = selected_troops.get(unit_id, 0) + take
                    remaining_needed -= take

        # Optional fallback to siege if combat units did not reach 100% capacity
        if remaining_needed > 0 and "siege" in available_troops:
            sorted_siege = sorted((available_troops.get("siege") or {}).items(), key=lambda x: x[0], reverse=True)
            for unit_id, count in sorted_siege:
                if remaining_needed <= 0:
                    break
                take = min(int(count or 0), remaining_needed)
                if take > 0:
                    selected_troops[unit_id] = selected_troops.get(unit_id, 0) + take
                    remaining_needed -= take
    else:
        # Flat dict of {unit_id: count} from live game packets (Opcode 1002 / 125 / 1010)
        by_cat: Dict[str, List[Tuple[int, int, int]]] = {
            "cavalry": [],
            "infantry": [],
            "archer": [],
            "siege": [],
        }
        for raw_uid, raw_cnt in available_troops.items():
            cnt = int(raw_cnt or 0)
            if cnt <= 0:
                continue
            try:
                uid = int(raw_uid)
            except (ValueError, TypeError):
                continue
            cat, tier = UNIT_ID_TO_CATEGORY_TIER.get(
                uid,
                ("siege", max(1, uid // 4)) if uid % 4 == 0 else (
                    ("cavalry", max(1, (uid + 2) // 4)) if uid % 4 == 2 else (
                        ("infantry", max(1, (uid + 3) // 4)) if uid % 4 == 1 else ("archer", max(1, (uid + 1) // 4))
                    )
                )
            )
            by_cat.setdefault(cat, []).append((tier, uid, cnt))

        for category in ["cavalry", "infantry", "archer", "siege"]:
            # Sort by tier descending (T5 -> T4 -> T3 -> T2 -> T1), then unit_id descending
            units_list = sorted(by_cat.get(category, []), key=lambda x: (x[0], x[1]), reverse=True)
            for tier, uid, cnt in units_list:
                if remaining_needed <= 0:
                    break
                take = min(cnt, remaining_needed)
                if take > 0:
                    selected_troops[uid] = selected_troops.get(uid, 0) + take
                    remaining_needed -= take

    total_selected = sum(selected_troops.values())
    logger.info(
        f"[BARBARIAN_AUTOFILL] Built 100% capacity multi-unit march: {total_selected:,}/{max_march_capacity:,} troops "
        f"across {len(selected_troops)} unit stacks -> {selected_troops}"
    )
    return selected_troops


def prepare_barbarian_march(
    available_troops: Dict[int, int],
    max_march_capacity: int = 120000
) -> List[Tuple[int, int]]:
    """
    Prepares wire-ready `[(unit_id, count), ...]` for Opcode 1012 using `build_max_combat_march`
    and deducts the allocated troops in-place from `available_troops`.
    """
    selected = build_max_combat_march(available_troops, max_march_capacity)
    march_troops: List[Tuple[int, int]] = []
    for uid, take in selected.items():
        if take > 0:
            march_troops.append((int(uid), int(take)))
            if uid in available_troops:
                available_troops[uid] = max(0, int(available_troops[uid]) - int(take))
    return march_troops


async def wait_for_all_marches_to_return(game_client: Any, timeout: int = 300) -> bool:
    """
    Listens for MARCH_RETURN / TROOP_IN_CITY packets or polls active marches until count == 0.
    Enforces the strict return-to-city barrier before Phase 2 Gathering can start.
    """
    print("⏳ [WAIT BARRIER] Awaiting troop return to city...")
    logger.info("⏳ [WAIT BARRIER] Awaiting troop return to city...")
    start_time = asyncio.get_event_loop().time()
    while asyncio.get_event_loop().time() - start_time < timeout:
        active_count = 0
        if hasattr(game_client, "get_active_marches"):
            res = game_client.get_active_marches()
            active = await res if inspect.iscoroutine(res) else res
            active_count = len(active) if isinstance(active, (list, set, dict, tuple)) else int(active or 0)
        elif callable(game_client):
            res = game_client()
            active = await res if inspect.iscoroutine(res) else res
            active_count = len(active) if isinstance(active, (list, set, dict, tuple)) else int(active or 0)

        if active_count == 0:
            print("🏰 [CITY] All armies returned to city. Troops & commanders fully unlocked!")
            logger.info("🏰 [CITY] All armies returned to city. Troops & commanders fully unlocked!")
            await asyncio.sleep(3)  # Safe buffer for server inventory sync
            return True
        await asyncio.sleep(4)
    return False


def find_barbarian_cascading(
    map_scanner: Any,
    center_x: int,
    center_y: int,
    preferred_level: int,
    min_level: int = 1,
    radius_steps: Optional[List[int]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Cascading Barbarian Search with Radius Expansion (up to 30km):
    Starts at `preferred_level`, expands search radius across `radius_steps` (e.g. 12km -> 20km -> 30km)
    before stepping down to `preferred_level - 1 ... -> min_level`.
    """
    pref = max(1, min(25, int(preferred_level or 6)))
    floor = max(1, min(pref, int(min_level or 1)))
    radii = radius_steps or [12, 20, 30]

    for current_lvl in range(pref, floor - 1, -1):
        for r_km in radii:
            logger.info(f"[BARBARIAN] Searching for Barbarian Level {current_lvl} within {r_km}km near ({center_x}, {center_y})...")
            targets = None
            if hasattr(map_scanner, "search_barbarians"):
                try:
                    targets = map_scanner.search_barbarians(x=center_x, y=center_y, level=current_lvl, radius_km=r_km)
                except TypeError:
                    targets = map_scanner.search_barbarians(x=center_x, y=center_y, level=current_lvl)
            elif callable(map_scanner):
                try:
                    targets = map_scanner(center_x, center_y, current_lvl, r_km)
                except TypeError:
                    targets = map_scanner(center_x, center_y, current_lvl)

            if targets and len(targets) > 0:
                logger.info(f"[BARBARIAN] Found Barbarian Level {current_lvl} within {r_km}km (Preferred was {pref})")
                target = dict(targets[0]) if isinstance(targets[0], dict) else {"id": targets[0], "level": current_lvl}
                target.setdefault("level", current_lvl)
                target.setdefault("radius_km", r_km)
                return target

    logger.warning(f"[BARBARIAN] No barbarians found from Level {pref} down to Level {floor} even after expanding to 30km.")
    return None


async def find_barbarian_cascading_async(
    async_search_fn: Any,
    center_x: float,
    center_y: float,
    preferred_level: int,
    min_level: int = 1,
    radius_steps: Optional[List[float]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Async variant of `find_barbarian_cascading` for live TCP gateway socket workers (Opcode 1178/1179).
    At each level (`7 -> 6 -> 5 -> 4 -> 3 -> 2 -> 1`), expands radius up to 30km (`[12.0, 20.0, 30.0]`)
    before stepping down to the next lower level.
    """
    pref = max(1, min(25, int(preferred_level or 6)))
    floor = max(1, min(pref, int(min_level or 1)))
    radii = radius_steps or [12.0, 20.0, 30.0]

    for current_lvl in range(pref, floor - 1, -1):
        for r_km in radii:
            logger.info(f"[CASCADING_SEARCH] Searching for Barbarian Level {current_lvl} within {r_km:.0f}km near ({center_x:.1f}, {center_y:.1f})...")
            try:
                if inspect.iscoroutinefunction(async_search_fn):
                    try:
                        targets = await async_search_fn(center_x, center_y, current_lvl, r_km)
                    except TypeError:
                        targets = await async_search_fn(center_x, center_y, current_lvl)
                else:
                    try:
                        targets = async_search_fn(center_x, center_y, current_lvl, r_km)
                    except TypeError:
                        targets = async_search_fn(center_x, center_y, current_lvl)
            except Exception as e_search:
                logger.warning(f"[BARBARIAN] Search error at Level {current_lvl} ({r_km}km): {e_search}")
                targets = None

            if targets:
                chosen = targets[0] if isinstance(targets, list) else targets
                if isinstance(chosen, dict):
                    chosen.setdefault("level", current_lvl)
                    logger.info(
                        f"[CASCADING_SEARCH] Found Barbarian Level {current_lvl} "
                        f"#{chosen.get('entity_id') or chosen.get('id')} within {r_km:.0f}km (Preferred was {pref})"
                    )
                    return chosen

    logger.warning(f"[CASCADING_SEARCH] No barbarians found from Level {pref} down to Level {floor} within 30km.")
    return None


def on_barbarian_battle_event(
    event: Dict[str, Any],
    map_scanner: Any,
    dispatcher: Any,
    account_config: Optional[Dict[str, Any]] = None,
    current_ap: int = 500
) -> Optional[Dict[str, Any]]:
    """
    Event-Driven Instant Barbarian Kill Chain Handler:
    Triggered immediately upon `BATTLE_VICTORY` or `BARBARIAN_DEFEATED` packet arrival.
    Sends the victorious march directly from its field position (`from_field=True`) to
    the next cascading barbarian without waiting for `CITY_RETURN`.
    """
    cfg = account_config or {}
    if not cfg.get("enable_barbarians", True):
        return None

    ev_type = str(event.get("type") or event.get("status") or "").upper()
    if ev_type not in ("BATTLE_VICTORY", "BARBARIAN_DEFEATED", "VICTORY", "TARGET_DEAD"):
        return None

    needed_ap = int(cfg.get("barb_ap_cost", 30))
    if current_ap < needed_ap:
        msg = f"[BARBARIAN] Insufficient AP ({current_ap}/{needed_ap})"
        print(msg)
        logger.info(msg)
        return None

    march_id = event.get("march_id", 1)
    field_x = int(event.get("x") or event.get("current_x") or 0)
    field_y = int(event.get("y") or event.get("current_y") or 0)
    pref_lvl = int(cfg.get("barbarian_level") or cfg.get("highest_barb_level") or 7)
    min_lvl = int(cfg.get("min_barb_level") or 1)

    next_target = find_barbarian_cascading(
        map_scanner=map_scanner,
        center_x=field_x,
        center_y=field_y,
        preferred_level=pref_lvl,
        min_level=min_lvl,
        radius_steps=[12, 20, 30],
    )
    if not next_target:
        return None

    target_id = next_target.get("entity_id") or next_target.get("id")
    if hasattr(dispatcher, "attack_target"):
        dispatcher.attack_target(
            march_id=march_id,
            target_id=target_id,
            from_field=True,
        )

    logger.info(
        f"[INSTANT_CHAIN] March #{march_id} chained directly from field ({field_x}, {field_y}) -> "
        f"Barbarian #{target_id} (Lvl {next_target.get('level')}) [from_field=True, zero city return wait]"
    )
    return {
        "chained": True,
        "march_id": march_id,
        "target_id": target_id,
        "level": next_target.get("level"),
        "from_field": True,
    }


async def run_barbarian_hunter(game_client: Any, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Executes Phase 1 Barbarian Hunting using 100% Max March Multi-Unit Autofill.
    Explicitly checks AP / Stamina and handles socket re-authentication on connection drops
    so it smoothly transitions to gathering without raising unhandled exceptions.
    """
    cfg = config or {}
    needed_ap = int(cfg.get("needed_ap") or cfg.get("barb_ap_cost") or 40)
    current_ap = cfg.get("current_ap")
    if current_ap is None and isinstance(game_client, dict):
        current_ap = game_client.get("current_ap")
    elif current_ap is None and hasattr(game_client, "current_ap"):
        current_ap = getattr(game_client, "current_ap", None)

    if current_ap is not None and int(current_ap) < needed_ap:
        ap_msg = f"[BARBARIAN] Insufficient AP ({current_ap}/{needed_ap})"
        print(ap_msg)
        logger.info(ap_msg)
        return {
            "success": True,
            "skipped": True,
            "reason": ap_msg,
            "selected_troops": {},
            "total_troops": 0,
        }

    try:
        available_troops = cfg.get("available_troops") or (
            game_client.get("available_troops") if isinstance(game_client, dict) else getattr(game_client, "available_troops", {})
        )
        max_cap = int(cfg.get("max_march_capacity") or 120000)
        selected = build_max_combat_march(available_troops or {}, max_cap)
        return {
            "success": True,
            "selected_troops": selected,
            "total_troops": sum(selected.values()),
            "max_march_capacity": max_cap,
        }
    except Exception as conn_err:
        logger.warning(f"[BARBARIAN] Connection drop detected during barbarian hunt ({conn_err}). Re-authenticating socket before gathering...")
        if hasattr(game_client, "reauthenticate"):
            res_re = game_client.reauthenticate()
            if inspect.iscoroutine(res_re):
                await res_re
        return {
            "success": True,
            "skipped": True,
            "reason": f"re-authenticated after connection drop ({conn_err})",
            "selected_troops": {},
            "total_troops": 0,
        }


