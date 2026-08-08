"""Rate-limit en memoria (P1.10) para login / altas / recuperación.

Pensado para 1 worker (Gunicorn en Render). Con varios workers cada proceso
tiene su contador; para multi-nodo haría falta Redis u otro store compartido.

Variables opcionales (intentos / ventana en segundos):

  AUTH_RL_LOGIN_MAX=10
  AUTH_RL_LOGIN_WINDOW=900
  AUTH_RL_ALTA_MAX=5
  AUTH_RL_ALTA_WINDOW=3600
  AUTH_RL_RESET_MAX=5
  AUTH_RL_RESET_WINDOW=3600
  AUTH_RL_VERIFY_MAX=20
  AUTH_RL_VERIFY_WINDOW=900
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque

_lock = threading.Lock()
_hits: dict[str, deque[float]] = defaultdict(deque)

_PRESETS: dict[str, tuple[str, str, int, int]] = {
    # bucket: (env_max, env_window, default_max, default_window)
    "login": ("AUTH_RL_LOGIN_MAX", "AUTH_RL_LOGIN_WINDOW", 10, 900),
    "alta": ("AUTH_RL_ALTA_MAX", "AUTH_RL_ALTA_WINDOW", 5, 3600),
    "activar": ("AUTH_RL_ALTA_MAX", "AUTH_RL_ALTA_WINDOW", 10, 3600),
    "reset": ("AUTH_RL_RESET_MAX", "AUTH_RL_RESET_WINDOW", 5, 3600),
    "verify": ("AUTH_RL_VERIFY_MAX", "AUTH_RL_VERIFY_WINDOW", 20, 900),
}


def _int_env(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _limites(bucket: str) -> tuple[int, int]:
    conf = _PRESETS.get(bucket) or ("", "", 10, 900)
    env_max, env_win, d_max, d_win = conf
    return _int_env(env_max, d_max), _int_env(env_win, d_win)


def comprobar_limite(
    bucket: str, clave: str, *, registrar: bool = True
) -> tuple[bool, int]:
    """True si permitido. Si no, (False, segundos_para_reintentar).

    Con ``registrar=False`` solo consulta (no suma el intento).
    """
    b = (bucket or "login").strip().lower() or "login"
    k = (clave or "anon").strip().lower() or "anon"
    max_hits, window = _limites(b)
    key = f"{b}:{k}"
    ahora = time.time()
    with _lock:
        q = _hits[key]
        while q and q[0] <= ahora - window:
            q.popleft()
        if len(q) >= max_hits:
            retry = max(1, int(window - (ahora - q[0])) + 1)
            return False, retry
        if registrar:
            q.append(ahora)
        return True, 0


def reset_limites_tests() -> None:
    """Solo tests."""
    with _lock:
        _hits.clear()
