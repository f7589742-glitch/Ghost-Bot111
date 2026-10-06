import os
import secrets
from fastapi import Request, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials

API_KEY_NAME = "X-API-Key"
BOT_SECRET_HEADER = "X-Bot-Secret"

api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)
bot_secret_header = APIKeyHeader(name=BOT_SECRET_HEADER, auto_error=False)
bearer_auth = HTTPBearer(auto_error=False)

ENV_FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env")


def get_or_create_secrets() -> tuple[str, str]:
    """Retrieve API_SECRET_KEY and BOT_STEALTH_SECRET from environment or .env."""
    api_key = os.environ.get("API_SECRET_KEY")
    stealth_secret = os.environ.get("BOT_STEALTH_SECRET")

    if os.path.exists(ENV_FILE_PATH):
        try:
            with open(ENV_FILE_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("API_SECRET_KEY="):
                        k = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if k:
                            api_key = k
                    elif line.startswith("BOT_STEALTH_SECRET="):
                        s = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if s:
                            stealth_secret = s
        except Exception:
            pass

    updated = False
    if not api_key:
        api_key = secrets.token_hex(16)
        updated = True
    if not stealth_secret:
        # Default stealth secret aligned to token
        stealth_secret = "rok_stealth_" + secrets.token_hex(16)
        updated = True

    if updated:
        try:
            with open(ENV_FILE_PATH, "w", encoding="utf-8") as f:
                f.write(f"API_SECRET_KEY={api_key}\n")
                f.write(f"BOT_STEALTH_SECRET={stealth_secret}\n")
        except Exception:
            pass

    os.environ["API_SECRET_KEY"] = api_key
    os.environ["BOT_STEALTH_SECRET"] = stealth_secret
    return api_key, stealth_secret


API_KEY, BOT_STEALTH_SECRET = get_or_create_secrets()


async def verify_stealth_and_api_key(
    request: Request,
    secret_header_val: str = Security(bot_secret_header),
    api_key_header_val: str = Security(api_key_header),
    bearer_creds: HTTPAuthorizationCredentials = Security(bearer_auth)
):
    """
    Dual-layer defense:
    1. Stealth Protection: Rejects any request missing valid X-Bot-Secret (or query param).
    2. API Key Protection: Enforces mutation/control access restrictions.
    """
    path = request.url.path
    method = request.method

    current_stealth = os.environ.get("BOT_STEALTH_SECRET", BOT_STEALTH_SECRET)

    # Check stealth header or query param token (useful for browser websockets)
    req_secret = secret_header_val or request.headers.get("x-bot-secret") or request.query_params.get("secret")
    
    # Internal localhost calls bypass stealth layer if direct
    client_host = request.client.host if request.client else ""
    is_internal = client_host in ("127.0.0.1", "::1", "localhost") and not request.headers.get("x-forwarded-for")

    if not is_internal:
        if not req_secret or req_secret.strip() != current_stealth.strip():
            # Return 403 / drop
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden"
            )

    # Public read-only endpoints (when stealth secret matches)
    if method in ("GET", "HEAD", "OPTIONS") or path.startswith("/ws"):
        return True

    # Allow same-origin dashboard UI and internal server requests to operate smoothly
    sec_site = request.headers.get("sec-fetch-site", "")
    referer = request.headers.get("referer", "")
    host_header = request.headers.get("host", "")
    is_same_origin = sec_site in ("same-origin", "same-site") or (bool(host_header) and host_header in referer)

    if is_internal or is_same_origin:
        return True

    # Mutating / Control endpoints require API Key
    token = None
    if api_key_header_val:
        token = api_key_header_val.strip()
    elif bearer_creds and bearer_creds.credentials:
        token = bearer_creds.credentials.strip()

    current_api_key = os.environ.get("API_SECRET_KEY", API_KEY)

    if not token or token != current_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid or missing API Key."
        )

    return True
