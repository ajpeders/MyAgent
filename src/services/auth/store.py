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
            "SELECT user_id, email, password_hash, encrypted_imap_creds, is_admin FROM users WHERE email = ?",
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
            "is_admin": bool(row[4]),
        }

    def get_user_by_id(self, user_id: str) -> dict | None:
        conn = _connect()
        row = conn.execute(
            "SELECT user_id, email, password_hash, encrypted_imap_creds, is_admin FROM users WHERE user_id = ?",
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
            "is_admin": bool(row[4]),
        }

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