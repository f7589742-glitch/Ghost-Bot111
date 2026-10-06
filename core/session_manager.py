"""
session_manager.py — Persist and manage fresh auth token profiles.

Pipeline:
  1. Frida hook_limpc_fresh.js captures {access_token, app_token, app_uid}
  2. This module saves them to a named profile (JSON + IPC heartbeat)
  3. Consumers (headless_client.py, bots) load the profile and construct
     the login protobuf with the fresh token.

Token lifecycle:
  - app_token_expire_at: Unix seconds when the token expires (~27 days)
  - The token is single-use per TCP connection (server drops replay)
  - After consumption, the caller MUST invalidate locally so stale
    tokens are not retried
"""

import json
import os
import time
import logging
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any

logger = logging.getLogger("session_manager")

PROFILES_DIR = Path(__file__).resolve().parent.parent / "profiles"
IPC_FILE = Path(__file__).resolve().parent.parent / "session.ipc"


@dataclass
class TokenProfile:
    """A single captured token profile with crypto seeds."""
    access_token: str = ""
    app_token: str = ""
    app_uid: str = ""
    app_token_expire_at: int = 0
    seed1: int = 0
    seed2: int = 0
    captured_at: float = 0.0
    consumed: bool = False
    profile_name: str = "default"

    @property
    def is_valid(self) -> bool:
        if not self.access_token or not self.app_token or not self.app_uid:
            return False
        if self.consumed:
            return False
        if self.app_token_expire_at > 0 and time.time() > self.app_token_expire_at:
            return False
        return True

    @property
    def expires_in_days(self) -> float:
        if self.app_token_expire_at <= 0:
            return float("inf")
        remaining = self.app_token_expire_at - time.time()
        return remaining / 86400


class SessionManager:
    """Manages token profile save/load/invalidation."""

    def __init__(self, profile_name: str = "default"):
        self.profile_name = profile_name
        self._profile: Optional[TokenProfile] = None
        PROFILES_DIR.mkdir(parents=True, exist_ok=True)

    # ── Public API ───────────────────────────────────────────────────

    def save_tokens(self, tokens: Dict[str, Any]) -> TokenProfile:
        """
        Save a token dict received from the Frida hook.
        tokens: {access_token, app_token, app_uid, app_token_expire_at?,
                 seed1?, seed2?, ...}
        """
        profile = TokenProfile(
            access_token=tokens.get("access_token", ""),
            app_token=tokens.get("app_token", ""),
            app_uid=str(tokens.get("app_uid", "")),
            app_token_expire_at=tokens.get("app_token_expire_at", 0),
            seed1=tokens.get("seed1", 0),
            seed2=tokens.get("seed2", 0),
            captured_at=time.time(),
            consumed=False,
            profile_name=self.profile_name,
        )

        path = PROFILES_DIR / f"{self.profile_name}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(profile), f, indent=2)

        # Also write IPC heartbeat
        self._write_ipc(profile)

        logger.info(
            f"Token profile saved → {path}  "
            f"(expires in {profile.expires_in_days:.1f}d)"
        )

        self._profile = profile
        return profile

    def load_profile(self, profile_name: Optional[str] = None) -> Optional[TokenProfile]:
        """Load a previously saved profile."""
        name = profile_name or self.profile_name
        path = PROFILES_DIR / f"{name}.json"

        if not path.exists():
            logger.warning(f"Profile not found: {path}")
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            known = {f.name for f in TokenProfile.__dataclass_fields__.values()}
            profile = TokenProfile(**{k: v for k, v in data.items() if k in known})
            self._profile = profile

            if profile.is_valid:
                logger.info(
                    f"Loaded profile '{name}'  "
                    f"(expires in {profile.expires_in_days:.1f}d)"
                )
            else:
                reason = "expired" if profile.expires_in_days <= 0 else \
                         "consumed" if profile.consumed else "incomplete"
                logger.warning(f"Profile '{name}' is invalid ({reason})")

            return profile
        except Exception as e:
            logger.error(f"Failed to load profile '{name}': {e}")
            return None

    def mark_consumed(self, profile_name: Optional[str] = None):
        """Mark a profile as consumed (token used on one TCP connection)."""
        profile = self.load_profile(profile_name)
        if profile:
            profile.consumed = True
            path = PROFILES_DIR / f"{profile.profile_name}.json"
            with open(path, "w", encoding="utf-8") as f:
                json.dump(asdict(profile), f, indent=2)
            logger.info(f"Profile '{profile.profile_name}' marked consumed")

    def list_profiles(self) -> list[Dict[str, Any]]:
        """List all saved profiles with validity status."""
        results = []
        for p in PROFILES_DIR.glob("*.json"):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                profile = TokenProfile(**data)
                results.append({
                    "name": profile.profile_name,
                    "valid": profile.is_valid,
                    "consumed": profile.consumed,
                    "expires_in_days": round(profile.expires_in_days, 1),
                    "uid": profile.app_uid,
                    "captured_at": profile.captured_at,
                })
            except Exception as e:
                results.append({"name": p.stem, "error": str(e)})
        return results

    def get_valid_profile(self) -> Optional[TokenProfile]:
        """Return the first valid (non-consumed, non-expired) profile."""
        for p in PROFILES_DIR.glob("*.json"):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                profile = TokenProfile(**data)
                if profile.is_valid:
                    return profile
            except Exception:
                continue
        return None

    # ── Internals ────────────────────────────────────────────────────

    def _write_ipc(self, profile: TokenProfile):
        """Write IPC file for the Frida launcher / bot to read."""
        try:
            ipc_data = {
                "access_token": profile.access_token,
                "app_token": profile.app_token,
                "app_uid": profile.app_uid,
                "captured_at": profile.captured_at,
                "expires_at": profile.app_token_expire_at,
                "profile": profile.profile_name,
            }
            with open(IPC_FILE, "w", encoding="utf-8") as f:
                json.dump(ipc_data, f)
            logger.debug(f"IPC written → {IPC_FILE}")
        except Exception as e:
            logger.error(f"IPC write failed: {e}")


# ── Standalone helpers ───────────────────────────────────────────────

def save_tokens_from_frida(tokens: dict, profile: str = "default") -> TokenProfile:
    """Convenience: called by the launcher when Frida fires 'tokens' event."""
    mgr = SessionManager(profile)
    return mgr.save_tokens(tokens)


def get_latest_tokens() -> Optional[dict]:
    """Return the most recent valid token dict, or None."""
    mgr = SessionManager()
    profile = mgr.get_valid_profile()
    if profile:
        return asdict(profile)
    return None


# ── CLI quick-check ──────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    mgr = SessionManager()

    profiles = mgr.list_profiles()
    print(f"Profiles found: {len(profiles)}")
    for p in profiles:
        status = "VALID" if p.get("valid") else "INVALID"
        print(f"  [{status}] {p['name']}  uid={p.get('uid','?')}  "
              f"expires={p.get('expires_in_days','?')}d")

    valid = mgr.get_valid_profile()
    if valid:
        print(f"\nActive profile: {valid.profile_name}")
        print(f"  access_token: {valid.access_token[:30]}...")
        print(f"  app_token:    {valid.app_token[:30]}...")
        print(f"  app_uid:      {valid.app_uid}")
        print(f"  expires:      {valid.expires_in_days:.1f}d")
    else:
        print("\nNo valid profile available. Launch the game and log in.")
