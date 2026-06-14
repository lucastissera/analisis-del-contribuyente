"""Persistencia de altas en PostgreSQL (p. ej. Neon) cuando hay DATABASE_URL."""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any

_LOG = logging.getLogger(__name__)
_lock = threading.Lock()
_initialized = False

_BLOBS = (
    "usuarios_registrados",
    "solicitudes_pendientes",
    "altas_completadas",
)


def database_url() -> str:
    raw = (os.environ.get("DATABASE_URL") or os.environ.get("AUTH_DATABASE_URL") or "").strip()
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://") :]
    return raw


def enabled() -> bool:
    return bool(database_url())


def _connect():
    import psycopg2

    return psycopg2.connect(database_url())


def _ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_registro_blob (
                name TEXT PRIMARY KEY,
                data JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    conn.commit()


def init_db() -> None:
    global _initialized
    if not enabled() or _initialized:
        return
    with _lock:
        if _initialized:
            return
        conn = _connect()
        try:
            _ensure_schema(conn)
            _initialized = True
            _LOG.info("Persistencia de altas: PostgreSQL listo")
        finally:
            conn.close()


def read_json(name: str, default: Any) -> Any:
    if name not in _BLOBS:
        raise ValueError(f"blob desconocido: {name}")
    init_db()
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT data FROM auth_registro_blob WHERE name = %s", (name,))
            row = cur.fetchone()
        if not row:
            return default
        data = row[0]
        if isinstance(data, str):
            return json.loads(data)
        return data
    except Exception as exc:
        _LOG.warning("No se pudo leer %s desde PostgreSQL: %s", name, exc)
        return default
    finally:
        conn.close()


def write_json(name: str, data: Any) -> None:
    if name not in _BLOBS:
        raise ValueError(f"blob desconocido: {name}")
    init_db()
    payload = json.dumps(data, ensure_ascii=False)
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO auth_registro_blob (name, data, updated_at)
                VALUES (%s, %s::jsonb, NOW())
                ON CONFLICT (name) DO UPDATE
                SET data = EXCLUDED.data, updated_at = NOW()
                """,
                (name, payload),
            )
        conn.commit()
    finally:
        conn.close()


def estado_db() -> dict[str, Any]:
    if not enabled():
        return {"activo": False, "url_configurada": False}
    init_db()
    out: dict[str, Any] = {"activo": True, "url_configurada": True, "blobs": {}}
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT name, updated_at FROM auth_registro_blob WHERE name = ANY(%s)",
                (list(_BLOBS),),
            )
            for name, updated_at in cur.fetchall():
                out["blobs"][name] = updated_at.isoformat() if updated_at else None
    except Exception as exc:
        out["error"] = str(exc)
    finally:
        conn.close()
    return out
