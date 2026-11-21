# -*- coding: utf-8 -*-
"""Database access of the API: a small pool of psycopg connections (standard library only).

A new connection costs about 15 ms of server CPU (a process and a SCRAM handshake) against 0.25 ms for a query on an open one, so
connections are kept and reused. The pool also limits how many requests work on the database at once; the rest wait up to
POOL_WAIT_SECONDS and then get 503. Reads use a read-only transaction, writes commit themselves.
"""
from __future__ import annotations

import os
import queue
import threading
import time

import psycopg
from fastapi import HTTPException
from psycopg.rows import dict_row

from backend.app.core.config import DATABASE_URL

POOL_SIZE = int(os.environ.get("DB_POOL_SIZE", "12"))
POOL_WAIT_SECONDS = float(os.environ.get("DB_POOL_WAIT_SECONDS", "10"))


class Pool:
    def __init__(self, dsn: str, size: int):
        self.dsn, self.size = dsn, size
        self._idle: queue.LifoQueue = queue.LifoQueue()
        self._created = 0
        self._lock = threading.Lock()

    def _connect(self):
        return psycopg.connect(self.dsn, row_factory=dict_row, connect_timeout=5)

    def acquire(self):
        """A working connection (HTTP 503 when the database is unreachable or no connection frees up within POOL_WAIT_SECONDS)."""
        deadline = time.monotonic() + POOL_WAIT_SECONDS
        while True:
            try:
                con = self._idle.get_nowait()
            except queue.Empty:
                with self._lock:
                    make = self._created < self.size
                    if make:
                        self._created += 1
                if make:
                    try:
                        return self._connect()
                    except psycopg.OperationalError:
                        with self._lock:
                            self._created -= 1
                        raise HTTPException(status_code=503, detail="database is not reachable")
                try:                                           # wait once, for all the time that is left
                    con = self._idle.get(timeout=max(0.0, deadline - time.monotonic()))
                except queue.Empty:
                    raise HTTPException(status_code=503, detail="busy, try again in a moment")
            try:
                con.execute("SELECT 1")                        # cheap check that the connection survived (restart, timeout)
                con.rollback()
                return con
            except psycopg.Error:
                self._drop(con)                                # and try again: a slot is free for a new connection

    def release(self, con) -> None:
        try:
            if con.closed or con.broken:
                raise psycopg.OperationalError("connection is not usable")
            con.rollback()                                     # an uncommitted transaction never leaks to the next request
        except psycopg.Error:
            self._drop(con)
            return
        self._idle.put(con)

    def _drop(self, con) -> None:
        try:
            con.close()
        except psycopg.Error:
            pass
        with self._lock:
            self._created -= 1


_pool: Pool | None = None
_pool_lock = threading.Lock()


def _get_pool() -> Pool:
    global _pool
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="database is not configured (DATABASE_URL)")
    with _pool_lock:
        if _pool is None:
            _pool = Pool(DATABASE_URL, POOL_SIZE)
        return _pool


def get_db():
    """FastAPI dependency: a pooled connection for reading (read-only transaction, dict rows)."""
    pool = _get_pool()
    con = pool.acquire()
    con.read_only = True
    try:
        yield con
    finally:
        pool.release(con)


def get_db_rw():
    """FastAPI dependency: a pooled connection for writes. The endpoint commits itself; without a commit it is rolled back."""
    pool = _get_pool()
    con = pool.acquire()
    con.read_only = False
    try:
        yield con
    finally:
        pool.release(con)
