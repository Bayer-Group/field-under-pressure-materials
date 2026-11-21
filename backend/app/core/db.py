# -*- coding: utf-8 -*-
"""Database access of the API: one psycopg connection per request, read-only (the API reads the views of schema serve)."""
from __future__ import annotations

import psycopg
from fastapi import HTTPException
from psycopg.rows import dict_row

from backend.app.core.config import DATABASE_URL


def get_db_rw():
    """FastAPI dependency: a connection for writes. The endpoint commits itself; closing without a commit rolls back."""
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="database is not configured (DATABASE_URL)")
    try:
        con = psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=5)
    except psycopg.OperationalError:
        raise HTTPException(status_code=503, detail="database is not reachable")
    try:
        yield con
    finally:
        con.close()


def get_db():
    """FastAPI dependency: a read-only connection returning dict rows; 503 when the database is not reachable."""
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="database is not configured (DATABASE_URL)")
    try:
        con = psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=5)
    except psycopg.OperationalError:
        raise HTTPException(status_code=503, detail="database is not reachable")
    con.read_only = True
    try:
        yield con
    finally:
        con.close()
