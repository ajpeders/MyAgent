"""Pydantic models for auth service."""
from pydantic import BaseModel


class AuthResult(BaseModel):
    user_id: str
    session_id: str
    token: str
    account: str


class User(BaseModel):
    user_id: str
    email: str
    created_at: float


class ImapAccount(BaseModel):
    name: str
    server: str
    port: int = 993
    username: str
    imap_password: str


class ImapAccountResponse(BaseModel):
    id: str
    name: str
    server: str
    username: str
    created_at: str


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: str
    password: str
