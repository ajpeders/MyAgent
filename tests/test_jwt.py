"""Tests for JWT sign/verify with encrypted sensitive fields."""
import os
import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    """Ensure JWT_SECRET is set for all tests."""
    monkeypatch.setattr("src.core.config.JWT_SECRET", "test-secret-key-at-least-32-bytes!")
    monkeypatch.setattr("src.core.jwt.JWT_SECRET", "test-secret-key-at-least-32-bytes!")


class TestEncodeDecode:
    def test_roundtrip_preserves_payload(self):
        from src.core.jwt import encode, decode
        payload = {"user_id": "u1", "enc_key": "my-secret-password"}
        token = encode(payload)
        decoded = decode(token)
        assert decoded["user_id"] == "u1"
        assert decoded["enc_key"] == "my-secret-password"

    def test_enc_key_not_visible_in_raw_token(self):
        """The enc_key should be encrypted — not readable by base64 decoding."""
        import base64
        import json
        from src.core.jwt import encode

        token = encode({"user_id": "u1", "enc_key": "super-secret"})
        # JWT is header.payload.signature — decode the payload
        payload_b64 = token.split(".")[1]
        # Add padding
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        raw_payload = json.loads(base64.urlsafe_b64decode(payload_b64))

        assert "enc_key" not in raw_payload, "enc_key should be encrypted, not in plain JWT payload"
        assert "_enc" in raw_payload, "encrypted blob should be present as _enc"

    def test_non_sensitive_fields_remain_plain(self):
        """Fields not in _ENCRYPTED_FIELDS should be readable in the raw JWT."""
        import base64
        import json
        from src.core.jwt import encode

        token = encode({"user_id": "u1", "enc_key": "secret", "is_admin": True})
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        raw_payload = json.loads(base64.urlsafe_b64decode(payload_b64))

        assert raw_payload["user_id"] == "u1"
        assert raw_payload["is_admin"] is True

    def test_token_without_enc_key_has_no_encrypted_blob(self):
        import base64
        import json
        from src.core.jwt import encode

        token = encode({"user_id": "u1"})
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        raw_payload = json.loads(base64.urlsafe_b64decode(payload_b64))

        assert "_enc" not in raw_payload

    def test_expired_token_raises(self):
        import jwt as pyjwt
        from datetime import datetime, timedelta, timezone
        from src.core.jwt import decode

        expired_payload = {
            "user_id": "u1",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        }
        token = pyjwt.encode(expired_payload, "test-secret-key-at-least-32-bytes!", algorithm="HS256")
        with pytest.raises(Exception):
            decode(token)

    def test_wrong_secret_raises(self):
        import jwt as pyjwt
        from src.core.jwt import decode

        token = pyjwt.encode({"user_id": "u1"}, "wrong-secret", algorithm="HS256")
        with pytest.raises(Exception):
            decode(token)


class TestCreateSessionToken:
    def test_creates_token_with_user_id_and_enc_key(self):
        from src.core.jwt import create_session_token, decode

        token = create_session_token("user-123", enc_key="password", is_admin=False)
        decoded = decode(token)
        assert decoded["user_id"] == "user-123"
        assert decoded["enc_key"] == "password"
        assert decoded["is_admin"] is False

    def test_admin_flag_preserved(self):
        from src.core.jwt import create_session_token, decode

        token = create_session_token("admin-1", enc_key="pw", is_admin=True)
        decoded = decode(token)
        assert decoded["is_admin"] is True


class TestEmptySecretGuard:
    def test_encode_raises_on_empty_secret(self, monkeypatch):
        monkeypatch.setattr("src.core.jwt.JWT_SECRET", "")
        from src.core.jwt import encode

        with pytest.raises(RuntimeError, match="JWT_SECRET is not set"):
            encode({"user_id": "u1"})

    def test_decode_raises_on_empty_secret(self, monkeypatch):
        monkeypatch.setattr("src.core.jwt.JWT_SECRET", "")
        from src.core.jwt import decode

        with pytest.raises(RuntimeError, match="JWT_SECRET is not set"):
            decode("some.fake.token")
