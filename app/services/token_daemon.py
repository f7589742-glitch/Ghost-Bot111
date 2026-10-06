# app/services/token_daemon.py
"""
Silent Token Auto-Refresher Daemon.
Background lifecycle service to automatically refresh Lilith cloud tokens
prior to their 30-day expiration, keeping multi-tenant accounts authenticated indefinitely.
"""
import time
import asyncio
import logging
from app.models import AccountDAO
from app.services.lilith_cloud import LilithCloudService

logger = logging.getLogger("TokenDaemon")

class TokenDaemon:
    _running = False

    @classmethod
    async def start(cls, check_interval_seconds: int = 3600):
        """
        Runs periodic checks per tenant and refreshes tokens close to expiry.
        Iterates tenant by tenant so every upsert re-binds the row to its
        owning Discord user_id — never touching another tenant's accounts.
        """
        cls._running = True
        logger.info("[TokenDaemon] Silent Token Auto-Refresher daemon started.")

        while cls._running:
            try:
                now = int(time.time())
                refresh_window = 3 * 86400  # 3 days before expiration

                for uid in AccountDAO.get_all_user_ids():
                    accounts = AccountDAO.get_all(uid)
                    for acc in accounts:
                        app_uid = acc.get("app_uid")
                        app_token = acc.get("app_token")
                        expires_at = acc.get("token_expires_at") or 0
                        udid = acc.get("udid")

                        # If token exists and is near expiry (or expires_at == 0)
                        if app_uid and app_token and udid:
                            if expires_at and (expires_at - now) > refresh_window:
                                continue  # Token is still plenty fresh

                            logger.info(f"[TokenDaemon] Refreshing token for account {acc['email']} (UID: {app_uid})...")
                            ref_res = LilithCloudService.refresh_token(app_uid, app_token, udid)
                            if ref_res.get("success"):
                                new_token = ref_res.get("app_token")
                                new_exp = ref_res.get("token_expires_at")
                                AccountDAO.upsert(
                                    email=acc["email"],
                                    user_id=uid,
                                    encrypted_password=acc.get("encrypted_password", ""),
                                    udid=udid,
                                    app_uid=app_uid,
                                    app_token=new_token,
                                    token_expires_at=new_exp,
                                    device_profile=acc.get("device_profile")
                                )
                                logger.info(f"[TokenDaemon] Token refreshed successfully for {acc['email']}.")
                            else:
                                logger.warning(f"[TokenDaemon] Token refresh failed for {acc['email']}.")

            except Exception as e:
                logger.error(f"[TokenDaemon] Error in refresh loop: {e}")

            await asyncio.sleep(check_interval_seconds)

    @classmethod
    def stop(cls):
        cls._running = False
