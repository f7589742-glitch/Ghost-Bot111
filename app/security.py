import base64
import hashlib
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
from app.config import SECRET_KEY

# Derive a 256-bit AES key from SECRET_KEY
_AES_KEY = hashlib.sha256(SECRET_KEY.encode('utf-8')).digest()

def encrypt_password(plain_password: str) -> str:
    """
    Encrypts plaintext password using AES-256-GCM.
    Output format: base64(nonce + tag + ciphertext)
    """
    if not plain_password:
        return ""
    nonce = get_random_bytes(12)
    cipher = AES.new(_AES_KEY, AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(plain_password.encode('utf-8'))
    packed = nonce + tag + ciphertext
    return base64.b64encode(packed).decode('ascii')

def decrypt_password(encrypted_b64: str) -> str:
    """
    Decrypts base64 encoded AES-256-GCM ciphertext back to plaintext password.
    """
    if not encrypted_b64:
        return ""
    try:
        raw = base64.b64decode(encrypted_b64.encode('ascii'))
        if len(raw) < 28:
            return ""
        nonce = raw[:12]
        tag = raw[12:28]
        ciphertext = raw[28:]
        cipher = AES.new(_AES_KEY, AES.MODE_GCM, nonce=nonce)
        plaintext = cipher.decrypt_and_verify(ciphertext, tag)
        return plaintext.decode('utf-8')
    except Exception:
        return ""
