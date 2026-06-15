"""Señales de cancelación de procesos en curso (por job_id o análisis programado)."""

from __future__ import annotations

import threading

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
