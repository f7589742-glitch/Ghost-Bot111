"""
gathering_calculator.py - Dynamic Troop Load Calculation & Greedy March Allocation Engine
Implements mathematically optimal troop distribution for Rise of Kingdoms gathering marches.
Prevents march starvation across multi-queue accounts and guarantees node depletion with a +1% safety margin.
"""

import math
from typing import Dict, List, Tuple, Union

# Base load table per unit category and tier (T1 to T5)
BASE_LOAD_TABLE = {
    "siege": {1: 20, 2: 22, 3: 24, 4: 26, 5: 30},
    "infantry":{1: 7, 2: 11, 3: 12, 4: 13, 5: 15},
    "archery": {1: 6, 2: 8, 3: 9, 4: 11, 5: 13},
    "cavalry": {1: 5, 2: 7, 3: 8, 4: 10, 5: 12},
}

# Unit ID to Category & Tier mapping for wire protocol
UNIT_ID_TO_CAT_TIER = {
    # Siege (Category 4)
    4: ("siege", 1),
    8: ("siege", 2),
    12: ("siege", 3),
    16: ("siege", 4),
    20: ("siege", 5),

    # Infantry (Category 1)
    1: ("infantry", 1),
    5: ("infantry", 2),
    9: ("infantry", 3),
    13: ("infantry", 4),
    17: ("infantry", 5),
    # Special Civilization Infantry T4
    101: ("infantry", 4), # Samurai (Japan)
    102: ("infantry", 4), # Legionary (Rome)
    103: ("infantry", 4), # Throwing Axeman (France)
    104: ("infantry", 4), # Halberdier
    105: ("infantry", 4), # Highlander
    107: ("infantry", 4), # Eagle Knight
    113: ("infantry", 4), # Berserker (Viking)
    114: ("infantry", 4), # Landsknecht (Germany)
    116: ("infantry", 4), # Janissary (Ottoman)
    117: ("infantry", 4), # Iron Prow

    # Archery (Category 3)
    3: ("archery", 1),
    7: ("archery", 2),
    11: ("archery", 3),
    15: ("archery", 4),
    19: ("archery", 5),
    # Special Civilization Archery T4
    111: ("archery", 4), # Chu-Ko-Nu (China)
    115: ("archery", 4), # Longbowman (Britain)
    119: ("archery", 4), # Slinger

    # Cavalry (Category 2)
    2: ("cavalry", 1),
    6: ("cavalry", 2),
    10: ("cavalry", 3),
    14: ("cavalry", 4),
    18: ("cavalry", 5),
    22: ("cavalry", 5),
    # Special Civilization Cavalry T4
    106: ("cavalry", 4), # Teutonic Knight (Germany)
    108: ("cavalry", 4), # Knight (Spain)
    109: ("cavalry", 4), # Mamluk (Arabia)
    110: ("cavalry", 4), # Cataphract (Byzantium)
    112: ("cavalry", 4), # Winged Hussar
    118: ("cavalry", 4), # Huszar
}

CAT_TIER_TO_UNIT_ID = {
    ("siege", 1): 4,
    ("siege", 2): 8,
    ("siege", 3): 12,
    ("siege", 4): 16,
    ("siege", 5): 20,

    ("infantry", 1): 1,
    ("infantry", 2): 5,
    ("infantry", 3): 9,
    ("infantry", 4): 13,
    ("infantry", 5): 17,

    ("archery", 1): 3,
    ("archery", 2): 7,
    ("archery", 3): 11,
    ("archery", 4): 15,
    ("archery", 5): 19,

    ("cavalry", 1): 2,
    ("cavalry", 2): 6,
    ("cavalry", 3): 10,
    ("cavalry", 4): 14,
    ("cavalry", 5): 18,
}

COMMANDER_LOAD_BONUS = {
    105: 25.0, # Joan of Arc
    4: 30.0,   # Šárka
    38: 30.0,  # Gaius Marius
    34: 20.0,  # Constance
    33: 20.0,  # Constance (alt)
    15: 25.0,  # Centurion
    24: 10.0,  # Cleopatra VII
    463: 30.0, # Queen Tamar
    32: 50.0, 
    46: 30.0, 
    43: 30.0,  # Seondeok
    57: 30.0,  # Ishida
    44: 30.0,  # Matilda
}

class GatheringLoadEngine:

    @classmethod
    def get_unit_load(
        cls,
        category: str,
        tier: int,
        account_bonuses: dict,
        commander_bonus_pct: float = 0.0,
    ) -> float:
        """Calculates effective load per single unit including account tech and commander bonuses."""
        base = BASE_LOAD_TABLE.get(category, {}).get(tier, 5)
        flat_bonus = (account_bonuses or {}).get(f"{category}_load_bonus", 0)
        # Conservative caps to prevent under-allocating troops
        raw_tech = (account_bonuses or {}).get("global_load_pct", 0.0)
        tech_pct = min(raw_tech, 10.0)
        eff_cmd_bonus = min(commander_bonus_pct, 10.0)

        effective_load = (base + flat_bonus) * (
            1.0 + (tech_pct + eff_cmd_bonus) / 100.0
        )
        return max(effective_load, 1.0)

    @classmethod
    def calculate_required_march_composition(
        cls,
        target_resource_amount: int,
        available_troops: dict,
        account_bonuses: dict,
        commander_bonus_pct: float = 0.0,
        march_cap: int = 64000,
        remaining_queues: int = 1,
        safety_margin_pct: float = 1.0,
        flat_cushion: int = 0,
        node_level: int = 0,
    ) -> dict:
        """
        Greedily selects optimal troop distribution to cover node capacity with exact +1% safety buffer
        (Target Load = Remaining Node Resources * 1.01) so the node is 100% depleted with 0 crumbs left.
        Multi-class priority order: Siege -> Infantry -> Archery -> Cavalry.
        BACKUP MODE: If siege is depleted or 0, seamlessly falls back to Infantry, Archery, and Cavalry.
        MULTI-QUEUE FAIR BUDGETING: If remaining_queues > 1, budgets available troops to prevent Queue 1
        from monopolizing the army and starving subsequent march queues.
        """
        target_load = int(math.ceil(target_resource_amount * (1.0 + safety_margin_pct / 100.0))) + flat_cushion
        priority_order = ["siege", "infantry", "archery", "cavalry"]
        cat_rank = {"siege": 0, "infantry": 1, "archery": 2, "cavalry": 3}

        # Check if available_troops is flat {uid: count}
        is_flat = any(isinstance(k, int) for k in (available_troops or {}).keys())

        if is_flat:
            # Build list of available units: (unit_id, category, tier, count, unit_load)
            flat_unit_items = []
            total_avail_soldiers = 0
            siege_avail_soldiers = 0
            for uid, cnt in (available_troops or {}).items():
                if not isinstance(uid, int) or cnt <= 0:
                    continue
                total_avail_soldiers += cnt
                cat_tier = UNIT_ID_TO_CAT_TIER.get(uid)
                if cat_tier:
                    cat, tier = cat_tier
                else:
                    u = int(uid)
                    rem = u % 4
                    cat = "infantry" if rem == 1 else ("cavalry" if rem == 2 else ("archery" if rem == 3 else "siege"))
                    tier = min(5, max(1, (u // 4) + (1 if rem != 0 else 0)))
                if cat == "siege":
                    siege_avail_soldiers += cnt
                u_load = cls.get_unit_load(cat, tier, account_bonuses, commander_bonus_pct)
                flat_unit_items.append((uid, cat, tier, cnt, u_load))

            is_backup_mode = (siege_avail_soldiers <= 0)

            # Multi-Queue Fair Troop Budgeting:
            effective_march_cap = march_cap
            if remaining_queues > 1 and total_avail_soldiers > 0:
                if total_avail_soldiers < (remaining_queues * march_cap):
                    fair_budget = max(50, total_avail_soldiers // remaining_queues)
                    if is_backup_mode or (siege_avail_soldiers < remaining_queues * 1000):
                        effective_march_cap = min(march_cap, fair_budget)

            # Sort units: Siege first, then Infantry -> Archery -> Cavalry, lowest tier first
            flat_unit_items.sort(key=lambda x: (cat_rank.get(x[1], 9), x[2], x[0]))

            selected_troops = {}
            current_load = 0.0
            total_units_selected = 0
            siege_units_selected = 0

            for uid, cat, tier, avail, u_load in flat_unit_items:
                remaining_load = target_load - current_load
                if remaining_load <= 0 and total_units_selected > 0:
                    break

                units_needed = int(math.ceil(remaining_load / u_load))
                units_to_take = min(avail, units_needed)

                if total_units_selected + units_to_take > effective_march_cap:
                    units_to_take = max(0, effective_march_cap - total_units_selected)

                if units_to_take > 0:
                    selected_troops[uid] = units_to_take
                    current_load += units_to_take * u_load
                    total_units_selected += units_to_take
                    if cat == "siege":
                        siege_units_selected += units_to_take

                if current_load >= target_load or total_units_selected >= effective_march_cap:
                    break

            # Emergency sweep if target not reached or 0 selected but soldiers exist
            if total_units_selected <= 0 and total_avail_soldiers > 0:
                for uid, cat, tier, avail, u_load in flat_unit_items:
                    take = min(avail, effective_march_cap - total_units_selected)
                    if take > 0:
                        selected_troops[uid] = take
                        current_load += take * u_load
                        total_units_selected += take
                        if cat == "siege":
                            siege_units_selected += take
                    if total_units_selected >= effective_march_cap:
                        break

            sanity_passed = (total_units_selected > 0)
            sanity_reason = "" if sanity_passed else "No troops available in city to allocate."

            wire_army = [(uid, cnt) for uid, cnt in selected_troops.items() if cnt > 0]

            return {
                "troops": selected_troops,
                "wire_army": wire_army,
                "total_load": int(current_load),
                "total_units": total_units_selected,
                "target_covered": current_load >= target_load,
                "sanity_passed": sanity_passed,
                "sanity_reason": sanity_reason,
                "is_backup": (siege_units_selected <= 0),
            }

        # Fallback for nested troops dictionary:
        nested_troops = cls.ensure_nested_troops(available_troops)
        total_avail_soldiers = sum(sum(tier_dict.values()) for tier_dict in nested_troops.values())
        siege_avail_soldiers = sum(nested_troops.get("siege", {}).values())
        is_backup_mode = (siege_avail_soldiers <= 0)

        effective_march_cap = march_cap
        if remaining_queues > 1 and total_avail_soldiers > 0:
            if total_avail_soldiers < (remaining_queues * march_cap):
                fair_budget = max(50, total_avail_soldiers // remaining_queues)
                if is_backup_mode or (siege_avail_soldiers < remaining_queues * 1000):
                    effective_march_cap = min(march_cap, fair_budget)

        selected_troops = {}
        current_load = 0.0
        total_units_selected = 0
        siege_units_selected = 0

        for category in priority_order:
            for tier in range(1, 6):
                avail = nested_troops.get(category, {}).get(tier, 0)
                if avail <= 0:
                    continue

                unit_load = cls.get_unit_load(
                    category, tier, account_bonuses, commander_bonus_pct
                )
                remaining_load = target_load - current_load
                if remaining_load <= 0 and total_units_selected > 0:
                    break

                units_needed = int(math.ceil(remaining_load / unit_load))
                units_to_take = min(avail, units_needed)

                if total_units_selected + units_to_take > effective_march_cap:
                    units_to_take = max(0, effective_march_cap - total_units_selected)

                if units_to_take > 0:
                    selected_troops[(category, tier)] = units_to_take
                    current_load += units_to_take * unit_load
                    total_units_selected += units_to_take
                    if category == "siege":
                        siege_units_selected += units_to_take

                if current_load >= target_load or total_units_selected >= effective_march_cap:
                    break
            if current_load >= target_load or total_units_selected >= effective_march_cap:
                break

        if total_units_selected <= 0 and total_avail_soldiers > 0:
            for category in priority_order:
                for tier in range(1, 6):
                    avail = nested_troops.get(category, {}).get(tier, 0)
                    if avail > 0:
                        take = min(avail, effective_march_cap - total_units_selected)
                        if take > 0:
                            selected_troops[(category, tier)] = take
                            eff_load = cls.get_unit_load(category, tier, account_bonuses, commander_bonus_pct)
                            current_load += take * eff_load
                            total_units_selected += take
                            if category == "siege":
                                siege_units_selected += take
                    if total_units_selected >= effective_march_cap:
                        break
                if total_units_selected >= effective_march_cap:
                    break

        sanity_passed = (total_units_selected > 0)
        sanity_reason = "" if sanity_passed else "No troops available in city to allocate."

        return {
            "troops": selected_troops,
            "wire_army": cls.to_wire_army_list(selected_troops),
            "total_load": int(current_load),
            "total_units": total_units_selected,
            "target_covered": current_load >= target_load,
            "sanity_passed": sanity_passed,
            "sanity_reason": sanity_reason,
            "is_backup": (siege_units_selected <= 0),
        }

    @classmethod
    def ensure_nested_troops(cls, troops: dict) -> Dict[str, Dict[int, int]]:
        if not troops:
            return {"siege": {}, "infantry": {}, "archery": {}, "cavalry": {}}
        if any(cat in troops for cat in ("siege", "infantry", "archery", "cavalry")):
            return troops
        nested = {"siege": {}, "infantry": {}, "archery": {}, "cavalry": {}}
        for uid, count in troops.items():
            if count <= 0:
                continue
            cat_tier = UNIT_ID_TO_CAT_TIER.get(int(uid))
            if cat_tier:
                cat, tier = cat_tier
                nested[cat][tier] = nested[cat].get(tier, 0) + count
            else:
                # Robust fallback for unmapped unit IDs: deduce category and tier via modulo 4
                u = int(uid)
                rem = u % 4
                cat = "infantry" if rem == 1 else ("cavalry" if rem == 2 else ("archery" if rem == 3 else "siege"))
                tier = min(5, max(1, (u // 4) + (1 if rem != 0 else 0)))
                nested[cat][tier] = nested[cat].get(tier, 0) + count
        return nested

    @classmethod
    def to_wire_army_list(cls, selected_troops: dict) -> List[Tuple[int, int]]:
        wire_list = []
        for key, count in selected_troops.items():
            if count <= 0:
                continue
            if isinstance(key, tuple):
                cat, tier = key
                unit_id = CAT_TIER_TO_UNIT_ID.get((cat, tier))
                if unit_id:
                    wire_list.append((unit_id, count))
            elif isinstance(key, int):
                wire_list.append((key, count))
        return wire_list

    @classmethod
    def deduct_troops(cls, available_troops: dict, used_troops: dict) -> None:
        """In-place deducts allocated troops from available_troops (supports both flat and nested)."""
        is_flat = any(isinstance(k, int) for k in available_troops.keys())
        for key, count in used_troops.items():
            if isinstance(key, tuple):
                cat, tier = key
                uid = CAT_TIER_TO_UNIT_ID.get((cat, tier))
                if is_flat and uid in available_troops:
                    available_troops[uid] = max(0, available_troops[uid] - count)
                elif not is_flat and cat in available_troops:
                    available_troops[cat][tier] = max(0, available_troops[cat].get(tier, 0) - count)
            elif isinstance(key, int):
                if is_flat and key in available_troops:
                    available_troops[key] = max(0, available_troops[key] - count)
                elif not is_flat:
                    cat_tier = UNIT_ID_TO_CAT_TIER.get(key)
                    if cat_tier:
                        c, t = cat_tier
                        available_troops[c][t] = max(0, available_troops[c].get(t, 0) - count)

    @classmethod
    def get_max_marches_for_city_hall(cls, city_hall_level: int) -> int:
        """Official Rise of Kingdoms Town Hall March Queues."""
        lvl = int(city_hall_level or 17)
        if lvl >= 22:
            return 5
        elif lvl >= 17:
            return 4
        elif lvl >= 11:
            return 3
        elif lvl >= 5:
            return 2
        return 1

    @classmethod
    def get_base_capacity_for_city_hall(cls, city_hall_level: int) -> int:
        """Town Hall 17 base capacity = 64,000."""
        ch_caps = {
            11: 28000, 12: 33000, 13: 38000, 14: 44000,
            15: 50000, 16: 57000, 17: 64000, 18: 71000,
            19: 78000, 20: 85000, 21: 95000, 22: 110000,
            23: 130000, 24: 160000, 25: 200000
        }
        return ch_caps.get(int(city_hall_level or 17), 64000 if int(city_hall_level or 17) >= 17 else 30000)


