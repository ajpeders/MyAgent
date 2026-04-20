"""Cryptographic utilities for encrypting/decrypting user data at rest.

All encryption uses AES-256-GCM with keys derived from the user's password
via PBKDF2-SHA256 (100k iterations). The server never sees plaintext
credentials or email data.
"""
import base64
import hashlib
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def derive_key(password: str, salt: bytes) -> bytes:
    """PBKDF2-SHA256, 100k iterations, 32-byte key."""
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000, dklen=32)


def encrypt_payload(data: dict, password: str) -> dict:
    """Encrypt a dict to an AES-GCM payload.

    Returns {salt: base64, iv: base64, data: base64} where data contains
    the ciphertext || auth_tag.
    """
    salt = os.urandom(16)
    iv = os.urandom(12)
    key = derive_key(password, salt)
    plaintext = json.dumps(data).encode()
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(iv, plaintext, None)
    return {
        "salt": base64.b64encode(salt).decode(),
        "iv": base64.b64encode(iv).decode(),
        "data": base64.b64encode(ciphertext).decode(),
    }


def decrypt_payload(encrypted: dict, password: str) -> dict:
    """Decrypt an AES-GCM payload back to a dict.

    encrypted: {salt: base64, iv: base64, data: base64}
    Raises on auth failure.
    """
    salt = base64.b64decode(encrypted["salt"])
    iv = base64.b64decode(encrypted["iv"])
    data = base64.b64decode(encrypted["data"])
    key = derive_key(password, salt)
    # AES-GCM: last 16 bytes are auth tag
    ciphertext = data[:-16]
    auth_tag = data[-16:]
    aesgcm = AESGCM(key)
    decrypted = aesgcm.decrypt(iv, ciphertext + auth_tag, None)
    return json.loads(decrypted.decode())


def hash_password(password: str) -> dict:
    """Hash a password for storage using PBKDF2-SHA256.

    Returns {salt: base64, hash: base64}.
    """
    salt = os.urandom(16)
    hashed = derive_key(password, salt)
    return {
        "salt": base64.b64encode(salt).decode(),
        "hash": base64.b64encode(hashed).decode(),
    }


def verify_password(password: str, stored: dict) -> bool:
    """Verify a password against a stored hash. Constant-time comparison."""
    import hmac as _hmac
    salt = base64.b64decode(stored["salt"])
    expected = base64.b64decode(stored["hash"])
    actual = derive_key(password, salt)
    return _hmac.compare_digest(actual, expected)
