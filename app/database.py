import sqlite3
import threading
from app.config import DB_PATH

_local = threading.local()

def get_db_connection() -> sqlite3.Connection:
    """
    Returns a thread-local SQLite connection with dictionary row access.
    """
    if not hasattr(_local, "connection") or _local.connection is None:
        con = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15.0)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA foreign_keys=ON;")
        _local.connection = con
    return _local.connection

def init_db():
    """
    Initializes the database schema for Accounts, Characters, and TaskLogs.
    """
    con = get_db_connection()
    with con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            user_id TEXT NOT NULL DEFAULT '',
            encrypted_password TEXT NOT NULL,
            udid TEXT NOT NULL,
            app_uid TEXT,
            app_token TEXT,
            token_expires_at INTEGER,
            device_profile TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        
        con.execute("""
        CREATE TABLE IF NOT EXISTS characters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            role_id TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            kingdom_id INTEGER NOT NULL,
            power INTEGER DEFAULT 0,
            city_level INTEGER DEFAULT 1,
            avatar_url TEXT,
            alliance_tag TEXT,
            is_active_cloud BOOLEAN DEFAULT 0,
            last_synced TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
        );
        """)

        con.execute("""
        CREATE TABLE IF NOT EXISTS task_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            character_id INTEGER,
            role_id TEXT,
            task_type TEXT NOT NULL,
            status TEXT NOT NULL,
            details TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        con.execute("""
        CREATE TABLE IF NOT EXISTS character_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            character_id INTEGER UNIQUE NOT NULL,
            train_pct INTEGER DEFAULT 100,
            train_count_custom INTEGER,
            tiers_json TEXT DEFAULT '{}',
            gather_json TEXT DEFAULT '{}',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
        );
        """)

        con.execute("""
        CREATE TABLE IF NOT EXISTS bot_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        con.execute("""
        CREATE TABLE IF NOT EXISTS march_nodes (
            node_id INTEGER NOT NULL,
            role_id TEXT DEFAULT '',
            kingdom_id INTEGER DEFAULT 0,
            tenant TEXT DEFAULT '',
            dispatched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            details TEXT DEFAULT '{}',
            PRIMARY KEY (node_id, kingdom_id, tenant)
        );
        """)

        # Real-time per-character inventory snapshot (INVENTORY tab).
        # One row per bot_id+role_id — upserted on every Opcode 1002 sync.
        con.execute("""
        CREATE TABLE IF NOT EXISTS character_inventories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id TEXT NOT NULL DEFAULT '',
            role_id TEXT NOT NULL,
            name TEXT DEFAULT '',
            kingdom_id INTEGER DEFAULT 0,
            city_hall_level INTEGER DEFAULT 0,
            power INTEGER DEFAULT 0,
            food INTEGER DEFAULT 0,
            wood INTEGER DEFAULT 0,
            stone INTEGER DEFAULT 0,
            gold INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (bot_id, role_id)
        );
        """)

        # Session run records (HISTORY tab): one row per fleet sweep per bot.
        con.execute("""
        CREATE TABLE IF NOT EXISTS bot_run_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT UNIQUE NOT NULL,
            bot_id TEXT NOT NULL DEFAULT '',
            user_id TEXT NOT NULL DEFAULT '',
            account_email TEXT DEFAULT '',
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            duration_minutes INTEGER DEFAULT 0,
            characters_visited TEXT DEFAULT '0 / 0',
            food_gathered INTEGER DEFAULT 0,
            wood_gathered INTEGER DEFAULT 0,
            stone_gathered INTEGER DEFAULT 0,
            gold_gathered INTEGER DEFAULT 0,
            summary_json TEXT DEFAULT '{}'
        );
        """)

        # Per-character breakdown inside a run (Farm run summary modal).
        con.execute("""
        CREATE TABLE IF NOT EXISTS bot_run_characters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            role_id TEXT NOT NULL,
            name TEXT DEFAULT '',
            kingdom_id INTEGER DEFAULT 0,
            city_hall_level INTEGER DEFAULT 0,
            power INTEGER DEFAULT 0,
            visit_duration_seconds INTEGER DEFAULT 0,
            food_gathered INTEGER DEFAULT 0,
            wood_gathered INTEGER DEFAULT 0,
            stone_gathered INTEGER DEFAULT 0,
            gold_gathered INTEGER DEFAULT 0,
            details_json TEXT DEFAULT '{}'
        );
        """)
        try:
            con.execute("CREATE INDEX IF NOT EXISTS idx_runs_bot_started ON bot_run_records(bot_id, started_at DESC);")
        except Exception:
            pass
        try:
            con.execute("CREATE INDEX IF NOT EXISTS idx_runs_bot_user ON bot_run_records(bot_id, user_id, started_at DESC);")
        except Exception:
            pass
        try:
            con.execute("CREATE INDEX IF NOT EXISTS idx_run_chars_run ON bot_run_characters(run_id);")
        except Exception:
            pass


        # Migrations for existing databases
        try:
            con.execute("ALTER TABLE bot_run_records ADD COLUMN user_id TEXT NOT NULL DEFAULT '';")
        except Exception:
            pass
        try:
            con.execute("ALTER TABLE accounts ADD COLUMN user_id TEXT NOT NULL DEFAULT '';")
        except Exception:
            pass
        try:
            con.execute("ALTER TABLE accounts ADD COLUMN is_active BOOLEAN DEFAULT 1;")
        except Exception:
            pass
        try:
            con.execute("ALTER TABLE accounts ADD COLUMN last_run TIMESTAMP;")
        except Exception:
            pass

        try:
            con.execute("ALTER TABLE characters ADD COLUMN enabled BOOLEAN DEFAULT 1;")
        except Exception:
            pass
        try:
            con.execute("ALTER TABLE characters ADD COLUMN last_run TIMESTAMP;")
        except Exception:
            pass
        try:
            con.execute("ALTER TABLE characters ADD COLUMN next_run TIMESTAMP;")
        except Exception:
            pass
        try:
            con.execute("ALTER TABLE character_settings ADD COLUMN commanders_json TEXT DEFAULT '[]';")
        except Exception:
            pass
        try:
            con.execute("ALTER TABLE character_settings ADD COLUMN combat_json TEXT DEFAULT '{}';")
        except Exception:
            pass
        try:
            con.execute("ALTER TABLE character_settings ADD COLUMN hospital_json TEXT DEFAULT '{}';")
        except Exception:
            pass
        try:
            con.execute("ALTER TABLE character_settings ADD COLUMN alliance_json TEXT DEFAULT '{}';")
        except Exception:
            pass
        try:
            con.execute("ALTER TABLE character_settings ADD COLUMN daily_claims_json TEXT DEFAULT '{}';")
        except Exception:
            pass
        try:
            con.execute("ALTER TABLE character_settings ADD COLUMN city_json TEXT DEFAULT '{}';")
        except Exception:
            pass
