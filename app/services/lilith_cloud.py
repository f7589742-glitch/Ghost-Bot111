# app/services/lilith_cloud.py
"""
Lilith Cloud Native HTTP Service.
Pure multi-tenant SaaS integration with Lilith Passport & rocdir API.
Zero emulator or local game client dependencies.
"""
import os
import json
import time
import hashlib
import urllib.parse
import requests
from typing import Optional, Dict, Any, List, Tuple
from app.services.device_generator import DeviceGenerator

class LilithCloudService:
    APP_ID = 2104267
    GAME_ID = 10043
    CHANNEL_ID = "self-lilith-0.7"
    OS_TYPE = "android"
    PACK_NAME = "com.lilithgame.roc.gp"
    APP_VERSION = "1.1.11.25"
    SDK_VERSION = "7.17.0.0"

    @staticmethod
    def hash_password(password: str) -> str:
        """MD5(password + 'PassHandler').lower()"""
        return hashlib.md5((password + "PassHandler").encode('utf-8')).hexdigest().lower()

    @staticmethod
    def _pick_session_token(d: Dict[str, Any]) -> Tuple[str, str]:
        """
        Accepts whatever session credential Lilith minted for this login:
        game-scoped ``app_token`` (``A-...``) preferred, otherwise the
        passport session ``token`` / ``access_token`` (exchange step resolves
        it into a game token afterwards). Returns (token, source_field).
        """
        for field in ("app_token", "token", "access_token"):
            val = d.get(field)
            if val:
                return str(val), field
        return "", ""

    @classmethod
    def _official_login_form(
        cls,
        email: str,
        pass_hash: str,
        device_profile: Dict[str, Any],
        app_uid: Optional[str] = None,
        app_token: Optional[str] = None,
        captcha_id: Optional[str] = None,
    ) -> Dict[str, str]:
        """
        Builds the EXACT form body the official Android client POSTs to
        ``/v2/api/sdk/login`` (field order + values intercepted 2026-09-10
        via Frida SSL_write tap on LDPlayer):

        - Email/password login  -> type="1", auth_type="0", login_mode="4"
        - Token refresh/session -> type="7", player_id=app_uid, pass=app_token
        - Post-captcha retry    -> same + captcha_id=<uuid from CaptchaDialog>

        NOTE: the official client also sends a per-request ``signature``
        (64-hex). Its generation is not yet reversed, so it is omitted;
        Lilith historically accepts unsigned SDK logins (semantic error
        codes instead of signature errors).
        """
        device_profile = DeviceGenerator.ensure_sdk_fields(device_profile, email)
        udid = device_profile.get("udid") or hashlib.md5(email.encode()).hexdigest().upper()
        ts = str(int(time.time()))
        form: Dict[str, str] = {}
        if app_uid:
            form["app_uid"] = str(app_uid)
        form["device_country_code"] = device_profile.get("device_country_code", "US")
        if captcha_id:
            form["captcha_id"] = str(captcha_id)
        form["gpu_model"] = device_profile.get("gpu_model", "Adreno (TM) 750")
        form["app_version"] = cls.APP_VERSION
        form["device_model"] = device_profile.get("model", "SM-S918B")
        form["real_package_name"] = cls.PACK_NAME
        if app_token:
            form["app_token"] = str(app_token)
        form["mobile_channel"] = device_profile.get("mobile_channel", "official")
        form["timezone"] = device_profile.get("timezone", "Asia/Gaza")
        form["soc_model"] = device_profile.get("soc_model", "aosp-user")
        form["type"] = "1"
        form["player_id"] = email
        form["lilith_language"] = device_profile.get("lilith_language", "en")
        form["install_id"] = device_profile.get("install_id", "")
        form["sdk_version"] = cls.SDK_VERSION
        form["lang"] = device_profile.get("lang", "2")
        form["app_id"] = str(cls.APP_ID)
        form["game_id"] = str(cls.GAME_ID)
        form["system_language"] = device_profile.get("system_language", "en")
        form["timestamp"] = ts
        form["pack_name"] = cls.PACK_NAME
        form["auth_type"] = "0"
        form["pass"] = pass_hash
        form["os_version"] = device_profile.get("os_version", "13")
        form["store_country"] = device_profile.get("store_country", "")
        form["session_id"] = "0"
        form["login_mode"] = "4"
        form["device_abi"] = device_profile.get("device_abi", "arm64-v8a")
        form["is_simulator"] = device_profile.get("is_simulator", "false")
        form["google_aid"] = device_profile.get("google_aid", "")
        form["env_id"] = device_profile.get("env_id", "")
        form["device_brand"] = device_profile.get("brand", "Samsung")
        form["sdk_session_id"] = device_profile.get("sdk_session_id", "")
        form["os_type"] = cls.OS_TYPE
        form["mcc_codes"] = device_profile.get("mcc_codes", "")
        form["android_id"] = device_profile.get("android_id", "")
        form["channel_id"] = cls.CHANNEL_ID
        form["account"] = email
        return form

    @classmethod
    def authenticate(
        cls,
        email: str,
        password: str,
        device_profile: Optional[Dict[str, Any]] = None,
        app_uid: Optional[str] = None,
        app_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Pure cloud authentication against https://app.lilithgame.com/v2/api/sdk/login
        using the EXACT official-client form (type=1 / auth_type=0 / login_mode=4).
        When a previous session exists, its app_uid/app_token ride along exactly
        like the official client sends them.
        """
        email_clean = email.strip().lower()
        if not device_profile:
            device_profile = DeviceGenerator.generate(email_clean)
        device_profile = DeviceGenerator.ensure_sdk_fields(device_profile, email_clean)

        udid = device_profile.get("udid") or hashlib.md5(email_clean.encode()).hexdigest().upper()
        pass_hash = cls.hash_password(password)

        payload = cls._official_login_form(
            email_clean, pass_hash, device_profile,
            app_uid=app_uid, app_token=app_token,
        )

        headers = {
            "User-Agent": device_profile.get("user_agent", "Dalvik/2.1.0"),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept-Encoding": "gzip"
        }

        try:
            resp = requests.post(
                "https://app.lilithgame.com/v2/api/sdk/login",
                data=payload,
                headers=headers,
                timeout=12.0
            )
            res_json = resp.json()
            print("\n====== [LILITH RAW AUTH RESPONSE] ======")
            print(f"HTTP Status: {resp.status_code}")
            print(f"Response JSON: {res_json}")
            print("=========================================\n")
            result = res_json.get("result", {})
            code = result.get("code")
            msg = result.get("msg", "")
            d = res_json.get("data", {})

            # 1. Successful Authentication — accept whatever session token
            # Lilith minted (no artificial format blocking here).
            if code == 0:
                app_token, token_source = cls._pick_session_token(d)
                if not app_token:
                    return {
                        "success": False,
                        "status": "FAILED",
                        "error": f"Lilith login returned code 0 without any token field (data keys: {sorted(d.keys())}).",
                        "device_profile": device_profile
                    }
                print(f"[LilithCloud] authenticate: session token from '{token_source}' "
                      f"(prefix={app_token[:3]}..., len={len(app_token)})")
                app_uid = str(d.get("app_uid") or d.get("gm_openid"))
                expire_at = int(d.get("app_token_expire_at") or (time.time() + 2592000))
                lilith_id = str(d.get("uid") or "")
                return {
                    "success": True,
                    "status": "AUTHENTICATED",
                    "app_uid": app_uid,
                    "app_token": app_token,
                    "token_expires_at": expire_at,
                    "lilith_id": lilith_id,
                    "udid": udid,
                    "device_profile": device_profile,
                    "raw": d
                }

            # 2. Captcha / Verification Challenge (Code 11027 or 11005)
            if code in (11027, 11005):
                captcha_url = d.get("captcha_url", "")
                if not captcha_url:
                    encoded_email = urllib.parse.quote(email_clean)
                    captcha_url = f"https://passport.lilithgame.com/v2/api/captcha?app_id={cls.APP_ID}&game_id={cls.GAME_ID}&account={encoded_email}&login_mode=4"

                return {
                    "success": False,
                    "status": "REQUIRES_VERIFICATION",
                    "captcha_type": "lilith_popup",
                    "captcha_url": captcha_url,
                    "email": email_clean,
                    "device_profile": device_profile,
                    "error": "Authentic Lilith human verification challenge required."
                }

            elif code == 11401:
                return {
                    "success": False,
                    "status": "INVALID_PASSWORD",
                    "error": "كلمة المرور غير صحيحة (Invalid Lilith Password)",
                    "device_profile": device_profile
                }
            else:
                return {
                    "success": False,
                    "status": "FAILED",
                    "error": f"Lilith auth failed: {msg} (Code {code})",
                    "device_profile": device_profile
                }

        except Exception as e:
            return {
                "success": False,
                "status": "ERROR",
                "error": f"Network error during authentication: {str(e)}",
                "device_profile": device_profile
            }

    @classmethod
    def authenticate_with_code(
        cls,
        email: str,
        code: str,
        device_profile: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Email-OTP login (verified live against app.lilithgame.com).

        Mirrors the official client's code form (EmailAuthParamsConverter):
        same /v2/api/sdk/login endpoint as passwords, but login_mode=1 and
        the code travels PLAIN in `pass` (no MD5). Proves itself with
        `11010 verify_code_fail` on a wrong code instead of `1001`.
        """
        from app.services.device_generator import DeviceGenerator as _DG

        email_clean = (email or "").strip().lower()
        code_clean = (code or "").strip()
        if not email_clean or not code_clean:
            return {"success": False, "status": "FAILED",
                    "error": "Email and 6-digit code are required."}
        if not device_profile:
            device_profile = _DG.generate(email_clean)
        device_profile = _DG.ensure_sdk_fields(device_profile, email_clean)

        udid = device_profile.get("udid") or hashlib.md5(email_clean.encode()).hexdigest().upper()
        form = dict(cls._official_login_form(email_clean, "000000", device_profile))
        # Overwrite password-form specifics with the code form.
        form["pass"] = code_clean
        form["account"] = email_clean
        form["login_mode"] = "1"
        form["session_id"] = "0"
        form["is_subscribe"] = "0"
        form["auth_type"] = "0"
        form["type"] = "1"
        form["player_id"] = email_clean

        headers = {
            "User-Agent": device_profile.get("user_agent", "Dalvik/2.1.0"),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept-Encoding": "gzip",
        }
        try:
            resp = requests.post(
                "https://app.lilithgame.com/v2/api/sdk/login",
                data=form, headers=headers, timeout=12.0,
            )
            res_json = resp.json()
            result = res_json.get("result", {})
            code_num = result.get("code")
            msg = result.get("msg", "")
            d = res_json.get("data", {})

            if code_num == 0:
                app_token, token_source = cls._pick_session_token(d)
                if not app_token:
                    return {"success": False, "status": "FAILED",
                            "error": "Login returned code 0 without any token.",
                            "device_profile": device_profile}
                app_uid = str(d.get("app_uid") or d.get("gm_openid"))
                expire_at = int(d.get("app_token_expire_at") or (time.time() + 2592000))
                return {"success": True, "status": "AUTHENTICATED",
                        "app_uid": app_uid, "app_token": app_token,
                        "token_expires_at": expire_at,
                        "lilith_id": str(d.get("uid") or ""),
                        "udid": udid, "device_profile": device_profile, "raw": d}
            if code_num == 11010:
                return {"success": False, "status": "INVALID_CODE",
                        "error": "رمز التحقق غير صحيح أو منتهي الصلاحية. اطلب رمزًا جديدًا وأعد المحاولة.",
                        "device_profile": device_profile}
            if code_num in (11027, 11005):
                captcha_url = d.get("captcha_url", "")
                if not captcha_url:
                    encoded_email = urllib.parse.quote(email_clean)
                    captcha_url = (f"https://passport.lilithgame.com/v2/api/captcha?app_id={cls.APP_ID}"
                                   f"&game_id={cls.GAME_ID}&account={encoded_email}&login_mode=1")
                return {"success": False, "status": "REQUIRES_VERIFICATION",
                        "captcha_type": "lilith_popup", "captcha_url": captcha_url,
                        "email": email_clean, "device_profile": device_profile,
                        "error": "Security check required."}
            return {"success": False, "status": "FAILED",
                    "error": f"Lilith code login failed: {msg} (Code {code_num})",
                    "device_profile": device_profile}
        except Exception as e:
            return {"success": False, "status": "ERROR",
                    "error": f"Network error during code login: {str(e)}"}

    @classmethod
    def verify_captcha(
        cls,
        email: str,
        password: str,
        captcha_id: str,
        device_profile: Optional[Dict[str, Any]] = None,
        app_uid: Optional[str] = None,
        app_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Retries the official login form with the ``captcha_id`` UUID issued by
        the in-game CaptchaDialog bridge after the user solves the slider at
        captcha-global.lilithgame.com. Exactly mirrors the intercepted retry.
        """
        email_clean = email.strip().lower()
        if not device_profile:
            device_profile = DeviceGenerator.generate(email_clean)
        device_profile = DeviceGenerator.ensure_sdk_fields(device_profile, email_clean)

        udid = device_profile.get("udid") or hashlib.md5(email_clean.encode()).hexdigest().upper()
        pass_hash = cls.hash_password(password)

        payload = cls._official_login_form(
            email_clean, pass_hash, device_profile,
            app_uid=app_uid, app_token=app_token,
            captcha_id=captcha_id.strip(),
        )

        headers = {
            "User-Agent": device_profile.get("user_agent", "Dalvik/2.1.0"),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept-Encoding": "gzip"
        }

        try:
            resp = requests.post(
                "https://app.lilithgame.com/v2/api/sdk/login",
                data=payload,
                headers=headers,
                timeout=12.0
            )
            res_json = resp.json()
            result = res_json.get("result", {})
            code = result.get("code")
            msg = result.get("msg", "")
            d = res_json.get("data", {})

            if code == 0:
                app_token, token_source = cls._pick_session_token(d)
                if not app_token:
                    return {
                        "success": False,
                        "status": "VERIFICATION_FAILED",
                        "error": f"Verification returned code 0 without any token field (data keys: {sorted(d.keys())})"
                    }
                print(f"[LilithCloud] verify_captcha: session token from '{token_source}' "
                      f"(prefix={app_token[:3]}..., len={len(app_token)})")
                app_uid = str(d.get("app_uid") or d.get("gm_openid"))
                expire_at = int(d.get("app_token_expire_at") or (time.time() + 2592000))
                lilith_id = str(d.get("uid") or "")
                return {
                    "success": True,
                    "status": "AUTHENTICATED",
                    "app_uid": app_uid,
                    "app_token": app_token,
                    "token_expires_at": expire_at,
                    "lilith_id": lilith_id,
                    "udid": udid,
                    "device_profile": device_profile,
                    "raw": d
                }
            else:
                return {
                    "success": False,
                    "status": "VERIFICATION_FAILED",
                    "error": f"Verification failed: {msg} (Code {code})"
                }
        except Exception as e:
            return {
                "success": False,
                "status": "ERROR",
                "error": f"Verification network error: {str(e)}"
            }

    @classmethod
    def finalize_captcha(
        cls,
        email: str,
        password: str,
        ticket: str,
        randstr: str = "",
        device_profile: Optional[Dict[str, Any]] = None,
        app_uid: Optional[str] = None,
        app_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Submits the ``captcha_id`` UUID issued by the CaptchaDialog bridge
        (passed in as ``ticket``) via the official login retry form.
        """
        email_clean = email.strip().lower()
        if not device_profile:
            device_profile = DeviceGenerator.generate(email_clean)
        device_profile = DeviceGenerator.ensure_sdk_fields(device_profile, email_clean)

        udid = device_profile.get("udid") or hashlib.md5(email_clean.encode()).hexdigest().upper()
        pass_hash = cls.hash_password(password)

        clean_ticket = ticket.strip()

        payload = cls._official_login_form(
            email_clean, pass_hash, device_profile,
            app_uid=app_uid, app_token=app_token,
            captcha_id=clean_ticket if clean_ticket and clean_ticket != "verified" else None,
        )

        headers = {
            "User-Agent": device_profile.get("user_agent", "Dalvik/2.1.0"),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept-Encoding": "gzip"
        }

        try:
            resp = requests.post(
                "https://app.lilithgame.com/v2/api/sdk/login",
                data=payload,
                headers=headers,
                timeout=12.0
            )
            res_json = resp.json()
            result = res_json.get("result", {})
            code = result.get("code")
            msg = result.get("msg", "")
            d = res_json.get("data", {})

            if code == 0:
                app_token, token_source = cls._pick_session_token(d)
                if not app_token:
                    return {
                        "success": False,
                        "status": "VERIFICATION_FAILED",
                        "error": f"Verification returned code 0 without any token field (data keys: {sorted(d.keys())})"
                    }
                print(f"[LilithCloud] finalize_captcha: session token from '{token_source}' "
                      f"(prefix={app_token[:3]}..., len={len(app_token)})")
                app_uid = str(d.get("app_uid") or d.get("gm_openid"))
                expire_at = int(d.get("app_token_expire_at") or (time.time() + 2592000))
                lilith_id = str(d.get("uid") or "")
                return {
                    "success": True,
                    "status": "AUTHENTICATED",
                    "app_uid": app_uid,
                    "app_token": app_token,
                    "token_expires_at": expire_at,
                    "lilith_id": lilith_id,
                    "udid": udid,
                    "device_profile": device_profile,
                    "raw": d
                }
            else:
                return {
                    "success": False,
                    "status": "VERIFICATION_FAILED",
                    "error": f"Lilith rejected verification ticket: {msg} (Code {code})"
                }
        except Exception as e:
            return {
                "success": False,
                "status": "ERROR",
                "error": f"Verification network error: {str(e)}"
            }

    @classmethod
    def refresh_token(cls, app_uid: str, app_token: str, udid: str) -> Dict[str, Any]:
        """
        Extends 30-day token expiration using Lilith's cloud refresh API.
        """
        payload = {
            "app_id": str(cls.APP_ID),
            "game_id": str(cls.GAME_ID),
            "channel_id": cls.CHANNEL_ID,
            "os_type": cls.OS_TYPE,
            "type": "7",
            "player_id": app_uid,
            "pass": app_token,
            "device_id": udid
        }
        try:
            resp = requests.post("https://app.lilithgame.com/v2/api/sdk/login", data=payload, timeout=10.0)
            res = resp.json()
            d = res.get("data", {})
            if res.get("result", {}).get("code") == 0 and d.get("app_token"):
                return {
                    "success": True,
                    "app_token": d.get("app_token"),
                    "token_expires_at": int(d.get("app_token_expire_at") or (time.time() + 2592000))
                }
        except Exception:
            pass
        return {"success": False}

    #: Exact rocdir headers sent by the official client (User-Agent: nativeCode).
    ROCDIR_HEADERS = {
        "User-Agent": "nativeCode",
        "Accept-Encoding": "gzip",
        "Appid": "gamename",
        "ClientKey": "AND_10111_628788_25",
        "clientv": "1.1.11.25",
        "shiqu": "Asia/Gaza",
    }

    _public_ip_cache: Optional[str] = None

    @classmethod
    def public_ip(cls) -> str:
        """Public egress IP (the official client sends it as &ip=.. on rocdir). Cached."""
        if not cls._public_ip_cache:
            try:
                cls._public_ip_cache = requests.get("https://api.ipify.org", timeout=4.0).text.strip()
            except Exception:
                cls._public_ip_cache = ""
        return cls._public_ip_cache or ""

    @classmethod
    def _rocdir_headers(cls, app_uid: str, app_token: str, udid: str) -> Dict[str, str]:
        h = dict(cls.ROCDIR_HEADERS)
        h["AppUid"] = str(app_uid)
        h["SdkAppToken"] = str(app_token)
        h["udid"] = str(udid)
        return h

    @classmethod
    def get_roles(cls, app_uid: str, app_token: str, udid: str) -> List[Dict[str, Any]]:
        """
        Discovers all governors for this account — EXACT official shape
        (intercepted 2026-09-10):
        GET /get/roles?app_uid=..&app_token=..&app_id=..&lg_channel=and
            &sdk_type=1&ip=..&udid=..&lang=en&platform=android&ignoreserverlist=true
        """
        url = (
            f"https://rocdir.lilithgame.com/get/roles"
            f"?app_uid={app_uid}&app_token={app_token}&app_id={cls.APP_ID}"
            f"&lg_channel=and&sdk_type=1"
            f"&udid={udid}&lang=en&platform=android&ignoreserverlist=true"
        )
        if cls.public_ip():
            url += f"&ip={cls.public_ip()}"
        headers = cls._rocdir_headers(app_uid, app_token, udid)
        last_error = None
        for attempt in range(1, 4):
            try:
                resp = requests.get(url, headers=headers, timeout=12.0)
                res_json = resp.json()

                # Lilith explicitly rejected the token (expired, truncated, or
                # belonging to another session). No retry: rejected stays rejected.
                if res_json.get("success") is False:
                    print(f"[LilithCloud] get_roles rejected (uid={app_uid}): "
                          f"{res_json.get('message')} (errorType={res_json.get('errorType')})")
                    return []

                characters = []
                # Region-agnostic: official keys are ("1","41","2") but Lilith
                # may serve an account's players under another region key.
                # Any top-level dict carrying a Players list is collected.
                regions = []
                for region_key in ("1", "41", "2"):
                    region_data = res_json.get(region_key)
                    if isinstance(region_data, dict):
                        regions.append((region_key, region_data))
                for k, v in res_json.items():
                    if isinstance(v, dict) and isinstance(v.get("Players"), list):
                        if all(rd is not v for _, rd in regions):
                            regions.append((k, v))
                if not regions:
                    print(f"[LilithCloud] get_roles: no Players region (uid={app_uid}); top keys={sorted(res_json.keys())}")
                seen_pids = set()
                for region_key, region_data in regions:
                    players = region_data.get("Players") or []
                    for p in players:
                        pid = str(p.get("PlayerId"))
                        if pid in seen_pids:
                            continue
                        seen_pids.add(pid)
                        avatar_raw = p.get("Avatar", "")
                        avatar_url = ""
                        try:
                            if avatar_raw and avatar_raw.startswith("{"):
                                av_json = json.loads(avatar_raw)
                                avatar_url = av_json.get("avatar") or av_json.get("avatarFrame") or ""
                            elif avatar_raw:
                                avatar_url = avatar_raw
                        except Exception:
                            avatar_url = avatar_raw

                        characters.append({
                            "role_id": str(p.get("PlayerId")),
                            "name": p.get("PlayerName", f"Governor_{p.get('PlayerId')}"),
                            "kingdom_id": int(p.get("ServerId") or p.get("OriServerId") or 1001),
                            "power": int(p.get("Power") or 0),
                            "city_level": int(p.get("TownCenterLevel") or 1),
                            "avatar_url": avatar_url,
                            "alliance_tag": p.get("Abbr") or "",
                            "origin_server_id": int(p.get("OriginServerId") or 0),
                            "last_login_time": int(p.get("LastLoginTime") or 0),
                            "last_login_ip": p.get("LastLoginIP") or ""
                        })
                if characters or attempt == 3:
                    if attempt > 1:
                        print(f"[LilithCloud] get_roles recovered on attempt {attempt} (uid={app_uid})")
                    return characters
                # success:true but zero players = suspicious/transient: retry.
                last_error = "empty Players on success:true"
                print(f"[LilithCloud] get_roles empty (uid={app_uid}), retrying [{attempt}/3]...")
                time.sleep(2.0)
            except Exception as e:
                last_error = str(e)
                print(f"[LilithCloud] Error fetching roles (attempt {attempt}/3): {e}")
                if attempt < 3:
                    time.sleep(2.0)
        print(f"[LilithCloud] get_roles failed after 3 attempts (uid={app_uid}): {last_error}")
        return []

    @classmethod
    def set_active_role(cls, app_uid: str, app_token: str, udid: str, role_id: str, kingdom_id: int) -> bool:
        """
        Sends POST request with PascalCase JSON payload to https://rocdir.lilithgame.com/login/role
        to switch active role context, with automatic GET fallback.
        """
        headers = cls._rocdir_headers(app_uid, app_token, udid)
        headers["Content-Type"] = "application/json; charset=utf-8"

        post_body = {
            "AppId": str(cls.APP_ID),
            "AppUid": str(app_uid),
            "AppToken": str(app_token),
            "PlayerId": str(role_id),
            "ServerId": str(kingdom_id),
            "Udid": str(udid),
            "LgChannel": "and",
            "SdkType": "1",
            "Platform": "android"
        }

        try:
            resp = requests.post(
                "https://rocdir.lilithgame.com/login/role",
                json=post_body,
                headers=headers,
                timeout=10.0
            )
            if resp.status_code == 200:
                res_json = resp.json()
                if res_json.get("success") is True or res_json.get("code") == 0 or res_json.get("errorType") in (0, 241):
                    return True
        except Exception as e:
            print(f"[LilithCloud] POST /login/role notice: {e}")

        # Fallback to GET query params if POST was rejected
        ip_part = f"&ip={cls.public_ip()}" if cls.public_ip() else ""
        url = (
            f"https://rocdir.lilithgame.com/login/role"
            f"?app_uid={app_uid}&app_token={app_token}&app_id={cls.APP_ID}"
            f"&lg_channel=and&sdk_type=1"
            f"{ip_part}&udid={udid}&lang=en&region_id=1"
            f"&player_id={role_id}&server_id={kingdom_id}"
        )
        try:
            resp = requests.get(url, headers=cls._rocdir_headers(app_uid, app_token, udid), timeout=10.0)
            res_json = resp.json()
            return bool(res_json.get("success", False) or res_json.get("errorType") in (0, 241) or res_json.get("code") == 0)
        except Exception as e:
            print(f"[LilithCloud] Error setting active role {role_id}: {e}")
            return False
        """Exact JSON body the official client POSTs to /get/urls."""
        dp = device_profile or {}
        return {
            "AppVersion": cls.APP_VERSION,
            "AndroidID": dp.get("android_id", ""),
            "AppId": str(cls.APP_ID),
            "DeviceModel": dp.get("model", "SM-S918B"),
            "GoogleAid": dp.get("google_aid", ""),
            "LgChannel": "and",
            "AppUid": str(app_uid),
            "OsVersion": dp.get("os_version", "13"),
            "OsType": "android",
            "teststring": "teststring",
            "IDFA": "",
            "SdkType": "1",
            "ChannelID": cls.CHANNEL_ID,
            "PackName": cls.PACK_NAME,
        }

    @classmethod
    def resolve_gateway(
        cls,
        app_uid: str,
        app_token: str,
        udid: str,
        kingdom_id: int,
        device_profile: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, int]:
        """
        Resolves assigned Game Gateway host/port — EXACT official shape:
        POST /get/urls?key=..&udid=..&app_uid=..&sdk_type=1&lg_channel=and
             &app_id=..&app_token=..&region_id=1&server_id=..
        with the JSON device body above.
        """
        url = (
            f"https://rocdir.lilithgame.com/get/urls"
            f"?key=AND_10111_628788_25&udid={udid}"
            f"&app_uid={app_uid}&sdk_type=1&lg_channel=and&app_id={cls.APP_ID}"
            f"&app_token={app_token}&region_id=1&server_id={kingdom_id}"
        )
        headers = cls._rocdir_headers(app_uid, app_token, udid)
        try:
            resp = requests.post(
                url, json=cls._gateway_post_body(app_uid, udid, device_profile),
                headers=headers, timeout=10.0)
            res_json = resp.json()
            servers = res_json.get("Servers") or []
            if servers and isinstance(servers, list):
                addr = servers[0].get("Addr", "rocgate.lilithgame.com:3101")
                if ":" in addr:
                    h, p = addr.split(":")
                    return h, int(p)
                return addr, 3101
        except Exception:
            pass
        return "rocgate.lilithgame.com", 3101
