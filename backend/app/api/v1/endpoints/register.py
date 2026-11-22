# -*- coding: utf-8 -*-
"""POST /register: add yourself as a user with just a login and a password (a mock, not real authentication).

The new account owns an empty farm (owner `u-<login>`) that can be edited, and is logged in at once. Limited: requests per address,
a ceiling on the number of accounts, ALLOW_REGISTRATION and DEMO_READONLY switch it off.
"""
from __future__ import annotations

from typing import Optional

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.app.api.v1.endpoints.farm import session
from backend.app.core.config import ALLOW_REGISTRATION, DEMO_READONLY, MAX_ACCOUNTS
from backend.app.core.db import get_db_rw
from backend.app.core.limits import RateLimiter, client_ip, enforce
from backend.app.core.security import hash_password
from backend.app.services import accounts

router = APIRouter()

_register_limit = RateLimiter(20, 60)             # new accounts per minute and address (per worker process)


class RegisterIn(BaseModel):
    login: str
    password: str
    display_name: Optional[str] = Field(None, max_length=60)


@router.post("/register", status_code=201, summary="Add yourself: a login and a password, nothing else")
def register(body: RegisterIn, request: Request, con=Depends(get_db_rw)):
    if DEMO_READONLY or not ALLOW_REGISTRATION:
        raise HTTPException(status_code=503, detail="adding users is switched off now")
    enforce(_register_limit, client_ip(request))
    error = accounts.validate_registration(body.login, body.password)
    if error:
        raise HTTPException(status_code=422, detail=error)
    login = accounts.normalize_login(body.login)
    if con.execute("SELECT count(*) AS n FROM app.user_account").fetchone()["n"] >= MAX_ACCOUNTS:
        raise HTTPException(status_code=503, detail="the demo has no room for more users")
    if con.execute("SELECT 1 FROM app.demo_user WHERE login = %s", (login,)).fetchone():
        raise HTTPException(status_code=409, detail="this login is taken")
    name = (body.display_name or "").strip() or login
    try:
        con.execute("INSERT INTO app.user_account (login, password_hash, owner_id, role, display_name) VALUES (%s, %s, %s, 'farmer', %s)",
                    (login, hash_password(body.password), accounts.owner_for(login), name))
    except psycopg.errors.UniqueViolation:
        raise HTTPException(status_code=409, detail="this login is taken")
    con.commit()
    out = session({"kind": "account", "id": login, "owner_id": accounts.owner_for(login), "role": "farmer", "display_name": name})
    out["created"] = True
    return out
