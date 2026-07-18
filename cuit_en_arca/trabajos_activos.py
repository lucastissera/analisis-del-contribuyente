"""Indica si hay automatizaciones ARCA en curso (para no apagar el .exe portable)."""

from __future__ import annotations


def _job_en_curso(estado: str, actual: int, total: int) -> bool:
    if estado in ("ok", "error", "cancelado", "idle"):
        return False
    if estado in ("en_progreso", "en_curso"):
        return True
    if total > 0 and actual < total:
        return True
    return estado == "pendiente" and total > 0 and actual == 0


def hay_trabajos_arca_en_curso() -> bool:
    """True si algún módulo tiene un job de descarga/emisión activo."""
    try:
        from cuit_en_arca.progreso_analisis_programado import ejecutando_ap

        if ejecutando_ap():
            return True
    except Exception:
        pass

    modulos = (
        "cuit_en_arca.progreso_lote",
        "cuit_en_arca.progreso_dfe",
        "cuit_en_arca.progreso_vl",
        "cuit_en_arca.progreso_nuestra_parte",
        "cuit_en_arca.progreso_facturador",
    )
    for nombre in modulos:
        try:
            mod = __import__(nombre, fromlist=["_jobs", "_lock"])
            lock = getattr(mod, "_lock", None)
            jobs = getattr(mod, "_jobs", None)
            if lock is None or jobs is None:
                continue
            with lock:
                for item in jobs.values():
                    st = item.get("estado") if isinstance(item, dict) else item
                    if st is None:
                        continue
                    estado = getattr(st, "estado", "")
                    actual = int(getattr(st, "actual", 0) or 0)
                    total = int(getattr(st, "total", 0) or 0)
                    if _job_en_curso(str(estado), actual, total):
                        return True
                    pasos = getattr(st, "pasos", None) or []
                    if any(
                        isinstance(p, dict) and p.get("estado") in ("en_curso", "error")
                        for p in pasos
                    ):
                        if str(estado) not in ("ok", "error", "cancelado"):
                            return True
        except Exception:
            continue
    return False
