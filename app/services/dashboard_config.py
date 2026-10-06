"""Translate dashboard settings once and keep each room's configuration isolated."""
import json
import math

RESOURCES = ("food", "wood", "stone", "gold")


def sanitize_commander_pairs(pairs):
    """Validate manual commander pairs: {res: [{primary, secondary}]}.

    Keeps only integer hero IDs (1..5000); anything else becomes None.
    At most 5 pairs per resource. Non-dict input yields {}.
    One hero may lead only ONE march: repeats across all pairs are nulled
    (first occurrence wins), so a commander is never dispatched twice.
    """
    clean = {}
    if not isinstance(pairs, dict):
        return clean
    seen = set()
    for res in RESOURCES:
        raw = pairs.get(res)
        if not isinstance(raw, list):
            continue
        out = []
        for entry in raw[:5]:
            if not isinstance(entry, dict):
                continue
            def _hid(v):
                try:
                    v = int(v)
                except (TypeError, ValueError):
                    return None
                return v if 1 <= v <= 5000 else None
            pri = _hid(entry.get("primary"))
            sec = _hid(entry.get("secondary"))
            if pri is not None:
                if pri in seen:
                    pri = None
                else:
                    seen.add(pri)
            if sec is not None:
                if sec in seen or sec == pri:
                    sec = None
                else:
                    seen.add(sec)
            out.append({"primary": pri, "secondary": sec})
        if out:
            clean[res] = out
    return clean


def normalize_gather_config(config):
    result = dict(config)
    marches = config.get("marches") if isinstance(config.get("marches"), dict) else {}
    counts = {}
    for resource in RESOURCES:
        # Explicit counts take precedence over the legacy enabled booleans.
        value = config.get(f"{resource}_marches", marches.get(resource, config.get(resource, 0)))
        count = int(value)
        if not 0 <= count <= 5:
            raise ValueError(f"{resource} marches must be between 0 and 5")
        counts[resource] = count
        result[resource] = count > 0
        result[f"{resource}_marches"] = count
    result["marches"] = counts
    result["enabled"] = any(counts.values())
    for keys, default in (
        (("auto_balance_lowest_rss", "auto_balance", "autoBalanceLowest", "prioritize_lowest_rss"), False),
        (("skip_partially_gathered", "skip_partially", "skipPartial", "skip_partially_depleted", "skip_partially_gathered_nodes"), True),
        (("avoid_enemy_territory", "avoid_territory", "avoidEnemyTerritory", "avoid_other_alliance_territories"), True),
    ):
        value = next((config[k] for k in keys if k in config), default)
        if not isinstance(value, bool):
            value = str(value).lower() in ("true", "1", "on")
        result.update({key: value for key in keys})
    level = config.get("max_node_level", config.get("max_level", 0))
    result.update(max_node_level=level, max_level=level)
    manual = config.get("manual_commanders_enabled", config.get("manualCommanders", False))
    result["manual_commanders_enabled"] = bool(manual) if isinstance(manual, bool) else str(manual).lower() in ("true", "1", "on")
    result["manualCommanders"] = result["manual_commanders_enabled"]
    # sanitize_commander_pairs() also enforces one-hero-one-march, so pairs
    # saved before the UI guard (or hand-edited rows) are cleaned on read.
    result["custom_pairs"] = sanitize_commander_pairs(config.get("custom_pairs", config.get("commanderPairs", {})))
    result["commanderPairs"] = result["custom_pairs"]
    return result


def dashboard_patch(config):
    """Return settings in the vocabulary consumed by the Python workers."""
    gather = normalize_gather_config({
        **{f"{r}_marches": config.get(f"gather{r.title()}Marches", 0) for r in RESOURCES},
        "auto_balance_lowest_rss": config.get("autoBalanceLowest", False),
        "skip_partially_gathered": config.get("skipPartiallyGathered", True),
        "avoid_enemy_territory": config.get("avoidEnemyTerritory", True),
        "max_node_level": int(config.get("maxNodeLevel", 0)),
        "manual_commanders_enabled": config.get("manualCommanders", False),
        "manualCommanders": config.get("manualCommanders", False),
        "custom_pairs": config.get("commanderPairs", {}),
        "commanderPairs": config.get("commanderPairs", {}),
    })
    if not 0 <= gather["max_node_level"] <= 6:
        raise ValueError("maxNodeLevel must be between 0 and 6")
    tiers = {}
    for category, key in (("infantry", "trainInfantry"), ("cavalry", "trainCavalry"), ("archery", "trainArchers"), ("siege", "trainSiege")):
        if key in config:
            value = str(config[key]).lower()
            tiers[category] = "off" if value in ("disabled", "off", "none") else value
    patch = {"gather": gather, "tiers": tiers}
    for section, fields in {
        "alliance": {
            "allianceTech": "donate_tech",
            "allianceHelp": "help_alliance_members",
            "allianceGifts": "claim_gifts",
            "allianceSuperNode": "gather_super_node",
            "allianceTerritoryRss": "gather_resource_pit"
        },
        "hospital": {"healHospital": "heal_troops"},
        "combat": {"huntBarbs": "barbs"},
        "daily_claims": {
            "dailyVip": "daily_vip_claim",
            "cityHarvest": "city_harvest",
            "chronicleClaim": "chronicle_claim",
            "dailyQuests": "claim_daily_quests",
            "dailyQuestChests": "claim_daily_quest_chests",
            "sideQuests": "claim_side_quests",
            "autoScout": "auto_scout"
        },
        "city": {"collectResources": "collect_resources"},
    }.items():
        patch[section] = {target: bool(config[source]) for source, target in fields.items() if source in config}

    if "alliance" in patch:
        if "gather_super_node" in patch["alliance"]:
            val = patch["alliance"]["gather_super_node"]
            patch["alliance"]["super_node"] = val
            patch["alliance"]["alliance_super_node"] = val
            patch["alliance"]["allianceSuperNode"] = val
        if "gather_resource_pit" in patch["alliance"]:
            val = patch["alliance"]["gather_resource_pit"]
            patch["alliance"]["claim_territory_rss"] = val
            patch["alliance"]["claim_pit"] = val
            patch["alliance"]["allianceTerritoryRss"] = val

    def _pit_hero(value):
        try:
            value = int(value)
        except (TypeError, ValueError):
            return None
        return value if 1 <= value <= 5000 else None

    # Alliance pit manual commander pair (single march; validated per
    # character at dispatch, auto fallback otherwise).
    patch_alliance = patch.get("alliance") or {}
    patch_alliance["pit_primary"] = _pit_hero(config.get("alliancePitPrimary"))
    patch_alliance["pit_secondary"] = _pit_hero(config.get("alliancePitSecondary"))
    patch_alliance["alliancePitPrimary"] = patch_alliance["pit_primary"]
    patch_alliance["alliancePitSecondary"] = patch_alliance["pit_secondary"]
    patch["alliance"] = patch_alliance

    # The pit march runs before field gathering and takes its heroes first:
    # drop pit heroes from field custom_pairs (one hero, one march).
    _pit_used = {h for h in (patch_alliance["pit_primary"], patch_alliance["pit_secondary"]) if h}
    if _pit_used and isinstance(gather.get("custom_pairs"), dict):
        for _res, _lst in gather["custom_pairs"].items():
            if isinstance(_lst, list):
                for _entry in _lst:
                    if isinstance(_entry, dict):
                        if _entry.get("primary") in _pit_used:
                            _entry["primary"] = None
                        if _entry.get("secondary") in _pit_used:
                            _entry["secondary"] = None
        gather["commanderPairs"] = gather["custom_pairs"]

    return patch


def read_room_config(user_id, bot_id):
    from app.models import BotSettingsDAO
    bot_id = str(bot_id or "").strip()
    if bot_id.isdigit():
        bot_id = f"bot-{bot_id}"
    raw = BotSettingsDAO.get(f"dashboard_config_{bot_id}", user_id=user_id)
    return json.loads(raw) if raw else None


def _account_snapshot_key(bot_id, account_id):
    return f"dashboard_config_{bot_id}_acc_{account_id}"


def _role_snapshot_key(bot_id, role_id):
    return f"dashboard_config_{bot_id}_role_{role_id}"


def read_account_config(user_id, bot_id, account_id):
    """Per-account override snapshot (None when the account follows the room)."""
    from app.models import BotSettingsDAO
    if not account_id:
        return None
    bot_id = str(bot_id or "").strip()
    if bot_id.isdigit():
        bot_id = f"bot-{bot_id}"
    raw = BotSettingsDAO.get(_account_snapshot_key(bot_id, account_id), user_id=user_id)
    return json.loads(raw) if raw else None


def read_role_config(user_id, bot_id, role_id):
    """Per-character override snapshot (None when the character follows up)."""
    from app.models import BotSettingsDAO
    if not role_id:
        return None
    bot_id = str(bot_id or "").strip()
    if bot_id.isdigit():
        bot_id = f"bot-{bot_id}"
    raw = BotSettingsDAO.get(_role_snapshot_key(bot_id, role_id), user_id=user_id)
    return json.loads(raw) if raw else None


def merged_flat_config(user_id, bot_id, account_id=None, role_id=None):
    """Room snapshot with overrides laid over it (flat dashboard keys).

    Precedence: room < account < character.
    """
    from app.models import CharacterDAO
    base = read_room_config(user_id, bot_id) or {}
    acc_id = account_id
    if role_id and not acc_id:
        try:
            _ch = CharacterDAO.get_by_role_id(str(role_id))
            if _ch and _ch.get("account_id"):
                acc_id = _ch["account_id"]
        except Exception:
            pass
    if acc_id:
        base = {**base, **(read_account_config(user_id, bot_id, acc_id) or {})}
    if role_id:
        base = {**base, **(read_role_config(user_id, bot_id, role_id) or {})}
    return base


def effective_settings(character, account, settings=None):
    """Apply room settings at execution time, including newly linked characters.

    Precedence: character row < room snapshot < per-account override snapshot.
    """
    from app.models import CharacterSettingsDAO
    result = dict(settings or CharacterSettingsDAO.get_by_character_id(character["id"]))
    config = read_room_config(account.get("user_id", ""), account.get("bot_id", ""))
    if config is not None:
        for section, values in dashboard_patch(config).items():
            result[section] = {**result.get(section, {}), **values}
        if "autoTrainTroops" in config:
            result["training"] = {"enabled": bool(config["autoTrainTroops"])}
    acc_over = read_account_config(account.get("user_id", ""), account.get("bot_id", ""),
                                   account.get("id", ""))
    if acc_over:
        for section, values in dashboard_patch(acc_over).items():
            result[section] = {**result.get(section, {}), **values}
        if "autoTrainTroops" in acc_over:
            result["training"] = {"enabled": bool(acc_over["autoTrainTroops"])}
    role_over = read_role_config(account.get("user_id", ""), account.get("bot_id", ""),
                                 character.get("role_id", ""))
    if role_over:
        for section, values in dashboard_patch(role_over).items():
            result[section] = {**result.get(section, {}), **values}
        if "autoTrainTroops" in role_over:
            result["training"] = {"enabled": bool(role_over["autoTrainTroops"])}
    return result


def save_room_config(user_id, bot_id, config, account_id=None, role_id=None):
    from app.models import AccountDAO, CharacterDAO, CharacterSettingsDAO, BotSettingsDAO
    if not user_id or not bot_id:
        raise ValueError("User and room are required")
    bot_id = str(bot_id).strip()
    if bot_id.isdigit():
        bot_id = f"bot-{bot_id}"
    patch = dashboard_patch(config)
    interval = float(config.get("runIntervalHours", 4))
    if not math.isfinite(interval) or interval <= 0:
        raise ValueError("Run interval must be positive")
    if role_id:
        # Per-character override: snapshot + mirror ONLY this character row.
        role_id = str(role_id)
        BotSettingsDAO.set(_role_snapshot_key(bot_id, role_id), json.dumps(config), user_id=user_id)
        updated = 0
        try:
            _ch = CharacterDAO.get_by_role_id(role_id)
            if _ch and _ch.get("id"):
                CharacterSettingsDAO.upsert(_ch["id"], **patch)
                updated = 1
        except Exception:
            pass
        saved = read_role_config(user_id, bot_id, role_id)
        if saved != config:
            raise RuntimeError("Character configuration readback failed")
        return {"success": True, "bot_id": bot_id, "config": saved,
                "gather": patch["gather"], "characters_updated": updated,
                "scope": "role", "role_id": role_id}
    if account_id:
        # Per-account override: snapshot + mirror ONLY this account's characters.
        # The room snapshot stays the base; effective_settings() overlays this.
        account_id = str(account_id)
        BotSettingsDAO.set(_account_snapshot_key(bot_id, account_id), json.dumps(config), user_id=user_id)
        updated = 0
        for character in CharacterDAO.get_by_account_id(account_id):
            CharacterSettingsDAO.upsert(character["id"], **patch)
            updated += 1
        saved = read_account_config(user_id, bot_id, account_id)
        if saved != config:
            raise RuntimeError("Account configuration readback failed")
        return {"success": True, "bot_id": bot_id, "config": saved,
                "gather": patch["gather"], "characters_updated": updated,
                "scope": "account", "account_id": account_id}
    # Store the authoritative room snapshot first. Workers merge it on every task;
    # legacy character rows are mirrored for older consumers without touching peers.
    BotSettingsDAO.set(f"dashboard_config_{bot_id}", json.dumps(config), user_id=user_id)
    BotSettingsDAO.set(f"gather_config_{bot_id}", json.dumps(patch["gather"]), user_id=user_id)
    updated = 0
    for account in AccountDAO.get_all(user_id=user_id, bot_id=bot_id):
        for character in CharacterDAO.get_by_account_id(account["id"]):
            CharacterSettingsDAO.upsert(character["id"], **patch)
            updated += 1

    # Synchronize scheduled next_run times and interval settings with new interval
    try:
        import datetime
        from app.services.scheduler_service import BotScheduler
        now_dt = datetime.datetime.now()
        now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
        base_minutes = int(interval * 60)

        # Store explicit run_interval_hours in BotSettings for all query scopes
        if user_id:
            BotSettingsDAO.set("run_interval_hours", str(interval), user_id=user_id)
            BotSettingsDAO.set(f"run_interval_hours_{bot_id}", str(interval), user_id=user_id)
        BotSettingsDAO.set("run_interval_hours", str(interval))
        BotSettingsDAO.set(f"run_interval_hours_{bot_id}", str(interval))

        global_next_dt = BotScheduler.calculate_global_next_run(True, base_minutes)
        global_next_str = global_next_dt.strftime("%Y-%m-%d %H:%M:%S") if global_next_dt else ""

        if user_id:
            BotSettingsDAO.set(f"next_run_timestamp_{bot_id}", global_next_str, user_id=user_id)
            BotSettingsDAO.set("next_run_timestamp", global_next_str, user_id=user_id)
        BotSettingsDAO.set(f"next_run_timestamp_{bot_id}", global_next_str)
        BotSettingsDAO.set("next_run_timestamp", global_next_str)

        target_accounts = AccountDAO.get_all(user_id=user_id, bot_id=bot_id)
        if not target_accounts:
            target_accounts = AccountDAO.get_all(bot_id=bot_id)
        if not target_accounts and user_id:
            target_accounts = AccountDAO.get_all(user_id=user_id)

        for account in target_accounts:
            acc_next_dt = BotScheduler.calculate_next_run(account["id"], True, base_minutes)
            acc_next_str = acc_next_dt.strftime("%Y-%m-%d %H:%M:%S") if acc_next_dt else global_next_str
            AccountDAO.update_run_times(account["id"], last_run=now_str, next_run=acc_next_str)
            for character in CharacterDAO.get_by_account_id(account["id"]):
                char_next_dt = BotScheduler.calculate_next_run(character.get("role_id"), True, base_minutes)
                char_next_str = char_next_dt.strftime("%Y-%m-%d %H:%M:%S") if char_next_dt else acc_next_str
                CharacterDAO.update_run_times(character.get("role_id"), last_run=now_str, next_run=char_next_str)
    except Exception as e_resched:
        logger.warning(f"Error synchronizing room interval: {e_resched}")

    saved = read_room_config(user_id, bot_id)
    if saved != config:
        raise RuntimeError("Room configuration readback failed")
    return {"success": True, "bot_id": bot_id, "config": saved,
            "gather": patch["gather"], "characters_updated": updated, "scope": "room"}
