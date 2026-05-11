"""Auth service — register, login, IMAP account management."""
import hashlib
import json
import secrets
import time
import uuid

from src.core.config import ADMIN_EMAILS, DEFAULT_MODEL, SEARCH_PROVIDER
from src.core.crypto import decrypt_payload, encrypt_payload
from src.core.jwt import create_session_token

DEVICE_TOKEN_PREFIX = "whsk_"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

from src.services.auth.errors import (
    AuthServiceError,
    DecryptionError,
    InvalidCredentialsError,
    UserExistsError,
    UserNotFoundError,
)
from src.services.auth.models import (
    AuthResult,
    ImapAccount,
    ImapAccountResponse,
    User,
)
from src.services.auth.store import UserStore


class AuthService:
    def __init__(self):
        self._store = UserStore()
        # Import SessionStore from gateway.session (uses same DB path)
        from src.gateway.session import SessionStore as _SS
        self._session_store = _SS()

    def register(self, email: str, password: str) -> AuthResult:
        existing = self._store.get_user_by_email(email)
        if existing:
            raise UserExistsError(f"User {email} already exists")
        user_id = self._store.create_user(email, password)
        # Auto-promote if email is in ADMIN_EMAILS
        is_admin = email.lower() in ADMIN_EMAILS
        if is_admin:
            self._store.set_admin(user_id, True)
        token = create_session_token(user_id, enc_key="", is_admin=is_admin)
        session_id = self._session_store.create_session(user_id)
        return AuthResult(user_id=user_id, session_id=session_id, token=token, account=email)

    def get_decrypted_imap_accounts(self, user_id: str, enc_key: str) -> list[dict]:
        user = self._store.get_user_by_id(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")
        return self._decrypt_imap_accounts(user, enc_key)

    def get_mail_model(self, user_id: str) -> str:
        user = self._store.get_user_by_id(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")
        return user.get("mail_model") or DEFAULT_MODEL

    def get_mail_preferences(self, user_id: str) -> str:
        user = self._store.get_user_by_id(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")
        return user.get("mail_preferences") or ""

    def update_mail_model(self, user_id: str, mail_model: str) -> str:
        user = self._store.get_user_by_id(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")
        self._store.update_mail_model(user_id, mail_model.strip())
        return mail_model.strip()

    def update_mail_preferences(self, user_id: str, mail_preferences: str) -> str:
        user = self._store.get_user_by_id(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")
        self._store.update_mail_preferences(user_id, mail_preferences.strip())
        return mail_preferences.strip()

    def get_search_provider(self, user_id: str) -> str:
        user = self._store.get_user_by_id(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")
        return user.get("search_provider") or SEARCH_PROVIDER

    def update_search_provider(self, user_id: str, search_provider: str) -> str:
        user = self._store.get_user_by_id(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")
        self._store.update_search_provider(user_id, search_provider.strip())
        return search_provider.strip()

    def login(self, email: str, password: str) -> AuthResult:
        user = self._store.get_user_by_email(email)
        if not user:
            raise InvalidCredentialsError("Invalid email or password")
        stored_hash = json.loads(user["password_hash"]) if user["password_hash"] else None
        if not stored_hash:
            raise InvalidCredentialsError("Invalid email or password")
        from src.core.crypto import verify_password
        if not verify_password(password, stored_hash):
            raise InvalidCredentialsError("Invalid email or password")
        # Decrypt stored IMAP credentials using the provided password
        imap_accounts = self._decrypt_imap_accounts(user, password)

        # Auto-promote if email matches ADMIN_EMAILS
        is_admin = user.get("is_admin", False) or email.lower() in ADMIN_EMAILS
        if is_admin and not user.get("is_admin"):
            self._store.set_admin(user["user_id"], True)

        session_id = self._session_store.create_session(user["user_id"], imap_accounts=imap_accounts or None)
        token = create_session_token(user["user_id"], enc_key=password, is_admin=is_admin)
        return AuthResult(user_id=user["user_id"], session_id=session_id, token=token, account=email)

    def _decrypt_imap_accounts(self, user: dict, enc_key: str) -> list[dict]:
        imap_accounts: list[dict] = []
        blob = user["encrypted_imap_creds"]
        if not blob:
            return imap_accounts
        try:
            if isinstance(blob, bytes):
                blob = blob.decode()
            stored = json.loads(blob)
            for acc in stored:
                enc = acc.get("encrypted", {})
                if not enc:
                    continue
                plaintext = decrypt_payload(enc, enc_key)
                imap_accounts.append({
                    "name": acc.get("name", ""),
                    "host": plaintext.get("host", ""),
                    "port": plaintext.get("port", 993),
                    "user": plaintext.get("username", ""),
                    "password": plaintext.get("password", ""),
                })
        except Exception:
            raise DecryptionError("Failed to decrypt IMAP credentials — wrong password?")
        return imap_accounts

    def get_user(self, user_id: str) -> User:
        user = self._store.get_user_by_id(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")
        return User(user_id=user["user_id"], email=user["email"], created_at=user["created_at"])

    def verify_password(self, user_id: str, password: str) -> bool:
        return self._store.verify_password(user_id, password)

    def add_imap_account(self, user_id: str, account: ImapAccount, enc_key: str) -> ImapAccountResponse:
        user = self._store.get_user_by_id(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")
        existing = []
        if user["encrypted_imap_creds"]:
            blob = user["encrypted_imap_creds"]
            if isinstance(blob, bytes):
                blob = blob.decode()
            existing = json.loads(blob)
        creds_data = {
            "name": account.name,
            "host": account.server,
            "port": account.port,
            "username": account.username,
            "password": account.imap_password,
        }
        encrypted = encrypt_payload(creds_data, enc_key)
        existing.append({
            "name": account.name,
            "server": account.server,
            "username": account.username,
            "encrypted": encrypted,
        })
        self._store.update_imap_creds(user_id, existing)
        return ImapAccountResponse(
            id=str(len(existing) - 1),
            name=account.name,
            server=account.server,
            username=account.username,
            created_at=str(time.time()),
        )

    def update_imap_account(self, user_id: str, account_id: int, account: ImapAccount, enc_key: str) -> ImapAccountResponse:
        """Update an existing IMAP account by index."""
        user = self._store.get_user_by_id(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")
        if not user["encrypted_imap_creds"]:
            raise UserNotFoundError(f"Account {account_id} not found")
        blob = user["encrypted_imap_creds"]
        if isinstance(blob, bytes):
            blob = blob.decode()
        accounts = json.loads(blob)
        if account_id < 0 or account_id >= len(accounts):
            raise UserNotFoundError(f"Account {account_id} not found")
        creds_data = {
            "name": account.name,
            "host": account.server,
            "port": account.port,
            "username": account.username,
            "password": account.imap_password,
        }
        encrypted = encrypt_payload(creds_data, enc_key)
        accounts[account_id] = {
            "name": account.name,
            "server": account.server,
            "username": account.username,
            "encrypted": encrypted,
        }
        self._store.update_imap_creds(user_id, accounts)
        return ImapAccountResponse(
            id=str(account_id),
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
        if isinstance(blob, bytes):
            blob = blob.decode()
        accounts = json.loads(blob)
        return [
            ImapAccountResponse(
                id=str(i),
                name=a.get("name", ""),
                server=a.get("server", ""),
                username=a.get("username", ""),
                created_at="",
            )
            for i, a in enumerate(accounts)
        ]

    def delete_imap_account(self, user_id: str, account_id: int) -> bool:
        user = self._store.get_user_by_id(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")
        if not user["encrypted_imap_creds"]:
            return False
        blob = user["encrypted_imap_creds"]
        if isinstance(blob, bytes):
            blob = blob.decode()
        accounts = json.loads(blob)
        if account_id < 0 or account_id >= len(accounts):
            return False
        new_list = [a for i, a in enumerate(accounts) if i != account_id]
        self._store.update_imap_creds(user_id, new_list)
        return True

    def delete_user(self, user_id: str) -> bool:
        try:
            self._store.delete_user(user_id)
            return True
        except Exception:
            return False

    def generate_device_token(self, user_id: str) -> dict:
        """Create or rotate the user's device token. Returns plaintext once + metadata."""
        user = self._store.get_user_by_id(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")
        plaintext = DEVICE_TOKEN_PREFIX + secrets.token_urlsafe(32)
        token_hash = _hash_token(plaintext)
        last4 = plaintext[-4:]
        meta = self._store.upsert_device_token(user_id, token_hash, last4)
        return {"token": plaintext, "last4": last4, "created_at": meta["created_at"]}

    def get_device_token_meta(self, user_id: str) -> dict | None:
        user = self._store.get_user_by_id(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")
        meta = self._store.get_device_token_by_user(user_id)
        if not meta:
            return None
        return {"last4": meta["last4"], "created_at": meta["created_at"], "last_used_at": meta["last_used_at"]}

    def revoke_device_token(self, user_id: str) -> bool:
        user = self._store.get_user_by_id(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")
        return self._store.delete_device_token(user_id)

    def verify_device_token(self, token: str) -> str | None:
        """Look up a plaintext token. Returns user_id or None. Updates last_used_at on hit."""
        if not token or not token.startswith(DEVICE_TOKEN_PREFIX):
            return None
        token_hash = _hash_token(token)
        meta = self._store.get_device_token_by_hash(token_hash)
        if not meta:
            return None
        self._store.touch_device_token(meta["token_id"])
        return meta["user_id"]
