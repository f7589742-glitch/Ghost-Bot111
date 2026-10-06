"""
Account management — load, save, persist, and manage accounts.

Handles the full account lifecycle: creation, token management,
fingerprint assignment, and profile persistence.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import AccountConfig, PROFILES_DIR

logger = logging.getLogger("rokbot.account")


class AccountManager:
    """
    Manages account profiles on disk and in memory.

    Supports loading from existing profile JSON files, creating new
    accounts, and batch operations for large-scale deployments.
    """

    def __init__(self):
        PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        self._accounts: Dict[str, AccountConfig] = {}

    def load_all(self) -> List[AccountConfig]:
        """Load all accounts from the profiles directory."""
        accounts = []
        for path in PROFILES_DIR.glob("*.json"):
            try:
                account = self._load_profile(path)
                if account:
                    accounts.append(account)
                    self._accounts[account.profile_name] = account
            except Exception as e:
                logger.warning(f"Failed to load {path.name}: {e}")
        logger.info(f"Loaded {len(accounts)} accounts")
        return accounts

    def load(self, name: str) -> Optional[AccountConfig]:
        if name in self._accounts:
            return self._accounts[name]
        path = PROFILES_DIR / f"{name}.json"
        if path.exists():
            account = self._load_profile(path)
            if account:
                self._accounts[name] = account
            return account
        return None

    def _load_profile(self, path: Path) -> Optional[AccountConfig]:
        data = json.loads(path.read_text(encoding="utf-8"))
        return AccountConfig(
            profile_name=data.get("profile_name", path.stem),
            email=data.get("email", data.get("lilith_account", "")),
            password=data.get("password", ""),
            app_uid=str(data.get("app_uid", "")),
            player_id=str(data.get("player_id", data.get("app_uid", ""))),
            access_token=data.get("access_token", ""),
            app_token=data.get("app_token", ""),
            app_token_expire_at=data.get("app_token_expire_at", 0),
            region=data.get("region", ""),
            server_host=data.get("server_host", ""),
            server_port=int(data.get("server_port", 3101)),
            proxy_host=data.get("proxy_host", ""),
            proxy_port=int(data.get("proxy_port", 0)),
            proxy_user=data.get("proxy_user", ""),
            proxy_pass=data.get("proxy_pass", ""),
            proxy_type=data.get("proxy_type", "socks5"),
            device_udid=data.get("device_udid", ""),
            kingdom_id=int(data.get("kingdom_id", 0) or 0),
            fingerprint=data.get("fingerprint", {}),
        )

    def save(self, account: AccountConfig):
        data = {
            "profile_name": account.profile_name,
            "email": account.email,
            "password": account.password,
            "app_uid": account.app_uid,
            "player_id": account.player_id,
            "access_token": account.access_token,
            "app_token": account.app_token,
            "app_token_expire_at": account.app_token_expire_at,
            "region": account.region,
            "server_host": account.server_host,
            "server_port": account.server_port,
            "proxy_host": account.proxy_host,
            "proxy_port": account.proxy_port,
            "proxy_user": account.proxy_user,
            "proxy_pass": account.proxy_pass,
            "proxy_type": account.proxy_type,
            "device_udid": account.device_udid,
            "kingdom_id": account.kingdom_id,
            "fingerprint": account.fingerprint,
            "updated_at": time.time(),
        }
        path = PROFILES_DIR / f"{account.profile_name}.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        self._accounts[account.profile_name] = account

    def create(
        self,
        name: str,
        email: str = "",
        password: str = "",
        app_uid: str = "",
        access_token: str = "",
        **kwargs,
    ) -> AccountConfig:
        account = AccountConfig(
            profile_name=name,
            email=email,
            password=password,
            app_uid=app_uid,
            player_id=kwargs.get("player_id", app_uid),
            access_token=access_token,
            app_token=kwargs.get("app_token", access_token),
            region=kwargs.get("region", ""),
            server_host=kwargs.get("server_host", ""),
            server_port=int(kwargs.get("server_port", 3101)),
        )
        self.save(account)
        return account

    def delete(self, name: str) -> bool:
        path = PROFILES_DIR / f"{name}.json"
        if path.exists():
            path.unlink()
            self._accounts.pop(name, None)
            return True
        return False

    def list_all(self) -> List[Dict[str, Any]]:
        results = []
        for path in sorted(PROFILES_DIR.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                results.append({
                    "name": data.get("profile_name", path.stem),
                    "app_uid": data.get("app_uid", ""),
                    "has_token": bool(data.get("access_token") or data.get("app_token")),
                    "region": data.get("region", ""),
                })
            except Exception:
                results.append({"name": path.stem, "error": "corrupt"})
        return results

    def import_from_json(self, path: str):
        """Bulk import accounts from a JSON array file."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        count = 0
        for entry in data:
            name = entry.get("profile_name") or entry.get("name") or f"imported_{count}"
            self.create(name=name, **entry)
            count += 1
        logger.info(f"Imported {count} accounts from {path}")

    def assign_proxy(self, name: str, host: str, port: int, user: str = "", pwd: str = "", ptype: str = "socks5"):
        account = self.load(name)
        if account:
            account.proxy_host = host
            account.proxy_port = port
            account.proxy_user = user
            account.proxy_pass = pwd
            account.proxy_type = ptype
            self.save(account)

    @property
    def count(self) -> int:
        return len(list(PROFILES_DIR.glob("*.json")))
