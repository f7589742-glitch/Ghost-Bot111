import re

# 1. Patch smart_gather_search.py
sg_path = '/home/ubuntu/bot-backend/app/services/smart_gather_search.py'
with open(sg_path, 'r', encoding='utf-8') as f:
    sg_content = f.read()

# Replace Opcode 1002 block and add 8003 & 121 handling
old_target = """                        sub1002 = ProtobufCodec.decode_message(p2)
                        try:
                            from app.services.city_state_parser import parse_city_state_1002
                            from app.models import InventoryDAO
                            _snap = parse_city_state_1002(p2)
                            if _snap:
                                _bid = kwargs.get('bot_id') or kwargs.get('user_bot_id') or ''
                                _cname = kwargs.get('char_name') or _snap.get('name') or ''
                                InventoryDAO.upsert(
                                    bot_id=_bid,
                                    role_id=str(active_role_id),
                                    name=_cname,
                                    kingdom_id=int(_snap.get('kingdom_id') or active_kingdom_id or 0),
                                    city_hall_level=int(_snap.get('city_hall_level') or 0),
                                    power=int(_snap.get('power') or 0),
                                    food=int(_snap.get('food') or 0),
                                    wood=int(_snap.get('wood') or 0),
                                    stone=int(_snap.get('stone') or 0),
                                    gold=int(_snap.get('gold') or 0)
                                )
                                print(f"   [INVENTORY] Opcode 1002 parsed for {_cname}: Food={_snap.get('food', 0):,} Wood={_snap.get('wood', 0):,} Stone={_snap.get('stone', 0):,} Gold={_snap.get('gold', 0):,} Power={_snap.get('power', 0):,}")
                        except Exception as _inv_err:
                            print(f"   [WARN] inventory 1002 sync: {_inv_err}")"""

new_target = """                        sub1002 = ProtobufCodec.decode_message(p2)
                        try:
                            from app.services.city_state_parser import parse_city_state_1002
                            from app.models import InventoryDAO
                            _snap = parse_city_state_1002(p2)
                            if _snap:
                                _bid = kwargs.get('bot_id') or kwargs.get('user_bot_id') or ''
                                _cname = kwargs.get('char_name') or _snap.get('name') or ''
                                InventoryDAO.upsert(
                                    bot_id=_bid,
                                    role_id=str(active_role_id),
                                    name=_cname,
                                    kingdom_id=int(_snap.get('kingdom_id') or active_kingdom_id or 0),
                                    city_hall_level=int(_snap.get('city_hall_level') or 0),
                                    power=int(_snap.get('power') or 0)
                                )
                                print(f"   [INVENTORY-1002] Profile parsed for {_cname}: CH={_snap.get('city_hall_level', 0)} Power={_snap.get('power', 0):,}")
                        except Exception as _inv_err:
                            print(f"   [WARN] inventory 1002 sync: {_inv_err}")"""

if old_target in sg_content:
    sg_content = sg_content.replace(old_target, new_target)
    print("Updated Opcode 1002 block in smart_gather_search.py")
else:
    print("WARN: Opcode 1002 target block not found verbatim in smart_gather_search.py")

# Add Opcode 8003 and Opcode 121 handling to smart_gather_search.py
op_search_pattern = r"(                # Active marches\s+elif op in \(1005, 1023\):)"
op_replacement = """                # Keepalive / Acknowledge Opcode 8003 -> server sends Opcode 121 (liquid resources)
                elif op == 8003:
                    try:
                        writer.write(FrameParser.build_frame(crypto_tx.encrypt(ProtobufCodec.encode_message({
                            1: 9, 2: ProtobufCodec.encode_message({1: 1})
                        }))))
                        await writer.drain()
                    except Exception:
                        pass

                # Opcode 121: Real in-city liquid resources (Food, Wood, Stone, Gold, Gems)
                elif op == 121:
                    try:
                        from app.models import InventoryDAO
                        from app.services.city_state_parser import parse_resources_121
                        p121 = m.get(2) or data
                        _rss = parse_resources_121(p121)
                        if _rss:
                            _bid = kwargs.get('bot_id') or kwargs.get('user_bot_id') or ''
                            _cname = kwargs.get('char_name') or getattr(active_char, 'name', '') or ''
                            InventoryDAO.upsert(
                                bot_id=_bid,
                                role_id=str(active_role_id),
                                name=_cname,
                                food=_rss.get('food', 0),
                                wood=_rss.get('wood', 0),
                                stone=_rss.get('stone', 0),
                                gold=_rss.get('gold', 0),
                                gems=_rss.get('gems', 0)
                            )
                            print(f"   [INVENTORY-121] Live Liquid Resources for {_cname}: Food={_rss.get('food', 0):,} Wood={_rss.get('wood', 0):,} Stone={_rss.get('stone', 0):,} Gold={_rss.get('gold', 0):,} Gems={_rss.get('gems', 0):,}")
                    except Exception as _rss_err:
                        print(f"   [WARN] opcode 121 sync error: {_rss_err}")

\\1"""

sg_content, count_sg = re.subn(op_search_pattern, op_replacement, sg_content)
if count_sg > 0:
    with open(sg_path, 'w', encoding='utf-8') as f:
        f.write(sg_content)
    print("Added Opcode 8003 and 121 handling to smart_gather_search.py")
else:
    print("WARN: Active marches pattern not matched in smart_gather_search.py")

# 2. Patch daily_claims.py
dc_path = '/home/ubuntu/bot-backend/app/services/daily_claims.py'
with open(dc_path, 'r', encoding='utf-8') as f:
    dc_content = f.read()

dc_old = """                            if op in (125, 1002):
                                done = True
                                try:
                                    from app.services.city_state_parser import parse_city_state_1002
                                    snap = parse_city_state_1002(sub)
                                    if snap and user_bot_id:
                                        from app.models import InventoryDAO
                                        InventoryDAO.upsert(
                                            bot_id=user_bot_id,
                                            role_id=str(target_role_id),
                                            name=char_name or f"Role_{target_role_id}",
                                            kingdom_id=int(kingdom_id or snap.get("kingdom_id") or 0),
                                            city_hall_level=int(snap.get("city_hall_level") or 0),
                                            power=int(snap.get("power") or 0),
                                            food=int(snap.get("food") or 0),
                                            wood=int(snap.get("wood") or 0),
                                            stone=int(snap.get("stone") or 0),
                                            gold=int(snap.get("gold") or 0),
                                        )
                                        log(f"[INVENTORY] Snapshot stored: food={snap.get('food', 0):,} wood={snap.get('wood', 0):,} stone={snap.get('stone', 0):,} gold={snap.get('gold', 0):,}")
                                except Exception as _ie:
                                    log(f"[WARN] inventory snapshot note: {_ie}")"""

dc_new = """                            if op == 8003:
                                try:
                                    writer.write(FrameParser.build_frame(crypto_tx.encrypt(ProtobufCodec.encode_message({
                                        1: 9, 2: ProtobufCodec.encode_message({1: 1})
                                    }))))
                                    await writer.drain()
                                except Exception: pass
                            elif op == 121:
                                try:
                                    from app.models import InventoryDAO
                                    from app.services.city_state_parser import parse_resources_121
                                    _rss = parse_resources_121(sub.get(2) or ch)
                                    if _rss and user_bot_id:
                                        InventoryDAO.upsert(
                                            bot_id=user_bot_id,
                                            role_id=str(target_role_id),
                                            name=char_name or f"Role_{target_role_id}",
                                            food=_rss.get('food', 0),
                                            wood=_rss.get('wood', 0),
                                            stone=_rss.get('stone', 0),
                                            gold=_rss.get('gold', 0),
                                            gems=_rss.get('gems', 0)
                                        )
                                        log(f"[INVENTORY-121] Live Resources: Food={_rss.get('food', 0):,} Wood={_rss.get('wood', 0):,} Stone={_rss.get('stone', 0):,} Gold={_rss.get('gold', 0):,} Gems={_rss.get('gems', 0):,}")
                                except Exception as _ie:
                                    log(f"[WARN] 121 sync note: {_ie}")
                            elif op in (125, 1002):
                                done = True
                                try:
                                    from app.services.city_state_parser import parse_city_state_1002
                                    snap = parse_city_state_1002(sub)
                                    if snap and user_bot_id:
                                        from app.models import InventoryDAO
                                        InventoryDAO.upsert(
                                            bot_id=user_bot_id,
                                            role_id=str(target_role_id),
                                            name=char_name or f"Role_{target_role_id}",
                                            kingdom_id=int(kingdom_id or snap.get("kingdom_id") or 0),
                                            city_hall_level=int(snap.get("city_hall_level") or 0),
                                            power=int(snap.get("power") or 0)
                                        )
                                        log(f"[INVENTORY-1002] Profile stored: CH={snap.get('city_hall_level', 0)} power={snap.get('power', 0):,}")
                                except Exception as _ie:
                                    log(f"[WARN] inventory snapshot note: {_ie}")"""

if dc_old in dc_content:
    dc_content = dc_content.replace(dc_old, dc_new)
    with open(dc_path, 'w', encoding='utf-8') as f:
        f.write(dc_content)
    print("Updated daily_claims.py with 8003 & 121 handling")
else:
    print("WARN: daily_claims target block not found verbatim")

# 3. Patch app/api/routes.py to include gems
routes_path = '/home/ubuntu/bot-backend/app/api/routes.py'
with open(routes_path, 'r', encoding='utf-8') as f:
    routes_content = f.read()

old_in_cities = """    in_cities = {
        "food": sum(int(c.get("food") or 0) for c in characters),
        "wood": sum(int(c.get("wood") or 0) for c in characters),
        "stone": sum(int(c.get("stone") or 0) for c in characters),
        "gold": sum(int(c.get("gold") or 0) for c in characters),
    }"""

new_in_cities = """    in_cities = {
        "food": sum(int(c.get("food") or 0) for c in characters),
        "wood": sum(int(c.get("wood") or 0) for c in characters),
        "stone": sum(int(c.get("stone") or 0) for c in characters),
        "gold": sum(int(c.get("gold") or 0) for c in characters),
        "gems": sum(int(c.get("gems") or 0) for c in characters),
    }"""

if old_in_cities in routes_content:
    routes_content = routes_content.replace(old_in_cities, new_in_cities)
    # Also in chars_out
    routes_content = routes_content.replace('"gold": int(c.get("gold") or 0),', '"gold": int(c.get("gold") or 0),\n            "gems": int(c.get("gems") or 0),')
    with open(routes_path, 'w', encoding='utf-8') as f:
        f.write(routes_content)
    print("Updated app/api/routes.py with gems support")
else:
    print("WARN: routes in_cities not found verbatim")
