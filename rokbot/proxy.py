"""
ProxyManager — Per-account SOCKS5/HTTP proxy isolation.

Every account socket is routed through a unique static residential proxy
to defeat IP-based rate-limiting and behavior correlation.

Supports:
  - SOCKS5 proxies (preferred, for TCP game connections)
  - HTTP CONNECT proxies (fallback)
  - Direct connection (no proxy)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("rokbot.proxy")

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class ProxyConfig:
    host: str
    port: int
    proxy_type: str = "socks5"
    username: str = ""
    password: str = ""
    assigned_account: str = ""

    @property
    def url(self) -> str:
        auth = ""
        if self.username:
            auth = f"{self.username}:{self.password}@"
        return f"{self.proxy_type}://{auth}{self.host}:{self.port}"

    @property
    def is_available(self) -> bool:
        return not self.assigned_account

    def to_aiohttp_proxy(self) -> Optional[str]:
        """Return proxy URL suitable for aiohttp."""
        if not self.host:
            return None
        auth = ""
        if self.username:
            from urllib.parse import quote
            auth = f"{quote(self.username, safe='')}:{quote(self.password, safe='')}@"
        return f"{self.proxy_type}://{auth}{self.host}:{self.port}"

    def to_socket_params(self) -> dict:
        """Return kwargs for asyncio.open_connection via SOCKS proxy."""
        if not self.host or self.proxy_type not in ("socks5", "socks4"):
            return {}
        return {
            "sock_host": self.host,
            "sock_port": self.port,
            "sock_login": self.username or None,
            "sock_pass": self.password or None,
        }


class ProxyManager:
    """
    Manages a pool of proxies mapped to accounts.

    Each account gets exactly one proxy for the lifetime of its session.
    When a session ends, the proxy is released back to the pool.
    """

    PROXIES_FILE = PROJECT_ROOT / "proxies.json"

    def __init__(self):
        self._proxies: List[ProxyConfig] = []
        self._assignments: Dict[str, ProxyConfig] = {}
        self._load()

    def _load(self):
        if self.PROXIES_FILE.exists():
            try:
                data = json.loads(self.PROXIES_FILE.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    for entry in data:
                        self._proxies.append(ProxyConfig(
                            host=entry.get("host", ""),
                            port=int(entry.get("port", 0)),
                            proxy_type=entry.get("type", "socks5"),
                            username=entry.get("username", ""),
                            password=entry.get("password", ""),
                        ))
                logger.info(f"Loaded {len(self._proxies)} proxies")
            except Exception as e:
                logger.error(f"Failed to load proxies: {e}")

    def save(self):
        data = [
            {
                "host": p.host,
                "port": p.port,
                "type": p.proxy_type,
                "username": p.username,
                "password": p.password,
            }
            for p in self._proxies
        ]
        self.PROXIES_FILE.write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )

    def add_proxy(self, proxy: ProxyConfig):
        self._proxies.append(proxy)
        self.save()

    def add_proxies_from_file(self, path: str, fmt: str = "host:port:user:pass"):
        """
        Bulk import proxies from a text file.

        Formats:
          - "host:port:user:pass" (one per line)
          - "host:port" (no auth)
          - "socks5://user:pass@host:port" (URL format)
        """
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "://" in line:
                    proxy = self._parse_url(line)
                else:
                    parts = line.split(":")
                    if len(parts) >= 4:
                        proxy = ProxyConfig(
                            host=parts[0], port=int(parts[1]),
                            username=parts[2], password=parts[3],
                        )
                    elif len(parts) >= 2:
                        proxy = ProxyConfig(host=parts[0], port=int(parts[1]))
                    else:
                        continue
                self._proxies.append(proxy)
        self.save()
        logger.info(f"Imported proxies, total: {len(self._proxies)}")

    def _parse_url(self, url: str) -> ProxyConfig:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return ProxyConfig(
            host=parsed.hostname or "",
            port=parsed.port or 0,
            proxy_type=parsed.scheme or "socks5",
            username=parsed.username or "",
            password=parsed.password or "",
        )

    def assign(self, account_id: str) -> Optional[ProxyConfig]:
        """Assign an available proxy to an account."""
        for proxy in self._proxies:
            if proxy.is_available:
                proxy.assigned_account = account_id
                self._assignments[account_id] = proxy
                return proxy
        return None

    def release(self, account_id: str):
        """Release a proxy back to the pool."""
        if account_id in self._assignments:
            proxy = self._assignments.pop(account_id)
            proxy.assigned_account = ""

    def get_assignment(self, account_id: str) -> Optional[ProxyConfig]:
        return self._assignments.get(account_id)

    def get_direct(self) -> Optional[ProxyConfig]:
        """Return a DirectConnection sentinel (no proxy)."""
        return None

    @property
    def pool_size(self) -> int:
        return len(self._proxies)

    @property
    def available_count(self) -> int:
        return sum(1 for p in self._proxies if p.is_available)

    @property
    def assigned_count(self) -> int:
        return len(self._assignments)

    def stats(self) -> dict:
        return {
            "total": self.pool_size,
            "available": self.available_count,
            "assigned": self.assigned_count,
        }
