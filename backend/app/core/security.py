# -*- coding: utf-8 -*-
"""Demo authentication with the standard library only: scrypt password hashes and HMAC-signed tokens.

A demonstration login, not a production system (a production system would use OIDC). Isolation of the data is done on the server
by the owner in the token, never by the client.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Optional

_N, _R, _P = 2 ** 14, 8, 1


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str, salt: Optional[bytes] = None) -> str:
    """scrypt$n$r$p$salt$hash (base64url)."""
    salt = salt or os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        got = hashlib.scrypt(password.encode(), salt=_unb64(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(got, _unb64(digest))
    except (ValueError, TypeError):
        return False


def make_token(claims: dict, secret: str, ttl_seconds: int, now: Optional[float] = None) -> str:
    payload = dict(claims, exp=int((now if now is not None else time.time()) + ttl_seconds))
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    sig = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def read_token(token: str, secret: str, now: Optional[float] = None) -> Optional[dict]:
    """The claims, or None when the signature is wrong, the token is malformed or expired."""
    try:
        body, sig = token.split(".")
        expected = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        claims = json.loads(_unb64(body))
        if claims.get("exp", 0) < (now if now is not None else time.time()):
            return None
        return claims
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
