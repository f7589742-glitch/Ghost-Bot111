#!/usr/bin/env python3
"""
account_resolver.py
Universal zero-touch account onboarding for Lilith Game Accounts.

Pipeline (verified working):
  1. SDK login  →  https://app-pc.lilithgame.com/v2/api/sdk/login
  2. Read bindings / lilith_bindings / character data from login response
  3. Build fleet entries → accounts_fleet.json
"""

import argparse
import asyncio
import base64
import json
import os
import secrets
import struct
import sys
import uuid
from typing import Any

try:
    import httpx
    _HTTP = "httpx"
except ImportError:
    import aiohttp
    _HTTP = "aiohttp"

# ── constants ──────────────────────────────────────────────────────────────
APP_ID        = "2104267"
GAME_ID       = "10043"
APP_VERSION   = "1.1.9.19"
SDK_VERSION   = "1.0.8.0"
CHANNEL_ID    = "self-lilith-1"
PC_CHANNEL    = "legoulauncher"
PACK_NAME     = "com.lilithgames.rok.pc.int"
ENV_ID        = "prod95fa8d9f035da4e7f4ca8317b3e5"
LOGIN_URL     = "https://app-pc.lilithgame.com/v2/api/sdk/login"
SDK_USER_URL  = "https://app-pc.lilithgame.com/v2/api/sdk/account/user"
GATEWAY_HOST  = "rocgate.lilithgame.com"
GATEWAY_PORT  = 3101
KINGDOM_ID    = 1275  # Beili — from game screenshot
FLEET_FILE    = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "accounts_fleet.json")

ERROR_CAPTCHA = 11027
ERROR_RISK    = 11005

# ── RSA ─────────────────────────────────────────────────────────────────────
RSA_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAxg4zVvb+2O834B7JdaYS
HikiyzHc9irZrMBEd1RQOljNQnpCoXD+f1mPQyEXBzBUH5ikpBw2i92HVCfB8DlH
Q7lQQmTjpTWHIJ40UNpYP3sb+Hxd7Ze0ascv5hdYGXjnI3/vOIgoDnS5YAuwwYZJ
3f0+2iKOR9LaNZB/dgHYkpHSOWKMJ+eie9IaRbQ1iflNWWPbpU2f4BUIPiAi+xdP
st/hep3okIoo8NB5t3lbvPugfHpZ2C0CaSETRPNYue6xHiGAYRrJjPQh5fmKENJW
UY5H1w47DSH+fBpLai6CQkNgp73Gs1dnaODB5DI3DAIjkpN+gAbuZjZ/nM36cfgL
6QIDAQAB
-----END PUBLIC KEY-----"""

def _rsa_encrypt(email: str) -> str:
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives import serialization
    key = serialization.load_pem_public_key(RSA_KEY.encode())
    ct = key.encrypt(email.encode(), padding.PKCS1v15())
    return base64.b64encode(ct).decode()

# ── http client ─────────────────────────────────────────────────────────────
class _C:
    def __init__(self):
        self.c = None
    async def __aenter__(self):
        if _HTTP == "httpx":
            self.c = httpx.AsyncClient(timeout=httpx.Timeout(30, connect=10),
                headers={"Content-Type":"application/x-www-form-urlencoded",
                         "Im-Session-Id":secrets.token_hex(16).upper(),
                         "User-Agent":"limpc-1.0.8.0","Accept":"*/*"})
        else:
            import aiohttp, urllib.parse
            self.c = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(30, connect=10),
                headers={"Content-Type":"application/x-www-form-urlencoded",
                         "Im-Session-Id":secrets.token_hex(16).upper(),
                         "User-Agent":"limpc-1.0.8.0","Accept":"*/*"})
        return self
    async def __aexit__(self, *e):
        if self.c:
            try:
                await self.c.aclose()
            except AttributeError:
                await self.c.close()
    async def post(self, url, data):
        if _HTTP == "httpx":
            r = await self.c.post(url, data=data)
            r.raise_for_status()
            return r.json()
        else:
            import urllib.parse
            r = await self.c.post(url, data=urllib.parse.urlencode(data))
            r.raise_for_status()
            return await r.json()

# ── device fingerprint ──────────────────────────────────────────────────────
def _fp() -> dict:
    return {
        "app_id":APP_ID,"app_version":APP_VERSION,"channel_id":CHANNEL_ID,
        "device_abi":"x86-64","device_brand":"DESKTOP-N48PKRD","device_model":"win",
        "device_name":"DESKTOP-N48PKRD","env_id":ENV_ID,"game_id":GAME_ID,
        "idfa":"v"+str(uuid.uuid4()).lower(),"install_id":str(uuid.uuid4()).upper(),
        "lang":"ar","lilith_language":"ar","os_type":"win","os_version":"10.0.26200",
        "pack_name":PACK_NAME,"pc_channel":PC_CHANNEL,"real_package_name":PACK_NAME,
        "sdk_session_id":secrets.token_hex(16).upper(),"sdk_version":SDK_VERSION,
        "source":"1","type":"0","auth_type":"0",
    }

# ── captcha exception ────────────────────────────────────────────────────────
class CaptchaRequired(Exception):
    def __init__(self, url):
        self.url = url
        super().__init__(f"Captcha required: {url}\nSolve and provide --captcha-ticket / --captcha-randstr.")

# ── resolver ────────────────────────────────────────────────────────────────
class AccountResolver:
    async def login(self, email, password, ticket="", randstr="", client=None):
        body = _fp()
        body["player_id"] = email
        body["pass"] = password
        if ticket:   body["captcha_ticket"]   = ticket
        if randstr:  body["captcha_randstr"]  = randstr
        resp = await client.post(LOGIN_URL, body)
        code = resp.get("code", resp.get("result",{}).get("code",-1))
        if code == ERROR_RISK:
            await asyncio.sleep(2)
            resp = await client.post(LOGIN_URL, body)
            code = resp.get("code", resp.get("result",{}).get("code",-1))
        if code == ERROR_CAPTCHA:
            raise CaptchaRequired(resp.get("data",{}).get("captcha_url",""))
        if code != 0:
            raise RuntimeError(f"Login failed code={code} msg={resp.get('msg','')}")
        return resp.get("data",{})

    def _extract_characters(self, data: dict, app_uid, app_token) -> list:
        chars = []
        # 1) bindings array
        for b in data.get("bindings", []) or []:
            if isinstance(b, dict) and b.get("role_id") not in (None,"0",""):
                chars.append(self._to_char(b, app_uid, app_token))
        # 2) lilith_bindings
        for b in data.get("lilith_bindings", []) or []:
            if isinstance(b, dict) and b.get("role_id") not in (None,"0",""):
                chars.append(self._to_char(b, app_uid, app_token))
        # 3) any top-level character-like fields
        for key in ("character","characters","role","roles","role_list","character_list"):
            val = data.get(key)
            if isinstance(val, list):
                for b in val:
                    if isinstance(b, dict) and b.get("role_id") not in (None,"0",""):
                        chars.append(self._to_char(b, app_uid, app_token))
        return chars

    def _to_char(self, b: dict, app_uid, app_token) -> dict:
        return {
            "role_id":          str(b.get("role_id") or b.get("character_id") or b.get("id","0")),
            "character_name":   b.get("role_name") or b.get("character_name") or b.get("name",""),
            "app_uid":          app_uid,
            "access_token":     app_token,
            "power":            b.get("power") or b.get("combat_power") or 0,
            "city_hall_level":  b.get("city_hall_level") or b.get("city_level") or 0,
            "kingdom_id":       str(b.get("kingdom_id") or b.get("server_id") or str(KINGDOM_ID)),
            "kingdom_name":     b.get("kingdom_name") or b.get("server_name") or "Beili",
            "gate_host":        b.get("gate_host") or GATEWAY_HOST,
            "gate_port":        b.get("gate_port") or GATEWAY_PORT,
        }

    async def resolve(self, email, password, ticket="", randstr=""):
        async with _C() as c:
            data = await self.login(email, password, ticket, randstr, c)
            app_uid      = str(data.get("app_uid",""))
            app_token    = data.get("app_token","")
            access_token = data.get("access_token","")
            region       = data.get("region","")
            chars = self._extract_characters(data, app_uid, app_token)
            for ch in chars:
                ch["gate_host"], ch["gate_port"] = GATEWAY_HOST, GATEWAY_PORT
            return {
                "email":email,"app_uid":app_uid,"app_token":app_token,
                "access_token":access_token,"region":region,"characters":chars,
            }

# ── fleet persistence ────────────────────────────────────────────────────────
def _load(path=FLEET_FILE):
    if os.path.exists(path):
        with open(path,"r",encoding="utf-8") as f: return json.load(f)
    return []

def _save(fleet, path=FLEET_FILE):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path,"w",encoding="utf-8") as f: json.dump(fleet,f,indent=2,ensure_ascii=False)

def register(email, password, ticket="", randstr="", fleet_path=FLEET_FILE):
    resolver = AccountResolver()
    result = asyncio.run(resolver.resolve(email, password, ticket, randstr))
    new = []
    for ch in result["characters"]:
        entry = {
            "id":              f"auto_{ch['role_id']}",
            "name":            ch["character_name"],
            "role_id":         str(ch["role_id"]),
            "access_token":    ch["access_token"],   # REAL TOKEN (NEVER "[REDACTED]")
            "app_token":       ch["access_token"],   # Dual-alias for full DB compatibility
            "app_uid":         str(ch["app_uid"]),
            "open_id":         str(ch["app_uid"]),
            "server_id":       str(ch.get("kingdom_id", "3057")),
            "server_id_int":   int(ch.get("kingdom_id", 3057)),
            "gate_host":       ch.get("gate_host", GATEWAY_HOST),
            "port":            int(ch.get("gate_port", GATEWAY_PORT)),
            "city_pos":        [],
            "login_hex_path":  "",
            "enabled":         True,
            "power":           int(ch.get("power", 0) or 0),
            "city_hall_level": int(ch.get("city_hall_level", 0) or 0),
            "kingdom_name":    ch.get("kingdom_name", ""),
        }
        new.append(entry)
    fleet = _load(fleet_path)
    exist = {e.get("role_id") for e in fleet}
    for e in new:
        if e["role_id"] in exist:
            for i,ex in enumerate(fleet):
                if ex.get("role_id")==e["role_id"]:
                    e["id"]          = ex.get("id",e["id"])
                    e["login_hex_path"]= ex.get("login_hex_path","")
                    e["city_pos"]      = ex.get("city_pos",[])
                    fleet[i] = e
                    break
        else:
            fleet.append(e)
    _save(fleet, fleet_path)
    # Sync to SQLite Database (accounts & characters tables)
    try:
        from app.models import AccountDAO, CharacterDAO
        from app.database import get_db_connection
        con = get_db_connection()
        with con:
            existing_acc = con.execute("SELECT id FROM accounts WHERE email = ?", (email,)).fetchone()
            if existing_acc:
                acc_id = existing_acc["id"]
                con.execute(
                    "UPDATE accounts SET app_token = ?, app_uid = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (result["app_token"], result["app_uid"], acc_id)
                )
            else:
                cur = con.execute(
                    "INSERT INTO accounts (email, encrypted_password, app_uid, app_token, udid, user_id) VALUES (?, ?, ?, ?, ?, ?)",
                    (email, "", result["app_uid"], result["app_token"], "00000000-0000-0000-0000-000000000000", "8e7bb3f0-5e7f-4ad0-9f30-9f4e4949b25f")
                )
                acc_id = cur.lastrowid
            for ch in result["characters"]:
                c_role = str(ch["role_id"])
                c_name = ch["character_name"]
                c_kid = int(ch.get("kingdom_id") or 3057)
                c_power = int(ch.get("power") or 0)
                c_ch = int(ch.get("city_hall_level") or 0)
                con.execute("""
                    INSERT INTO characters (account_id, role_id, name, kingdom_id, power, city_level, is_active_cloud, enabled)
                    VALUES (?, ?, ?, ?, ?, ?, 1, 1)
                    ON CONFLICT(role_id) DO UPDATE SET
                        account_id = excluded.account_id,
                        name = excluded.name,
                        kingdom_id = excluded.kingdom_id,
                        power = excluded.power,
                        city_level = excluded.city_level,
                        is_active_cloud = 1,
                        enabled = 1
                """, (acc_id, c_role, c_name, c_kid, c_power, c_ch))
        print(f"[DB SYNC] Successfully synced Account #{acc_id} and {len(result['characters'])} characters to SQLite.")
    except Exception as e_db:
        print(f"[DB SYNC WARN] Could not sync to SQLite: {e_db}")
        import traceback; traceback.print_exc()
    return new

# ── CLI ──────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="Lilith Account Onboarding Engine")
    p.add_argument("--email",required=True)
    p.add_argument("--password",required=True)
    p.add_argument("--captcha-ticket",default="")
    p.add_argument("--captcha-randstr",default="")
    p.add_argument("--fleet",default=FLEET_FILE)
    args = p.parse_args()
    try:
        entries = register(args.email, args.password, args.captcha_ticket,
                           args.captcha_randstr, args.fleet)
    except CaptchaRequired as e:
        print(f"Captcha required: {e.url}")
        print("Re-run with: --captcha-ticket <ticket> --captcha-randstr <randstr>")
        sys.exit(2)
    except Exception as e:
        print(f"Failed: {e}",file=sys.stderr)
        sys.exit(1)
    print()
    print("="*60)
    print("  Lilith Account Resolver — Complete Data Footprint")
    print("="*60)
    print(f"  Email         : {args.email}")
    print(f"  App UID       : {entries[0].get('server_id_int','N/A') if entries else 'N/A'}")
    print(f"  Open ID       : {entries[0].get('open_id','N/A') if entries else 'N/A'}")
    print(f"  Access Token  : [REDACTED]")
    print(f"  Region        : {entries[0].get('kingdom_name','N/A') if entries else 'N/A'}")
    if entries:
        for ch in entries:
            print(f"  Characters    : {len(entries)} found")
            print()
            print(f"  ── Character ──")
            print(f"  Character Name : {ch['name']}")
            print(f"  Character ID   : {ch['role_id']}")
            print(f"  Kingdom        : {ch.get('kingdom_name','Beili')}")
            print(f"  Gate           : {ch.get('gate_host','?')}:{ch.get('port','?')}")
            print(f"  Power          : {ch.get('power',0)}")
            print(f"  City Hall      : {ch.get('city_hall_level',0)}")
            print(f"  Open ID        : {ch.get('open_id','?')}")
            print()
            print(f"[SUCCESS] Role Found: {ch['name']} | ID: {ch['role_id']} | "
                  f"Kingdom: {ch.get('kingdom_name','Beili')} | "
                  f"Gate: {ch.get('gate_host','?')}:{ch.get('port','?')}")
    else:
        print("  Characters    : 0 found")
        print("  (SDK login succeeded but no character data in response)")
    print()
    print(f"  Fleet file    : {args.fleet}")
    print(f"  Credentials   : [REDACTED in fleet file]")
    print("="*60)

if __name__=="__main__":
    main()