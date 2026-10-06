"""
Packet dispatcher with multi-account isolation, HOME latch (1004 C->S)
and Resource Discovery ingestion (1003 S->C)
"""
import struct
import math
import logging

logger = logging.getLogger('bot.protocol')

RESOURCE_TYPE_MAP_LOCAL = {
    1: ('food','Cropland'),
    2: ('wood','Logging Camp'),
    3: ('stone','Stone Deposit'),
    4: ('gold','Gold Mine'),
    5: ('gem','Gem Deposit'),
}

def build_barbarian_search(target_level: int) -> bytes:
    """
    Wire payload format for barbarian level search / force-spawn (Opcode 1178):
    p2 = 1801 10{target_level} 0801 2001
    """
    return b'\x18\x01\x10' + bytes([int(target_level)]) + b'\x08\x01\x20\x01'

def handle_c2s_packet(opcode: int, payload: bytes, state) -> None:
    if opcode == 14:
        try:
            pid = getattr(state, 'current_player_id', None)
            if pid and hasattr(state, 'clear_tiles'):
                state.clear_tiles(pid)
        except Exception:
            pass
        return
    if opcode == 1004:
        pid = getattr(state, 'current_player_id', None)
        already = False
        if pid and hasattr(state, 'player_homes') and str(pid) in state.player_homes:
            already = True
        elif getattr(state, 'home_coords_set', False) and not pid:
            already = True
        if already:
            return
        if not isinstance(payload, (bytes, bytearray)):
            return
        x_idx = payload.find(b'\x0d')
        y_idx = payload.find(b'\x15')
        if x_idx != -1 and y_idx != -1 and x_idx+5 <= len(payload) and y_idx+5 <= len(payload):
            try:
                raw_x = struct.unpack('<f', payload[x_idx + 1 : x_idx + 5])[0]
                raw_y = struct.unpack('<f', payload[y_idx + 1 : y_idx + 5])[0]
                if 500 < raw_x < 8000 and 500 < raw_y < 8000:
                    if hasattr(state, 'set_home'):
                        state.set_home(raw_x, raw_y, player_id=pid)
                    else:
                        state.home_x = raw_x
                        state.home_y = raw_y
                        state.home_coords_set = True
                    logger.info(f'[HOME_FOUND] player={pid} Castle Latched at Wire: ({raw_x:.2f}, {raw_y:.2f}) | Km: ({raw_x/6.0:.2f}, {raw_y/6.0:.2f})')
                    print(f'[HOME_FOUND] player={pid} Castle Latched at Wire: ({raw_x:.2f}, {raw_y:.2f}) | Km: ({raw_x/6.0:.2f}, {raw_y/6.0:.2f})')
                    if hasattr(state, 'gather_scanner') and state.gather_scanner:
                        try:
                            state.gather_scanner.start(state.home_x, state.home_y)
                        except Exception as e:
                            logger.debug(f'gather_scanner start failed: {e}')
            except Exception as e:
                logger.debug(f'handle_c2s 1004 decode failed: {e}')

def handle_s2c_packet(opcode: int, payload: bytes, state) -> list:
    if opcode != 1003:
        return []
    try:
        from headless_client import ProtobufCodec
    except Exception:
        return []
    tiles = []
    try:
        if isinstance(payload, dict):
            pmsg = payload
        elif isinstance(payload, (bytes, bytearray)):
            try:
                pmsg = ProtobufCodec.decode_message(payload)
            except Exception:
                return []
        else:
            return []
        items = pmsg.get(5, [])
        if not isinstance(items, list):
            items = [items]
        home = None
        if hasattr(state, 'get_home'):
            home = state.get_home()
        elif getattr(state, 'home_coords_set', False):
            home = (state.home_x, state.home_y)
        hx, hy = home if home else (0.0, 0.0)
        for item_bytes in items:
            if not isinstance(item_bytes, bytes):
                continue
            try:
                obj = ProtobufCodec.decode_message(item_bytes)
            except Exception:
                continue
            f1_raw = obj.get(1)
            if isinstance(f1_raw, bytes):
                try:
                    f1 = ProtobufCodec.decode_message(f1_raw)
                except Exception:
                    f1 = {}
            elif isinstance(f1_raw, dict):
                f1 = f1_raw
            else:
                continue
            node_id = f1.get(1)
            if not node_id:
                continue
            pos_b = f1.get(3)
            px = py = 0.0
            if isinstance(pos_b, (bytes, bytearray)) and len(pos_b) >= 10:
                try:
                    v1 = struct.unpack('<f', pos_b[1:5])[0]
                    v2 = struct.unpack('<f', pos_b[6:10])[0]
                    if pos_b[0] == 0x0d:
                        px, py = v1, v2
                    else:
                        px, py = v2, v1
                except Exception:
                    pass
            type_id = obj.get(2, 1)
            level = obj.get(3, 1)
            occupier = obj.get(7, 0)
            march_st = obj.get(8, 0)
            is_free = (not occupier or occupier == 0 or occupier == b'') and (not march_st or march_st == 0)
            if not is_free:
                continue
            if type_id == 5:
                continue
            if hx and hy:
                wire_dist = math.hypot(px - hx, py - hy)
                km_dist = round(wire_dist / 6.0, 2)
            else:
                km_dist = 999.0
            res_name_key, res_display = RESOURCE_TYPE_MAP_LOCAL.get(type_id, ('food','Resource Field'))
            max_res = rem_res = 0
            try:
                from app.services.smart_gather_search import unpack_double_field, STANDARD_NODE_CAPACITIES
                max_res = unpack_double_field(obj.get(4))
                rem_res = unpack_double_field(obj.get(5))
                std_cap = float(STANDARD_NODE_CAPACITIES.get(type_id, {}).get(level, 472500.0))
                if max_res <= 0: max_res = std_cap
                if rem_res <= 0: rem_res = max_res
            except Exception:
                max_res = rem_res = 472500.0
            tiles.append({
                'node_id': node_id,
                'pos': (round(px,2), round(py,2)),
                'dist': km_dist,
                'type': res_name_key,
                'type_id': type_id,
                'name': res_display,
                'level': level,
                'free': is_free,
                'max_reserves': max_res,
                'remaining_reserves': rem_res,
            })
        tiles.sort(key=lambda x: (float(x['dist']), -int(x['level'])))
        if tiles and hasattr(state, 'add_tiles'):
            pid = getattr(state, 'current_player_id', None)
            state.add_tiles(pid, tiles)
            logger.info(f'[1003_INGEST] player={pid} ingested {len(tiles)} free tiles closest {tiles[0]["dist"]}km {tiles[0]["name"]}#{tiles[0]["node_id"]}')
    except Exception as e:
        logger.debug(f'handle_s2c 1003 failed: {e}')
    return tiles

def handle_disconnect(state, player_id=None):
    try:
        pid = player_id or getattr(state, 'current_player_id', None)
        if hasattr(state, 'reset_session'):
            state.reset_session(pid)
            logger.info(f'[DISCONNECT] reset session for player {pid}')
        else:
            state.home_coords_set=False
            state.home_x=state.home_y=0.0
    except Exception as e:
        logger.debug(f'handle_disconnect failed {e}')
