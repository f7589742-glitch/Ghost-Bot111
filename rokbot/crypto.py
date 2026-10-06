"""
Crypto layer — wraps the reverse-engineered RokCrypto stream cipher.

Provides stateful encrypt/decrypt instances with proper directional
isolation (TX cipher for outgoing, RX cipher for incoming).
"""
from __future__ import annotations

import sys
from pathlib import Path

_PYTHON_DIR = str(Path(__file__).resolve().parent.parent / "python")
if _PYTHON_DIR not in sys.path:
    sys.path.insert(0, _PYTHON_DIR)

from crypto_module import RokCrypto as _RokCrypto  # noqa: E402

__all__ = ["RokCrypto", "CryptoPair"]


class RokCrypto(_RokCrypto):
    """Thin wrapper around the original RokCrypto with convenience methods."""

    def clone_state(self) -> "RokCrypto":
        """Create an independent copy of this cipher instance."""
        import copy
        return copy.deepcopy(self)


class CryptoPair:
    """
    A matched TX/RX cipher pair derived from a single greeting nonce.

    seed1 (from greeting n2) → TX: encrypt outgoing client frames
    seed2 (from greeting n1) → RX: decrypt incoming server frames
    """

    def __init__(self, seed1: int, seed2: int):
        self.seed1 = seed1
        self.seed2 = seed2
        self.tx = RokCrypto(seed1)
        self.rx = RokCrypto(seed2)

    def __repr__(self) -> str:
        return (
            f"CryptoPair(tx=0x{self.seed1:08x}, rx=0x{self.seed2:08x}, "
            f"tx_id=0x{self.tx.get_identifier():08x}, "
            f"rx_id=0x{self.rx.get_identifier():08x})"
        )
