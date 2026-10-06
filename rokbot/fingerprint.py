"""
FingerprintGenerator — Dynamically generate realistic, non-repeating
hardware signatures to defeat Anti-Abuse cascade banning.

Each account gets a unique but structurally valid device identity that is
persisted statically across reconnects. The fingerprints match the game's
embedded limpc/launcher parameters observed in production captures.

Per-account fields (user_agent, env_id, sdk_session_id) are fully randomized
per seed to prevent structural fingerprint correlation across accounts.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict

PROJECT_ROOT = Path(__file__).resolve().parent.parent

GPU_BRANDS = [
    "NVIDIA GeForce RTX 3050", "NVIDIA GeForce RTX 3060", "NVIDIA GeForce RTX 3070",
    "NVIDIA GeForce RTX 3080", "NVIDIA GeForce RTX 3090", "NVIDIA GeForce RTX 4060",
    "NVIDIA GeForce RTX 4070", "NVIDIA GeForce RTX 4080", "NVIDIA GeForce RTX 4090",
    "NVIDIA GeForce GTX 1650", "NVIDIA GeForce GTX 1660 SUPER", "NVIDIA GeForce GTX 1060",
    "AMD Radeon RX 6600", "AMD Radeon RX 6700 XT", "AMD Radeon RX 6800 XT",
    "AMD Radeon RX 6900 XT", "AMD Radeon RX 7600", "AMD Radeon RX 7700 XT",
]

CPUS = [
    "12th Gen Intel(R) Core(TM) i5-12400", "12th Gen Intel(R) Core(TM) i5-12600K",
    "12th Gen Intel(R) Core(TM) i7-12700K", "12th Gen Intel(R) Core(TM) i9-12900K",
    "13th Gen Intel(R) Core(TM) i5-13600K", "13th Gen Intel(R) Core(TM) i7-13700K",
    "13th Gen Intel(R) Core(TM) i9-13900K", "11th Gen Intel(R) Core(TM) i5-11400",
    "11th Gen Intel(R) Core(TM) i7-11700K", "AMD Ryzen 5 5600X", "AMD Ryzen 7 5800X",
    "AMD Ryzen 7 5800X3D", "AMD Ryzen 9 5900X", "AMD Ryzen 5 7600X",
    "AMD Ryzen 7 7700X", "AMD Ryzen 9 7900X", "AMD Ryzen 9 7950X",
]

OS_VERSIONS = ["10.0.22621", "10.0.22631", "10.0.19045", "10.0.22000", "10.0.26100"]

MEM_SIZES = ["8 GB", "12 GB", "16 GB", "24 GB", "32 GB", "48 GB", "64 GB"]


def _rand_hex(n: int) -> str:
    return "".join(random.choices("0123456789abcdef", k=n))


def _rand_uuid4() -> str:
    return str(uuid.UUID(bytes=os.urandom(16), version=4))


def _deterministic_hwid(seed_material: str) -> str:
    """Generate a deterministic HWID from seed material (account email/name)."""
    h = hashlib.sha256(seed_material.encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}".upper()


@dataclass
class DeviceFingerprint:
    device_name: str = ""
    device_model: str = "win"
    device_brand: str = ""
    device_abi: str = "x86-64"
    os_version: str = ""
    device_id: str = ""
    install_id: str = ""
    idfa: str = ""
    gpu_name: str = ""
    cpu_name: str = ""
    ram_size: str = ""
    mainboard_serial: str = ""
    disk_serial: str = ""
    user_agent: str = ""
    env_id: str = ""
    sdk_session_id: str = ""
    custom_data: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_headers_dict(self) -> dict:
        """Return fields that map to HTTP header form values."""
        return {
            "device_name": self.device_name,
            "device_model": self.device_model,
            "device_brand": self.device_brand,
            "device_abi": self.device_abi,
            "device_id": self.device_id,
            "os_version": self.os_version,
            "install_id": self.install_id,
            "idfa": self.idfa,
        }


class FingerprintGenerator:
    """
    Generates realistic Windows environment fingerprints for the game's
    authentication API, preventing structural fingerprint detection.

    Each account gets a unique but internally consistent device identity.
    Fingerprints are deterministic per seed (email/profile_name) so they
    remain stable across reconnects.
    """

    FINGERPRINTS_FILE = PROJECT_ROOT / "fingerprints.json"

    def __init__(self):
        self._cache: Dict[str, DeviceFingerprint] = {}
        self._load_cache()

    def _load_cache(self):
        if self.FINGERPRINTS_FILE.exists():
            try:
                data = json.loads(self.FINGERPRINTS_FILE.read_text(encoding="utf-8"))
                for name, fp_data in data.items():
                    self._cache[name] = DeviceFingerprint(**fp_data)
            except Exception:
                self._cache.clear()

    def _save_cache(self):
        data = {name: asdict(fp) for name, fp in self._cache.items()}
        self.FINGERPRINTS_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def get_fingerprint(self, account_id: str) -> DeviceFingerprint:
        """Get or generate a persistent fingerprint for an account."""
        if account_id in self._cache:
            return self._cache[account_id]
        fp = self._generate(account_id)
        self._cache[account_id] = fp
        self._save_cache()
        return fp

    def _generate(self, account_id: str) -> DeviceFingerprint:
        seed = account_id
        rng = random.Random(hashlib.sha256(seed.encode()).hexdigest())

        hwid = _deterministic_hwid(seed + "_hwid")
        # Real format: UUID-TIMESTAMP (e.g. D8A25671-E7B3-4c30-8F0D-D9A47D7059A3-1783452778)
        install_id = f"{hwid}-{random.randint(1000000000, 9999999999)}"

        device_name = f"DESKTOP-{_rand_hex(4).upper()}{_rand_hex(2).upper()}"

        gpu = rng.choice(GPU_BRANDS)
        cpu = rng.choice(CPUS)
        os_ver = rng.choice(OS_VERSIONS)
        ram = rng.choice(MEM_SIZES)

        gpu_short = gpu.split(" ")[-1] if len(gpu.split(" ")) > 2 else gpu
        brand_parts = gpu.split(" ")[:2]
        brand = " ".join(brand_parts)

        cpu_family = cpu.split(" ")[0]
        if "Intel" in cpu:
            mb_brand = rng.choice(["ASUSTeK", "MSI", "Gigabyte", "ASRock", "EVGA"])
            mb_chipset = rng.choice(['560', '660', '760'])
            mb_suffix = rng.choice(['DS3H', 'PRO-VDH', 'GAMING X', 'ELITE'])
            mb_model = f"{mb_brand}-B{mb_chipset}M-{mb_suffix}"
        else:
            mb_brand = rng.choice(["ASUSTeK", "MSI", "Gigabyte", "ASRock"])
            mb_model = f"{mb_brand}-B{rng.choice(['550', '650'])}M-{rng.choice(['PRO-VDH', 'GAMING', 'ELITE'])}"

        mainboard_serial = f"{_rand_hex(4).upper()}{random.randint(1000, 9999)}"
        disk_serial = f"WD_{_rand_hex(8).upper()}"

        # Real format: vUUID (e.g. v26698f7b2-24d7-41a3-a76f-cd74260794f8)
        idfa_uuid = _rand_uuid4()
        idfa = f"v{idfa_uuid}"

        # Per-account Limpc launcher version (varies to match real traffic)
        la_version = f"limpc-{rng.randint(1,4)}.0.{rng.randint(1,30)}.{rng.randint(0,9)}"

        # Per-account env_id (unique production environment identifier)
        env_id = _rand_hex(26)

        # Per-account SDK session (already unique)
        sdk_session_id = _rand_hex(32).upper()

        fp = DeviceFingerprint(
            device_name=device_name,
            device_model="win",
            device_brand=mb_model,
            device_abi="x86-64",
            os_version=os_ver,
            device_id=hwid,
            install_id=install_id,
            idfa=idfa,
            gpu_name=gpu,
            cpu_name=cpu,
            ram_size=ram,
            mainboard_serial=mainboard_serial,
            disk_serial=disk_serial,
            user_agent=la_version,
            env_id=env_id,
            sdk_session_id=sdk_session_id,
            custom_data={
                "gpu_short": gpu_short,
                "brand": brand,
                "cpu_family": cpu_family,
                "mb_brand": mb_brand,
            },
        )
        return fp

    def get_login_overrides(self, account_id: str) -> Dict[str, str]:
        """
        Return form body overrides for the email_login API that match
        this account's unique fingerprint.
        """
        fp = self.get_fingerprint(account_id)
        return {
            "device_name": fp.device_name,
            "device_model": fp.device_model,
            "device_brand": fp.device_brand,
            "device_abi": fp.device_abi,
            "os_version": fp.os_version,
            "idfa": fp.idfa,
            "install_id": fp.install_id,
            "sdk_session_id": fp.sdk_session_id,
        }

    def get_tcp_client_info(self, account_id: str) -> bytes:
        """
        Build the client-info protobuf bytes that match this fingerprint.
        Used as the login inner field 7 sub-fields to emulate MASS.exe.
        """
        fp = self.get_fingerprint(account_id)
        return fp.device_name.encode("utf-8")
