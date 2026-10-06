"""
Authentication — async email login with fingerprint-spoofed headers.

Flow (reversed from limpc.dll + park-login webview JS):
  1. RSA-PKCS#1-v1.5 encrypt email with public key from login webview
  2. POST /v2/api/sdk/lilith_account/check_account (optional)
  3. POST /v2/api/sdk/login with player_id=email + pass + auth_type:0
  4. Extract access_token + app_token from response

Each request carries unique per-account fingerprint headers to prevent
structural fingerprint correlation.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

import aiohttp

from .config import (
    CHECK_ACCOUNT_URL,
    DEFAULT_LOGIN_URL,
    RSA_KEY_URL,
)
from .fingerprint import FingerprintGenerator

logger = logging.getLogger("rokbot.auth")

LILITH_DEFAULTS = {
    "app_id": "2104267",
    "app_version": "1.1.9.19",
    "channel_id": "self-lilith-1",
    "device_abi": "x86-64",
    "device_brand": "ASUSTeK-B660M-DS3H DDR4",
    "device_model": "win",
    "device_name": "DESKTOP-U0L0GKB",
    "env_id": "prod95fa8d9f035da4e7f4ca8317b3e5",
    "game_id": "10043",
    "idfa": "v26698f7b2-24d7-41a3-a76f-cd74260794f8",
    "install_id": "D8A25671-E7B3-4c30-8F0D-D9A47D7059A3-1783452778",
    "lang": "en",
    "lilith_language": "en",
    "os_type": "win",
    "os_version": "10.0.26200",
    "pack_name": "com.lilithgames.rok.pc.int",
    "pc_channel": "legoulauncher",
    "real_package_name": "com.lilithgames.rok.pc.int",
    "sdk_session_id": "406C2861DEE2F53B7A25BF3ECC001423",
    "sdk_version": "1.0.8.0",
    "source": "1",
    "type": "7",
}

LILITH_HEADERS = {
    "Accept": "*/*",
    "Content-Type": "application/x-www-form-urlencoded",
    "Im-Session-Id": LILITH_DEFAULTS["sdk_session_id"],
    "User-Agent": "limpc-1.0.8.0",
}

_RSA_KEY_CACHE: Optional[list] = None
_RSA_KEY_CACHE_TIME: float = 0
_RSA_KEY_CACHE_TTL: float = 3600


def _load_rsa_keys_sync() -> list:
    import requests as _requests
    global _RSA_KEY_CACHE, _RSA_KEY_CACHE_TIME
    now = time.time()
    if _RSA_KEY_CACHE and (now - _RSA_KEY_CACHE_TIME) < _RSA_KEY_CACHE_TTL:
        return _RSA_KEY_CACHE
    try:
        js = _requests.get(RSA_KEY_URL, timeout=25).text
        pems = re.findall(
            r"-----BEGIN [A-Z ]*PUBLIC KEY-----.*?-----END [A-Z ]*PUBLIC KEY-----",
            js, re.S,
        )
        _RSA_KEY_CACHE = pems
        _RSA_KEY_CACHE_TIME = now
        return pems
    except Exception as e:
        logger.error(f"Failed to load RSA keys: {e}")
        return []


def encrypt_email_sync(email: str) -> str:
    """RSA-PKCS#1-v1.5 encrypt email (synchronous, for initial key load)."""
    try:
        from Crypto.PublicKey import RSA
        from Crypto.Cipher import PKCS1_v1_5
    except ImportError:
        from Cryptodome.PublicKey import RSA
        from Cryptodome.Cipher import PKCS1_v1_5
    pems = _load_rsa_keys_sync()
    if len(pems) < 2:
        raise RuntimeError("RSA keys not available")
    key = RSA.import_key(pems[1])
    cipher = PKCS1_v1_5.new(key)
    enc = cipher.encrypt(email.encode("utf-8"))
    return base64.b64encode(enc).decode("ascii")


class AuthManager:
    """
    Async authentication manager with per-account fingerprint spoofing.

    Each login request carries unique device headers matching the
    account's persisted fingerprint, preventing cascade bans.
    """

    def __init__(self, fingerprint_gen: Optional[FingerprintGenerator] = None):
        self.fingerprint_gen = fingerprint_gen or FingerprintGenerator()
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _solve_captcha(self, captcha_url: str, account_id: str) -> Optional[Dict[str, str]]:
        """Solve Geetest captcha via headless browser + template matching."""
        def _solve_sync():
            try:
                import sys as _sys
                _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
                from geetest_solver import solve
                result = solve(debug=False, captcha_url=captcha_url)
                if result.get("solved"):
                    return result.get("tokens", {})
                logger.warning(f"[{account_id}] Captcha not solved: {result}")
                return None
            except Exception as e:
                logger.error(f"[{account_id}] Captcha solver error: {e}")
                return None
        return await asyncio.to_thread(_solve_sync)

    async def email_login(
        self,
        email: str,
        password: str,
        account_id: str,
        captcha_ticket: str = "",
        captcha_randstr: str = "",
    ) -> Dict[str, Any]:
        """
        Perform email+password login with fingerprint-spoofed headers.

        Returns dict with: access_token, app_token, app_uid, region, etc.
        Raises RuntimeError on failure.
        """
        session = await self._get_session()
        fp = self.fingerprint_gen.get_fingerprint(account_id)
        overrides = self.fingerprint_gen.get_login_overrides(account_id)

        headers = dict(LILITH_HEADERS)
        headers["Im-Session-Id"] = fp.sdk_session_id
        headers["User-Agent"] = fp.user_agent

        enc_blob = await asyncio.to_thread(encrypt_email_sync, email)

        body = dict(LILITH_DEFAULTS)
        body.update(overrides)
        body["type"] = "0"

        logger.info(f"[{account_id}] check_account ...")
        async with session.post(
            CHECK_ACCOUNT_URL, data={**body, "account": enc_blob}, headers=headers
        ) as resp:
            check_result = await resp.json()

        if check_result.get("result", {}).get("code") != 0:
            logger.warning(f"[{account_id}] check_account: {check_result.get('result')}")

        # Password login uses type=0 (NOT type=1): auth_type=0, type=0,
        # source=1, player_id=<plaintext email>, pass=<password>.
        # Proven 2026-07-20 (MASTER §12.30/12.31, farm12213): server answers
        # 11027 need_captcha -> solve Geetest -> retry with ticket -> tokens.
        # (type=1 yields 11025 validate_fail; the old comment claiming
        # type=0 expects app_token was wrong.)
        # Password encoding lock: MD5(password + "PassHandler").
        # Raw passwords yield 11025 validate_fail (proven live).
        from .lilith_authenticator import build_password_login_body, hash_password
        login_body = build_password_login_body(
            email, hash_password(password), overrides,
            captcha_ticket, captcha_randstr,
        )

        logger.info(f"[{account_id}] login ...")
        async with session.post(DEFAULT_LOGIN_URL, data=login_body, headers=headers) as resp:
            login_resp = await resp.json()

        result = login_resp.get("result", {})
        data = login_resp.get("data", {})

        if result.get("code") == 11027:
            logger.warning(f"[{account_id}] need_captcha — auto-solving ...")
            captcha_url = data.get("captcha_url", "")
            tokens = await self._solve_captcha(captcha_url, account_id)
            if tokens:
                login_body["captcha_ticket"] = tokens.get("pass_token") or tokens.get("lot_number", "")
                login_body["captcha_randstr"] = tokens.get("lot_number") or tokens.get("captcha_id", "")
                logger.info(f"[{account_id}] retrying login with captcha tokens ...")
                async with session.post(
                    DEFAULT_LOGIN_URL, data=login_body, headers=headers
                ) as resp:
                    login_resp = await resp.json()
                result = login_resp.get("result", {})
                data = login_resp.get("data", {})
            else:
                raise RuntimeError("captcha_solve_failed")

        if result.get("code") != 0 and not data.get("app_token"):
            raise RuntimeError(
                f"Login failed (code {result.get('code')}): {result.get('msg', 'unknown')}"
            )

        # Strict validation: app_token is the real authentication token.
        # access_token is a DUMMY field — the game TCP server does not validate it.
        # See: auth_pipeline.py line 57-58 for reference.
        app_token = data.get("app_token", "")
        if not app_token:
            raise RuntimeError(
                f"Login failed: No app_token in response. "
                f"Server returned: code={result.get('code')}, data={list(data.keys())}"
            )

        app_uid = str(data.get("app_uid") or data.get("uid", ""))
        if not app_uid or app_uid == "0":
            raise RuntimeError(
                f"Login failed: Invalid app_uid='{app_uid}'. "
                f"This may indicate a fake account or server mitigation."
            )

        # access_token is NULL by design — use app_token for TCP auth
        access_token = data.get("access_token") or app_token

        logger.info(f"[{account_id}] login OK uid={app_uid}")

        return {
            "email": email,
            "app_uid": app_uid,
            "app_token": app_token,
            "access_token": access_token,
            "app_token_expire_at": data.get("app_token_expire_at", 0),
            "region": data.get("region", ""),
        }

    async def refresh_token(
        self,
        app_token: str,
        app_uid: str,
        account_id: str,
    ) -> Dict[str, Any]:
        """
        Refresh an existing app_token (self-renewing via pass=app_token).
        """
        session = await self._get_session()
        fp = self.fingerprint_gen.get_fingerprint(account_id)
        overrides = self.fingerprint_gen.get_login_overrides(account_id)

        headers = dict(LILITH_HEADERS)
        headers["Im-Session-Id"] = fp.sdk_session_id

        body = dict(LILITH_DEFAULTS)
        body.update(overrides)
        body["type"] = "7"
        body["pass"] = app_token
        body["player_id"] = str(app_uid)

        logger.info(f"[{account_id}] refresh_token uid={app_uid}")
        async with session.post(DEFAULT_LOGIN_URL, data=body, headers=headers) as resp:
            login_resp = await resp.json()

        result = login_resp.get("result", {})
        data = login_resp.get("data", {})

        if result.get("code") != 0:
            raise RuntimeError(f"Token refresh failed: {result}")

        app_token = data.get("app_token", "")
        if not app_token:
            raise RuntimeError(f"Token refresh failed: No app_token in response")

        return {
            "access_token": data.get("access_token") or app_token,
            "app_token": app_token,
            "app_uid": str(data.get("app_uid", app_uid)),
            "app_token_expire_at": data.get("app_token_expire_at", 0),
            "region": data.get("region", ""),
        }
