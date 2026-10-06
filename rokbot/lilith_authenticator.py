"""
Fresh HTTPS Lilith SDK authenticator — password-based token minting.

Generates fresh (app_token, access_token, app_uid) on demand from Lilith
Passport servers, bypassing cached/stale XML tokens entirely.

Protocol facts (verified):
  - Password is NEVER sent plaintext: MD5(password + "PassHandler").
    Raw-password attempts yield 11025 validate_fail.
  - Endpoint flow (MASTER knowledge §12.30/12.31 + live auth reverse):
      1. RSA-PKCS#1-v1.5 encrypt email -> check_account
         (expects code 0 + has_pass:true).
      2. POST /v2/api/sdk/login with auth_type=0, type=0, source=1,
         player_id=<plaintext email>, pass=<md5 hash>.
      3. 11027 need_captcha -> solve Geetest -> retry with ticket/randstr.
      4. code 0 + app_token -> fresh credentials.
  - 11005 register_risk = server-side risk block (spoofed device / attempt
    velocity). Do NOT hammer: single attempt, then back off for hours.

Pipeline injection: rokbot/auth.py AuthManager.email_login delegates the
password hashing + login body to this module (single source of truth).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any, Dict, Optional

import aiohttp

from .auth import (
    LILITH_DEFAULTS,
    LILITH_HEADERS,
    AuthManager,
    CHECK_ACCOUNT_URL,
    DEFAULT_LOGIN_URL,
    encrypt_email_sync,
)

logger = logging.getLogger("rokbot.lilith_authenticator")

#: Salt observed in the Lilith PC login webview JS (pc-park-login bundle).
PASSWORD_SALT = "PassHandler"


def hash_password(password: str, salt: str = PASSWORD_SALT) -> str:
    """MD5(password + salt) lowercase hex — the only accepted pass encoding."""
    return hashlib.md5((password + salt).encode("utf-8")).hexdigest()


def build_password_login_body(
    email: str,
    password_hash: str,
    overrides: Optional[Dict[str, Any]] = None,
    captcha_ticket: str = "",
    captcha_randstr: str = "",
) -> Dict[str, Any]:
    """Assemble the type=0 password-login form body."""
    body = dict(LILITH_DEFAULTS)
    if overrides:
        body.update(overrides)
    body.pop("type", None)
    body.update({
        "auth_type": "0",
        "type": "0",
        "source": "1",
        "player_id": email,
        "pass": password_hash,
        "captcha_ticket": captcha_ticket,
        "captcha_randstr": captcha_randstr,
    })
    return body


class LilithPassportClient:
    """
    Minimal fresh-token minter over HTTPS.

    Usage:
        client = LilithPassportClient(auth_manager)
        fresh = await client.login_fresh(email, password, account_id)
        # fresh -> {"email", "app_uid", "app_token", "access_token",
        #           "app_token_expire_at", "region"}
    """

    def __init__(self, auth_manager: Optional[AuthManager] = None):
        self.auth = auth_manager or AuthManager()

    async def close(self):
        await self.auth.close()

    async def check_account(self, email: str, account_id: str) -> Dict[str, Any]:
        """Verify the account exists and has a password (code 0)."""
        session = await self.auth._get_session()
        fp = self.auth.fingerprint_gen.get_fingerprint(account_id)
        overrides = self.auth.fingerprint_gen.get_login_overrides(account_id)
        headers = dict(LILITH_HEADERS)
        headers["Im-Session-Id"] = fp.sdk_session_id
        enc_blob = await asyncio.to_thread(encrypt_email_sync, email)
        body = dict(LILITH_DEFAULTS)
        body.update(overrides)
        body["type"] = "0"
        async with session.post(
            CHECK_ACCOUNT_URL, data={**body, "account": enc_blob}, headers=headers
        ) as resp:
            return await resp.json()

    async def login_fresh(
        self,
        email: str,
        password: str,
        account_id: str,
        captcha_ticket: str = "",
        captcha_randstr: str = "",
    ) -> Dict[str, Any]:
        """
        Single fresh-login attempt. Raises RuntimeError with server code on
        failure (11025 validate_fail, 11005 register_risk, 11027 captcha).
        Callers must NOT loop on failure — back off instead.
        """
        session = await self.auth._get_session()
        fp = self.auth.fingerprint_gen.get_fingerprint(account_id)
        overrides = self.auth.fingerprint_gen.get_login_overrides(account_id)
        headers = dict(LILITH_HEADERS)
        headers["Im-Session-Id"] = fp.sdk_session_id
        headers["User-Agent"] = fp.user_agent

        pass_hash = hash_password(password)
        login_body = build_password_login_body(
            email, pass_hash, overrides, captcha_ticket, captcha_randstr
        )
        logger.info(f"[{account_id}] passport login (hashed pass) ...")
        async with session.post(
            DEFAULT_LOGIN_URL, data=login_body, headers=headers
        ) as resp:
            login_resp = await resp.json()

        result = login_resp.get("result", {})
        data = login_resp.get("data", {})

        if result.get("code") == 11027:
            logger.warning(f"[{account_id}] need_captcha — auto-solving ...")
            captcha_url = data.get("captcha_url", "")
            tokens = await self.auth._solve_captcha(captcha_url, account_id)
            if not tokens:
                raise RuntimeError("captcha_solve_failed")
            login_body["captcha_ticket"] = tokens.get("pass_token") or tokens.get("lot_number", "")
            login_body["captcha_randstr"] = tokens.get("lot_number") or tokens.get("captcha_id", "")
            logger.info(f"[{account_id}] retrying with captcha tokens ...")
            async with session.post(
                DEFAULT_LOGIN_URL, data=login_body, headers=headers
            ) as resp:
                login_resp = await resp.json()
            result = login_resp.get("result", {})
            data = login_resp.get("data", {})

        if result.get("code") != 0 and not data.get("app_token"):
            raise RuntimeError(
                f"Passport login failed (code {result.get('code')}): "
                f"{result.get('msg', 'unknown')}"
            )

        app_token = data.get("app_token", "")
        if not app_token:
            raise RuntimeError(
                f"Passport login failed: no app_token "
                f"(code={result.get('code')}, keys={list(data.keys())})"
            )
        app_uid = str(data.get("app_uid") or data.get("uid", ""))
        if not app_uid or app_uid == "0":
            raise RuntimeError(f"Passport login failed: invalid app_uid='{app_uid}'")

        logger.info(f"[{account_id}] passport login OK uid={app_uid}")
        return {
            "email": email,
            "app_uid": app_uid,
            "app_token": app_token,
            "access_token": data.get("access_token") or app_token,
            "app_token_expire_at": data.get("app_token_expire_at", 0),
            "region": data.get("region", ""),
        }
