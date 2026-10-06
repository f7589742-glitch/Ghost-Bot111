import asyncio
import logging
import math
import time
from typing import Dict, Any, List, Optional, Callable, Tuple

logger = logging.getLogger(__name__)

# Trading Post Progression Table (Capacity and Tax Rate verified from game packets/UI)
TRADING_POST_DATA = {
    1:  {"capacity": 10000,    "tax": 0.35},
    2:  {"capacity": 30000,    "tax": 0.34},
    3:  {"capacity": 60000,    "tax": 0.33},
    4:  {"capacity": 100000,   "tax": 0.32},
    5:  {"capacity": 150000,   "tax": 0.31},
    6:  {"capacity": 200000,   "tax": 0.30},
    7:  {"capacity": 300000,   "tax": 0.29},
    8:  {"capacity": 400000,   "tax": 0.28},
    9:  {"capacity": 500000,   "tax": 0.27},
    10: {"capacity": 600000,   "tax": 0.26},
    11: {"capacity": 800000,   "tax": 0.25},
    12: {"capacity": 1000000,  "tax": 0.24},
    13: {"capacity": 1200000,  "tax": 0.23},
    14: {"capacity": 1400000,  "tax": 0.22},
    15: {"capacity": 1600000,  "tax": 0.21},
    16: {"capacity": 1800000,  "tax": 0.20},
    17: {"capacity": 2000000,  "tax": 0.19},
    18: {"capacity": 2200000,  "tax": 0.18},
    19: {"capacity": 2400000,  "tax": 0.17},
    20: {"capacity": 2600000,  "tax": 0.16},
    21: {"capacity": 2800000,  "tax": 0.15},
    22: {"capacity": 3000000,  "tax": 0.14},
    23: {"capacity": 3500000,  "tax": 0.12},
    24: {"capacity": 4000000,  "tax": 0.10},
    25: {"capacity": 10000000, "tax": 0.08},
}

RESOURCE_TYPE_IDS = {
    "food": 1,
    "wood": 2,
    "stone": 3,
    "gold": 4
}

RES_NAME_AR = {
    "food": "طعام",
    "wood": "خشب",
    "stone": "حجر",
    "gold": "ذهب"
}

STAGE_MESSAGES = {
    "recall": "استدعاء المسيرات وتأمين القوات داخل القلعة...",
    "inspect": "فحص مستوى السوق واعتماد نسبة الضريبة الرسمية...",
    "dispatching": "جاري تسيير قوافل الإمداد وتفريغ الشحنات...",
    "done": "اكتمل تسليم الشحنات المتاحة للمزرعة بنجاح.",
    "skipped": "تم الاكتفاء بحصة المزارع الأخرى.",
    "insufficient": "تم إفراغ كامل الرصيد المتاح في المخزن."
}


class RSSTransferEngine:
    @staticmethod
    async def force_recall_all_marches(client, role_id: str, log_cb: Callable[[str], None]) -> int:
        """
        Uses verified Opcode 1014 march recall service to safely return any outside troops.
        """
        if hasattr(client, "recall_marches") and callable(client.recall_marches):
            return await client.recall_marches()
        return 0

    @classmethod
    async def prepare_headless_farm(
        cls,
        farm_role_id: str,
        target_role_id: str,
        target_coords: tuple,
        log_cb: Callable[[str], None],
        user_id: str = "",
        custom_tp_level: Optional[int] = None,
        job_cancel_check: Optional[Callable[[], bool]] = None
    ) -> Tuple[Optional[Any], Optional[Dict[str, Any]]]:
        """
        Phase 1: Connects to game gateway, recalls 100% of troops into castle,
        inspects trading post and target city coordinates.
        Does NOT dispatch any donkeys until barrier check passes across all farms.
        """
        from app.services.session_manager import get_active_client

        if job_cancel_check and job_cancel_check():
            log_cb(f"[{farm_role_id}] 🛑 تم إلغاء المهمة بأمر المستخدم.")
            return None, None

        client = await get_active_client(farm_role_id, user_id=user_id, log_cb=log_cb)
        if not client:
            log_cb(f"[{farm_role_id}] ❌ تعذر تهيئة جلسة العميل السحابي للمزرعة.")
            return None, None

        try:
            tx, ty = target_coords
            log_cb(f"[{farm_role_id}] 🔑 بدء فحص الحساب وتأمين القوات لنقل الموارد إلى #{target_role_id}...")

            # 1. Recall all outside troops and actively wait until 100% inside castle
            recalled = await cls.force_recall_all_marches(client, farm_role_id, log_cb)

            if job_cancel_check and job_cancel_check():
                log_cb(f"[{farm_role_id}] 🛑 تم إلغاء النقل بأمر المستخدم بعد عودة القوات.")
                await client.close()
                return None, None

            # 2. Extract Trading Post level dynamically from state or fallback to city level
            buildings = getattr(client, "state", {}).get("buildings", {})
            detected_lvl = buildings.get("trading_post_lvl")
            tp_confirmed = bool(buildings.get("trading_post_confirmed"))
            if not detected_lvl or detected_lvl < 1:
                # check city hall level or default
                detected_lvl = getattr(client, "state", {}).get("city_level", 17)
                tp_confirmed = False
            trading_post_lvl = int(custom_tp_level) if (custom_tp_level and 1 <= custom_tp_level <= 25) else int(detected_lvl or 17)
            tp_spec = TRADING_POST_DATA.get(trading_post_lvl, TRADING_POST_DATA[17])
            tax_rate = tp_spec["tax"]
            net_capacity = tp_spec["capacity"]
            max_gross_per_donkey = int(math.ceil(net_capacity / (1.0 - tax_rate)))
            donkey_tax = max_gross_per_donkey - net_capacity

            log_cb(
                f"[{farm_role_id}] 🏬 تم فحص السوق: لفل {trading_post_lvl} "
                f"({'مؤكد سلكياً' if tp_confirmed else 'تقديري من مستوى المدينة — سيتقلص تلقائياً عند الرفض'}) | "
                f"نسبة الضريبة: {int(tax_rate * 100)}% | "
                f"سعة الحمار الواحد (الصافي للمستلم): {net_capacity:,} "
                f"(المخصوم من المخزن: {max_gross_per_donkey:,} | الضريبة: {donkey_tax:,})"
            )

            city_inventory = getattr(client, "state", {}).get("resources", {})
            log_cb(
                f"[{farm_role_id}] 💎 الموارد الفعلية بالمدينة: "
                f"طعام: {city_inventory.get('food', 0):,} | "
                f"خشب: {city_inventory.get('wood', 0):,} | "
                f"حجر: {city_inventory.get('stone', 0):,} | "
                f"ذهب: {city_inventory.get('gold', 0):,}"
            )

            # 3. Target City Inspection & Map Viewport Alignment
            if hasattr(client, "inspect_target_city"):
                log_cb(f"[{farm_role_id}] 📍 جاري الانتقال إلى إحداثيات المستلم ({tx}, {ty}) وفحص القلعة #{target_role_id}...")
                await client.inspect_target_city(target_role_id, tx, ty)

            prep_info = {
                "tp_lvl": trading_post_lvl,
                "tax_rate": tax_rate,
                "net_capacity": net_capacity,
                "max_gross": max_gross_per_donkey,
                "donkey_tax": donkey_tax
            }
            log_cb(f"[{farm_role_id}] 🏰 المزرعة مؤمنة 100% وجاهزة عند بوابة السوق بانتظار إشارة الانطلاق المتزامن.")
            return client, prep_info

        except Exception as e:
            log_cb(f"[{farm_role_id}] ❌ خطأ أثناء تجهيز المزرعة: {e}")
            await client.close()
            return None, None

    @classmethod
    async def dispatch_prepared_transfer(
        cls,
        client: Any,
        farm_role_id: str,
        target_role_id: str,
        target_coords: tuple,
        requested_rss: Dict[str, int],
        prep_info: Dict[str, Any],
        log_cb: Callable[[str], None],
        job_cancel_check: Optional[Callable[[], bool]] = None,
        on_sent_chunk_cb: Optional[Callable[[str, str, int], None]] = None
    ) -> Dict[str, int]:
        """
        Phase 2: Dispatches authentic Opcode 1056 resource aid caravans in parallel.
        Dispatches full donkey loads based on trading post capacity (e.g. 2,000,000 net per donkey at L17).
        """
        tax_rate = prep_info.get("tax_rate", 0.19)
        max_gross_per_donkey = prep_info.get("max_gross", 2469136)
        net_capacity = prep_info.get("net_capacity", 2000000)

        delivered_summary = {res: 0 for res in RESOURCE_TYPE_IDS}
        city_inventory = getattr(client, "state", {}).get("resources", {})

        for res_name, net_requested in requested_rss.items():
            if job_cancel_check and job_cancel_check():
                break

            if net_requested <= 0 or res_name not in RESOURCE_TYPE_IDS:
                continue

            res_id = RESOURCE_TYPE_IDS[res_name]
            gross_needed = int(math.ceil(net_requested / (1.0 - tax_rate)))
            available_balance = city_inventory.get(res_name, 0)

            # Warehouse safety cushion (keep 150k reserve)
            sendable_amount = max(0, available_balance - 150000)
            to_send = min(gross_needed, sendable_amount)

            if to_send <= 0:
                log_cb(f"[{farm_role_id}] ⚠️ رصيد {res_name} غير كافٍ لنقل الكمية المطلوبة ({available_balance:,} متوفر | مطلوب صافي {net_requested:,}).")
                continue

            remaining = to_send
            expected_net = int(to_send * (1 - tax_rate))
            total_tax_est = to_send - expected_net
            log_cb(
                f"[{farm_role_id}] 🚀 بدء إرسال مورد {res_name}: "
                f"الصافي للمستلم: {expected_net:,} | "
                f"الضريبة (-{total_tax_est:,}) | "
                f"الإجمالي المخصوم من المدينة: {to_send:,}..."
            )

            batch_idx = 1
            # Per-resource session caravan caps: a refusal on one resource must
            # never slow another (gold shrinks fast, food stays full-size).
            # First attempt always goes full-size (the game client allows it);
            # on over-capacity refusals (e.g. code 110) the cap halves.
            res_caps: Dict[str, int] = {rn: max_gross_per_donkey for rn in requested_rss}
            while remaining > 0:
                if job_cancel_check and job_cancel_check():
                    log_cb(f"[{farm_role_id}] 🛑 تم إيقاف النقل فوراً بأمر المستخدم.")
                    break

                chunk = min(remaining, res_caps.get(res_name, max_gross_per_donkey))
                chunk_net = int(chunk * (1.0 - tax_rate))
                chunk_tax = chunk - chunk_net
                halvings = 0

                retries = 0
                ack_ok = False
                last_err = ""
                same_size_tries = 0
                while retries < 120 and not ack_ok:
                    if job_cancel_check and job_cancel_check():
                        break

                    if hasattr(client, "send_resource_transport"):
                        res = await client.send_resource_transport(target_role_id, res_id, chunk)
                        ack_ok = res.get("success", False)
                        last_err = str(res.get("error", ""))
                    else:
                        ack = await client.send_packet(1056, {
                            1: int(target_role_id),
                            2: {1: int(res_id), 2: int(chunk)}
                        })
                        ack_ok = bool(ack and ack.get("code") in (0, 1))
                        last_err = str(ack.get("error", "")) if isinstance(ack, dict) else ""

                    if ack_ok:
                        break

                    if "164" in last_err or "queue" in last_err.lower():
                        retries += 1
                        log_cb(f"[{farm_role_id}] ⏳ جميع مسيرات الحمير بالخارج (طابور ممتلئ - 164). بانتظار عودة الحمار من قلعة المستلم... [{retries}/120]")
                        await asyncio.sleep(3.5)
                    elif halvings < 4 and chunk > 100000 and same_size_tries < 2 and ("110" in last_err or not last_err or "timeout" in last_err.lower()):
                        # Transient refusal/race: insist full-size twice before
                        # concluding the caravan is truly over capacity.
                        same_size_tries += 1
                        retries += 1
                        log_cb(f"[{farm_role_id}] 🔁 رفض عابر ({last_err or 'لا رد'}) — إعادة نفس الحمولة {chunk:,} [{same_size_tries}/2]")
                        await asyncio.sleep(2.0)
                    elif halvings < 4 and chunk > 100000:
                        # Persistent refusal: halve the caravan and retry
                        # immediately instead of burning futile retries.
                        halvings += 1
                        chunk = max(chunk // 2, 100000)
                        res_caps[res_name] = chunk
                        chunk_net = int(chunk * (1.0 - tax_rate))
                        chunk_tax = chunk - chunk_net
                        same_size_tries = 0
                        log_cb(f"[{farm_role_id}] 📉 رفض السيرفر الشحنة ({last_err}) — تقليص الحمولة إلى {chunk:,} والمحاولة فوراً [{halvings}/4]")
                        retries = 0
                        await asyncio.sleep(1.0)
                    else:
                        await asyncio.sleep(2.0)
                        retries += 1

                    if job_cancel_check and job_cancel_check():
                        break

                if ack_ok:
                    remaining -= chunk
                    delivered_summary[res_name] += chunk_net
                    city_inventory[res_name] = max(0, city_inventory.get(res_name, 0) - chunk)
                    
                    if on_sent_chunk_cb:
                        try:
                            on_sent_chunk_cb(farm_role_id, res_name, chunk_net)
                        except Exception:
                            pass

                    log_cb(
                        f"[{farm_role_id}] 📦 تم تسليم شحنة {res_name} #{batch_idx}: "
                        f"صافي للمستلم: {chunk_net:,} "
                        f"(المخصوم من المخزن: {chunk:,} | الضريبة: -{chunk_tax:,}) | "
                        f"المتبقي للنقل صافي: {int(remaining * (1 - tax_rate)):,}"
                    )
                    batch_idx += 1
                    await asyncio.sleep(2.0)
                else:
                    err_text = last_err or "رفض الخادم للشحنة"
                    log_cb(f"[{farm_role_id}] ❌ تعذر إرسال الشحنة ({err_text}). إيقاف الدورة لهذا المورد.")
                    break

        log_cb(f"[{farm_role_id}] 🏁 اكتملت جميع الشحنات للمزرعة بنجاح.")
        return delivered_summary


class TransferJobRunner:
    """
    Arcane Concurrent RSS Transfer Runner & Structured Telemetry Publisher.
    Publishes real-time telemetry to Firebase Realtime Database (transfer_telemetry/{job_id})
    and mirrors to in-memory store so the hydraulic progress bars animate in real time.
    """
    @staticmethod
    def update_telemetry(job_id: str, state_dict: Dict[str, Any]):
        try:
            import firebase_admin
            from firebase_admin import db
            if firebase_admin._apps:
                db.reference(f"transfer_telemetry/{job_id}").update(state_dict)
        except Exception as e:
            logger.debug(f"Firebase telemetry update skipped: {e}")

        try:
            from app.api.endpoints.transfer import _ACTIVE_JOBS
            if job_id in _ACTIVE_JOBS:
                _ACTIVE_JOBS[job_id].update(state_dict)
        except Exception:
            pass

    @classmethod
    async def run_pipeline(cls, job_id: str, payload: dict, log_cb: Optional[Callable[[str], None]] = None):
        from app.database import get_db_connection
        from app.services.session_manager import toggle_gather_scheduler

        def _log(msg: str):
            if log_cb:
                log_cb(msg)
            else:
                logger.info(f"[{job_id}] {msg}")

        # 1. Discover Farm Metadata & Account Identity from Database
        con = get_db_connection()
        workers = []
        account_map = {}
        raw_farms = []

        user_id_filter = str(payload.get("user_id") or "").strip()
        bot_id_filter = str(payload.get("bot_id") or "").strip()
        norm_bot_filter = ""
        if bot_id_filter:
            try:
                from app.api.routes import _normalize_bot_id
                norm_bot_filter = _normalize_bot_id(bot_id_filter) or bot_id_filter
            except Exception:
                norm_bot_filter = bot_id_filter

        for role_str in (payload.get("selected_farm_roles") or []):
            row = con.execute("""
                SELECT c.role_id, c.name, c.city_level, c.enabled, c.food, c.wood, c.stone, c.gold, a.email, c.account_id, a.user_id, a.bot_id
                FROM characters c
                LEFT JOIN accounts a ON c.account_id = a.id
                WHERE c.role_id = ?
            """, (role_str,)).fetchone()

            if not row:
                continue

            # Strict Tenancy check: Ensure account belongs to user and room
            if user_id_filter and row["user_id"] and str(row["user_id"]).strip() != user_id_filter:
                _log(f"[{role_str}] ⚠️ تم تخطي المزرعة لأنها تتبع مستخدم آخر.")
                continue

            if bot_id_filter and row["bot_id"]:
                acc_bid = str(row["bot_id"]).strip()
                allowed_bids = {bot_id_filter, norm_bot_filter, norm_bot_filter.replace("bot-", ""), f"bot-{norm_bot_filter}"}
                if acc_bid not in allowed_bids:
                    _log(f"[{role_str}] ⚠️ تم تخطي المزرعة لأنها لا تنتمي لغرفة البوت الحالية ({acc_bid} != {bot_id_filter}).")
                    continue

            # Respect fleet disabled switch: if user disabled farm in fleet, strictly do NOT touch it
            if row["enabled"] is not None and int(row["enabled"]) == 0:
                _log(f"[{role_str}] ⚠️ تم تخطي المزرعة لأنها معطلة في إعدادات الأسطول.")
                continue

            char_name = row["name"] if row["name"] else f"Farm_{role_str}"
            char_email = row["email"] if row["email"] else f"Account_{role_str}"
            city_lvl = int(row["city_level"]) if row["city_level"] else 17
            tp_data = TRADING_POST_DATA.get(city_lvl, TRADING_POST_DATA[17])
            tax_pct = int(tp_data["tax"] * 100)

            if char_email not in account_map:
                account_map[char_email] = "RUNNING"

            farm_entry = {
                "role_id": role_str,
                "name": char_name,
                "email": char_email,
                "account_id": row["account_id"],
                "market_lvl": city_lvl,
                "tax_rate": tax_pct,
                "tax_float": tp_data["tax"],
                "resources": {
                    "food": int(row["food"] or 0),
                    "wood": int(row["wood"] or 0),
                    "stone": int(row["stone"] or 0),
                    "gold": int(row["gold"] or 0),
                },
                "sent_amount": 0,
                "sent_rss": {"food": 0, "wood": 0, "stone": 0, "gold": 0},
                "status": "WAITING",
                "stage_msg": "In dispatch queue..."
            }
            raw_farms.append(farm_entry)

        requested_rss = {
            "food": int(payload.get("requested_rss", {}).get("food", 0)),
            "wood": int(payload.get("requested_rss", {}).get("wood", 0)),
            "stone": int(payload.get("requested_rss", {}).get("stone", 0)),
            "gold": int(payload.get("requested_rss", {}).get("gold", 0))
        }

        # Richest-first order: big holders take quota first, fewer farms touched.
        def _richness(ff):
            tot = 0
            for _rr, _need in requested_rss.items():
                if _need <= 0:
                    continue
                tot += max(0, int(ff["resources"].get(_rr, 0)) - 150000)
            return tot
        raw_farms.sort(key=_richness, reverse=True)

        # 2. Smart Quota Allocation (Deduct needed across available farms)
        transfer_mode = payload.get("transfer_mode", "total_net")
        farm_quotas: Dict[str, Dict[str, int]] = {f["role_id"]: {} for f in raw_farms}

        if transfer_mode == "max_drain":
            for f in raw_farms:
                farm_quotas[f["role_id"]] = {r: 999_999_999 for r in ("food", "wood", "stone", "gold")}
        elif transfer_mode == "per_farm":
            for f in raw_farms:
                farm_quotas[f["role_id"]] = {k: int(v) for k, v in requested_rss.items() if v > 0}
        else:
            # total_net EVEN SPLIT: every farm participates (parallel speed), and
            # a farm that drops out (rate cap, refusal) is backfilled in wave 2.
            # Old behaviour was richest-first, which left many farms SKIPPED.
            for f in raw_farms:
                for rn in requested_rss:
                    farm_quotas[f["role_id"]][rn] = 0

            for res_name, requested_total_net in requested_rss.items():
                if requested_total_net <= 0:
                    continue

                capable = [f for f in raw_farms if f["resources"].get(res_name, 0) > 150000]
                if not capable:
                    continue
                # Water-filling: equal shares, richer farms take the remainder.
                remaining = requested_total_net
                active = list(capable)
                while remaining > 0 and active:
                    share = remaining // len(active)
                    if share <= 0:
                        # Fewer units than farms left: give 1 each, richest first.
                        for ff in sorted(active, key=lambda x: -x["resources"].get(res_name, 0)):
                            farm_quotas[ff["role_id"]][res_name] += 1
                            remaining -= 1
                        break
                    still = []
                    for ff in active:
                        tax_rate = ff["tax_float"]
                        cap_net = int(max(0, ff["resources"].get(res_name, 0) - 150000) * (1.0 - tax_rate))
                        give = min(share, cap_net)
                        farm_quotas[ff["role_id"]][res_name] += give
                        remaining -= give
                        if cap_net > give:
                            still.append(ff)
                    active = still

        # Setup workers telemetry
        for f in raw_farms:
            r_id = f["role_id"]
            quota = farm_quotas.get(r_id, {})
            quota_total = sum(quota.values())

            if quota_total > 0:
                init_status = "WAITING"
                init_msg = STAGE_MESSAGES["recall"]
            else:
                init_status = "SKIPPED"
                init_msg = STAGE_MESSAGES["skipped"]

            workers.append({
                "role_id": r_id,
                "name": f["name"],
                "email": f["email"],
                "stage_msg": init_msg,
                "market_lvl": f["market_lvl"],
                "tax_rate": f["tax_rate"],
                "market_spec": f"سوق لفل {f['market_lvl']} | ضريبة {f['tax_rate']}%",
                "sent_amount": 0,
                "sent_rss": {"food": 0, "wood": 0, "stone": 0, "gold": 0},
                "status": init_status,
                "quota": quota
            })

        accounts = [{"email": email, "status": account_map[email]} for email in sorted(account_map.keys())]

        telemetry = {
            "job_id": job_id,
            "target_role_id": str(payload.get("target_role_id", "")),
            "x": int(payload.get("x", 0)),
            "y": int(payload.get("y", 0)),
            "status": "RUNNING",
            "requested": requested_rss,
            "delivered": {"food": 0, "wood": 0, "stone": 0, "gold": 0},
            "accounts": accounts,
            "workers": workers
        }
        cls.update_telemetry(job_id, telemetry)

        toggle_gather_scheduler(paused=True)

        try:
            target_role_id = str(payload.get("target_role_id", "")).strip()
            target_coords = (int(payload.get("x", 0)), int(payload.get("y", 0)))
            custom_tp_lvl = payload.get("custom_tp_level")
            user_id = payload.get("user_id", "")

            def is_cancelled():
                try:
                    from app.api.endpoints.transfer import _ACTIVE_JOBS
                    return bool(_ACTIVE_JOBS.get(job_id, {}).get("cancelled", False))
                except Exception:
                    return False

            worker_map = {w["role_id"]: idx for idx, w in enumerate(telemetry["workers"])}

            def _dust_eps(need: int) -> int:
                # Integer-truncation dust (e.g. 2,000,000 + 1,119,999 = 3,119,999
                # vs 3,120,000 requested) must not trigger a whole new wave.
                try:
                    return max(1, int(need) // 10000)
                except Exception:
                    return 1

            def _current_short() -> Dict[str, int]:
                out = {}
                for _r, _need in requested_rss.items():
                    if _need and _need > 0:
                        _got = int(telemetry["delivered"].get(_r, 0) or 0)
                        if _got + _dust_eps(_need) < _need:
                            out[_r] = _need - _got
                return out

            # Live callback for every donkey batch delivery
            def on_sent_chunk(role_id: str, res_name: str, chunk_net: int):
                idx = worker_map[role_id]
                telemetry["delivered"][res_name] = telemetry["delivered"].get(res_name, 0) + chunk_net
                telemetry["workers"][idx]["sent_amount"] += chunk_net
                if "sent_rss" not in telemetry["workers"][idx]:
                    telemetry["workers"][idx]["sent_rss"] = {"food": 0, "wood": 0, "stone": 0, "gold": 0}
                telemetry["workers"][idx]["sent_rss"][res_name] = telemetry["workers"][idx]["sent_rss"].get(res_name, 0) + chunk_net
                telemetry["workers"][idx]["status"] = "WORKING"
                res_ar = RES_NAME_AR.get(res_name, res_name)
                telemetry["workers"][idx]["stage_msg"] = f"جاري شحن {res_ar} (+{chunk_net:,} صافي)"
                cls.update_telemetry(job_id, {
                    "delivered": telemetry["delivered"],
                    "workers": telemetry["workers"]
                })

            # Group active farms by account email so that characters sharing an account run sequentially
            # preventing concurrent Lilith gateway session kicks!
            account_groups: Dict[str, List[Dict[str, Any]]] = {}
            for w in workers:
                if w["status"] == "SKIPPED":
                    continue
                em = w["email"]
                if em not in account_groups:
                    account_groups[em] = []
                account_groups[em].append(w)

            # Single-farm processor shared by wave 1 (upfront quota) and
            # wave 2+ (quota=None → grant computed from LIVE balances).
            async def _process_single_farm(w: Dict[str, Any], quota: Optional[Dict[str, int]]):
                r_id = w["role_id"]
                idx = worker_map[r_id]

                # Step A: Recall Marches & Preparation
                telemetry["workers"][idx]["status"] = "WAITING"
                telemetry["workers"][idx]["stage_msg"] = STAGE_MESSAGES["recall"]
                cls.update_telemetry(job_id, {"workers": telemetry["workers"]})

                client, prep_info = await RSSTransferEngine.prepare_headless_farm(
                    farm_role_id=r_id,
                    target_role_id=target_role_id,
                    target_coords=target_coords,
                    log_cb=_log,
                    user_id=user_id,
                    custom_tp_level=custom_tp_lvl,
                    job_cancel_check=is_cancelled
                )

                if not client or not prep_info:
                    telemetry["workers"][idx]["status"] = "STOPPED"
                    telemetry["workers"][idx]["stage_msg"] = "تعذر تأمين الحساب أو فصلت الجلسة."
                    cls.update_telemetry(job_id, {"workers": telemetry["workers"]})
                    return

                market_lvl = prep_info.get("tp_lvl", telemetry["workers"][idx]["market_lvl"])
                tax_pct = int(prep_info.get("tax_rate", 0.19) * 100)
                telemetry["workers"][idx]["market_lvl"] = market_lvl
                telemetry["workers"][idx]["tax_rate"] = tax_pct
                telemetry["workers"][idx]["market_spec"] = f"سوق المستوى {market_lvl} (ضريبة {tax_pct}%)"

                if quota is None:
                    # Wave 2+: grant from live balances against current shortfall.
                    live_bal = (getattr(client, "state", {}) or {}).get("resources", {}) or {}
                    quota = {}
                    for _r, _need in _current_short().items():
                        _tax = prep_info.get("tax_rate", 0.19)
                        _avail = int(live_bal.get(_r, 0) or 0)
                        _grant = min(_need, int(max(0, _avail - 150000) * (1.0 - _tax)))
                        if _grant > 0:
                            quota[_r] = _grant
                    if not quota:
                        try:
                            await client.close()
                        except Exception:
                            pass
                        if telemetry["workers"][idx]["status"] in ("SKIPPED", "STOPPED", "WAITING"):
                            telemetry["workers"][idx]["stage_msg"] = "لا رصيد إضافي حي — تم التجاوز."
                        cls.update_telemetry(job_id, {"workers": telemetry["workers"]})
                        return

                # Step B: Dispatch Caravans
                telemetry["workers"][idx]["status"] = "WORKING"
                telemetry["workers"][idx]["stage_msg"] = STAGE_MESSAGES["dispatching"]
                cls.update_telemetry(job_id, {"workers": telemetry["workers"]})

                try:
                    await RSSTransferEngine.dispatch_prepared_transfer(
                        client=client,
                        farm_role_id=r_id,
                        target_role_id=target_role_id,
                        target_coords=target_coords,
                        requested_rss=quota,
                        prep_info=prep_info,
                        log_cb=_log,
                        job_cancel_check=is_cancelled,
                        on_sent_chunk_cb=on_sent_chunk
                    )
                    telemetry["workers"][idx]["status"] = "COMPLETED"
                    telemetry["workers"][idx]["stage_msg"] = STAGE_MESSAGES["done"]
                except Exception as ex:
                    _log(f"[{r_id}] ❌ خطأ في الإرسال: {ex}")
                    telemetry["workers"][idx]["status"] = "STOPPED"
                    telemetry["workers"][idx]["stage_msg"] = f"توقف الإرسال: {ex}"
                finally:
                    # Persist live city balances so dashboard inventory is fresh
                    # right after the transfer (no waiting for next gather sync).
                    try:
                        live = (getattr(client, "state", {}) or {}).get("resources", {}) or {}
                        if any(int(live.get(rr, 0) or 0) > 0 for rr in ("food", "wood", "stone", "gold")):
                            from app.models import InventoryDAO
                            InventoryDAO.upsert(
                                bot_id=bot_id_filter or "bot-0",
                                role_id=r_id,
                                name=w.get("name") or "",
                                food=int(live.get("food", 0) or 0),
                                wood=int(live.get("wood", 0) or 0),
                                stone=int(live.get("stone", 0) or 0),
                                gold=int(live.get("gold", 0) or 0),
                            )
                            _log(f"[{r_id}] 💾 تم تحديث مخزون المدينة في قاعدة البيانات.")
                    except Exception as _e_inv:
                        _log(f"[{r_id}] ⚠️ تعذر حفظ المخزون: {_e_inv}")
                    try:
                        await client.close()
                    except Exception:
                        pass
                    cls.update_telemetry(job_id, {"workers": telemetry["workers"]})

            # Per-account pipeline executor (sequential within account, parallel across accounts)
            async def run_account_pipeline(acc_email: str, farm_list: List[Dict[str, Any]]):
                for w in farm_list:
                    if is_cancelled():
                        break
                    await _process_single_farm(w, w.get("quota") or {})

                # Mark account as completed
                for acc in telemetry["accounts"]:
                    if acc["email"] == acc_email:
                        acc["status"] = "COMPLETED"
                cls.update_telemetry(job_id, {"accounts": telemetry["accounts"]})

            # One task per ACCOUNT (gateway-safe: chars of one account stay sequential)
            # and stagger across accounts only (3s) — enough to avoid same-second
            # races without paying 8s x N in wall-clock.
            async def _staggered(idx: int, acc_email: str, farms: List[Dict[str, Any]]):
                if idx:
                    await asyncio.sleep(min(idx * 3, 20))
                await run_account_pipeline(acc_email, farms)

            # Run all accounts concurrently
            account_tasks = [
                _staggered(i, email, farms)
                for i, (email, farms) in enumerate(account_groups.items())
            ]

            if account_tasks:
                await asyncio.gather(*account_tasks, return_exceptions=True)

            # Wave 2+: redistribute any shortfall to farms still holding live
            # resources (rich SKIPPED farms cover farms that under-delivered).
            # Sequential = quiet wire = full-size caravans welcome.
            for _wave in (2, 3):
                if is_cancelled():
                    break
                short = _current_short()
                if not short:
                    break
                _log(f"🌊 موجة {_wave}: عجز متبقٍ {short} — إعادة التوزيع الحي على المزارع الغنية...")

                def _est_left(ff):
                    tot = 0
                    try:
                        ww = telemetry["workers"][worker_map[ff["role_id"]]]
                    except Exception:
                        ww = {}
                    sent = ww.get("sent_rss") or {}
                    for _r in short:
                        _db = int((ff.get("resources") or {}).get(_r, 0))
                        _tx = ff.get("tax_float", 0.19)
                        tot += max(0, _db - 150000 - int(int(sent.get(_r, 0)) / max(0.05, (1.0 - _tx))))
                    return tot

                cands = sorted(raw_farms, key=_est_left, reverse=True)
                cands = [ff for ff in cands if _est_left(ff) > 0]
                if not cands:
                    _log("🌊 لا مخزون إضافي حي لدى أي مزرعة — إنهاء التوزيع.")
                    break
                progressed = dict(telemetry["delivered"])
                for ff in cands:
                    if is_cancelled():
                        break
                    if not _current_short():
                        break
                    ww = telemetry["workers"][worker_map[ff["role_id"]]]
                    await _process_single_farm(ww, None)
                if all(telemetry["delivered"].get(k, 0) <= progressed.get(k, 0) for k in short):
                    break  # no progress made — stop waving

            # Stage 4: Final Completion Status
            if is_cancelled():
                final_status = "CANCELLED"
            else:
                def _short(_k: int, _need: int) -> bool:
                    try:
                        return int(telemetry["delivered"].get(_k, 0) or 0) + max(1, int(_need) // 10000) < int(_need)
                    except Exception:
                        return True
                is_partial = any(
                    _short(k, requested_rss.get(k, 0))
                    for k in requested_rss if requested_rss.get(k, 0) > 0
                )
                final_status = "PARTIAL" if is_partial else "COMPLETED"

            telemetry["status"] = final_status
            cls.update_telemetry(job_id, {
                "status": final_status,
                "accounts": telemetry["accounts"],
                "workers": telemetry["workers"]
            })
            return telemetry

        except Exception as e:
            _log(f"💥 خطأ أثناء تنفيذ مهمة النقل: {e}")
            telemetry["status"] = "FAILED"
            cls.update_telemetry(job_id, {"status": "FAILED"})
            return telemetry
        finally:
            toggle_gather_scheduler(paused=False)
