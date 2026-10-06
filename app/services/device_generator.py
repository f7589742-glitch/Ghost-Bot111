# app/services/device_generator.py
"""
Hardware Fingerprint & Device Profile Generator.
Generates unique, realistic, persistent Android hardware identities per account.
Prevents Lilith Anti-Abuse cascade flags (Code 11005 register_risk).
"""
import os
import json
import random
import hashlib
import uuid
from typing import Dict, Any, Optional

DEVICE_POOL = [
    {"brand": "Samsung", "model": "SM-S918B", "name": "Galaxy S23 Ultra", "os": "13", "res": "1440x3088", "dpi": 500},
    {"brand": "Samsung", "model": "SM-G998B", "name": "Galaxy S21 Ultra", "os": "12", "res": "1440x3200", "dpi": 515},
    {"brand": "Samsung", "model": "SM-A546B", "name": "Galaxy A54", "os": "13", "res": "1080x2340", "dpi": 403},
    {"brand": "Google", "model": "Pixel 7 Pro", "name": "Pixel 7 Pro", "os": "13", "res": "1440x3120", "dpi": 512},
    {"brand": "Google", "model": "Pixel 8", "name": "Pixel 8", "os": "14", "res": "1080x2400", "dpi": 428},
    {"brand": "Xiaomi", "model": "2210132G", "name": "Xiaomi 13 Pro", "os": "13", "res": "1440x3200", "dpi": 522},
    {"brand": "Xiaomi", "model": "23049PCD8G", "name": "POCO F5 Pro", "os": "13", "res": "1440x3200", "dpi": 526},
    {"brand": "OnePlus", "model": "CPH2449", "name": "OnePlus 11", "os": "13", "res": "1440x3216", "dpi": 525},
    {"brand": "Sony", "model": "XQ-DQ72", "name": "Xperia 1 V", "os": "13", "res": "1644x3840", "dpi": 643}
]

BUILD_IDS = [
    "TP1A.220624.014",
    "TP1A.220905.001",
    "TQ3A.230805.001",
    "TQ3A.230901.001",
    "UP1A.231005.007",
    "SP1A.210812.016"
]

# Static Lilith SDK Environment ID for the official RoK Android client.
# Intercepted 2026-09-10: IDENTICAL in all 7 official /v2/api/sdk/login
# POSTs (type=1 and type=7). Random values are rejected with
# "env_id not valid (Code 1001)". NOTE: this is the LOGIN-FORM field;
# the Forum API uses a different envId (d3e82cf85ffcf36b92d3f9996f7c6f3c).
OFFICIAL_LOGIN_ENV_ID = "prod59355cd51a219778b7489ab7c3c1"

class DeviceGenerator:
    @staticmethod
    def generate(email: Optional[str] = None) -> Dict[str, Any]:
        """
        Generates a persistent mobile device fingerprint.
        If email is provided, uses deterministic hashing so the profile remains
        consistent for the same account unless regenerated.
        """
        if email:
            seed_val = int(hashlib.sha256(email.strip().lower().encode()).hexdigest()[:8], 16)
            rng = random.Random(seed_val)
            udid_raw = hashlib.md5(f"rok_cloud_{email.strip().lower()}_udid".encode()).hexdigest().upper()
        else:
            rng = random.Random()
            udid_raw = hashlib.md5(uuid.uuid4().bytes).hexdigest().upper()

        dev = rng.choice(DEVICE_POOL)
        build_id = rng.choice(BUILD_IDS)
        
        user_agent = f"Dalvik/2.1.0 (Linux; U; Android {dev['os']}; {dev['model']} Build/{build_id})"

        profile = {
            "udid": udid_raw,
            "brand": dev["brand"],
            "model": dev["model"],
            "device_name": dev["name"],
            "os_version": dev["os"],
            "resolution": dev["res"],
            "dpi": dev["dpi"],
            "build_id": build_id,
            "user_agent": user_agent,
            "mac_address": ":".join([f"{rng.randint(0, 255):02x}" for _ in range(6)]),
            "android_id": hashlib.md5(uuid.uuid4().bytes).hexdigest()[:16]
        }
        return DeviceGenerator.ensure_sdk_fields(profile, email)

    @staticmethod
    def ensure_sdk_fields(profile: Dict[str, Any], email: Optional[str] = None) -> Dict[str, Any]:
        """
        Backfills Lilith SDK identity fields (captured from the official
        client) into older stored profiles. Deterministic per email so a
        backfilled value stays stable across calls even before persistence.
        """
        seed_src = (email or profile.get("udid") or uuid.uuid4().hex).strip().lower()
        dh = lambda tag: hashlib.md5(f"rok_cloud_{seed_src}_{tag}".encode()).hexdigest()
        rng = random.Random(int(hashlib.sha256(seed_src.encode()).hexdigest()[:8], 16))

        defaults = {
            # install_id format: <32hex>_<10digits>  (e.g. fa5db3..._1788562061)
            "install_id": f"{dh('install')}_{rng.randint(1700000000, 1799999999)}",
            "sdk_session_id": dh("sdk_session"),
            "google_aid": str(uuid.UUID(dh("gaid")[:32])),
            "env_id": OFFICIAL_LOGIN_ENV_ID,
            "gpu_model": "Adreno (TM) 750",
            "soc_model": "aosp-user",
            "device_abi": "arm64-v8a",
            "is_simulator": "false",
            "device_country_code": "US",
            "timezone": "Asia/Gaza",
            "system_language": "en",
            "lilith_language": "en",
            "lang": "2",
            "store_country": "",
            "mcc_codes": "",
            "mobile_channel": "official",
        }
        for k, v in defaults.items():
            if not profile.get(k):
                profile[k] = v
        # env_id is NOT per-device: force the static official value even over
        # previously stored random ones (they trigger Code 1001).
        profile["env_id"] = OFFICIAL_LOGIN_ENV_ID
        if not profile.get("android_id"):
            profile["android_id"] = dh("android")[:16]
        return profile
