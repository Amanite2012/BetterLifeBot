"""AES-256-GCM encryption for sensitive tokens (Garmin, OAuth)."""
from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from bot.config import get_settings

_NONCE_SIZE = 12  # 96-bit nonce for GCM


def _key() -> bytes:
    return get_settings().encryption_key_bytes()


def encrypt(plaintext: str) -> str:
    """Encrypt plaintext → base64-encoded `nonce||ciphertext`."""
    key = _key()
    nonce = os.urandom(_NONCE_SIZE)
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ct).decode()


def decrypt(token: str) -> str:
    """Decrypt base64-encoded `nonce||ciphertext` → plaintext."""
    key = _key()
    raw = base64.b64decode(token)
    nonce, ct = raw[:_NONCE_SIZE], raw[_NONCE_SIZE:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ct, None).decode()
