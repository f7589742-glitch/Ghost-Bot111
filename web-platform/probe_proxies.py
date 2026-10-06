"""Proxy connectivity matrix: every pooled proxy -> rocgate:3101 via each method."""
import asyncio
import json
import sys
import time

sys.path.insert(0, "/home/ubuntu/bot-backend")
from app.services.proxy_pool import _load  # noqa: E402
from app.services.proxy_transport import open_via_proxy, _parse  # noqa: E402


async def probe(url: str) -> dict:
    out = {"proxy": url.split("@")[-1], "socks5": None, "http": None}
    for method in ("socks5", "http"):
        t0 = time.time()
        try:
            p = _parse(url)
            reader, writer = await asyncio.open_connection(p["host"], p["port"])
            from app.services.proxy_transport import _socks5_handshake, _http_connect_handshake
            if method == "socks5":
                await asyncio.wait_for(
                    _socks5_handshake(reader, writer, "rocgate.lilithgame.com", 3101, p["user"], p["pw"]),
                    timeout=12)
            else:
                await asyncio.wait_for(
                    _http_connect_handshake(reader, writer, "rocgate.lilithgame.com", 3101, p["user"], p["pw"]),
                    timeout=12)
            writer.close()
            out[method] = f"OPEN {time.time()-t0:.2f}s"
        except Exception as e:  # noqa: BLE001
            out[method] = f"FAIL {type(e).__name__}"
    return out


async def main():
    data = _load()
    print(json.dumps([await probe(u) for u in data["proxies"]], indent=1))


asyncio.run(main())
