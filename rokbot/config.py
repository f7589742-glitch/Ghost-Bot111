"""
Global configuration and constants for the RoK headless bot.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROFILES_DIR = PROJECT_ROOT / "profiles"
COMMANDS_DIR = PROJECT_ROOT / "commands"

GAME_SERVERS = {
    "eu": ("43.159.113.101", 3101),
    "eu2": ("43.159.112.101", 3101),
    "asia": ("34.54.22.150", 3101),
}

KEEPALIVE_INTERVAL = 5.0
RECEIVE_BUFFER_SIZE = 65536
RECEIVE_TIMEOUT = 30.0
GREETING_TIMEOUT = 10.0
LOGIN_TIMEOUT = 10.0

DEFAULT_EMAIL_API_HOST = "https://app-pc.lilithgame.com"
DEFAULT_LOGIN_URL = f"{DEFAULT_EMAIL_API_HOST}/v2/api/sdk/login"
CHECK_ACCOUNT_URL = f"{DEFAULT_EMAIL_API_HOST}/v2/api/sdk/lilith_account/check_account"
RSA_KEY_URL = "https://static.farlicdn.com/p/pc-park-login/2.1.0/3723.bbd76af2.async.js"

MAX_CONCURRENT_BOTS = 200
RECONNECT_BACKOFF_BASE = 2.0
RECONNECT_BACKOFF_MAX = 300.0
RECONNECT_JITTER_RANGE = 0.3


@dataclass
class AccountConfig:
    profile_name: str
    email: str = ""
    password: str = ""
    app_uid: str = ""
    player_id: str = ""
    access_token: str = ""
    app_token: str = ""
    app_token_expire_at: int = 0
    region: str = ""
    server_host: str = ""
    server_port: int = 3101

    proxy_host: str = ""
    proxy_port: int = 0
    proxy_user: str = ""
    proxy_pass: str = ""
    proxy_type: str = "socks5"

    # Device UDID (32-hex, e.g. fleet F682A511...): sent as Op 161 f2 and
    # observed as login inner[4] in live captures. Empty = skip 161 f2.
    device_udid: str = ""

    # Kingdom id of the target role (per-role!): Op 110 f2. E.g. AmmAr 11543,
    # ssar3 3105. Wrong value -> S2C Op 1 {110, 246} reject.
    kingdom_id: int = 0

    fingerprint: dict = field(default_factory=dict)

    @property
    def has_proxy(self) -> bool:
        return bool(self.proxy_host and self.proxy_port)

    @property
    def effective_player_id(self) -> str:
        return self.player_id or self.app_uid

    @property
    def effective_token(self) -> str:
        # Game TCP (login Op 14 + second-auth Op 161) uses the BOUND access
        # token — the `b` token in the device's auto_login_users record, which
        # the live client puts in TCP auth.f2 (device-forensics 2026-09-10:
        # A-7O... got AmmAr+15+302 on the real client). The SDK platform
        # token (njRc..., also mirrored by token refresh) is NOT valid on
        # the TCP wire (yields S2C 162 validate_app_device_token_fail).
        # Keep app_token fresh separately — it powers the refresh chain.
        return self.access_token or self.app_token

    def server_addr(self) -> tuple[str, int]:
        if self.server_host:
            return (self.server_host, self.server_port)
        region = self.region.lower() if self.region else "eu"
        host, port = GAME_SERVERS.get(region, GAME_SERVERS["eu"])
        return (host, port)
