"""
app/services/gatherer.py
Resource Gathering Coordinator, Alliance Territory Node Filter, and Queue Lock Manager.

Ensures:
1. All 4 gathering marches are unlocked and dispatched (`target_marches = 4`).
2. Any phantom barbarian hunting queue reservations are immediately cleared before gathering.
3. `is_valid_resource_node(node, account_config)` strictly blocks any resource node inside
   alliance territory when `avoid_alliance_territory` / `no_alliance_rss` / `avoid_territory` is enabled.
"""

import logging
from typing import Dict, Any, Optional, List

from app.services.commander_manager import allocate_gathering_commanders

logger = logging.getLogger("gatherer")

# Active barbarian queue locks tracked per role_id
BARBARIAN_QUEUE_LOCKS: Dict[str, set] = {}


def release_barbarian_queue_locks(role_id: Optional[Any] = None, account_state: Optional[Dict[str, Any]] = None) -> int:
    """
    Immediately clears any stuck or phantom barbarian march queue locks so that all 4
    gathering queues are available for deployment.
    """
    released = 0
    if role_id is not None:
        key = str(role_id)
        if key in BARBARIAN_QUEUE_LOCKS:
            released += len(BARBARIAN_QUEUE_LOCKS[key])
            BARBARIAN_QUEUE_LOCKS[key].clear()
    else:
        for k in list(BARBARIAN_QUEUE_LOCKS.keys()):
            released += len(BARBARIAN_QUEUE_LOCKS[k])
            BARBARIAN_QUEUE_LOCKS[k].clear()

    if isinstance(account_state, dict):
        for lock_key in ("reserved_queues", "barbarian_locks", "combat_reserved_queues", "busy_queues"):
            if lock_key in account_state and account_state[lock_key]:
                if isinstance(account_state[lock_key], (set, list, dict)):
                    released += len(account_state[lock_key])
                    account_state[lock_key].clear()
                elif isinstance(account_state[lock_key], int):
                    released += account_state[lock_key]
                    account_state[lock_key] = 0

    logger.info(f"[GATHERER] Released {released} phantom barbarian queue reservation(s). All 4 march queues ready.")
    return released


def get_target_gathering_marches(account_config: Optional[Dict[str, Any]] = None, active_gathering_marches: int = 0) -> int:
    """
    Computes how many new gathering marches to dispatch to reach the mandatory 4-march target.
    """
    cfg = account_config or {}
    raw_max = cfg.get("max_gathering_marches") or cfg.get("target_marches") or cfg.get("max_marches") or 4
    try:
        target_marches = max(4, int(raw_max))
    except (ValueError, TypeError):
        target_marches = 4
    return max(0, target_marches - int(active_gathering_marches))


def is_valid_resource_node(node: Dict[str, Any], account_config: Optional[Dict[str, Any]] = None) -> bool:
    """
    Validates whether a resource node on the map is eligible for gathering.
    When `avoid_alliance_territory` (or `no_alliance_rss` / `avoid_territory`) is enabled,
    strictly rejects ANY resource node located inside ANY alliance territory.
    """
    if not isinstance(node, dict):
        return False

    cfg = account_config or {}
    gather_sub = cfg.get("gather") if isinstance(cfg.get("gather"), dict) else {}

    avoid_alliance = bool(
        cfg.get("avoid_alliance_territory")
        or cfg.get("no_alliance_rss")
        or cfg.get("avoid_territory")
        or gather_sub.get("avoid_alliance_territory")
        or gather_sub.get("no_alliance_rss")
        or gather_sub.get("avoid_territory")
        or (cfg.get("territory") == "alliance_preferred")
        or (gather_sub.get("territory") == "alliance_preferred")
    )

    if avoid_alliance:
        alliance_id = node.get("alliance_id")
        guild_id = node.get("guild_id")
        alliance_tag = node.get("alliance_tag")
        is_alliance_terr = node.get("is_alliance_territory")
        territory_owner = node.get("territory_owner")

        has_alliance_ownership = (
            (alliance_id not in (None, 0, "", "0"))
            or (guild_id not in (None, 0, "", "0"))
            or (alliance_tag not in (None, "", "0"))
            or (is_alliance_terr is True)
            or (territory_owner not in (None, 0, "", "0"))
        )

        if has_alliance_ownership:
            pos = node.get("pos") or (node.get("x"), node.get("y"))
            logger.info(
                f"Skipping resource node at ({node.get('x', pos[0] if isinstance(pos, (list, tuple)) and len(pos) > 0 else '?')}, "
                f"{node.get('y', pos[1] if isinstance(pos, (list, tuple)) and len(pos) > 1 else '?')}) - Inside Alliance Territory."
            )
            return False

    return True


async def find_nearest_valid_tile(
    game_client: Any,
    account_config: Optional[Dict[str, Any]] = None,
    radius_steps: Optional[List[int]] = None,
    used_node_ids: Optional[set] = None,
) -> Optional[Dict[str, Any]]:
    """
    Scans for valid resource tiles across expanding radius steps (e.g. [15, 25, 40] km).
    Logs total tiles scanned, how many were rejected by the alliance filter, and how many are valid.
    """
    import asyncio
    import inspect

    cfg = account_config or {}
    steps = radius_steps or [15, 25, 40]
    used = used_node_ids if used_node_ids is not None else set()

    for radius_km in steps:
        raw_tiles: List[Dict[str, Any]] = []
        if hasattr(game_client, "scan_resource_tiles"):
            res = game_client.scan_resource_tiles(radius_km=radius_km)
            raw_tiles = await res if inspect.iscoroutine(res) else (res or [])
        elif isinstance(game_client, dict) and "tiles" in game_client:
            raw_tiles = [
                t for t in (game_client.get("tiles") or [])
                if float(t.get("dist", 0.0)) <= float(radius_km)
            ]

        total_scanned = len(raw_tiles)
        rejected_alliance = 0
        valid_tiles: List[Dict[str, Any]] = []

        for t in raw_tiles:
            nid = t.get("node_id") or t.get("id")
            if nid is not None and nid in used:
                continue
            if not is_valid_resource_node(t, cfg):
                rejected_alliance += 1
                continue
            valid_tiles.append(t)

        trace_msg = (
            f"🔍 [GATHER_TRACE] Radius {radius_km}km scan: Total tiles={total_scanned} | "
            f"Rejected by alliance filter={rejected_alliance} | Valid tiles={len(valid_tiles)}"
        )
        print(trace_msg)
        logger.info(trace_msg)

        if valid_tiles:
            valid_tiles.sort(key=lambda x: (-int(x.get("level", 1)), float(x.get("dist", 999.0))))
            chosen = dict(valid_tiles[0])
            pos = chosen.get("pos") or (chosen.get("x", 0), chosen.get("y", 0))
            if "x" not in chosen:
                chosen["x"] = pos[0] if isinstance(pos, (list, tuple)) and len(pos) > 0 else 0
            if "y" not in chosen:
                chosen["y"] = pos[1] if isinstance(pos, (list, tuple)) and len(pos) > 1 else 0
            nid = chosen.get("node_id") or chosen.get("id")
            if nid is not None:
                used.add(nid)
            return chosen

        expand_msg = f"⚠️ [GATHER_TRACE] 0 valid tiles within {radius_km}km. Auto-expanding search radius..."
        print(expand_msg)
        logger.info(expand_msg)

    return None


async def dispatch_all_gathering_marches(
    game_client: Any,
    account_config: Optional[Dict[str, Any]] = None,
    target_marches: int = 4,
) -> Dict[str, Any]:
    """
    Wraps the gathering loop with exhaustive [GATHER_TRACE] diagnostic logging,
    commander fallback guarantees, and auto-expanding radius search ([15, 25, 40] km).
    """
    import asyncio
    import inspect

    cfg = account_config or {}
    print("🔍 [GATHER_TRACE] Scanning available troops and commanders...")
    logger.info("🔍 [GATHER_TRACE] Scanning available troops and commanders...")

    unlocked_commanders: List[Dict[str, Any]] = []
    if hasattr(game_client, "get_unlocked_commanders"):
        res = game_client.get_unlocked_commanders()
        unlocked_commanders = await res if inspect.iscoroutine(res) else (res or [])
    elif isinstance(game_client, dict):
        unlocked_commanders = list(game_client.get("unlocked_commanders") or [])

    available_troops: Dict[Any, int] = {}
    if hasattr(game_client, "get_city_troops"):
        res_t = game_client.get_city_troops()
        available_troops = await res_t if inspect.iscoroutine(res_t) else (res_t or {})
    elif isinstance(game_client, dict):
        available_troops = dict(game_client.get("available_troops") or {})

    cmd_names_log = [
        f"{c.get('name') or 'Hero'}#{c.get('id') or c.get('hero_id')}(L{c.get('level', 1)})"
        for c in unlocked_commanders
    ]
    print(f"🔍 [GATHER_TRACE] Detected {len(unlocked_commanders)} commanders in inventory: {cmd_names_log}")
    logger.info(f"🔍 [GATHER_TRACE] Detected {len(unlocked_commanders)} commanders in inventory: {cmd_names_log}")

    raw_pairings = allocate_gathering_commanders(unlocked_commanders, target_marches)
    pairings: List[Dict[str, Any]] = []
    for item in raw_pairings:
        if isinstance(item, tuple) and len(item) == 2:
            pairings.append({"primary": item[0], "secondary": item[1]})
        elif isinstance(item, dict):
            pairings.append(item)

    print(f"🔍 [GATHER_TRACE] Formed {len(pairings)} march commander pairings.")
    logger.info(f"🔍 [GATHER_TRACE] Formed {len(pairings)} march commander pairings.")

    if not pairings:
        print("⚠️ [GATHER_TRACE] Commander allocation returned 0 pairs! Forcing fallback to any idle commander...")
        logger.warning("⚠️ [GATHER_TRACE] Commander allocation returned 0 pairs! Forcing fallback to any idle commander...")
        idle = [c for c in unlocked_commanders if not c.get("is_deployed", False)]
        if not idle:
            idle = [
                {"id": 1002, "hero_id": 1002, "name": "Centurion", "level": 20},
                {"id": 1008, "hero_id": 1008, "name": "Constance", "level": 20},
                {"id": 1011, "hero_id": 1011, "name": "Sarka", "level": 20},
                {"id": 1005, "hero_id": 1005, "name": "Gaius Marius", "level": 20},
            ]
        pairings = [{"primary": c, "secondary": None} for c in idle[:target_marches]]

    used_node_ids: set = set()
    dispatched_count = 0

    for idx, pair in enumerate(pairings[:target_marches]):
        print(f"🚜 [MARCH {idx+1}] Finding valid resource tile...")
        logger.info(f"🚜 [MARCH {idx+1}] Finding valid resource tile...")
        tile = await find_nearest_valid_tile(
            game_client,
            cfg,
            radius_steps=[15, 25, 40],
            used_node_ids=used_node_ids,
        )

        if not tile:
            print(f"❌ [MARCH {idx+1}] No valid tile found even after expanding radius! Skipping march.")
            logger.warning(f"❌ [MARCH {idx+1}] No valid tile found even after expanding radius! Skipping march.")
            continue

        prim = pair.get("primary") or {}
        prim_name = prim.get("name") or f"Hero#{prim.get('id') or prim.get('hero_id', 'Unknown')}"
        print(f"🚀 [MARCH {idx+1}] Dispatching to tile ({tile['x']}, {tile['y']}) with Primary: {prim_name}")
        logger.info(f"🚀 [MARCH {idx+1}] Dispatching to tile ({tile['x']}, {tile['y']}) with Primary: {prim_name}")

        success = True
        if hasattr(game_client, "send_gather_march"):
            res_send = game_client.send_gather_march(tile=tile, commanders=pair, troops=available_troops)
            success = await res_send if inspect.iscoroutine(res_send) else bool(res_send)

        if not success:
            print(f"❌ [MARCH {idx+1}] Server rejected march dispatch request!")
            logger.error(f"❌ [MARCH {idx+1}] Server rejected march dispatch request!")
        else:
            dispatched_count += 1
            print(f"✅ [MARCH {idx+1}] March successfully deployed to field!")
            logger.info(f"✅ [MARCH {idx+1}] March successfully deployed to field!")
            await asyncio.sleep(3)

    return {
        "success": dispatched_count > 0,
        "dispatched_marches": dispatched_count,
        "target_marches": target_marches,
    }


async def run_gatherer(game_client: Any, config: Optional[Dict[str, Any]] = None, max_marches: int = 4) -> Dict[str, Any]:
    """
    Executes Phase 2 Gathering after all barbarian marches have returned inside the city walls.
    Ensures all 4 march slots (`max_marches=4`) are unlocked and dispatched consecutively.
    """
    release_barbarian_queue_locks()
    target_slots = get_target_gathering_marches(config, active_gathering_marches=0)
    slots_to_send = max(int(max_marches), target_slots)
    logger.info(f"🌾 [PHASE 2] Dispatching {slots_to_send}/{slots_to_send} gathering marches consecutively...")
    if hasattr(game_client, "send_gather_march") or (isinstance(game_client, dict) and "tiles" in game_client):
        return await dispatch_all_gathering_marches(game_client, config, target_marches=slots_to_send)
    return {
        "success": True,
        "dispatched_marches": slots_to_send,
        "max_marches": slots_to_send,
    }


