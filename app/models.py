import datetime
import json
import sqlite3
from typing import Optional, List, Dict, Any
from app.database import get_db_connection


def make_json_serializable(obj: Any) -> Any:
    """Recursively converts bytes, sets, and non-serializable objects into JSON-safe representations."""
    if isinstance(obj, (bytes, bytearray)):
        try:
            return obj.decode("utf-8")
        except Exception:
            return obj.hex()
    elif isinstance(obj, set):
        return [make_json_serializable(item) for item in sorted(list(obj), key=lambda x: str(x))]
    elif isinstance(obj, dict):
        return {
            (k.decode("utf-8", "ignore") if isinstance(k, (bytes, bytearray)) else str(k)): make_json_serializable(v)
            for k, v in obj.items()
        }
    elif isinstance(obj, (list, tuple)):
        return [make_json_serializable(item) for item in obj]
    elif isinstance(obj, (int, float, bool, str)) or obj is None:
        return obj
    return str(obj)


def safe_json_dumps(obj: Any, ensure_ascii: bool = False) -> str:
    """Bulletproof json.dumps that never throws TypeError on bytes or custom types."""
    try:
        sanitized = make_json_serializable(obj)
        return json.dumps(sanitized, ensure_ascii=ensure_ascii, default=str)
    except Exception:
        try:
            return json.dumps(str(obj), ensure_ascii=ensure_ascii)
        except Exception:
            return "{}"


class AccountDAO:
    @staticmethod
    def get_by_email(email: str, user_id: str) -> Optional[Dict[str, Any]]:
        con = get_db_connection()
        row = con.execute(
            "SELECT * FROM accounts WHERE LOWER(email) = LOWER(?) AND user_id = ?",
            (email.strip(), user_id),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        if d.get("device_profile") and isinstance(d["device_profile"], str):
            try:
                d["device_profile"] = json.loads(d["device_profile"])
            except Exception:
                pass
        return d

    @staticmethod
    def get_by_id(account_id: int, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        con = get_db_connection()
        if user_id is not None:
            row = con.execute(
                "SELECT * FROM accounts WHERE id = ? AND user_id = ?", (account_id, user_id)
            ).fetchone()
        else:
            row = con.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        if d.get("device_profile") and isinstance(d["device_profile"], str):
            try:
                d["device_profile"] = json.loads(d["device_profile"])
            except Exception:
                pass
        return d

    @staticmethod
    def update_device_profile(email: str, user_id: str, device_profile: Dict[str, Any]) -> None:
        """Persists a (possibly backfilled) device profile for an account."""
        con = get_db_connection()
        with con:
            con.execute(
                "UPDATE accounts SET device_profile = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE LOWER(email) = LOWER(?) AND user_id = ?",
                (json.dumps(device_profile, ensure_ascii=False), email.strip(), user_id),
            )

    @staticmethod
    def get_all_user_ids() -> List[str]:
        con = get_db_connection()
        rows = con.execute(
            "SELECT DISTINCT user_id FROM accounts WHERE user_id <> ''"
        ).fetchall()
        return [r[0] for r in rows]

    @staticmethod
    def get_all(user_id: Optional[str] = None, bot_id: Optional[str] = None) -> List[Dict[str, Any]]:
        con = get_db_connection()
        conds = []
        params: list = []
        if bot_id:
            bid = str(bot_id).strip()
            bids = {bid}
            if bid.startswith("bot-"):
                bids.add(bid[4:])
            elif bid.isdigit():
                bids.add(f"bot-{bid}")
            try:
                from app.api.routes import _normalize_bot_id, _BOT_ID_CACHE
                resolved = _normalize_bot_id(bid)
                if resolved:
                    bids.add(resolved)
                    if resolved.startswith("bot-"):
                        bids.add(resolved[4:])
                for k, v in _BOT_ID_CACHE.items():
                    if v in bids or k in bids:
                        bids.add(k)
                        bids.add(v)
            except Exception:
                pass
            bids_list = [b for b in bids if b]
            placeholders = ",".join("?" for _ in bids_list)
            if user_id:
                conds.append(f"bot_id IN ({placeholders}) AND user_id = ?")
                params.extend(bids_list)
                params.append(user_id)
            else:
                conds.append(f"bot_id IN ({placeholders})")
                params.extend(bids_list)
        elif user_id:
            conds.append("user_id = ?")
            params.append(user_id)
        where = f"WHERE {' AND '.join(conds)}" if conds else ""
        rows = con.execute(
            f"SELECT id, email, udid, app_uid, token_expires_at, device_profile, is_active, last_run, next_run, created_at, updated_at, bot_id, user_id FROM accounts {where} ORDER BY id ASC",
            tuple(params),
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            if d.get("device_profile") and isinstance(d["device_profile"], str):
                try:
                    d["device_profile"] = json.loads(d["device_profile"])
                except Exception:
                    pass
            results.append(d)
        return results

    @staticmethod
    def set_active(account_id: int, user_id: str, is_active: bool) -> None:
        con = get_db_connection()
        with con:
            con.execute("UPDATE accounts SET is_active = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?", (1 if is_active else 0, account_id, user_id))

    @staticmethod
    def update_last_run(account_id: int, last_run: Optional[str] = None) -> None:
        con = get_db_connection()
        with con:
            con.execute("UPDATE accounts SET last_run = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (last_run or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), account_id,))

    @staticmethod
    def update_run_times(account_id: int, last_run: Optional[str] = None, next_run: Optional[str] = None) -> None:
        con = get_db_connection()
        fields = []
        vals = []
        if last_run is not None:
            fields.append("last_run = ?")
            vals.append(last_run)
        if next_run is not None:
            fields.append("next_run = ?")
            vals.append(next_run)
        if not fields:
            return
        fields.append("updated_at = CURRENT_TIMESTAMP")
        vals.append(account_id)
        sql = f"UPDATE accounts SET {', '.join(fields)} WHERE id = ?"
        with con:
            con.execute(sql, tuple(vals))

    @staticmethod
    def upsert(
        email: str,
        user_id: str,
        encrypted_password: str,
        udid: str,
        app_uid: Optional[str],
        app_token: Optional[str],
        token_expires_at: Optional[int],
        device_profile: Optional[Dict[str, Any]] = None,
        bot_id: Optional[str] = None
    ) -> Dict[str, Any]:
        if not user_id:
            raise PermissionError("user_id is required to bind an account to a tenant")
        con = get_db_connection()
        norm_bot_id = None
        if bot_id:
            try:
                from app.api.routes import _normalize_bot_id
                norm_bot_id = _normalize_bot_id(bot_id) or bot_id
            except Exception:
                norm_bot_id = bot_id

        dev_json = json.dumps(device_profile, ensure_ascii=False) if device_profile else None
        with con:
            existing = con.execute("SELECT id, user_id, device_profile, bot_id FROM accounts WHERE LOWER(email) = LOWER(?)", (email.strip(),)).fetchone()
            if existing:
                # Re-assign ownership to the newly authenticated user_id and target bot_id
                # when the user explicitly links/authenticates the game account
                final_dev = dev_json or existing["device_profile"]
                final_bot_id = norm_bot_id if norm_bot_id is not None else existing["bot_id"]
                con.execute("""
                    UPDATE accounts 
                    SET user_id = ?, encrypted_password = ?, udid = ?, app_uid = ?, app_token = ?, token_expires_at = ?, device_profile = ?, bot_id = ?, is_active = 1, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (user_id, encrypted_password, udid, app_uid, app_token, token_expires_at, final_dev, final_bot_id, existing["id"]))
                account_id = existing["id"]
            else:
                cur = con.execute("""
                    INSERT INTO accounts (email, user_id, encrypted_password, udid, app_uid, app_token, token_expires_at, device_profile, bot_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (email.strip(), user_id, encrypted_password, udid, app_uid, app_token, token_expires_at, dev_json, norm_bot_id or bot_id))
                account_id = cur.lastrowid
        res = AccountDAO.get_by_id(account_id, user_id)
        if res and res.get("device_profile") and isinstance(res["device_profile"], str):
            try:
                res["device_profile"] = json.loads(res["device_profile"])
            except Exception:
                pass
        return res

    @staticmethod
    def delete(identifier: Any, user_id: Optional[str] = None) -> bool:
        """Permanently deletes an account and all its characters, settings, logs, and inventories
        identified by integer account ID OR email string, with optional user_id scoping."""
        con = get_db_connection()
        with con:
            acc = None
            ident_str = str(identifier or "").strip()
            if not ident_str:
                return False

            if ident_str.isdigit():
                if user_id:
                    row = con.execute("SELECT id, email, user_id FROM accounts WHERE id = ? AND user_id = ?", (int(ident_str), user_id)).fetchone()
                else:
                    row = con.execute("SELECT id, email, user_id FROM accounts WHERE id = ?", (int(ident_str),)).fetchone()
                if row:
                    acc = dict(row)

            if not acc:
                if user_id:
                    row = con.execute("SELECT id, email, user_id FROM accounts WHERE LOWER(email) = LOWER(?) AND user_id = ?", (ident_str, user_id)).fetchone()
                else:
                    row = con.execute("SELECT id, email, user_id FROM accounts WHERE LOWER(email) = LOWER(?)", (ident_str,)).fetchone()
                if row:
                    acc = dict(row)

            if not acc:
                return False

            acc_id = acc["id"]
            chars = con.execute("SELECT id, role_id FROM characters WHERE account_id = ?", (acc_id,)).fetchall()
            role_ids = [str(c["role_id"]) for c in chars if c["role_id"]]
            for c in chars:
                try:
                    con.execute("DELETE FROM character_settings WHERE character_id = ?", (c["id"],))
                except Exception:
                    pass
                try:
                    con.execute("DELETE FROM character_inventories WHERE role_id = ?", (str(c["role_id"]),))
                except Exception:
                    pass
                try:
                    con.execute("DELETE FROM task_logs WHERE character_id = ? OR role_id = ?", (c["id"], str(c["role_id"])))
                except Exception:
                    pass
            # Orphan cleanup: run history, node locks, per-march rows.
            if role_ids:
                try:
                    q = ",".join("?" for _ in role_ids)
                    con.execute(f"DELETE FROM bot_run_characters WHERE role_id IN ({q})", tuple(role_ids))
                except Exception:
                    pass
                try:
                    q = ",".join("?" for _ in role_ids)
                    con.execute(f"DELETE FROM claimed_resource_nodes WHERE role_id IN ({q})", tuple(role_ids))
                except Exception:
                    pass
            try:
                if acc.get("user_id"):
                    con.execute("DELETE FROM bot_run_records WHERE LOWER(account_email) = LOWER(?) AND user_id = ?", (acc["email"], acc["user_id"]))
                else:
                    con.execute("DELETE FROM bot_run_records WHERE LOWER(account_email) = LOWER(?)", (acc["email"],))
            except Exception:
                pass
            con.execute("DELETE FROM characters WHERE account_id = ?", (acc_id,))
            con.execute("DELETE FROM accounts WHERE id = ?", (acc_id,))
        return True


class CharacterDAO:
    @staticmethod
    def _owner_join() -> str:
        return "JOIN accounts a ON c.account_id = a.id"

    @staticmethod
    def owns_character(user_id: str, role_id: str) -> Optional[Dict[str, Any]]:
        """Returns the character only if it belongs to the tenant's account."""
        con = get_db_connection()
        row = con.execute(
            "SELECT c.* FROM characters c JOIN accounts a ON c.account_id = a.id "
            "WHERE c.role_id = ? AND a.user_id = ?",
            (str(role_id), user_id),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def get_by_role_id(role_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if user_id:
            res = CharacterDAO.owns_character(user_id, role_id)
            if res:
                return res
        con = get_db_connection()
        row = con.execute("SELECT * FROM characters WHERE role_id = ?", (str(role_id),)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def get_by_account_id(account_id: int) -> List[Dict[str, Any]]:
        con = get_db_connection()
        rows = con.execute("SELECT * FROM characters WHERE account_id = ? ORDER BY power DESC", (account_id,)).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def get_all(kingdom_id: Optional[int] = None, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        con = get_db_connection()
        conds = []
        params: list = []
        if user_id is not None:
            conds.append("a.user_id = ?")
            params.append(user_id)
        if kingdom_id is not None:
            conds.append("c.kingdom_id = ?")
            params.append(kingdom_id)
        where = f"WHERE {' AND '.join(conds)}" if conds else ""
        rows = con.execute(f"""
                SELECT c.*, a.email as account_email 
                FROM characters c 
                JOIN accounts a ON c.account_id = a.id 
                {where}
                ORDER BY c.power DESC
            """, tuple(params)).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def upsert(
        account_id: int,
        role_id: str,
        name: str,
        kingdom_id: int,
        power: int,
        city_level: int,
        avatar_url: Optional[str] = None,
        alliance_tag: Optional[str] = None,
        is_active_cloud: bool = False
    ) -> Dict[str, Any]:
        con = get_db_connection()
        with con:
            existing = con.execute("SELECT id FROM characters WHERE role_id = ?", (str(role_id),)).fetchone()
            if existing:
                con.execute("""
                    UPDATE characters
                    SET account_id = ?, name = ?, kingdom_id = ?, power = ?, city_level = ?, avatar_url = ?, alliance_tag = ?, is_active_cloud = ?, last_synced = CURRENT_TIMESTAMP
                    WHERE role_id = ?
                """, (account_id, name, kingdom_id, power, city_level, avatar_url, alliance_tag, int(is_active_cloud), str(role_id)))
            else:
                con.execute("""
                    INSERT INTO characters (account_id, role_id, name, kingdom_id, power, city_level, avatar_url, alliance_tag, is_active_cloud)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (account_id, str(role_id), name, kingdom_id, power, city_level, avatar_url, alliance_tag, int(is_active_cloud)))
        return CharacterDAO.get_by_role_id(role_id)

    @staticmethod
    def set_active_cloud(account_id: int, role_id: str) -> None:
        """Marks role_id as the gateway-bound character; clears siblings."""
        con = get_db_connection()
        with con:
            con.execute(
                "UPDATE characters SET is_active_cloud = 0 WHERE account_id = ?",
                (account_id,),
            )
            con.execute(
                "UPDATE characters SET is_active_cloud = 1, last_synced = CURRENT_TIMESTAMP "
                "WHERE account_id = ? AND role_id = ?",
                (account_id, str(role_id)),
            )

    @staticmethod
    def set_enabled(role_id: str, enabled: bool) -> None:
        con = get_db_connection()
        with con:
            con.execute("UPDATE characters SET enabled = ? WHERE role_id = ?", (1 if enabled else 0, str(role_id)))

    @staticmethod
    def update_run_times(role_id: str, last_run: Optional[str] = None, next_run: Optional[str] = None, next_run_ts: Optional[str] = None) -> None:
        con = get_db_connection()
        nr = next_run or next_run_ts
        with con:
            if last_run and nr:
                con.execute("UPDATE characters SET last_run = ?, next_run = ? WHERE role_id = ?", (last_run, nr, str(role_id)))
            elif last_run:
                con.execute("UPDATE characters SET last_run = ? WHERE role_id = ?", (last_run, str(role_id)))
            elif nr:
                con.execute("UPDATE characters SET last_run = CURRENT_TIMESTAMP, next_run = ? WHERE role_id = ?", (nr, str(role_id)))
            else:
                con.execute("UPDATE characters SET last_run = CURRENT_TIMESTAMP WHERE role_id = ?", (str(role_id),))

    @staticmethod
    def delete(role_id: str, user_id: Optional[str] = None) -> bool:
        con = get_db_connection()
        with con:
            if user_id is not None and not CharacterDAO.owns_character(user_id, role_id):
                return False
            char = con.execute("SELECT id FROM characters WHERE role_id = ?", (str(role_id),)).fetchone()
            if char:
                con.execute("DELETE FROM character_settings WHERE character_id = ?", (char["id"],))
                con.execute("DELETE FROM task_logs WHERE character_id = ? OR role_id = ?", (char["id"], str(role_id)))
                try:
                    con.execute("DELETE FROM character_inventories WHERE role_id = ?", (str(role_id),))
                except Exception:
                    pass
                try:
                    con.execute("DELETE FROM claimed_resource_nodes WHERE role_id = ?", (str(role_id),))
                except Exception:
                    pass
                try:
                    con.execute("DELETE FROM bot_run_characters WHERE role_id = ?", (str(role_id),))
                except Exception:
                    pass
                con.execute("DELETE FROM characters WHERE id = ?", (char["id"],))
        return True


class TaskLogDAO:
    @staticmethod
    def create(task_id: str, role_id: Optional[str], task_type: str, status: str, details: Optional[Dict[str, Any]] = None, character_id: Optional[int] = None) -> int:
        con = get_db_connection()
        det_str = safe_json_dumps(details, ensure_ascii=False) if details else "{}"
        with con:
            cur = con.execute("""
                INSERT INTO task_logs (task_id, character_id, role_id, task_type, status, details)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (task_id, character_id, str(role_id) if role_id else None, task_type, status, det_str))
            return cur.lastrowid

    @staticmethod
    def update_status(task_id: str, status: str, details: Optional[Dict[str, Any]] = None):
        con = get_db_connection()
        det_str = safe_json_dumps(details, ensure_ascii=False) if details else None
        with con:
            if det_str is not None:
                con.execute("UPDATE task_logs SET status = ?, details = ? WHERE task_id = ?", (status, det_str, task_id))
            else:
                con.execute("UPDATE task_logs SET status = ? WHERE task_id = ?", (status, task_id))

    @staticmethod
    def get_by_task_id(task_id: str) -> Optional[Dict[str, Any]]:
        con = get_db_connection()
        row = con.execute("SELECT * FROM task_logs WHERE task_id = ? ORDER BY id DESC LIMIT 1", (task_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["details"] = json.loads(d["details"])
        except Exception:
            d["details"] = {}
        return d

    @staticmethod
    def get_recent(limit: int = 50, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        con = get_db_connection()
        if user_id is not None:
            rows = con.execute("""
                SELECT t.* FROM task_logs t
                LEFT JOIN characters c ON c.role_id = t.role_id
                LEFT JOIN accounts a ON a.id = c.account_id
                WHERE a.user_id = ? OR t.role_id IS NULL
                ORDER BY t.id DESC LIMIT ?
            """, (user_id, limit)).fetchall()
        else:
            rows = con.execute("SELECT * FROM task_logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["details"] = json.loads(d["details"])
            except Exception:
                d["details"] = {}
            result.append(d)
        return result


class MarchNodeDAO:
    """Cross-run node ledger: never send two marches to the same node id.

    Keyed by (node_id, kingdom_id, tenant) so farms of one tenant never
    collide, tenants never see each other, and kingdoms can't alias.
    Rows older than the reuse window are treated as free (march returned).
    """
    REUSE_HOURS_DEFAULT = 12.0

    @staticmethod
    def is_claimed(node_id: int, kingdom_id: int = 0, tenant: str = "",
                   reuse_hours: float = REUSE_HOURS_DEFAULT) -> bool:
        con = get_db_connection()
        row = con.execute(
            "SELECT dispatched_at FROM march_nodes WHERE node_id = ? AND kingdom_id = ? AND tenant = ?",
            (int(node_id), int(kingdom_id or 0), tenant or "")).fetchone()
        if not row:
            return False
        try:
            import datetime as _dt
            ts = _dt.datetime.strptime(str(row["dispatched_at"])[:19], "%Y-%m-%d %H:%M:%S")
            age_h = (_dt.datetime.now() - ts).total_seconds() / 3600.0
            return age_h < float(reuse_hours)
        except Exception:
            return True

    @staticmethod
    def claim(node_id: int, role_id: str = "", kingdom_id: int = 0, tenant: str = "",
              details: Optional[Dict[str, Any]] = None) -> None:
        import datetime as _dt
        con = get_db_connection()
        with con:
            con.execute("""
                INSERT INTO march_nodes (node_id, role_id, kingdom_id, tenant, dispatched_at, details)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(node_id, kingdom_id, tenant) DO UPDATE SET
                    role_id = excluded.role_id,
                    dispatched_at = excluded.dispatched_at,
                    details = excluded.details
            """, (int(node_id), str(role_id or ""), int(kingdom_id or 0), tenant or "",
                  _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                  json.dumps(details or {}, ensure_ascii=False)))
            try:
                cutoff = (_dt.datetime.now() - _dt.timedelta(hours=48)).strftime("%Y-%m-%d %H:%M:%S")
                con.execute("DELETE FROM march_nodes WHERE dispatched_at < ?", (cutoff,))
            except Exception:
                pass


class NodeReservationDAO:
    """Live node locks in claimed_resource_nodes: at most one role holds a node.

    claim_node() is atomic-ish (SELECT + UPSERT under one connection lock):
    returns True when THIS role holds the lock afterwards, False when another
    role holds an unexpired lock. Accepts both duration_minutes and ttl_seconds.
    """

    @staticmethod
    def _ensure_table(con) -> None:
        con.execute("""
            CREATE TABLE IF NOT EXISTS claimed_resource_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id INTEGER NOT NULL,
                kingdom_id INTEGER NOT NULL,
                role_id TEXT NOT NULL,
                character_name TEXT,
                resource_type TEXT,
                node_level INTEGER,
                pos_x REAL,
                pos_y REAL,
                claimed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                UNIQUE(kingdom_id, node_id)
            )
        """)

    @staticmethod
    def claim_node(node_id: int, role_id: str = "", kingdom_id: int = 0,
                   character_name: str = "", resource_type: str = "unknown",
                   node_level: int = 1, pos_x: float = 0.0, pos_y: float = 0.0,
                   duration_minutes: int = 10, ttl_seconds: Optional[int] = None) -> bool:
        import datetime as _dt
        ttl = int(ttl_seconds) if ttl_seconds else int(duration_minutes or 10) * 60
        now = _dt.datetime.now()
        exp = (now + _dt.timedelta(seconds=max(60, ttl))).strftime("%Y-%m-%d %H:%M:%S")
        now_s = now.strftime("%Y-%m-%d %H:%M:%S")
        con = get_db_connection()
        with con:
            NodeReservationDAO._ensure_table(con)
            row = con.execute(
                "SELECT role_id, expires_at FROM claimed_resource_nodes "
                "WHERE node_id = ? AND kingdom_id = ?",
                (int(node_id), int(kingdom_id or 0))).fetchone()
            if row and str(row["expires_at"]) > now_s and str(row["role_id"]) != str(role_id or ""):
                return False
            con.execute("""
                INSERT INTO claimed_resource_nodes
                    (node_id, kingdom_id, role_id, character_name, resource_type,
                     node_level, pos_x, pos_y, claimed_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(kingdom_id, node_id) DO UPDATE SET
                    role_id = excluded.role_id,
                    character_name = excluded.character_name,
                    resource_type = excluded.resource_type,
                    node_level = excluded.node_level,
                    pos_x = excluded.pos_x,
                    pos_y = excluded.pos_y,
                    claimed_at = excluded.claimed_at,
                    expires_at = excluded.expires_at
            """, (int(node_id), int(kingdom_id or 0), str(role_id or ""),
                  character_name or "", resource_type or "unknown", int(node_level or 1),
                  float(pos_x or 0.0), float(pos_y or 0.0), now_s, exp))
            try:
                con.execute("DELETE FROM claimed_resource_nodes WHERE expires_at <= ?", (now_s,))
            except Exception:
                pass
        return True

    @staticmethod
    def get_claimed_nodes(kingdom_id: int = 0) -> Dict[int, Dict[str, Any]]:
        import datetime as _dt
        now_s = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        con = get_db_connection()
        try:
            NodeReservationDAO._ensure_table(con)
            if kingdom_id and int(kingdom_id) > 0:
                rows = con.execute(
                    "SELECT node_id, role_id, character_name, resource_type, node_level "
                    "FROM claimed_resource_nodes WHERE kingdom_id = ? AND expires_at > ?",
                    (int(kingdom_id), now_s)).fetchall()
            else:
                rows = con.execute(
                    "SELECT node_id, role_id, character_name, resource_type, node_level "
                    "FROM claimed_resource_nodes WHERE expires_at > ?",
                    (now_s,)).fetchall()
            return {int(r["node_id"]): {
                "role_id": r["role_id"],
                "character_name": r["character_name"],
                "resource_type": r["resource_type"],
                "node_level": r["node_level"],
            } for r in rows}
        except Exception:
            return {}

    @staticmethod
    def release_node(node_id: int, kingdom_id: int = 0, role_id: Optional[str] = None) -> None:
        con = get_db_connection()
        with con:
            try:
                if role_id is not None:
                    con.execute("DELETE FROM claimed_resource_nodes "
                                "WHERE node_id = ? AND kingdom_id = ? AND role_id = ?",
                                (int(node_id), int(kingdom_id or 0), str(role_id)))
                else:
                    con.execute("DELETE FROM claimed_resource_nodes "
                                "WHERE node_id = ? AND kingdom_id = ?",
                                (int(node_id), int(kingdom_id or 0)))
            except Exception:
                pass

    @staticmethod
    def purge_all_reservations(kingdom_id: Optional[int] = None) -> int:
        con = get_db_connection()
        with con:
            NodeReservationDAO._ensure_table(con)
            try:
                if kingdom_id is not None:
                    cur = con.execute("DELETE FROM claimed_resource_nodes WHERE kingdom_id = ?", (int(kingdom_id),))
                else:
                    cur = con.execute("DELETE FROM claimed_resource_nodes")
                return cur.rowcount
            except Exception:
                return 0


class CharacterSettingsDAO:
    DEFAULTS = {
        "train_pct": 100,
        "train_count_custom": None,
        "tiers": {},
        "gather": {"node_min_level": 2, "node_max_level": 5, "max_node_level": "No cap", "auto_balance_lowest_rss": True,
                   "priority_types": ["food", "wood", "stone", "gold"]},
        "commanders": [],
        "combat": {"barbs": True, "min_barb_level": 1, "max_barb_level": 7, "highest_barb_level": "L7", "skip_barbs_below": "None", "primary_commander": "Auto", "secondary_commander": "Auto (best available)", "combat_rounds": 10, "dispatch_all_marches": True, "max_combat_marches": 5, "hold_position": False},
        "hospital": {"heal_troops": True, "heal_batch": 0},
        "alliance": {
            "help_alliance_members": True,
            "gather_resource_pit": False,
            "donate_tech": True,
            "claim_gifts": True,
            "claim_territory_rss": True
        },
        "daily_claims": {
            "daily_vip_claim": True,
            "city_harvest": True,
            "chronicle_claim": False,
            "claim_daily_quests": True,
            "claim_daily_quest_chests": True,
            "claim_side_quests": False,
            "auto_scout": True
        },
        "city": {
            "collect_resources": True
        }
    }

    @staticmethod
    def _decode(row) -> Dict[str, Any]:
        d = dict(row)
        for key, json_col in [
            ("tiers", "tiers_json"),
            ("gather", "gather_json"),
            ("combat", "combat_json"),
            ("hospital", "hospital_json"),
            ("alliance", "alliance_json"),
            ("daily_claims", "daily_claims_json"),
            ("city", "city_json"),
        ]:
            try:
                d[key] = json.loads(d.get(json_col) or "{}")
            except Exception:
                d[key] = {}
        try:
            cmds = json.loads(d.get("commanders_json") or "[]")
            if isinstance(cmds, list):
                if cmds and isinstance(cmds[0], dict):
                    d["commanders"] = [int(x.get("hero_id")) for x in cmds if x.get("hero_id")]
                    d["commanders_meta"] = cmds
                else:
                    d["commanders"] = [int(x) for x in cmds]
                    d["commanders_meta"] = [{"hero_id": int(x), "level": 1, "star": 1} for x in cmds]
            else:
                d["commanders"] = []
                d["commanders_meta"] = []
        except Exception:
            d["commanders"] = []
            d["commanders_meta"] = []
        return d

    @staticmethod
    def get_by_character_id(character_id: int) -> Dict[str, Any]:
        con = get_db_connection()
        row = con.execute("SELECT * FROM character_settings WHERE character_id = ?",
                          (character_id,)).fetchone()
        if not row:
            return {k: (dict(v) if isinstance(v, dict) else (list(v) if isinstance(v, list) else v)) for k, v in CharacterSettingsDAO.DEFAULTS.items()}
        d = CharacterSettingsDAO._decode(row)
        merged = {k: (dict(v) if isinstance(v, dict) else (list(v) if isinstance(v, list) else v)) for k, v in CharacterSettingsDAO.DEFAULTS.items()}
        merged.update({k: v for k, v in d.items()
                       if k in ("train_pct", "train_count_custom") and v is not None})
        if d.get("tiers"):
            merged["tiers"] = d["tiers"]
        if d.get("commanders"):
            merged["commanders"] = d["commanders"]
        if d.get("commanders_meta"):
            merged["commanders_meta"] = d["commanders_meta"]
        for section in ("gather", "combat", "hospital", "alliance", "daily_claims", "city"):
            if d.get(section):
                s_merged = dict(CharacterSettingsDAO.DEFAULTS.get(section, {}))
                s_merged.update(d[section])
                merged[section] = s_merged
        return merged

    @staticmethod
    def upsert(character_id: int, train_pct: Optional[int] = None,
               train_count_custom: Optional[int] = None,
               tiers: Optional[Dict[str, Any]] = None,
               gather: Optional[Dict[str, Any]] = None,
               commanders: Optional[List[int]] = None,
               combat: Optional[Dict[str, Any]] = None,
               hospital: Optional[Dict[str, Any]] = None,
               alliance: Optional[Dict[str, Any]] = None,
               daily_claims: Optional[Dict[str, Any]] = None,
               city: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        con = get_db_connection()
        cur = CharacterSettingsDAO.get_by_character_id(character_id)
        if train_pct is not None:
            cur["train_pct"] = max(1, min(100, int(train_pct)))
        if train_count_custom is not None:
            cur["train_count_custom"] = int(train_count_custom) if int(train_count_custom) > 0 else None
        if tiers:
            t = dict(cur.get("tiers") or {})
            t.update({k: v for k, v in tiers.items()})
            cur["tiers"] = t
        if gather:
            g = dict(cur.get("gather") or {})
            g.update(gather)
            cur["gather"] = g
        if combat:
            cb = dict(cur.get("combat") or {})
            cb.update(combat)
            cur["combat"] = cb
        if hospital:
            h = dict(cur.get("hospital") or {})
            h.update(hospital)
            cur["hospital"] = h
        if alliance:
            al = dict(cur.get("alliance") or {})
            al.update(alliance)
            cur["alliance"] = al
        if daily_claims:
            dc = dict(cur.get("daily_claims") or {})
            dc.update(daily_claims)
            cur["daily_claims"] = dc
        if city:
            ct = dict(cur.get("city") or {})
            ct.update(city)
            cur["city"] = ct
        if commanders is not None:
            if commanders and isinstance(commanders[0], dict):
                cur["commanders_meta"] = commanders
                cur["commanders"] = [int(x.get("hero_id")) for x in commanders if x.get("hero_id")]
            else:
                cur["commanders"] = [int(x) for x in commanders]

        # Always preserve rich commanders_meta when available
        if cur.get("commanders_meta") and isinstance(cur["commanders_meta"], list) and cur["commanders_meta"] and isinstance(cur["commanders_meta"][0], dict):
            cmds_payload = cur["commanders_meta"]
        else:
            cmds_payload = cur.get("commanders") or []

        with con:
            con.execute("""
                INSERT INTO character_settings (
                    character_id, train_pct, train_count_custom, tiers_json, gather_json, commanders_json,
                    combat_json, hospital_json, alliance_json, daily_claims_json, city_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(character_id) DO UPDATE SET
                    train_pct = excluded.train_pct,
                    train_count_custom = excluded.train_count_custom,
                    tiers_json = excluded.tiers_json,
                    gather_json = excluded.gather_json,
                    commanders_json = excluded.commanders_json,
                    combat_json = excluded.combat_json,
                    hospital_json = excluded.hospital_json,
                    alliance_json = excluded.alliance_json,
                    daily_claims_json = excluded.daily_claims_json,
                    city_json = excluded.city_json,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                character_id, cur["train_pct"], cur.get("train_count_custom"),
                json.dumps(cur.get("tiers") or {}, ensure_ascii=False),
                json.dumps(cur.get("gather") or {}, ensure_ascii=False),
                json.dumps(cmds_payload, ensure_ascii=False),
                json.dumps(cur.get("combat") or {}, ensure_ascii=False),
                json.dumps(cur.get("hospital") or {}, ensure_ascii=False),
                json.dumps(cur.get("alliance") or {}, ensure_ascii=False),
                json.dumps(cur.get("daily_claims") or {}, ensure_ascii=False),
                json.dumps(cur.get("city") or {}, ensure_ascii=False),
            ))
        return CharacterSettingsDAO.get_by_character_id(character_id)

    @staticmethod
    def clear_custom_count(character_id: int) -> Dict[str, Any]:
        con = get_db_connection()
        with con:
            con.execute("UPDATE character_settings SET train_count_custom = NULL, "
                        "updated_at = CURRENT_TIMESTAMP WHERE character_id = ?", (character_id,))
        return CharacterSettingsDAO.get_by_character_id(character_id)


class BotSettingsDAO:
    @staticmethod
    def _key(key: str, user_id: Optional[str]) -> str:
        # Per-tenant namespaced settings: one tenant's toggles/intervals
        # must never leak into another tenant's execution.
        return f"{user_id}:{key}" if user_id else key

    @staticmethod
    def get(key: str, default: str = "", user_id: Optional[str] = None) -> str:
        con = get_db_connection()
        row = con.execute("SELECT value FROM bot_settings WHERE key = ?", (BotSettingsDAO._key(key, user_id),)).fetchone()
        return str(row["value"]) if row else default

    @staticmethod
    def set(key: str, value: str, user_id: Optional[str] = None) -> None:
        con = get_db_connection()
        with con:
            con.execute("""
                INSERT INTO bot_settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
            """, (BotSettingsDAO._key(key, user_id), str(value)))

    @staticmethod
    def get_all(user_id: Optional[str] = None) -> Dict[str, str]:
        con = get_db_connection()
        rows = con.execute("SELECT key, value FROM bot_settings").fetchall()
        res = {
            "run_interval_hours": "4",
            "bot_running": "true",
            "discord_notifications": "false",
            "apply_changes_to": "all"
        }
        prefix = f"{user_id}:" if user_id else None
        for r in rows:
            k = str(r["key"])
            if prefix:
                if k.startswith(prefix):
                    res[k[len(prefix):]] = str(r["value"])
            else:
                res[k] = str(r["value"])
        return res

    @staticmethod
    def is_bot_running(bot_id: Optional[str] = None, user_id: Optional[str] = None) -> bool:
        bid = str(bot_id).strip() if bot_id else ""
        uid = str(user_id).strip() if user_id else ""
        con = get_db_connection()

        if uid:
            # When user_id is provided, strictly isolate by user_id and bot_id (never leak other tenants or global)
            if bid:
                bot_keys = [
                    f"{uid}:bot_running_{bid}",
                    f"{uid}:bot_running_{bid.replace('bot-', '')}",
                    f"{uid}:bot_running",
                ]
                for k in bot_keys:
                    row = con.execute("SELECT value FROM bot_settings WHERE key = ?", (k,)).fetchone()
                    if row:
                        val = str(row["value"]).strip().lower()
                        return val in ("true", "1", "yes", "running", "on")
                return False
            else:
                row = con.execute("SELECT value FROM bot_settings WHERE key = ?", (f"{uid}:bot_running",)).fetchone()
                if row:
                    val = str(row["value"]).strip().lower()
                    return val in ("true", "1", "yes", "running", "on")
                return False

        # Fallback only when user_id is NOT provided (CLI / legacy single-tenant)
        if bid:
            bot_keys = [
                f"bot_running_{bid}",
                f"bot_running_{bid.replace('bot-', '')}",
                f"{bid}:bot_running",
            ]
            for k in bot_keys:
                row = con.execute("SELECT value FROM bot_settings WHERE key = ?", (k,)).fetchone()
                if row:
                    val = str(row["value"]).strip().lower()
                    return val in ("true", "1", "yes", "running", "on")

        row = con.execute("SELECT value FROM bot_settings WHERE key = 'bot_running'").fetchone()
        if row:
            val = str(row["value"]).strip().lower()
            return val in ("true", "1", "yes", "running", "on")

        return False


class InventoryDAO:
    """Real-time per-character resource inventory (INVENTORY tab).

    Upserted from live Opcode 121 (liquid resources) and Opcode 1002 (profile);
    strictly scoped by bot_id so one dashboard unit never sees another unit's characters.
    """

    @staticmethod
    def _normalize_bot_id(bot_id: str, role_id: str = "", name: str = "") -> str:
        bid = str(bot_id or "").strip()
        if not bid:
            return "bot-0"
        if bid.isdigit():
            return f"bot-{bid}"
        return bid

    @staticmethod
    def upsert(bot_id: str, role_id: str, name: str = "", kingdom_id: int = 0,
               city_hall_level: int = 0, power: int = 0, food: int = 0,
               wood: int = 0, stone: int = 0, gold: int = 0, gems: int = 0) -> None:
        if not role_id:
            return
        con = get_db_connection()
        norm_bot_id = InventoryDAO._normalize_bot_id(bot_id, role_id=str(role_id), name=name)
        with con:
            con.execute("""
                INSERT INTO character_inventories
                    (bot_id, role_id, name, kingdom_id, city_hall_level, power, food, wood, stone, gold, gems, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(bot_id, role_id) DO UPDATE SET
                    name = CASE WHEN excluded.name != '' THEN excluded.name ELSE character_inventories.name END,
                    kingdom_id = CASE WHEN excluded.kingdom_id > 0 THEN excluded.kingdom_id ELSE character_inventories.kingdom_id END,
                    city_hall_level = CASE WHEN excluded.city_hall_level > 0 THEN excluded.city_hall_level ELSE character_inventories.city_hall_level END,
                    power = CASE WHEN excluded.power > 0 THEN excluded.power ELSE character_inventories.power END,
                    food = CASE WHEN excluded.food > 0 THEN excluded.food ELSE character_inventories.food END,
                    wood = CASE WHEN excluded.wood > 0 THEN excluded.wood ELSE character_inventories.wood END,
                    stone = CASE WHEN excluded.stone > 0 THEN excluded.stone ELSE character_inventories.stone END,
                    gold = CASE WHEN excluded.gold > 0 THEN excluded.gold ELSE character_inventories.gold END,
                    gems = CASE WHEN excluded.gems > 0 THEN excluded.gems ELSE character_inventories.gems END,
                    updated_at = CURRENT_TIMESTAMP
            """, (norm_bot_id, str(role_id), str(name or ""), int(kingdom_id or 0),
                  int(city_hall_level or 0), int(power or 0),
                  int(food or 0), int(wood or 0), int(stone or 0), int(gold or 0), int(gems or 0)))
            # A character lives in exactly one room: drop stale rows left over
            # from previous room assignments so other rooms never show ghosts.
            try:
                con.execute(
                    "DELETE FROM character_inventories WHERE role_id = ? AND bot_id != ?",
                    (str(role_id), norm_bot_id),
                )
            except Exception:
                pass
            con.execute("""
                UPDATE characters SET                    food = CASE WHEN ? > 0 THEN ? ELSE food END,
                    wood = CASE WHEN ? > 0 THEN ? ELSE wood END,
                    stone = CASE WHEN ? > 0 THEN ? ELSE stone END,
                    gold = CASE WHEN ? > 0 THEN ? ELSE gold END,
                    gems = CASE WHEN ? > 0 THEN ? ELSE gems END,
                    power = CASE WHEN ? > 0 THEN ? ELSE power END,
                    city_level = CASE WHEN ? > 0 THEN ? ELSE city_level END,
                    city_hall = CASE WHEN ? > 0 THEN ? ELSE city_hall END,
                    last_run_at = CURRENT_TIMESTAMP
                WHERE role_id = ?
            """, (
                int(food or 0), int(food or 0),
                int(wood or 0), int(wood or 0),
                int(stone or 0), int(stone or 0),
                int(gold or 0), int(gold or 0),
                int(gems or 0), int(gems or 0),
                int(power or 0), int(power or 0),
                int(city_hall_level or 0), int(city_hall_level or 0),
                int(city_hall_level or 0), int(city_hall_level or 0),
                str(role_id)
            ))

    @staticmethod
    def list_for_bot(bot_id: str, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        con = get_db_connection()
        bid = str(bot_id).strip()
        bids = [bid]
        if bid.startswith("bot-"):
            bids.append(bid[4:])
        else:
            bids.append(f"bot-{bid}")
        placeholders = ",".join("?" for _ in bids)
        try:
            uid = str(user_id or "").strip()
            if uid:
                rows = con.execute(
                    f"""SELECT ci.* FROM character_inventories ci
                        JOIN characters c ON c.role_id = ci.role_id
                        JOIN accounts a ON a.id = c.account_id
                        WHERE ci.bot_id IN ({placeholders}) AND a.user_id = ?
                        ORDER BY ci.power DESC""",
                    (*bids, uid)
                ).fetchall()
            else:
                rows = con.execute(
                    f"SELECT * FROM character_inventories WHERE bot_id IN ({placeholders}) ORDER BY power DESC",
                    tuple(bids)
                ).fetchall()
            if rows:
                return [dict(r) for r in rows]
        except Exception:
            pass
        return []


class RunHistoryDAO:
    """Fleet-sweep run records for the HISTORY tab + run summary modal."""

    @staticmethod
    def record_run(run_id: str, bot_id: str, account_email: str, started_at: str,
                   duration_minutes: int, characters_visited: str,
                   food_gathered: int, wood_gathered: int, stone_gathered: int, gold_gathered: int,
                   summary_json: str, character_details: list = None, user_id: str = "") -> None:
        RunHistoryDAO.create_run(run_id, bot_id, account_email, user_id=user_id)
        RunHistoryDAO.finish_run(run_id, duration_minutes, characters_visited,
                                food_gathered, wood_gathered, stone_gathered, gold_gathered, summary_json)
        if character_details:
            for c in character_details:
                RunHistoryDAO.add_run_character(
                    run_id=run_id,
                    role_id=c.get("role_id", ""),
                    name=c.get("name", ""),
                    kingdom_id=c.get("kingdom_id", 0),
                    city_hall_level=c.get("city_hall_level", 0),
                    power=c.get("power", 0),
                    visit_duration_seconds=c.get("visit_duration_seconds", 0),
                    food=c.get("food_gathered", 0),
                    wood=c.get("wood_gathered", 0),
                    stone=c.get("stone_gathered", 0),
                    gold=c.get("gold_gathered", 0),
                    details_json=safe_json_dumps(c) if isinstance(c, dict) else str(c)
                )

    @staticmethod
    def create_run(run_id: str, bot_id: str, account_email: str = "", user_id: str = "") -> None:
        con = get_db_connection()
        with con:
            try:
                con.execute("""
                    INSERT OR IGNORE INTO bot_run_records (run_id, bot_id, user_id, account_email, started_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (str(run_id), str(bot_id or ""), str(user_id or ""), str(account_email or "")))
            except Exception:
                pass

    @staticmethod
    def finish_run(run_id: str, duration_minutes: int, characters_visited: str,
                   food: int, wood: int, stone: int, gold: int, summary_json: str = "{}") -> None:
        con = get_db_connection()
        with con:
            try:
                con.execute("""
                    UPDATE bot_run_records SET
                        duration_minutes = ?, characters_visited = ?,
                        food_gathered = ?, wood_gathered = ?, stone_gathered = ?, gold_gathered = ?,
                        summary_json = ?
                    WHERE run_id = ?
                """, (int(duration_minutes or 0), str(characters_visited or "0 / 0"),
                      int(food or 0), int(wood or 0), int(stone or 0), int(gold or 0),
                      str(summary_json or "{}"), str(run_id)))
            except Exception:
                pass

    @staticmethod
    def add_run_character(run_id: str, role_id: str, name: str = "", kingdom_id: int = 0,
                          city_hall_level: int = 0, power: int = 0,
                          visit_duration_seconds: int = 0, food: int = 0, wood: int = 0,
                          stone: int = 0, gold: int = 0, details_json: str = "{}") -> None:
        con = get_db_connection()
        with con:
            try:
                con.execute("""
                    INSERT INTO bot_run_characters
                        (run_id, role_id, name, kingdom_id, city_hall_level, power,
                         visit_duration_seconds, food_gathered, wood_gathered, stone_gathered,
                         gold_gathered, details_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (str(run_id), str(role_id), str(name or ""), int(kingdom_id or 0),
                      int(city_hall_level or 0), int(power or 0), int(visit_duration_seconds or 0),
                      int(food or 0), int(wood or 0), int(stone or 0), int(gold or 0),
                      str(details_json or "{}")))
            except Exception:
                pass

    @staticmethod
    def list_runs(bot_id: str, limit: int = 30, offset: int = 0, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        con = get_db_connection()
        try:
            bid = str(bot_id).strip()
            uid = str(user_id or "").strip()
            if uid:
                rows = con.execute(
                    "SELECT * FROM bot_run_records WHERE bot_id = ? AND user_id = ? ORDER BY started_at DESC LIMIT ? OFFSET ?",
                    (bid, uid, int(limit), int(offset)),
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT * FROM bot_run_records WHERE bot_id = ? ORDER BY started_at DESC LIMIT ? OFFSET ?",
                    (bid, int(limit), int(offset)),
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    @staticmethod
    def get_run(run_id: str, bot_id: str = "", user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        con = get_db_connection()
        try:
            bid = str(bot_id).strip()
            uid = str(user_id or "").strip()
            if bid and uid:
                row = con.execute("SELECT * FROM bot_run_records WHERE run_id = ? AND bot_id = ? AND user_id = ?", (str(run_id), bid, uid)).fetchone()
            elif bid:
                row = con.execute("SELECT * FROM bot_run_records WHERE run_id = ? AND bot_id = ?", (str(run_id), bid)).fetchone()
            else:
                row = con.execute("SELECT * FROM bot_run_records WHERE run_id = ?", (str(run_id),)).fetchone()
            return dict(row) if row else None
        except Exception:
            return None

    @staticmethod
    def get_run_characters(run_id: str) -> List[Dict[str, Any]]:
        con = get_db_connection()
        try:
            rows = con.execute("SELECT * FROM bot_run_characters WHERE run_id = ? ORDER BY id ASC", (str(run_id),)).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    @staticmethod
    def aggregated_gathered(bot_id: str, days: int = 1, user_id: Optional[str] = None) -> Dict[str, int]:
        con = get_db_connection()
        try:
            cutoff = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            bid = str(bot_id).strip()
            uid = str(user_id or "").strip()
            if uid:
                row = con.execute("""
                    SELECT SUM(food_gathered) as food, SUM(wood_gathered) as wood,
                           SUM(stone_gathered) as stone, SUM(gold_gathered) as gold
                    FROM bot_run_records
                    WHERE bot_id = ? AND user_id = ? AND started_at >= ?
                """, (bid, uid, cutoff)).fetchone()
            else:
                row = con.execute("""
                    SELECT SUM(food_gathered) as food, SUM(wood_gathered) as wood,
                           SUM(stone_gathered) as stone, SUM(gold_gathered) as gold
                    FROM bot_run_records
                    WHERE bot_id = ? AND started_at >= ?
                """, (bid, cutoff)).fetchone()
            if not row:
                return {"food": 0, "wood": 0, "stone": 0, "gold": 0}
            return {
                "food": int(row["food"] or 0),
                "wood": int(row["wood"] or 0),
                "stone": int(row["stone"] or 0),
                "gold": int(row["gold"] or 0),
            }
        except Exception:
            return {"food": 0, "wood": 0, "stone": 0, "gold": 0}

    @staticmethod
    def daily_trend(bot_id: str, days: int = 7, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        con = get_db_connection()
        try:
            cutoff = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            bid = str(bot_id).strip()
            uid = str(user_id or "").strip()
            if uid:
                rows = con.execute("""
                    SELECT DATE(started_at) as day,
                           SUM(food_gathered) as food, SUM(wood_gathered) as wood,
                           SUM(stone_gathered) as stone, SUM(gold_gathered) as gold
                    FROM bot_run_records
                    WHERE bot_id = ? AND user_id = ? AND started_at >= ?
                    GROUP BY DATE(started_at)
                    ORDER BY day ASC
                """, (bid, uid, cutoff)).fetchall()
            else:
                rows = con.execute("""
                    SELECT DATE(started_at) as day,
                           SUM(food_gathered) as food, SUM(wood_gathered) as wood,
                           SUM(stone_gathered) as stone, SUM(gold_gathered) as gold
                    FROM bot_run_records
                    WHERE bot_id = ? AND started_at >= ?
                    GROUP BY DATE(started_at)
                    ORDER BY day ASC
                """, (bid, cutoff)).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

