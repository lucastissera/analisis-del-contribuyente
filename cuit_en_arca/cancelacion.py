"""Señales de cancelación de procesos en curso (por job_id o análisis programado)."""

from __future__ import annotations

import threading
from typing import Callable

_lock = threading.Lock()
_cancelados: set[str] = set()
_cancelar_ap = False


def reset_cancelacion(job_id: str) -> None:
    with _lock:
        _cancelados.discard(job_id)


def solicitar_cancelacion(job_id: str) -> None:
    with _lock:
        _cancelados.add(job_id)


def cancelacion_solicitada(job_id: str) -> bool:
    with _lock:
        return job_id in _cancelados


def reset_cancelacion_ap() -> None:
    global _cancelar_ap
    with _lock:
        _cancelar_ap = False


def solicitar_cancelacion_ap() -> None:
    global _cancelar_ap
    with _lock:
        _cancelar_ap = True


def cancelacion_solicitada_ap() -> bool:
    with _lock:
        return _cancelar_ap


def verificar_cancelacion(job_id: str | None = None, *, ap: bool = False) -> None:
    from cuit_en_arca.errores import CancelacionUsuarioError

    if ap:
        if cancelacion_solicitada_ap():
            raise CancelacionUsuarioError("Descarga cancelada por el usuario.")
        return
    if job_id and cancelacion_solicitada(job_id):
        raise CancelacionUsuarioError("Descarga cancelada por el usuario.")


def cupo_consumible_tras_cuit(
    job_id: str | None = None,
    *,
    modo_ap: bool = False,
) -> bool:
    """False si el usuario canceló: el CUIT en curso no debe descontar cupo."""
    if modo_ap and cancelacion_solicitada_ap():
        return False
    if job_id and cancelacion_solicitada(job_id):
        return False
    return True


def confirmar_cupo_cuit_procesado(
    on_cuit_exitoso: Callable[[], None] | None,
    *,
    usuario_cupo: str | None = None,
    job_id: str | None = None,
    modo_ap: bool = False,
    on_log: Callable[[str], None] | None = None,
) -> None:
    """Descuenta 1 CUIT del cupo al terminar bien una fila de un lote.

    Se invoca fila a fila: los CUIT ya confirmados conservan el descuento aunque
    el resto del lote falle o el job quede en estado de error parcial.
    """
    from cuit_en_arca.errores import CancelacionUsuarioError

    if not cupo_consumible_tras_cuit(job_id, modo_ap=modo_ap):
        raise CancelacionUsuarioError("Descarga cancelada por el usuario.")
    u = (usuario_cupo or "").strip()
    if u:
        from auth import es_administrador
        from auth_registro import consumir_cuit_exitoso, ultimo_error_cupo

        if not es_administrador(u) and not consumir_cuit_exitoso(u):
            msg = ultimo_error_cupo() or (
                f"Cupo no registrado para {u}. Revise auth_remote.txt y conexión."
            )
            import logging

            logging.getLogger(__name__).warning(msg)
            if on_log:
                try:
                    on_log(f"AVISO CUPO: {msg}")
                except Exception:
                    pass
    elif on_cuit_exitoso:
        on_cuit_exitoso()
