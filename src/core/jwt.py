"""JWT utilities — sign and verify tokens containing user session data.

Sensitive payload fields (enc_key) are encrypted with AES-256-GCM before
being placed inside the JWT, so they cannot be read by decoding the token.
"""
import json
from datetime import datetime, timedelta, timezone

import jwt

from src.core.config import JWT_SECRET, JWT_EXPIRY_HOURS
from src.core.crypto import decrypt_payload, encrypt_payload

_ENCRYPTED_FIELDS = ("enc_key",)


def _encrypt_sensitive(payload: dict) -> dict:
    """Encrypt sensitive fields in the payload before signing."""
    sensitive = {k: payload[k] for k in _ENCRYPTED_FIELDS if k in payload}
    if not sensitive:
        return payload
    encrypted = encrypt_payload(sensitive, JWT_SECRET)
    clean = {k: v for k, v in payload.items() if k not in _ENCRYPTED_FIELDS}
    clean["_enc"] = json.dumps(encrypted)
    return clean


def _decrypt_sensitive(payload: dict) -> dict:
    """Decrypt sensitive fields after verification."""
    enc_blob = payload.pop("_enc", None)
    if not enc_blob:
        return payload
    decrypted = decrypt_payload(json.loads(enc_blob), JWT_SECRET)
    payload.update(decrypted)
    return payload


def encode(payload: dict) -> str:
    """Sign a payload as a JWT. Sensitive fields are encrypted first."""
    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET is not set — cannot create tokens")
    exp = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS)
    encrypted_payload = _encrypt_sensitive({**payload, "exp": exp})
    return jwt.encode(encrypted_payload, JWT_SECRET, algorithm="HS256")


def decode(token: str) -> dict:
    """Verify and decode a JWT, decrypting sensitive fields.

    Raises RuntimeError if JWT_SECRET is not set.
    Raises jwt.InvalidTokenError on signature/expiry failure.
    """
    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET is not set — cannot verify tokens")
    payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    return _decrypt_sensitive(payload)


def create_session_token(user_id: str, enc_key: str, is_admin: bool = False) -> str:
    """Create a signed JWT containing user_id, encrypted enc_key, and admin flag."""
    return encode({"user_id": user_id, "enc_key": enc_key, "is_admin": is_admin})