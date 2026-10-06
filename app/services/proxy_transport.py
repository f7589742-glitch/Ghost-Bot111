"""Game-socket transport with per-account proxy support (Phase 2).

- Direct (proxy None): plain asyncio.open_connection (current behavior).
- Proxy: SOCKS5 CONNECT (RFC 1928, with username/password auth) or
  HTTP CONNECT tunneling, over asyncio streams. Returns (reader, writer)
  ready for the existing FrameParser/crypto pipeline — no caller changes
  beyond swapping the open call.
- Routing is per-asyncio-task via `use_proxy()` so engines inherit the
  account proxy automatically from the task entry point.

Webshare-style http://user:pass@host:port endpoints are treated as
tunnel endpoints (SOCKS5 first, HTTP CONNECT fallback).
"""
from __future__ import annotations

import asyncio
import base64
import contextvars
import struct
import urllib.parse

current_proxy: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "rok_proxy_url", default=None
)


class use_proxy:
    """Sync context manager binding a proxy URL for the current task."""

    def __init__(self, proxy_url: str | None):
        self.proxy_url = proxy_url
        self._token = None

    def __enter__(self):
        self._token = current_proxy.set(self.proxy_url)
        return self

    def __exit__(self, *exc):
        if self._token is not None:
            current_proxy.reset(self._token)
        return False


def _parse(proxy_url: str):
    u = urllib.parse.urlparse(proxy_url if "://" in proxy_url else f"socks5://{proxy_url}")
    return {
        "scheme": (u.scheme or "socks5").lower(),
        "host": u.hostname or "",
        "port": u.port or 1080,
        "user": urllib.parse.unquote(u.username or ""),
        "pw": urllib.parse.unquote(u.password or ""),
    }


async def _socks5_handshake(reader, writer, dest_host: str, dest_port: int, user: str, pw: str):
    methods = bytes([0x02]) + b"\x00\x02" if (user or pw) else b"\x00"
    writer.write(b"\x05" + bytes([len(methods)]) + methods)
    await writer.drain()
    ver, method = await reader.readexactly(2)
    if ver != 0x05:
        raise OSError(f"socks5 bad version {ver}")
    if method == 0x02:
        ub, pb = user.encode(), pw.encode()
        writer.write(b"\x01" + bytes([len(ub)]) + ub + bytes([len(pb)]) + pb)
        await writer.drain()
        v2, st = await reader.readexactly(2)
        if v2 != 0x01 or st != 0x00:
            raise OSError(f"socks5 auth failed status={st}")
    elif method != 0x00:
        raise OSError(f"socks5 no acceptable method ({method})")
    try:
        packed_ip = bytes(int(p) for p in dest_host.split("."))
        if len(packed_ip) == 4:
            addr = b"\x01" + packed_ip
        else:
            raise ValueError
    except ValueError:
        enc = dest_host.encode()
        addr = b"\x03" + bytes([len(enc)]) + enc
    writer.write(b"\x05\x01\x00" + addr + struct.pack(">H", dest_port))
    await writer.drain()
    ver, rep, _, atyp = await reader.readexactly(4)
    if ver != 0x05 or rep != 0x00:
        raise OSError(f"socks5 connect failed rep={rep}")
    if atyp == 0x01:
        await reader.readexactly(4 + 2)
    elif atyp == 0x03:
        (ln,) = await reader.readexactly(1)
        await reader.readexactly(ln + 2)
    elif atyp == 0x04:
        await reader.readexactly(16 + 2)
    else:
        raise OSError(f"socks5 bad atyp {atyp}")


async def _http_connect_handshake(reader, writer, dest_host: str, dest_port: int, user: str, pw: str):
    lines = [f"CONNECT {dest_host}:{dest_port} HTTP/1.1", f"Host: {dest_host}:{dest_port}"]
    if user or pw:
        tok = base64.b64encode(f"{user}:{pw}".encode()).decode()
        lines.append(f"Proxy-Authorization: Basic {tok}")
    writer.write(("\r\n".join(lines) + "\r\n\r\n").encode())
    await writer.drain()
    head = await reader.readuntil(b"\r\n\r\n")
    status = head.split(b"\r\n", 1)[0]
    if b" 200" not in status:
        raise OSError(f"http connect rejected: {status[:60]!r}")


async def open_via_proxy(proxy_url: str, dest_host: str, dest_port: int, timeout: float = 15.0):
    """Open a TCP stream to dest through the proxy. Returns (reader, writer)."""
    p = _parse(proxy_url)
    if not p["host"]:
        raise OSError("empty proxy host")
    methods = (
        ("socks5", "http") if p["scheme"].startswith("socks")
        else ("http", "socks5")
    )
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(p["host"], p["port"]), timeout=timeout
    )
    last_err: Exception | None = None
    for m in methods:
        try:
            if m == "socks5":
                await asyncio.wait_for(
                    _socks5_handshake(reader, writer, dest_host, dest_port, p["user"], p["pw"]),
                    timeout=timeout,
                )
            else:
                await asyncio.wait_for(
                    _http_connect_handshake(reader, writer, dest_host, dest_port, p["user"], p["pw"]),
                    timeout=timeout,
                )
            return reader, writer, m
        except Exception as e:  # noqa: BLE001 - try next method
            last_err = e
    writer.close()
    raise OSError(f"proxy {p['host']}:{p['port']} failed ({last_err})")


async def open_game_connection(host: str, port: int, proxy_url: str | None = None, timeout: float = 15.0):
    """Drop-in replacement for asyncio.open_connection for game sockets."""
    proxy = proxy_url if proxy_url is not None else current_proxy.get()
    if not proxy:
        return await asyncio.open_connection(host, port)
    reader, writer, _method = await open_via_proxy(proxy, host, port, timeout=timeout)
    return reader, writer


def requests_proxies(proxy_url: str | None = None) -> dict | None:
    """proxies= dict for requests calls (login/rocdir HTTPS via proxy)."""
    proxy = proxy_url if proxy_url is not None else current_proxy.get()
    if not proxy:
        return None
    return {"http": proxy, "https": proxy}
