"""Per-account proxy allocation pool (Phase 2 anti-detection).

Rules:
- At most MAX_PER_PROXY accounts share one proxy URL (default 10).
- Assignments are sticky per email and persisted as JSON on disk.
- Empty pool (today: no proxies purchased) -> assign() returns None and the
  account runs direct. Socket-layer tunneling rides on this assignment in a
  later phase, so no rework is needed when proxies arrive.

Store shape: {"proxies": [url, ...], "assign": {email_lower: url}}
"""
from __future__ import annotations

import json
import os

MAX_PER_PROXY = 10

_DEFAULT_PATH = os.path.join(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")),
    "proxies.json",
)
POOL_PATH = os.environ.get("PROXY_POOL_PATH", _DEFAULT_PATH)


def _coerce_url(e) -> str | None:
    if isinstance(e, str) and e.strip():
        return e.strip()
    if isinstance(e, dict) and e.get("host") not in (None, "", "1.2.3.4"):
        u = f"{e.get('type', 'socks5')}://"
        if e.get("username"):
            u += f"{e['username']}:{e.get('password', '')}@"
        u += f"{e['host']}:{e.get('port', 1080)}"
        return u
    return None


def _load() -> dict:
    try:
        with open(POOL_PATH, encoding="utf-8") as f:
            data = json.load(f) or {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        # Legacy flat list -> dict shape.
        data = {"proxies": data if isinstance(data, list) else [], "assign": {}}
    clean: list = []
    for e in data.get("proxies", []):
        u = _coerce_url(e)
        if u and u not in clean:
            clean.append(u)
    data["proxies"] = clean
    if not isinstance(data.get("proxies"), list):
        data["proxies"] = []
    if not isinstance(data.get("assign"), dict):
        data["assign"] = {}
    return data


def _save(data: dict) -> None:
    tmp = POOL_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, POOL_PATH)


def _counts(data: dict) -> dict:
    counts = {u: 0 for u in data["proxies"]}
    for url in data["assign"].values():
        if url in counts:
            counts[url] += 1
    return counts


def add_proxy(url: str) -> dict:
    data = _load()
    url = (url or "").strip()
    if url and url not in data["proxies"]:
        data["proxies"].append(url)
        _save(data)
    return status()


def remove_proxy(url: str) -> dict:
    data = _load()
    if url in data["proxies"]:
        data["proxies"].remove(url)
    data["assign"] = {e: u for e, u in data["assign"].items() if u != url}
    _save(data)
    return status()


def assign(email: str) -> str | None:
    """Sticky proxy for an account, or None when the pool is empty/full."""
    key = (email or "").strip().lower()
    if not key:
        return None
    data = _load()
    if key in data["assign"] and data["assign"][key] in data["proxies"]:
        return data["assign"][key]
    counts = _counts(data)
    candidates = [(c, u) for u, c in counts.items() if c < MAX_PER_PROXY]
    if not candidates:
        return None
    candidates.sort()
    chosen = candidates[0][1]
    data["assign"][key] = chosen
    _save(data)
    return chosen


def release(email: str) -> None:
    key = (email or "").strip().lower()
    data = _load()
    if key in data["assign"]:
        del data["assign"][key]
        _save(data)


def public_form(url: str | None) -> str | None:
    """Credential-stripped host:port for API responses and cloud mirrors."""
    if not url:
        return None
    try:
        import urllib.parse
        u = urllib.parse.urlparse(url if "://" in url else f"http://{url}")
        return u.host + (f":{u.port}" if u.port else "") if u.host else None
    except Exception:
        return None


def status() -> dict:
    data = _load()
    counts = _counts(data)
    unassigned = [e for e, u in data["assign"].items() if u not in data["proxies"]]
    return {
        "max_per_proxy": MAX_PER_PROXY,
        "proxies": [{"url": u, "accounts": counts[u]} for u in data["proxies"]],
        "assigned_total": len(data["assign"]) - len(unassigned),
        "path": POOL_PATH,
    }
