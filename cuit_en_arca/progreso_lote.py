"""Estado de jobs de descarga masiva ARCA (progreso en pantalla)."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from cuit_en_arca.stealth import SEC_ESTIMADOS_POR_CUIT

_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}


@dataclass
class EstadoJobLote:
    job_id: str
    total: int
    actual: int = 0
    mensaje: str = ""
    estado: str = "pendiente"  # pendiente | en_progreso | ok | error
    eta_seg: int | None = None
    error: str | None = None
    download_id: str | None = None
    nombre_archivo: str | None = None
    descargas_ok: int = 0
    ingresos_fallidos: int = 0
    _inicio: float = field(default_factory=time.time)
    _duraciones: list[float] = field(default_factory=list)
    _ultima_fila: float = field(default_factory=time.time)

    def a_dict(self) -> dict[str, Any]:
        pct = 0
        if self.total > 0:
            pct = min(100, int(round(100 * self.actual / self.total)))
        return {
            "job_id": self.job_id,
            "total": self.total,
            "actual": self.actual,
            "mensaje": self.mensaje,
            "estado": self.estado,
            "eta_seg": self.eta_seg,
            "error": self.error,
            "download_id": self.download_id,
            "nombre_archivo": self.nombre_archivo,
            "descargas_ok": self.descargas_ok,
            "ingresos_fallidos": self.ingresos_fallidos,
            "porcentaje": pct,
        }


def crear_job(job_id: str, total: int) -> None:
    with _lock:
        _jobs[job_id] = {
            "estado": EstadoJobLote(job_id=job_id, total=total, mensaje="Iniciando…"),
            "resultado": None,
        }


def callback_progreso(job_id: str) -> Callable[[int, int, str, bool], None]:
    """actual (1-based), total, mensaje, fila_terminada."""

    def _cb(actual: int, total: int, mensaje: str, fila_terminada: bool) -> None:
        with _lock:
            item = _jobs.get(job_id)
            if not item:
                return
            st: EstadoJobLote = item["estado"]
            st.actual = actual
            st.total = total
            st.mensaje = mensaje
            st.estado = "en_progreso"
            if fila_terminada:
                ahora = time.time()
                st._duraciones.append(ahora - st._ultima_fila)
                st._ultima_fila = ahora
            restantes = max(0, total - actual)
            if st._duraciones:
                prom = sum(st._duraciones) / len(st._duraciones)
                st.eta_seg = int(round(prom * restantes))
            else:
                st.eta_seg = int(round(SEC_ESTIMADOS_POR_CUIT * restantes))

    return _cb


def marcar_ok(
    job_id: str,
    *,
    download_id: str,
    nombre_archivo: str,
    descargas_ok: int,
    ingresos_fallidos: int,
) -> None:
    with _lock:
        item = _jobs.get(job_id)
        if not item:
            return
        st: EstadoJobLote = item["estado"]
        st.estado = "ok"
        st.actual = st.total
        st.eta_seg = 0
        st.mensaje = "Completado"
        st.download_id = download_id
        st.nombre_archivo = nombre_archivo
        st.descargas_ok = descargas_ok
        st.ingresos_fallidos = ingresos_fallidos


def marcar_error(job_id: str, error: str) -> None:
    with _lock:
        item = _jobs.get(job_id)
        if not item:
            return
        st: EstadoJobLote = item["estado"]
        st.estado = "error"
        st.error = error
        st.eta_seg = 0


def guardar_resultado(job_id: str, resultado) -> None:
    with _lock:
        item = _jobs.get(job_id)
        if item:
            item["resultado"] = resultado


def obtener_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        item = _jobs.get(job_id)
        if not item:
            return None
        return item["estado"].a_dict()


def tomar_resultado(job_id: str):
    with _lock:
        item = _jobs.pop(job_id, None)
        if not item:
            return None
        return item.get("resultado")
