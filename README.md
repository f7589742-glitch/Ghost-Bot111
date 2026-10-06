# RoK Headless Bot Framework

A headless bot framework for Rise of Kingdoms (RoK) by Lilith Games that connects directly to the game server on TCP port 3101, authenticates, and runs automated farming across multiple accounts.

## Features

- **Direct TCP connection** to RoK game servers (no game client required)
- **Multi-account support** — run concurrent bots for multiple accounts
- **Built-in fingerprint generation** — unique per-account device fingerprints (GPU, CPU, RAM, IP, etc.)
- **Farming automation** — gather, train, research, build, mail, daily rewards
- **Fingerprint capture** — capture real device fingerprint from game client and reuse in bot
- **Proxy support** — SOCKS5/HTTP proxy tunneling
- **Auto-reconnect** — handles disconnections gracefully

## Quick Start

### Installation

```bash
pip install -r requirements.txt
```

### Connect and test

```bash
# Test connection for a single account
python -m rokbot test-connection -p teez8888+v5

# Run ALL accounts
python -m rokbot run --all

# Run specific accounts
python -m rokbot run -p teez8888+v5 -p farm12213
```

### Capture your device fingerprint

```bash
# Capture from game client files
python -m rokbot capture-fingerprint -o fingerprints.json

# Apply captured fingerprint to an account
python -m rokbot use-fingerprint -p teez8888+v5 -f fingerprints.json
```

### Full login flow

```bash
python -m rokbot login -p myaccount --email user@example.com --password mypass
```

## Project Structure

```
D:\aa\Headless Bot RoK\
├── rokbot/                  # Production bot modules
│   ├── __main__.py          # CLI entry point
│   ├── account.py            # Account management (load/save profiles)
│   ├── auth.py               # Authentication (email login, token refresh)
│   ├── bot.py                # Headless bot with farming logic
│   ├── config.py             # Configuration and constants
│   ├── commands.py           # Command library for farming
│   ├── crypto.py             # RokCrypto stream cipher wrapper
│   ├── fingerprint.py        # Device fingerprint generator (unique per account)
│   ├── network.py            # TCP connection with encryption
│   ├── orchestrator.py       # Multi-account orchestration
│   ├── protobuf.py           # Protocol buffer encode/decode
│   ├── proxy.py              # SOCKS5/HTTP proxy support
│   ├── session.py            # Session state machine (login→active→farming)
│   └── behavior.py           # Human-like behavior simulation
├── python/                    # R&D and protocol analysis scripts
│   ├── headless_client.py    # Async protocol engine (reference)
│   ├── full_login.py         # Full 558-byte login payload builder
│   ├── crypto_module.py      # RokCrypto cipher implementation
│   ├── derive_seed_from_nonce.py  # Seed derivation from greeting nonce
│   └── auth_pipeline.py      # Complete auth + TCP pipeline
├── profiles/                  # Account profile JSON files
├── commands/                  # Command definitions
├── requirements.txt            # Python dependencies
└── README.md                  # This file
```

## Protocol Details

### Connection Flow

1. **TCP Connect** → `43.159.113.101:3101` (EU) or other regional servers
2. **Server Greeting** → Parse nonce (n1, n2), derive seeds
3. **Login Frame** → Send full 500+ byte login protobuf with device fingerprint
4. **Session Init** → Send 17 init commands (600, 8030, 2003, ...)
5. **ACTIVE** → Begin farming loop

### Game Servers

| Region | Address | Port |
|--------|---------|------|
| EU | `43.159.113.101` | 3101 |
| EU2 | `43.159.112.101` | 3101 |
| Asia | `34.54.22.150` | 3101 |

### Crypto

The protocol uses a custom stream cipher (`RokCrypto`) — a triple additive LFSR with seed derived from the server greeting nonce via `derive_seed(n1, n2)`.

**Login Payload:** The bot sends a ~500-byte login protobuf containing device fingerprint fields (GPU, CPU, RAM, IP, platform, etc.) in field 6, making the server treat the connection as a real game client rather than returning dummy/fake accounts.

### Key Findings from Protocol Analysis

- `access_token` is a **dummy field** (confirmed by `auth_pipeline.py` lines 57-58) — the game server validates `app_token`, not `access_token`
- The `build_minimal_login()` 79-byte frame (missing field 6, device fingerprint) causes the server to return fake/dummy accounts instead of authenticating the real user
- The full login frame (~500 bytes with device fingerprint) is required for proper authentication
- Per-account unique `user_agent` and `env_id` fingerprints prevent Lilith from detecting bot clusters

## Profile Format

Profiles are stored in JSON format in the `profiles/` directory:

```json
{
  "profile_name": "teez8888+v5",
  "email": "teez8888+v5@gmail.com",
  "password": "",
  "app_uid": "2599910662",
  "player_id": "2599910662",
  "access_token": "D-ZiAxhM0vy8Hl1AuVeF...",
  "app_token": "D-ZiAxhM0vy8Hl1AuVeF...",
  "region": "AR",
  "server_host": "",
  "server_port": 3101,
  "fingerprint": {},
  "updated_at": 1720000000.0
}
```

## Dependencies

- Python 3.14+
- `aiohttp` — async HTTP client (for web APIs if needed)
- `pycryptodome` — cryptographic operations
- `python-socks` — SOCKS5 proxy support

## License

For educational/research purposes. Using custom clients violates Rise of Kingdoms Terms of Service.

## Notes

- Banned accounts (Lilith Games error 11006): `teez8888@gmail.com` (uid=220293855), `teez9334+1@gmail.com`
- Active accounts: `teez8888+v5` (uid=2599910662), `farm12213` (uid=259665500)
- HHIP API creates NEW accounts (different UID each time), NOT linked to existing accounts
- `teez8888+v5@gmail.com` correct UID is `2599910662` (not the previously wrong `259920453`)
