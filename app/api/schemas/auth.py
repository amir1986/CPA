"""Pydantic schemas for the auth router."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=200)
    name: str | None = Field(default=None, max_length=120)
    firm_name: str | None = Field(default=None, max_length=200, description="Required for self-serve new-firm signup.")
    firm_invite_code: str | None = Field(default=None, max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"


class UserOut(BaseModel):
    id: str
    email: EmailStr
    name: str | None
    role: str
    locale: str
    firm_id: str
    email_verified: bool


class LoginOut(BaseModel):
    tokens: TokenPair
    user: UserOut


class VerifyIn(BaseModel):
    token: str


class ResetRequestIn(BaseModel):
    email: EmailStr


class ResetConfirmIn(BaseModel):
    token: str
    new_password: str = Field(min_length=12, max_length=200)


class RefreshIn(BaseModel):
    refresh_token: str


class MessageOut(BaseModel):
    detail: str
