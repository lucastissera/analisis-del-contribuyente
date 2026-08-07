"""Persistencia de altas en PostgreSQL (p. ej. Neon) cuando hay DATABASE_URL."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any

_LOG = logging.getLogger(__name__)
_lock = threading.RLock()
_initialized = False
_blob_cache: dict[str, tuple[str, float]] = {}
_estado_db_cache: tuple[dict[str, Any], float] | None = None

_BLOBS = (
    "usuarios_registrados",
    "solicitudes_pendientes",
    "altas_completadas",
)


def database_url() -> str:
    raw = (os.environ.get("DATABASE_URL") or os.environ.get("AUTH_DATABASE_URL") or "").strip()
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://") :]
    if raw and "sslmode=" not in raw:
        sep = "&" if "?" in raw else "?"
        raw = f"{raw}{sep}sslmode=require"
    return raw


def enabled() -> bool:
    return bool(database_url())


def _cache_ttl_sec() -> float:
    raw = (os.environ.get("AUTH_REGISTRO_CACHE_SEC") or "45").strip()
    try:
        ttl = float(raw)
    except ValueError:
        ttl = 45.0
    return max(0.0, ttl)


def _invalidar_cache_blob(name: str | None = None) -> None:
    global _estado_db_cache
    if name is None:
        _blob_cache.clear()
        _estado_db_cache = None
        return
    _blob_cache.pop(name, None)
    _estado_db_cache = None


def _leer_blob_cache(name: str) -> Any | None:
    ttl = _cache_ttl_sec()
    if ttl <= 0:
        return None
    ahora = time.time()
    with _lock:
        entry = _blob_cache.get(name)
        if not entry or entry[1] <= ahora:
            return None
        try:
            return json.loads(entry[0])
        except json.JSONDecodeError:
            _blob_cache.pop(name, None)
            return None


def _guardar_blob_cache(name: str, data: Any) -> None:
    ttl = _cache_ttl_sec()
    if ttl <= 0:
        return
    try:
        payload = json.dumps(data, ensure_ascii=False)
    except (TypeError, ValueError):
        return
    with _lock:
        _blob_cache[name] = (payload, time.time() + ttl)


def _connect():
    import psycopg2

    # connect_timeout corto: si Neon está frío, fallar rápido y no colgar el login.
    return psycopg2.connect(
        database_url(),
        connect_timeout=5,
        options="-c statement_timeout=8000",
    )


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
    # No retener el lock durante el TCP/SSL a Neon (bloqueaba login/cache).
    conn = None
    try:
        conn = _connect()
        _ensure_schema(conn)
        with _lock:
            _initialized = True
        _LOG.info("Persistencia de altas: PostgreSQL listo")
    except Exception:
        with _lock:
            _initialized = False
        raise
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def read_json(name: str, default: Any) -> Any:
    if name not in _BLOBS:
        raise ValueError(f"blob desconocido: {name}")
    cached = _leer_blob_cache(name)
    if cached is not None:
        return cached
    try:
        init_db()
        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT data FROM auth_registro_blob WHERE name = %s", (name,))
                row = cur.fetchone()
            if not row:
                _guardar_blob_cache(name, default)
                return default
            data = row[0]
            if isinstance(data, str):
                data = json.loads(data)
            _guardar_blob_cache(name, data)
            return data
        finally:
            conn.close()
    except Exception as exc:
        _LOG.warning("No se pudo leer %s desde PostgreSQL: %s", name, exc)
        return default


def write_json(name: str, data: Any) -> None:
    if name not in _BLOBS:
        raise ValueError(f"blob desconocido: {name}")
    try:
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
            _LOG.info("PostgreSQL: guardado blob %s", name)
            _invalidar_cache_blob(name)
            _guardar_blob_cache(name, data)
        finally:
            conn.close()
    except Exception as exc:
        _LOG.error("No se pudo escribir %s en PostgreSQL: %s", name, exc)
        raise


def estado_db(*, forzar: bool = False) -> dict[str, Any]:
    global _estado_db_cache
    if not enabled():
        return {"activo": False, "url_configurada": False}
    ttl = _cache_ttl_sec()
    if not forzar and ttl > 0:
        ahora = time.time()
        with _lock:
            cached = _estado_db_cache
            if cached and cached[1] > ahora:
                return dict(cached[0])
    try:
        init_db()
    except Exception as exc:
        return {"activo": False, "url_configurada": True, "error": str(exc)}
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
            try:
                cur.execute("SELECT pg_database_size(current_database())")
                row = cur.fetchone()
                if row and row[0] is not None:
                    size_bytes = int(row[0])
                    out["tamano_bytes"] = size_bytes
                    out["tamano_mb"] = round(size_bytes / (1024 * 1024), 2)
                    try:
                        warn_mb = int((os.environ.get("NEON_STORAGE_WARN_MB") or "400").strip())
                    except ValueError:
                        warn_mb = 400
                    out["alerta_tamano"] = size_bytes >= warn_mb * 1024 * 1024
                    out["umbral_alerta_mb"] = warn_mb
            except Exception as exc:
                out["tamano_error"] = str(exc)
    except Exception as exc:
        out["error"] = str(exc)
    finally:
        conn.close()
    if ttl > 0:
        with _lock:
            _estado_db_cache = (dict(out), time.time() + ttl)
    return out


def contar_usuarios_registrados() -> int:
    try:
        data = read_json("usuarios_registrados", {"users": {}})
        users = data.get("users") if isinstance(data, dict) else {}
        return len(users) if isinstance(users, dict) else 0
    except Exception:
        return 0


def migrar_disco_a_db_si_vacio() -> int:
    """Copia JSON locales a PostgreSQL si la base está vacía (útil tras activar DATABASE_URL)."""
    if not enabled():
        return 0
    try:
        if contar_usuarios_registrados() > 0:
            return 0
    except Exception:
        pass
    from auth_registro import dir_auth_servidor

    base = dir_auth_servidor()
    archivos = {
        "usuarios_registrados": base / "usuarios_registrados.json",
        "solicitudes_pendientes": base / "solicitudes_pendientes.json",
        "altas_completadas": base / "altas_completadas.json",
    }
    migrados = 0
    for name, path in archivos.items():
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            write_json(name, data)
            migrados += 1
            _LOG.info("Migrado %s desde disco a PostgreSQL", name)
        except Exception as exc:
            _LOG.warning("No se pudo migrar %s: %s", name, exc)
    return migrados
