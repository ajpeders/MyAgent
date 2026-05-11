"""UserStore — uses shared DB from core/db.py."""
import json
import time
import uuid

from src.core.crypto import hash_password, verify_password
from src.core.db import _connect


class UserStore:
    def create_user(self, email: str, password: str) -> str:
        user_id = str(uuid.uuid4())
        now = time.time()
        pw_hash = json.dumps(hash_password(password))
        conn = _connect()
        conn.execute(
            "INSERT INTO users (user_id, email, password_hash, encrypted_imap_creds, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, email.lower(), pw_hash, None, now, now),
        )
        conn.commit()
        conn.close()
        return user_id

    def verify_password(self, user_id: str, password: str) -> bool:
        user = self.get_user_by_id(user_id)
        if not user or not user["password_hash"]:
            return False
        stored = json.loads(user["password_hash"])
        return verify_password(password, stored)

    def get_user_by_email(self, email: str) -> dict | None:
        conn = _connect()
        row = conn.execute(
            "SELECT user_id, email, password_hash, encrypted_imap_creds, mail_model, mail_preferences, search_provider, is_admin FROM users WHERE email = ?",
            (email.lower(),),
        ).fetchone()
        conn.close()
        if not row:
            return None
        return {
            "user_id": row[0],
            "email": row[1],
            "password_hash": row[2],
            "encrypted_imap_creds": row[3],
            "mail_model": row[4],
            "mail_preferences": row[5],
            "search_provider": row[6],
            "is_admin": bool(row[7]),
        }

    def get_user_by_id(self, user_id: str) -> dict | None:
        conn = _connect()
        row = conn.execute(
            "SELECT user_id, email, password_hash, encrypted_imap_creds, mail_model, mail_preferences, search_provider, is_admin FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        conn.close()
        if not row:
            return None
        return {
            "user_id": row[0],
            "email": row[1],
            "password_hash": row[2],
            "encrypted_imap_creds": row[3],
            "mail_model": row[4],
            "mail_preferences": row[5],
            "search_provider": row[6],
            "is_admin": bool(row[7]),
        }

    def update_mail_model(self, user_id: str, mail_model: str) -> None:
        now = time.time()
        conn = _connect()
        conn.execute(
            "UPDATE users SET mail_model = ?, updated_at = ? WHERE user_id = ?",
            (mail_model or None, now, user_id),
        )
        conn.commit()
        conn.close()

    def update_mail_preferences(self, user_id: str, mail_preferences: str) -> None:
        now = time.time()
        conn = _connect()
        conn.execute(
            "UPDATE users SET mail_preferences = ?, updated_at = ? WHERE user_id = ?",
            (mail_preferences or None, now, user_id),
        )
        conn.commit()
        conn.close()

    def update_search_provider(self, user_id: str, search_provider: str) -> None:
        now = time.time()
        conn = _connect()
        conn.execute(
            "UPDATE users SET search_provider = ?, updated_at = ? WHERE user_id = ?",
            (search_provider or None, now, user_id),
        )
        conn.commit()
        conn.close()

    def set_admin(self, user_id: str, is_admin: bool) -> None:
        import time as _time
        conn = _connect()
        conn.execute(
            "UPDATE users SET is_admin = ?, updated_at = ? WHERE user_id = ?",
            (int(is_admin), _time.time(), user_id),
        )
        conn.commit()
        conn.close()

    def update_imap_creds(self, user_id: str, encrypted_creds: list) -> None:
        now = time.time()
        blob = json.dumps(encrypted_creds).encode()
        conn = _connect()
        conn.execute(
            "UPDATE users SET encrypted_imap_creds = ?, updated_at = ? WHERE user_id = ?",
            (blob, now, user_id),
        )
        conn.commit()
        conn.close()

    def delete_user(self, user_id: str) -> None:
        conn = _connect()
        conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()

    def list_users(self) -> list[dict]:
        conn = _connect()
        rows = conn.execute(
            "SELECT user_id, email, created_at, updated_at FROM users"
        ).fetchall()
        conn.close()
        return [
            {"user_id": r[0], "email": r[1], "created_at": r[2], "updated_at": r[3]}
            for r in rows
        ]

    def count_users(self) -> int:
        conn = _connect()
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        conn.close()
        return count

    def upsert_device_token(self, user_id: str, token_hash: str, last4: str) -> dict:
        token_id = str(uuid.uuid4())
        now = time.time()
        conn = _connect()
        conn.execute("DELETE FROM device_tokens WHERE user_id = ?", (user_id,))
        conn.execute(
            "INSERT INTO device_tokens (token_id, user_id, token_hash, last4, created_at, last_used_at) VALUES (?, ?, ?, ?, ?, NULL)",
            (token_id, user_id, token_hash, last4, now),
        )
        conn.commit()
        conn.close()
        return {"token_id": token_id, "user_id": user_id, "last4": last4, "created_at": now, "last_used_at": None}

    def get_device_token_by_user(self, user_id: str) -> dict | None:
        conn = _connect()
        row = conn.execute(
            "SELECT token_id, user_id, last4, created_at, last_used_at FROM device_tokens WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        conn.close()
        if not row:
            return None
        return {"token_id": row[0], "user_id": row[1], "last4": row[2], "created_at": row[3], "last_used_at": row[4]}

    def get_device_token_by_hash(self, token_hash: str) -> dict | None:
        conn = _connect()
        row = conn.execute(
            "SELECT token_id, user_id, last4, created_at, last_used_at FROM device_tokens WHERE token_hash = ?",
            (token_hash,),
        ).fetchone()
        conn.close()
        if not row:
            return None
        return {"token_id": row[0], "user_id": row[1], "last4": row[2], "created_at": row[3], "last_used_at": row[4]}

    def touch_device_token(self, token_id: str) -> None:
        conn = _connect()
        conn.execute(
            "UPDATE device_tokens SET last_used_at = ? WHERE token_id = ?",
            (time.time(), token_id),
        )
        conn.commit()
        conn.close()

    def delete_device_token(self, user_id: str) -> bool:
        conn = _connect()
        cursor = conn.execute("DELETE FROM device_tokens WHERE user_id = ?", (user_id,))
        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return deleted
