# app/services/lilith_otp.py
"""Email-OTP (verification code) login against Lilith Passport.

Shapes verified live against app.lilithgame.com (see
_archive/docs/OTP_STATIC_FINDINGS.md + dex reversing of
VerifyCodeHandler / EmailAuthParamsConverter):

  SEND   POST /api/park/sdk/account/send_auth_code
         {account: RSA2048(email), type: email, scene: login, lang: en, +commons}
         -> {result: {code: 0}, data: {result: success, length: 6}}
  LOGIN  POST /v2/api/sdk/login  (login_mode=1, code in `pass` PLAIN)

Only ever send codes to an address the user explicitly typed. Probing and
testing must use undeliverable dummy addresses (like @example.invalid).
"""
import base64
import json
import logging
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("LilithOTP")

# Lilith SDK release RSA-2048 public key (res/raw/ls_enc_r in base.apk).
# PUBLIC key — safe to embed. Used for EncryptUtils/RSA/ECB/PKCS1Padding,
# UTF-8 in, base64 NO_WRAP out.
LILITH_RSA_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAxg4zVvb+2O834B7JdaYS
HikiyzHc9irZrMBEd1RQOljNQnpCoXD+f1mPQyEXBzBUH5ikpBw2i92HVCfB8DlH
Q7lQQmTjpTWHIJ40UNpYP3sb+Hxd7Ze0ascv5hdYGXjnI3/vOIgoDnS5YAuwwYZJ
3f0+2iKOR9LaNZB/dgHYkpHSOWKMJ+eie9IaRbQ1iflNWWPbpU2f4BUIPiAi+xdP
st/hep3okIoo8NB5t3lbvPugfHpZ2C0CaSETRPNYue6xHiGAYRrJjPQh5fmKENJW
UY5H1w47DSH+fBpLai6CQkNgp73Gs1dnaODB5DI3DAIjkpN+gAbuZjZ/nM36cfgL
6QIDAQAB
-----END PUBLIC KEY-----"""

APP_HOST = "https://app.lilithgame.com"
SEND_PATH = "/api/park/sdk/account/send_auth_code"
OTP_UA = "Dalvik/2.1.0 (Linux; U; Android 14; 2311DRK48C Build/UQ1A.240205.07291809)"

_COMMONS = {
    "app_id": 2104267, "game_id": 10043,
    "pack_name": "com.lilithgame.roc.gp",
    "os_type": "android", "lang": "en",
    "lilith_language": "en", "channel_id": "self-lilith-0.7",
    "env_id": "prod59355cd51a219778b7489ab7c3c1",
    "sdk_version": "7.17.0.0", "app_version": "1.1.11.25",
    "is_simulator": "false", "timezone": "Asia/Gaza",
    "device_country_code": "US", "system_language": "en",
    "mobile_channel": "official",
    "device_model": "2311DRK48C", "device_brand": "Redmi",
    "device_abi": "arm64-v8a", "os_version": "14",
}


def rsa_encrypt_account(email: str) -> str:
    """RSA/ECB/PKCS1Padding(UTF-8) -> base64, exactly like the game client."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    key = serialization.load_pem_public_key(LILITH_RSA_PEM.encode())
    ct = key.encrypt(email.encode("utf-8"), padding.PKCS1v15())
    return base64.b64encode(ct).decode()


def _post_json(path: str, body: Dict[str, Any], timeout: float = 15.0) -> Tuple[int, Dict[str, Any]]:
    req = urllib.request.Request(
        APP_HOST + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json; charset=utf-8",
                 "User-Agent": OTP_UA},
        method="POST",
    )
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return r.status, json.loads(r.read().decode() or "{}")
    except Exception as e:
        if hasattr(e, "read"):
            try:
                return int(getattr(e, "code", 0) or 0), json.loads(e.read().decode() or "{}")
            except Exception:
                pass
        return -1, {"_transport_error": str(e)[:200]}


def send_email_code(email: str) -> Dict[str, Any]:
    """Ask Lilith to email a 6-digit login code. Returns parsed verdict."""
    email_clean = (email or "").strip().lower()
    if "@" not in email_clean:
        return {"success": False, "error": "Invalid email address."}
    try:
        enc = rsa_encrypt_account(email_clean)
    except Exception as e:
        return {"success": False, "error": f"Encryption unavailable: {e}"}
    body = {"account": enc, "type": "email", "scene": "login", **_COMMONS}
    status, res = _post_json(SEND_PATH, body)
    result = (res.get("result") or {}) if isinstance(res, dict) else {}
    data = (res.get("data") or {}) if isinstance(res, dict) else {}
    code_num = result.get("code")
    if status == 200 and code_num == 0:
        return {"success": True, "status": "CODE_SENT",
                "code_length": int(data.get("length") or 6),
                "message": "Verification code sent to your email."}
    msg = result.get("msg") or res.get("message") or "Failed to send code."
    logger.warning(f"[otp] send_code rejected for {email_clean}: http={status} code={code_num} msg={msg}")
    return {"success": False, "status": "FAILED",
            "error": f"{msg} (Code {code_num})" if code_num is not None else str(msg)}
