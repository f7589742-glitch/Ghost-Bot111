"""
proxy_manager.py - Automated Pre-Flight Proxy Security Validator & Residential Guardrail Engine.

Enforces strict IP-type criteria before allowing any proxy to be assigned or used by the bot fleet:
- Rejects any Datacenter, Hosting, or Public VPN IP (causes Error 11006 anti-cheat ban).
- Only permits verified Residential (ISP) or Mobile (4G/5G) connections.
- Validates via ipinfo.io and fallback provider (ip-api.com).
"""

from __future__ import annotations

import logging
from typing import Dict, Any, Optional
import aiohttp

logger = logging.getLogger("ProxyManager")


async def validate_proxy_safety(proxy: dict) -> bool:
    """
    Validates that a proxy is NOT a Datacenter, Hosting, or Public VPN IP.
    Only allows Residential (ISP) or Mobile proxies.
    """
    if not proxy or not isinstance(proxy, dict):
        return False

    host = proxy.get("host") or ""
    port = proxy.get("port") or 1080
    user = proxy.get("username") or ""
    pw = proxy.get("password") or ""

    if not host:
        return False

    proto = proxy.get("protocol") or proxy.get("type") or "http"
    if user and pw:
        proxy_url = f"http://{user}:{pw}@{host}:{port}"
    else:
        proxy_url = f"http://{host}:{port}"

    test_url = "https://ipinfo.io/json"

    try:
        timeout = aiohttp.ClientTimeout(total=7.0)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(test_url, proxy=proxy_url) as resp:
                if resp.status == 200:
                    data = await resp.json()

                    as_type = str(data.get("company", {}).get("type", "")).lower()
                    org = str(data.get("org", "")).lower()
                    is_bogon = bool(data.get("bogon", False))
                    privacy = data.get("privacy", {})
                    is_vpn = bool(
                        privacy.get("vpn", False)
                        or privacy.get("hosting", False)
                        or privacy.get("proxy", False)
                    )

                    # STRICT REJECTION CRITERIA
                    if "hosting" in as_type or is_vpn or is_bogon or "datacenter" in as_type or "hosting" in org:
                        print(f"🚨 [SECURITY REJECT] Proxy {host} is DATACENTER/VPN ({as_type} | {org}). Rejected to prevent bans!")
                        logger.warning(f"[SECURITY REJECT] Proxy {host} rejected: as_type={as_type}, is_vpn={is_vpn}, org={org}")
                        return False

                    print(f"✅ [SECURITY PASS] Proxy {host} verified as RESIDENTIAL/MOBILE (Type: {as_type or 'isp'}).")
                    return True
                else:
                    # Try secondary check via ip-api
                    fallback_url = f"http://ip-api.com/json?fields=status,message,country,isp,org,as,mobile,proxy,hosting,query"
                    async with session.get(fallback_url, proxy=proxy_url) as fb_resp:
                        if fb_resp.status == 200:
                            fb_data = await fb_resp.json()
                            is_hosting = bool(fb_data.get("hosting", False))
                            is_proxy = bool(fb_data.get("proxy", False))
                            isp_name = str(fb_data.get("isp", "")).lower()

                            if is_hosting or is_proxy or "hosting" in isp_name or "amazon" in isp_name:
                                print(f"🚨 [SECURITY REJECT] Proxy {host} is DATACENTER/HOSTING via ip-api. Rejected!")
                                return False

                            print(f"✅ [SECURITY PASS] Proxy {host} verified via fallback.")
                            return True
                        return False
    except Exception as e:
        print(f"⚠️ [PROXY VALIDATOR ERROR] Could not verify {host}: {e}")
        logger.error(f"[PROXY VALIDATOR ERROR] {host}: {e}")
        return False
