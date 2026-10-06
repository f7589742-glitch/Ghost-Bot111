"""rokbot — Autonomous headless bot for Rise of Kingdoms PC."""

from .account import AccountConfig, AccountManager
from .auth import AuthManager
from .bot import Bot
from .commands import CommandLibrary
from .crypto import CryptoPair, RokCrypto
from .decoder import GameState, PacketDecoder, ResourceNode
from .fingerprint import FingerprintGenerator
from .network import GameConnection
from .orchestrator import Orchestrator, run_orchestrator
from .protocol import Frame, FrameParser, GreetingNonce
from .proxy import ProxyConfig, ProxyManager
from .session import Session, SessionState

__version__ = "2.0.0"

__all__ = [
    "AccountConfig",
    "AccountManager",
    "AuthManager",
    "Bot",
    "CommandLibrary",
    "CryptoPair",
    "FingerprintGenerator",
    "Frame",
    "FrameParser",
    "GameConnection",
    "GameState",
    "GreetingNonce",
    "Orchestrator",
    "PacketDecoder",
    "ProxyConfig",
    "ProxyManager",
    "ResourceNode",
    "RokCrypto",
    "Session",
    "SessionState",
    "run_orchestrator",
]

