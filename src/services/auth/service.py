"""Auth service — register, login, IMAP account management."""
import base64
import json
import time
import uuid

from core.crypto import decrypt_payload, encrypt_payload

from services.auth.errors import (
    AuthServiceError,
    DecryptionError,
    InvalidCredentialsError,
    UserExistsError,
    UserNotFoundError,
)
from services.auth.models import (
    AuthResult,
    ImapAccount,
    ImapAccountResponse,
    User,
)
from services.auth.store import UserStore


class AuthService:
    def __init__(self):
        self._store = UserStore()
        # Import SessionStore from gateway.session (uses same DB path)
        from gateway.session import SessionStore as _SS
        self._session_store = _SS()

    def register(self, email: str, password: str) -> AuthResult:
        existing = self._store.get_user_by_email(email)
        if existing:
            raise UserExistsError(f"User {email} already exists")
        user_id = self._store.create_user(email, password)
        session_id = self._session_store.create_session(user_id)
        return AuthResult(user_id=user_id, session_id=session_id, account=email)

    def login(self, email: str, password: str) -> AuthResult:
        user = self._store.get_user_by_email(email)
        if not user:
            raise InvalidCredentialsError("Invalid email or password")
        stored_hash = json.loads(user["password_hash"]) if user["password_hash"] else None
        if not stored_hash:
            raise InvalidCredentialsError("Invalid email or password")
        from core.crypto import verify_password
        if not verify_password(password, stored_hash):
            raise InvalidCredentialsError("Invalid email or password")
        # Decrypt stored IMAP credentials using the provided password
        imap_accounts: list[dict] = []
        blob = user["encrypted_imap_creds"]
        if blob:
            try:
                if isinstance(blob, bytes):
                    blob = blob.decode()
                stored = json.loads(blob)
                for acc in stored:
                    enc = acc.get("encrypted", {})
                    if enc:
                        plaintext = decrypt_payload(enc, password)
                        imap_accounts.append({
                            "name": acc.get("name", ""),
                            "host": plaintext.get("host", ""),
                            "port": plaintext.get("port", 993),
                            "user": plaintext.get("username", ""),
                            "password": plaintext.get("password", ""),
                        })
            except Exception:
                raise DecryptionError("Failed to decrypt IMAP credentials — wrong password?")

        session_id = self._session_store.create_session(user["user_id"], imap_accounts=imap_accounts or None)
        return AuthResult(user_id=user["user_id"], session_id=session_id, account=email)

    def get_user(self, user_id: str) -> User:
        user = self._store.get_user_by_id(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")
        return User(user_id=user["user_id"], email=user["email"], created_at=user["created_at"])

    def verify_password(self, user_id: str, password: str) -> bool:
        return self._store.verify_password(user_id, password)

    def add_imap_account(self, user_id: str, account: ImapAccount, user_password: str) -> ImapAccountResponse:
        creds_data = {
            "name": account.name,
            "server": account.server,
            "port": account.port,
            "username": account.username,
            "imap_password": account.imap_password,
        }
        encrypted = encrypt_payload(creds_data, user_password)
        user = self._store.get_user_by_id(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")
        existing = []
        if user["encrypted_imap_creds"]:
            blob = user["encrypted_imap_creds"]
            if isinstance(blob, str):
                blob = blob.encode()
            try:
                decoded = base64.b64decode(blob)
                inner = json.loads(decoded.decode())
                existing = decrypt_payload(inner, user_password)
            except Exception:
                # legacy raw bytes format
                existing = json.loads(blob.decode())
        encrypted_list = existing + [{
            "name": account.name,
            "server": account.server,
            "port": account.port,
            "username": account.username,
            "encrypted": encrypted,
        }]
        self._store.update_imap_creds(user_id, encrypted_list)
        return ImapAccountResponse(
            id=str(len(encrypted_list) - 1),
            name=account.name,
            server=account.server,
            username=account.username,
            created_at=str(time.time()),
        )

    def list_imap_accounts(self, user_id: str) -> list[ImapAccountResponse]:
        user = self._store.get_user_by_id(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")
        if not user["encrypted_imap_creds"]:
            return []
        blob = user["encrypted_imap_creds"]
        if isinstance(blob, str):
            blob = blob.encode()
        try:
            decoded = base64.b64decode(blob)
            inner = json.loads(decoded.decode())
        except Exception:
            inner = json.loads(blob.decode())
        return [
            ImapAccountResponse(
                id=str(i),
                name=a.get("name", ""),
                server=a.get("server", ""),
                username=a.get("username", ""),
                created_at="",
            )
            for i, a in enumerate(inner)
        ]

    def delete_imap_account(self, user_id: str, account_id: int) -> bool:
        user = self._store.get_user_by_id(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")
        if not user["encrypted_imap_creds"]:
            return False
        blob = user["encrypted_imap_creds"]
        if isinstance(blob, str):
            blob = blob.encode()
        try:
            decoded = base64.b64decode(blob)
            inner = json.loads(decoded.decode())
        except Exception:
            inner = json.loads(blob.decode())
        if account_id < 0 or account_id >= len(inner):
            return False
        new_list = [a for i, a in enumerate(inner) if i != account_id]
        self._store.update_imap_creds(user_id, new_list)
        return True

    def delete_user(self, user_id: str) -> bool:
        try:
            self._store.delete_user(user_id)
            return True
        except Exception:
            return False