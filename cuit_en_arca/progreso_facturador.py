"""Estado de jobs del Facturador (emisión de comprobantes)."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from cuit_en_arca.hora_log import hora_log_ar

_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}

PASOS_FACTURADOR: tuple[tuple[str, str], ...] = (
    ("login", "Iniciar sesión en ARCA"),
    ("servicio", "Abrir Comprobantes en línea"),
    ("representado", "Seleccionar representado"),
    ("generar", "Generar comprobantes"),
    ("punto_venta", "Punto de venta y tipo de comprobante"),
    ("datos_emisor", "Datos del emisor"),
    ("datos_receptor", "Datos del receptor"),
    ("datos_operacion", "Productos / servicios"),
    ("confirmar", "Confirmar emisión"),
    ("menu", "Volver al menú principal"),
)

_MAX_LOG = 400


@dataclass
class EstadoJobFacturador:
    job_id: str
    total: int
    actual: int = 0
    mensaje: str = ""
    estado: str = "pendiente"
    error: str | None = None
    ok: int = 0
    fallidos: int = 0
    log: list[str] = field(default_factory=list)
    resumen: list[dict[str, Any]] = field(default_factory=list)
    pasos: list[dict[str, str]] = field(default_factory=list)

    def a_dict(self) -> dict[str, Any]:
        pct = min(100, int(round(100 * self.actual / self.total))) if self.total else 0
        return {
            "job_id": self.job_id,
            "total": self.total,
            "actual": self.actual,
            "mensaje": self.mensaje,
            "estado": self.estado,
            "error": self.error,
            "ok": self.ok,
            "fallidos": self.fallidos,
            "porcentaje": pct,
            "log": list(self.log),
            "resumen": list(self.resumen),
            "pasos": list(self.pasos),
        }


def crear_job_facturador(job_id: str, total: int) -> None:
    with _lock:
        _jobs[job_id] = {
            "estado": EstadoJobFacturador(job_id=job_id, total=total, mensaje="Iniciando…"),
        }


def reiniciar_pasos_facturador(job_id: str) -> None:
    with _lock:
        item = _jobs.get(job_id)
        if not item:
            return
        st: EstadoJobFacturador = item["estado"]
        st.pasos = [
            {"clave": clave, "etiqueta": etiqueta, "estado": "pendiente"}
            for clave, etiqueta in PASOS_FACTURADOR
        ]


def marcar_pasos_omitidos_hasta(job_id: str, clave_hasta: str) -> None:
    """Marca como OK los pasos previos al reutilizar sesión (sin volver a ejecutarlos)."""
    with _lock:
        item = _jobs.get(job_id)
        if not item:
            return
        st: EstadoJobFacturador = item["estado"]
        for p in st.pasos:
            if p["estado"] == "pendiente":
                p["estado"] = "ok"
            if p["clave"] == clave_hasta:
                break


def callback_log_facturador(job_id: str) -> Callable[[str], None]:
    def _log(msg: str) -> None:
        with _lock:
            item = _jobs.get(job_id)
            if not item:
                return
            st: EstadoJobFacturador = item["estado"]
            linea = f"[{hora_log_ar()}] {msg}"
            st.log.append(linea)
            if len(st.log) > _MAX_LOG:
                st.log = st.log[-_MAX_LOG:]

    return _log


def callback_paso_facturador(job_id: str) -> Callable[[str, str], None]:
    def _paso(clave: str, estado: str) -> None:
        with _lock:
            item = _jobs.get(job_id)
            if not item:
                return
            st: EstadoJobFacturador = item["estado"]
            for p in st.pasos:
                if p["clave"] == clave:
                    p["estado"] = estado
                    break

    return _paso


def progreso_facturador(job_id: str, actual: int, total: int, mensaje: str) -> None:
    with _lock:
        item = _jobs.get(job_id)
        if not item:
            return
        st: EstadoJobFacturador = item["estado"]
        st.actual = actual
        st.total = total
        st.mensaje = mensaje
        st.estado = "en_curso"


def finalizar_job_facturador(
    job_id: str,
    *,
    ok: int,
    fallidos: int,
    resumen: list[dict[str, Any]],
    error: str | None = None,
) -> None:
    with _lock:
        item = _jobs.get(job_id)
        if not item:
            return
        st: EstadoJobFacturador = item["estado"]
        st.ok = ok
        st.fallidos = fallidos
        st.resumen = resumen
        st.estado = "error" if error and ok == 0 else ("ok" if fallidos == 0 else "ok")
        if error and ok == 0:
            st.error = error
        st.mensaje = f"Finalizado: {ok} emitida(s), {fallidos} con error."


def obtener_estado_facturador(job_id: str) -> dict[str, Any] | None:
    with _lock:
        item = _jobs.get(job_id)
        if not item:
            return None
        return item["estado"].a_dict()


def marcar_cancelado_facturador(job_id: str, mensaje: str) -> None:
    with _lock:
        item = _jobs.get(job_id)
        if not item:
            return
        st: EstadoJobFacturador = item["estado"]
        st.estado = "cancelado"
        st.error = mensaje
        st.mensaje = mensaje
