"""
Deploy web-platform/ to Vercel project "zero-bot" via the REST API
(v13 deployments — files upload flow), bypassing the CLI's whoami
which fails for scoped tokens.

Usage: python deploy_vercel_api.py
"""
import base64
import hashlib
import json
import os
import time
import urllib.request

TOKEN = "vcp_84mR4rBgVJIgGHNdhOaraQMojHolhzy2a4rEQ9XVao80yz8WMT435nsX"
PROJECT = "zero-bot"
PROJECT_ID = "prj_ExR6zbNozHOOXJUqQ8D42zo17414"
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web-platform")

# Match the GitHub build: project root is the repo root of ZeroBot, whose
# contents equal this local web-platform/ folder.
SKIP_DIRS = {".next", "node_modules", ".git", ".vercel", "supabase"}
SKIP_FILES = {".env", ".env.local", ".gitignore", "tsconfig.tsbuildinfo"}


class ApiError(Exception):
    def __init__(self, status, body):
        super().__init__(f"HTTP {status}: {body[:500]}")
        self.status = status
        self.body = body


def api(method: str, path: str, body=None, is_json: bool = True):
    req = urllib.request.Request(
        f"https://api.vercel.com{path}",
        method=method,
        headers={"Authorization": f"Bearer {TOKEN}"},
        data=json.dumps(body).encode() if body is not None and is_json else body,
    )
    if body is not None and is_json:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        raise ApiError(e.code, e.read().decode(errors="replace"))
    return json.loads(data) if data else {}


def collect_files():
    files = []
    root_supabase = os.path.join(ROOT, "supabase")
    for dirpath, dirnames, filenames in os.walk(ROOT):
        # Skip heavy/irrelevant dirs — but only the ROOT supabase/ (migrations),
        # NOT src/lib/supabase/ which holds real app code.
        dirnames[:] = [
            d for d in dirnames
            if d not in {".next", "node_modules", ".git", ".vercel"}
            and os.path.join(dirpath, d) != root_supabase
        ]
        for name in filenames:
            if name in SKIP_FILES or name.endswith(".pyc"):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, ROOT).replace("\\", "/")
            with open(full, "rb") as f:
                raw = f.read()
            files.append({
                "path": rel,
                "size": len(raw),
                "sha": hashlib.sha1(raw).hexdigest(),
                "data": base64.b64encode(raw).decode(),
            })
    return files


def main():
    print("[1/4] Collecting files…")
    files = collect_files()
    print(f"      {len(files)} files, {sum(f['size'] for f in files) // 1024} KB")

    print("[2/4] Uploading missing files…")
    for f in files:
        req = urllib.request.Request(
            "https://api.vercel.com/v2/files",
            method="POST",
            headers={
                "Authorization": f"Bearer {TOKEN}",
                "Content-Type": "application/octet-stream",
                "x-vercel-digest": f["sha"],
            },
            data=base64.b64decode(f["data"]),
        )
        with urllib.request.urlopen(req) as r:
            if r.status not in (200, 409):
                raise RuntimeError(f"upload failed {r.status} for {f['path']}")
    print("      uploads done")

    print("[3/4] Creating production deployment…")
    payload = {
        "name": PROJECT,
        "project": PROJECT_ID,
        "target": "production",
        "files": [{"file": f["path"], "size": f["size"], "sha": f["sha"]} for f in files],
        "meta": {"source": "local-web-platform"},
    }
    try:
        dep = api("POST", "/v13/deployments", payload)
    except ApiError as e:
        print("      deploy rejected:", e.body[:800])
        raise SystemExit(1)
    uid = dep.get("id") or dep.get("uid")
    print(f"      deployment: {uid} ({dep.get('url')})")

    print("[4/4] Waiting for build…")
    for _ in range(120):
        time.sleep(5)
        d = api("GET", f"/v13/deployments/{uid}")
        state = d.get("state") or d.get("readyState")
        print(f"      {state}")
        if state in ("READY", "ERROR", "CANCELED"):
            break
    print("URL:", d.get("url"))
    print("ALIASES:", d.get("alias"))
    if state != "READY":
        logs = api("GET", f"/v2/deployments/{uid}/events?limit=100")
        events = logs if isinstance(logs, list) else logs.get("events", [])
        for e in events:
            t = e.get("payload", {}).get("text", "") or e.get("payload", {}).get("message", "")
            if t and any(k in t.lower() for k in ["error", "failed", "cannot", "exit", "missing"]):
                print(t[:400])
        raise SystemExit(1)


if __name__ == "__main__":
    main()
