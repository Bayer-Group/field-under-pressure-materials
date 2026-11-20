"""Backend registry. Only PostGIS is shipped; the Backend ABC keeps the pipeline engine-free
(tests plug in a SQLite double through `register_backend`)."""
from __future__ import annotations

import importlib

BACKENDS = {
    "postgis": "dbload.backends.postgis_backend:PostgisBackend",
}


def register_backend(name: str, target) -> None:
    """target: 'module:Class' string or a Backend subclass."""
    BACKENDS[name] = target


def get_backend_class(name: str):
    if name not in BACKENDS:
        raise SystemExit(f"unknown backend {name!r}; available: {', '.join(BACKENDS)}")
    target = BACKENDS[name]
    if not isinstance(target, str):
        return target
    module, cls = target.split(":")
    return getattr(importlib.import_module(module), cls)


def get_backend(name: str, dsn: str, **options):
    return get_backend_class(name)(dsn, **options)
