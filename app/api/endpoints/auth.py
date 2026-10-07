import logging
import time
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from app.models import AccountDAO, CharacterDAO
from app.services import lilith_otp
from app.services.lilith_cloud import LilithCloudService
from app.services.device_generator import DeviceGenerator

logger = logging.getLogger("OTPAuthAPI")

router = APIRouter(tags=["OTP Auth"])

# Per-email send cooldown (mirrors the 60s UI timer + SendCodeCache).
_LAST_SEND: Dict[str, float] = {}
SEND_COOLDOWN_S = 60.0


class SendCodeRequest(BaseModel):
    email: str = ""
    user_id: Optional[str] = ""


class VerifyCodeRequest(BaseModel):
    email: str = ""
    code: str = ""
    bot_id: Optional[str] = None
    user_id: Optional[str] = ""


def _resolve_uid(req: Request, body_uid: str = "") -> str:
    try:
        from app.api.routes import _resolve_tenant_uid, _normalize_bot_id
        uid = (req.headers.get("x-user-id", "") or "").strip() or (body_uid or "").strip()
        return _resolve_tenant_uid(uid, "bot-0", req)
    except Exception:
        return (req.headers.get("x-user-id", "") or "").strip() or (body_uid or "").strip()


@router.post("/auth/send-code")
@router.post("/v1/auth/send-code")
async def send_otp_code(payload: SendCodeRequest, request: Request):
    email = (payload.email or "").strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")
    now = time.time()
    last = _LAST_SEND.get(email, 0.0)
    if now - last < SEND_COOLDOWN_S:
        wait = int(SEND_COOLDOWN_S - (now - last))
        raise HTTPException(status_code=429, detail=f"Code already sent. Retry in {wait}s.")
    res = lilith_otp.send_email_code(email)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error") or "Failed to send code.")
    _LAST_SEND[email] = now
    return {"success": True, "status": "CODE_SENT",
            "code_length": res.get("code_length", 6),
            "message": "Verification code sent to your email."}


@router.post("/auth/verify-code")
@router.post("/v1/auth/verify-code")
async def verify_otp_code(payload: VerifyCodeRequest, request: Request):
    from app.api.routes import _normalize_bot_id
    email = (payload.email or "").strip().lower()
    code = (payload.code or "").strip()
    if "@" not in email or not code:
        raise HTTPException(status_code=400, detail="Email and 6-digit code are required.")
    uid = _resolve_uid(request, payload.user_id or "")
    if not uid:
        raise HTTPException(status_code=401, detail="Tenant authentication required")

    req_bot_id = _normalize_bot_id(payload.bot_id) if payload.bot_id else None

    from app.api.routes import check_cross_user_conflict, get_room_slots, count_active_room_characters
    check_cross_user_conflict(user_id=uid, email=email, bot_id=req_bot_id)

    max_slots = get_room_slots(uid, req_bot_id)
    used_slots = count_active_room_characters(uid, req_bot_id)
    if used_slots >= max_slots:
        raise HTTPException(
            status_code=400,
            detail=f"تم بلوغ الحد الأقصى للباقة ({max_slots} حكام). يرجى ترقية الباقة لإضافة المزيد."
        )

    existing_acc = AccountDAO.get_by_email(email, uid)
    device_profile = None
    if existing_acc:
        device_profile = existing_acc.get("device_profile")
        if not device_profile:
            device_profile = DeviceGenerator.generate(email)
        device_profile = DeviceGenerator.ensure_sdk_fields(device_profile, email)
    else:
        device_profile = DeviceGenerator.generate(email)
        device_profile = DeviceGenerator.ensure_sdk_fields(device_profile, email)

    auth_res = LilithCloudService.authenticate_with_code(email, code, device_profile=device_profile)
    if auth_res.get("status") in ("REQUIRES_VERIFICATION", "CAPTCHA_REQUIRED"):
        return {"success": False, "status": "REQUIRES_VERIFICATION",
                "captcha_url": auth_res.get("captcha_url", ""), "email": email,
                "error": "Security check required — solve it, then retry the code."}
    if not auth_res.get("success"):
        raise HTTPException(status_code=400, detail=auth_res.get("error") or "Code login failed.")

    app_uid = str(auth_res["app_uid"])
    app_token = auth_res["app_token"]
    udid = auth_res["udid"]
    expires_at = auth_res.get("token_expires_at")

    raw_characters = LilithCloudService.get_roles(app_uid, app_token, udid)
    if not raw_characters:
        gw_msg = LilithCloudService.roles_error_message()
        raise HTTPException(
            status_code=400,
            detail=gw_msg or ("Logged in, but Lilith returned no characters for this account. "
                              "Make sure the account owns Rise of Kingdoms governors."))

    check_cross_user_conflict(user_id=uid, email=email, raw_characters=raw_characters, bot_id=req_bot_id)

    # Preserve an already-stored password so the password tab keeps working.
    keep_pw = ""
    try:
        if existing_acc and existing_acc.get("encrypted_password"):
            keep_pw = existing_acc.get("encrypted_password") or ""
    except Exception:
        pass
    # OTP accounts store no password (keep any previously stored one so the
    # password tab keeps working for this email).
    try:
        acc_obj = AccountDAO.upsert(
            email=email, user_id=uid, encrypted_password=keep_pw,
            udid=udid, app_uid=app_uid, app_token=app_token,
            token_expires_at=expires_at, device_profile=device_profile,
            bot_id=req_bot_id,
        )
    except PermissionError as e:
        if "OWNED_BY_ANOTHER_USER" in str(e):
            raise HTTPException(
                status_code=409,
                detail="هذا الحساب أو الحاكم مسجل بالفعل لدى مستخدم آخر في المنصة. يرجى التواصل مع الدعم الفني إذا كنت المالك الحقيقي."
            )
        raise HTTPException(status_code=403, detail=str(e))
    account_id = acc_obj["id"]

    from app.api.routes import _seed_character_settings
    synced = []
    for rc in raw_characters:
        try:
            c_obj = CharacterDAO.upsert(
                account_id=account_id, role_id=str(rc["role_id"]), name=rc["name"],
                kingdom_id=int(rc["kingdom_id"]), power=int(rc.get("power", 0)),
                city_level=int(rc.get("city_level", 1)), avatar_url=rc.get("avatar_url", ""),
                alliance_tag=rc.get("alliance_tag", ""), is_active_cloud=False)
        except PermissionError as e:
            if "OWNED_BY_ANOTHER_USER" in str(e):
                raise HTTPException(
                    status_code=409,
                    detail="هذا الحساب أو الحاكم مسجل بالفعل لدى مستخدم آخر في المنصة. يرجى التواصل مع الدعم الفني إذا كنت المالك الحقيقي."
                )
            raise HTTPException(status_code=403, detail=str(e))
        synced.append(c_obj)
        _seed_character_settings(int(c_obj["id"]), uid)

    return {"success": True, "status": "AUTHENTICATED",
            "message": f"Code login OK — synced {len(synced)} characters for {email}",
            "account": {"id": account_id, "email": email, "app_uid": app_uid,
                        "characters_found": len(synced)},
            "characters": synced}
