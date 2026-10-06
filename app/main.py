import logging
import os
import sys
import uvicorn
from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "python"))
sys.path.insert(0, PROJECT_ROOT)

from app.database import init_db
from app.api.routes import router as api_router
from app.api.endpoints.marches import router as marches_router
from app.api.endpoints.alliance import router as alliance_router
from app.api.endpoints.transfer import router as transfer_router
from app.api.endpoints.auth import router as otp_auth_router
from app.services.activity_stream import activity_stream
from app.services.logger import install_ring_buffer_handler
from app.core.auth import verify_stealth_and_api_key
from fastapi import WebSocket, WebSocketDisconnect

app = FastAPI(
    title="RoK Cloud Fleet Control",
    description="100% Zero-Emulator Headless Automation SaaS Engine",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://ghost-bot-jade.vercel.app",
        "https://ghost-bot-git-main-ghost-bot.vercel.app",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "*"
    ],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def on_startup():
    init_db()
    # Mirror every log line into the in-memory ring buffer so /log/recent
    # serves from RAM (<2ms) instead of seeking bot.log on disk.
    install_ring_buffer_handler()
    # Silence uvicorn's HTTP access log (every request would otherwise be a
    # blacklisted technical line and flood bot.err) and drop its INFO chatter.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.WARNING)

app.include_router(api_router, dependencies=[Depends(verify_stealth_and_api_key)])
app.include_router(marches_router, dependencies=[Depends(verify_stealth_and_api_key)])
app.include_router(alliance_router, dependencies=[Depends(verify_stealth_and_api_key)])
app.include_router(transfer_router, prefix="/api", dependencies=[Depends(verify_stealth_and_api_key)])
app.include_router(transfer_router, dependencies=[Depends(verify_stealth_and_api_key)])
app.include_router(otp_auth_router, prefix="/api", dependencies=[Depends(verify_stealth_and_api_key)])
app.include_router(otp_auth_router, dependencies=[Depends(verify_stealth_and_api_key)])


@app.websocket("/ws/activity")
async def websocket_activity(websocket: WebSocket):
    await activity_stream.connect(websocket)
    try:
        while True:
            # Keep connection alive, listen for any incoming ping
            await websocket.receive_text()
    except WebSocketDisconnect:
        await activity_stream.disconnect(websocket)
    except Exception:
        await activity_stream.disconnect(websocket)

static_dir = os.path.join(PROJECT_ROOT, "frontend", "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def serve_index():
    index_path = os.path.join(PROJECT_ROOT, "frontend", "index.html")
    return FileResponse(index_path)

@app.get("/health")
def health_check():
    return {"status": "healthy", "engine": "100% pure headless"}

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
