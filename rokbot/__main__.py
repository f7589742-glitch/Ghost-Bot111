"""
CLI entry point for the RoK headless bot.

Usage:
    python -m rokbot status                          # Show all accounts
    python -m rokbot run --all                       # Run all accounts
    python -m rokbot run -p teez9334 -p teez8888     # Run specific accounts
    python -m rokbot login -p teez9334 --email x --password y
    python -m rokbot import-proxies proxies.txt
    python -m rokbot test-connection -p teez9334
    python -m rokbot capture-fingerprint -o fp.json  # Capture real device fingerprint
    python -m rokbot use-fingerprint -p teez8888 -f fp.json  # Apply captured fingerprint
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


async def cmd_status(args):
    from rokbot.account import AccountManager
    mgr = AccountManager()
    accounts = mgr.load_all()
    print(f"\nAccounts: {len(accounts)}")
    for a in accounts:
        has_token = bool(a.access_token or a.app_token)
        print(f"  {'[OK]' if has_token else '[--]'} {a.profile_name:<25} uid={a.app_uid:<15} region={a.region}")
    print()


async def cmd_run(args):
    from rokbot.orchestrator import run_orchestrator
    await run_orchestrator(
        account_names=args.profiles,
        proxy_file=args.proxy_file,
        max_concurrent=args.max_concurrent,
        status_interval=args.status_interval,
    )


async def cmd_login(args):
    from rokbot.account import AccountManager
    from rokbot.auth import AuthManager
    from rokbot.fingerprint import FingerprintGenerator

    fp_gen = FingerprintGenerator()
    auth = AuthManager(fp_gen)

    try:
        result = await auth.email_login(
            email=args.email,
            password=args.password,
            account_id=args.profile,
        )
        print("\nLogin successful:")
        print(f"  app_uid:      {result['app_uid']}")
        print(f"  access_token: {result['access_token'][:40]}...")
        print(f"  app_token:    {result['app_token'][:40]}...")
        print(f"  region:       {result['region']}")

        if not args.dry_run:
            mgr = AccountManager()
            account = mgr.load(args.profile)
            if not account:
                account = mgr.create(
                    name=args.profile,
                    email=args.email,
                    password=args.password,
                )
            account.app_uid = result["app_uid"]
            account.access_token = result["access_token"]
            account.app_token = result["app_token"]
            account.app_token_expire_at = result.get("app_token_expire_at", 0)
            account.region = result.get("region", "")
            mgr.save(account)
            print(f"  Saved to: profiles/{args.profile}.json")
    except Exception as e:
        print(f"Login failed: {e}")
    finally:
        await auth.close()


async def cmd_import_proxies(args):
    from rokbot.proxy import ProxyManager
    mgr = ProxyManager()
    mgr.add_proxies_from_file(args.file)
    print(f"Imported proxies. Pool size: {mgr.pool_size}")


async def cmd_test_connection(args):
    from rokbot.account import AccountManager
    from rokbot.network import GameConnection
    from rokbot.protocol import Frame

    mgr = AccountManager()
    account = mgr.load(args.profile)
    if not account:
        print(f"Profile not found: {args.profile}")
        return

    print(f"Testing connection for: {account.profile_name}")
    host, port = account.server_addr()
    print(f"Server: {host}:{port}")

    conn = GameConnection(host=host, port=port, account_id=account.profile_name)

    frames_received = []

    async def on_frame(frame: Frame):
        frames_received.append(frame)
        print(f"  RX: {frame}")

    conn.register_handler(on_frame)

    if not await conn.connect():
        print("TCP connect failed")
        return

    greeting = await conn.receive_greeting()
    if not greeting:
        print("Greeting failed")
        return

    print(f"Greeting OK: {greeting}")

    host, port = account.server_addr()
    server_str = f"{host}:{port}"
    if not await conn.send_login(account.effective_player_id, account.effective_token, server=server_str):
        print("Login send failed")
        return

    print("Login sent, waiting for data ...")
    initial = await conn.wait_for_initial_data(timeout=5.0)
    print(f"Initial frames: {len(initial)}")

    conn.start_receiving()
    await asyncio.sleep(3)
    await conn.disconnect()

    print(f"\nTotal frames received: {len(frames_received)}")
    print(f"Stats: {conn.stats()}")


async def cmd_commands(args):
    """List the command library (offline, no network)."""
    from rokbot.commands import CommandLibrary
    lib = CommandLibrary()
    stats = lib.stats()
    print(f"\nTotal commands: {stats['total_commands']}")
    for cat, names in sorted(lib._categories.items()):
        print(f"\n[{cat}] ({len(names)})")
        for n in sorted(names):
            cmd = lib.get(n)
            print(f"  {n:<22} op={cmd.msg_id:<6} {cmd.description}")
    print()


async def cmd_build(args):
    """Build a farming command offline and print its frame hex."""
    from rokbot.commands import COMMAND_BUILDERS, CommandLibrary
    from rokbot.protobuf import encode_message
    lib = CommandLibrary()
    cmd = lib.get(args.name)
    kwargs: dict = {}
    for p in args.param or []:
        if "=" not in p:
            print(f"Ignoring malformed --param (want k=v): {p}")
            continue
        k, v = p.split("=", 1)
        kwargs[k.strip()] = _parse_param_value(v.strip())
    if args.name == "auto_gather" and "city_pos" not in kwargs:
        kwargs.setdefault("alliance_id", args.alliance)
        kwargs.setdefault("node_id", args.node)
        kwargs.setdefault("city_pos", (args.city_x, args.city_y))
        kwargs.setdefault("node_pos", (args.target_x, args.target_y))
    if args.name == "gather_march":
        kwargs.setdefault("node_id", args.node)
        if "army" not in kwargs and args.army:
            kwargs["army"] = _parse_army(args.army)
    if args.name in ("train_infantry", "train_cavalry", "train_archer", "train_siege",
                     "train_troops") and "count" not in kwargs:
        kwargs.setdefault("count", args.count)
    try:
        if cmd is not None:
            op, payload = cmd.build_payload(**kwargs)
        elif args.name in COMMAND_BUILDERS:
            builder = COMMAND_BUILDERS[args.name]
            op, payload = builder(**kwargs) if kwargs else builder()
        else:
            print(f"Unknown command: {args.name}")
            print(f"Available: {', '.join(sorted(lib.all_names()))}")
            return
    except TypeError as e:
        print(f"Parameter error for '{args.name}': {e}")
        return
    frame = encode_message({1: op, 2: payload})
    print(f"op={op} payload={len(payload)}B frame={len(frame)}B")
    print(f"payload_hex={payload.hex()}")
    print(f"frame_hex={frame.hex()}")


def _parse_param_value(v: str):
    if "," in v and all(_is_number(x) for x in v.split(",")):
        parts = v.split(",")
        if len(parts) == 2:
            return (float(parts[0]), float(parts[1]))
        return [_to_number(x) for x in parts]
    return _to_number(v)


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def _to_number(s: str):
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return s


def _parse_army(s: str):
    """Parse 'unit:count,unit:count' into [(unit, count)]."""
    out = []
    for part in s.split(","):
        u, c = part.split(":")
        out.append((int(u.strip()), int(c.strip())))
    return out


async def cmd_decode(args):
    """Decode a hex frame offline via PacketDecoder (no network)."""
    from rokbot.decoder import GameState, PacketDecoder
    from rokbot.protobuf import decode_message
    raw = bytes.fromhex(args.hex.replace(" ", "").replace("\n", ""))
    # decode_frame expects the decrypted frame body ({1: opcode, 2: payload}).
    # If the hex includes the 2-byte BE length prefix, strip it first.
    payload = raw
    if len(raw) >= 2:
        prefixed_len = (raw[0] << 8) | raw[1]
        if prefixed_len == len(raw) - 2:
            payload = raw[2:]
    dec = PacketDecoder(GameState())
    result = dec.decode_frame(payload)
    print(f"\nop={result.get('opcode')} type={result.get('type')} size={result.get('size')}")
    for k, v in sorted(result.items()):
        if k in ("opcode", "type", "size", "timestamp"):
            continue
        print(f"  {k}: {v}")
    print()


async def cmd_capture_fingerprint(args):
    """Capture real device fingerprint from game client files."""
    output = args.output or str(PROJECT_ROOT / "fingerprints.json")
    captured = {}
    locations = [
        Path.home() / "AppData" / "Local" / "Lilith Games" / "ROK" / "config.json",
        Path.home() / "AppData" / "Local" / "Lilith Games" / "Rise of Kingdoms" / "config.ini",
        Path.home() / "AppData" / "LocalLow" / "Lilith Games" / "Rise of Kingdoms" / "player.dat",
    ]
    for loc in locations:
        if loc.exists():
            try:
                data = json.loads(loc.read_text(encoding="utf-8"))
                captured.update(data)
            except Exception:
                pass
    if captured:
        Path(output).write_text(json.dumps(captured, indent=2), encoding="utf-8")
        print(f"Fingerprint captured to {output}")
    else:
        print("No game client config found at known locations.")
        print("Manually export your device fingerprint and save to:")
        print(f"  {output}")


async def cmd_use_fingerprint(args):
    """Load a captured fingerprint for an account profile."""
    from rokbot.fingerprint import FingerprintGenerator
    fp_file = args.fingerprint_file or str(PROJECT_ROOT / "fingerprints.json")
    if not Path(fp_file).exists():
        print(f"Fingerprint file not found: {fp_file}")
        return
    try:
        data = json.loads(Path(fp_file).read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Failed to load fingerprint file: {e}")
        return
    fg = FingerprintGenerator()
    fp = fg.get_fingerprint(args.profile)
    applied = 0
    for key, val in data.items():
        if hasattr(fp, key):
            setattr(fp, key, val)
            applied += 1
    fg._cache[args.profile] = fp
    fg._save_cache()
    print(f"Applied {applied} fingerprint fields to '{args.profile}'")
    print(f"  device_id:  {fp.device_id}")
    print(f"  install_id: {fp.install_id}")
    print(f"  user_agent: {fp.user_agent}")


def main():
    parser = argparse.ArgumentParser(
        description="RoK Headless Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="Show all accounts")

    run_p = sub.add_parser("run", help="Run bots")
    run_p.add_argument("-p", "--profiles", nargs="+", help="Account names (default: all)")
    run_p.add_argument("--proxy-file", help="Proxy list file")
    run_p.add_argument("--max-concurrent", type=int, default=200)
    run_p.add_argument("--status-interval", type=float, default=30.0)

    login_p = sub.add_parser("login", help="Email login")
    login_p.add_argument("-p", "--profile", required=True)
    login_p.add_argument("--email", required=True)
    login_p.add_argument("--password", required=True)
    login_p.add_argument("--dry-run", action="store_true")

    proxy_p = sub.add_parser("import-proxies", help="Import proxies")
    proxy_p.add_argument("file", help="Proxy list file")

    test_p = sub.add_parser("test-connection", help="Test TCP connection")
    test_p.add_argument("-p", "--profile", required=True)

    fp_p = sub.add_parser("capture-fingerprint", help="Capture real device fingerprint from game client")
    fp_p.add_argument("-o", "--output", help="Output file (default: fingerprints.json)")

    use_fp_p = sub.add_parser("use-fingerprint", help="Load captured fingerprint for an account")
    use_fp_p.add_argument("-p", "--profile", required=True, help="Account profile name")
    use_fp_p.add_argument("-f", "--fingerprint-file", help="Fingerprint JSON file (default: fingerprints.json)")

    sub.add_parser("commands", help="List command library (offline)")

    build_p = sub.add_parser("build", help="Build a command frame offline (no network)")
    build_p.add_argument("name", help="Command name (see 'commands')")
    build_p.add_argument("--param", action="append", help="Builder kwarg as k=v (repeatable)")
    build_p.add_argument("--node", type=int, default=2981106, help="Resource node id")
    build_p.add_argument("--alliance", type=int, default=0, help="Alliance/chief id for auto_gather")
    build_p.add_argument("--city-x", type=float, default=7057.0)
    build_p.add_argument("--city-y", type=float, default=5687.0)
    build_p.add_argument("--target-x", type=float, default=7100.0)
    build_p.add_argument("--target-y", type=float, default=5700.0)
    build_p.add_argument("--count", type=int, default=100, help="Troop count for training")
    build_p.add_argument("--army", help="Army as 'unit:count,unit:count'")

    decode_p = sub.add_parser("decode", help="Decode a hex frame offline (no network)")
    decode_p.add_argument("hex", help="Frame hex (outer {1:op,2:payload} or raw payload)")

    args = parser.parse_args()
    setup_logging(args.verbose)

    if not args.command:
        parser.print_help()
        return

    cmd_map = {
        "status": cmd_status,
        "run": cmd_run,
        "login": cmd_login,
        "import-proxies": cmd_import_proxies,
        "test-connection": cmd_test_connection,
        "capture-fingerprint": cmd_capture_fingerprint,
        "use-fingerprint": cmd_use_fingerprint,
        "commands": cmd_commands,
        "build": cmd_build,
        "decode": cmd_decode,
    }

    handler = cmd_map.get(args.command)
    if handler:
        asyncio.run(handler(args))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()