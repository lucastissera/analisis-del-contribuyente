"""Estado de jobs de Ventas y Liquidaciones (progreso en pantalla)."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from cuit_en_arca.hora_log import hora_log_ar

_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}

PASOS_VL_LOGIN = ("login", "Iniciar sesión en ARCA")

PASOS_VL_GRANOS: tuple[tuple[str, str], ...] = (
    ("servicio_granos", "Abrir liquidaciones de granos"),
    ("contribuyente_granos", "Seleccionar contribuyente (granos)"),
    ("consulta_prim", "Consulta liquidaciones primarias recibidas"),
    ("descargar_prim", "Descargar PDF primarias"),
    ("consulta_sec", "Consulta liquidaciones secundarias recibidas"),
    ("descargar_sec", "Descargar PDF secundarias"),
)

PASOS_VL_HACIENDA: tuple[tuple[str, str], ...] = (
    ("servicio_hacienda", "Abrir Comprobantes en línea — Hacienda"),
    ("contribuyente_rcel", "Seleccionar empresa (Comprobantes en línea)"),
    ("contribuyente_lsp", "Seleccionar empresa (liquidación hacienda)"),
    ("consulta_emisor", "Consulta liquidaciones por emisor"),
    ("descargar_emisor", "Descargar PDF por emisor"),
    ("consulta_receptor", "Consulta liquidaciones por receptor"),
    ("descargar_receptor", "Descargar PDF por receptor"),
)

# Compatibilidad con código que aún referencia PASOS_VL
PASOS_VL = (PASOS_VL_LOGIN,) + PASOS_VL_GRANOS

_MAX_LOG = 400


def pasos_vl_para(sistemas: list[str] | None) -> tuple[tuple[str, str], ...]:
    sis = sistemas or ["granos"]
    out: list[tuple[str, str]] = [PASOS_VL_LOGIN]
    if "granos" in sis:
        out.extend(PASOS_VL_GRANOS)
    if "hacienda" in sis:
        out.extend(PASOS_VL_HACIENDA)
    return tuple(out)


@dataclass
class EstadoJobVl:
    job_id: str
    total: int
    actual: int = 0
    mensaje: str = ""
    estado: str = "pendiente"
    error: str | None = None
    carpeta: str | None = None
    total_archivos: int = 0
    cuits_ok: int = 0
    cuits_fallidos: int = 0
    log: list[str] = field(default_factory=list)
    resumen: list[dict[str, Any]] = field(default_factory=list)
    pasos: list[dict[str, str]] = field(default_factory=list)
    archivos: list[dict[str, str]] = field(default_factory=list)

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
            "error": self.error,
            "carpeta": self.carpeta,
            "total_archivos": self.total_archivos,
            "cuits_ok": self.cuits_ok,
            "cuits_fallidos": self.cuits_fallidos,
            "porcentaje": pct,
            "log": list(self.log),
            "resumen": list(self.resumen),
            "pasos": list(self.pasos),
            "archivos": list(self.archivos),
        }


def crear_job_vl(
    job_id: str,
    total: int,
    *,
    sistemas: list[str] | None = None,
) -> None:
    with _lock:
        _jobs[job_id] = {
            "estado": EstadoJobVl(job_id=job_id, total=total, mensaje="Iniciando…"),
            "sistemas": list(sistemas or ["granos"]),
        }


def reiniciar_pasos_vl(job_id: str, sistemas: list[str] | None = None) -> None:
    with _lock:
        item = _jobs.get(job_id)
        if not item:
            return
        st: EstadoJobVl = item["estado"]
        sis = sistemas or item.get("sistemas") or ["granos"]
        item["sistemas"] = list(sis)
        st.pasos = [
            {"clave": clave, "etiqueta": etiqueta, "estado": "pendiente"}
            for clave, etiqueta in pasos_vl_para(sis)
        ]


def callback_paso_vl(job_id: str) -> Callable[[str, str], None]:
    def _cb(clave: str, estado: str) -> None:
        with _lock:
            item = _jobs.get(job_id)
            if not item:
                return
            st: EstadoJobVl = item["estado"]
            for paso in st.pasos:
                if paso["clave"] == clave:
                    paso["estado"] = estado
                    break

    return _cb


def callback_log_vl(job_id: str) -> Callable[[str], None]:
    def _cb(texto: str) -> None:
        with _lock:
            item = _jobs.get(job_id)
            if not item:
                return
            st: EstadoJobVl = item["estado"]
            ts = hora_log_ar()
            st.log.append(f"[{ts}] {texto}")
            if len(st.log) > _MAX_LOG:
                st.log = st.log[-_MAX_LOG:]
            st.mensaje = texto

    return _cb


def progreso_cuit_vl(job_id: str, actual: int, total: int, mensaje: str = "") -> None:
    with _lock:
        item = _jobs.get(job_id)
        if not item:
            return
        st: EstadoJobVl = item["estado"]
        st.actual = actual
        st.total = total
        if mensaje:
            st.mensaje = mensaje


def agregar_archivo_vl(
    job_id: str, download_id: str, rel_path: str, nombre: str
) -> None:
    with _lock:
        item = _jobs.get(job_id)
        if not item:
            return
        st: EstadoJobVl = item["estado"]
        st.archivos.append(
            {"download_id": download_id, "path": rel_path, "nombre": nombre}
        )


def agregar_resumen_cuit_vl(
    job_id: str,
    *,
    cuit: str,
    razon_social: str | None,
    total_archivos: int,
    error: str | None,
) -> None:
    with _lock:
        item = _jobs.get(job_id)
        if not item:
            return
        st: EstadoJobVl = item["estado"]
        st.resumen.append(
            {
                "cuit": cuit,
                "razon_social": razon_social or "",
                "total_archivos": total_archivos,
                "error": error,
            }
        )
        st.total_archivos += int(total_archivos or 0)
        if error:
            st.cuits_fallidos += 1
        else:
            st.cuits_ok += 1


def marcar_ok_vl(job_id: str, *, carpeta: str) -> None:
    with _lock:
        item = _jobs.get(job_id)
        if not item:
            return
        st: EstadoJobVl = item["estado"]
        st.estado = "ok"
        st.carpeta = carpeta
        st.mensaje = "Proceso completado."


def marcar_error_vl(job_id: str, error: str) -> None:
    with _lock:
        item = _jobs.get(job_id)
        if not item:
            return
        st: EstadoJobVl = item["estado"]
        st.estado = "error"
        st.error = error
        st.mensaje = error


def marcar_cancelado_vl(job_id: str, msg: str) -> None:
    with _lock:
        item = _jobs.get(job_id)
        if not item:
            return
        st: EstadoJobVl = item["estado"]
        st.estado = "cancelado"
        st.error = msg
        st.mensaje = msg


def obtener_job_vl(job_id: str) -> dict[str, Any] | None:
    with _lock:
        item = _jobs.get(job_id)
        if not item:
            return None
        return item["estado"].a_dict()
