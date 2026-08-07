"""Registro central de métricas de uso por servicio (dashboard admin).

Al agregar una solapa/servicio nuevo con conteo de uso:
1. Añadir entrada en ``METRICAS_USO`` (servicio_id = clave en ``SERVICIOS_IDS``).
2. Registrar el uso en la automatización (``registrar_valor_*`` / ``RegistroValorUso``).
3. Añadir ``meta_key`` en ``auth._OVERLAY_SYNC_KEYS`` (sync portable).
4. Texto i18n ``admin_dashboard_valor_<dash_key>`` en ``i18n.py``.

El dashboard web, el Excel y el uso mensual se generan desde esta tabla.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MetricaUsoServicio:
    servicio_id: str
    meta_key: str
    mes_key: str
    dash_key: str
    i18n_label: str
    excel_label: str


METRICAS_USO: tuple[MetricaUsoServicio, ...] = (
    MetricaUsoServicio(
        servicio_id="procesador",
        meta_key="uso_mce_comprobantes",
        mes_key="mce",
        dash_key="mce_comprobantes",
        i18n_label="admin_dashboard_valor_mce",
        excel_label="Comprob. emitidos (MCE)",
    ),
    MetricaUsoServicio(
        servicio_id="procesador",
        meta_key="uso_mcr_comprobantes",
        mes_key="mcr",
        dash_key="mcr_comprobantes",
        i18n_label="admin_dashboard_valor_mcr",
        excel_label="Comprob. recibidos (MCR)",
    ),
    MetricaUsoServicio(
        servicio_id="dfe",
        meta_key="uso_dfe_notificaciones",
        mes_key="dfe",
        dash_key="dfe_notificaciones",
        i18n_label="admin_dashboard_valor_dfe",
        excel_label="Notificaciones DFE",
    ),
    MetricaUsoServicio(
        servicio_id="vl",
        meta_key="uso_vl_cuits",
        mes_key="vl",
        dash_key="vl_cuits",
        i18n_label="admin_dashboard_valor_vl",
        excel_label="CUIT Ventas y Liquidaciones",
    ),
    MetricaUsoServicio(
        servicio_id="np",
        meta_key="uso_np_cuits",
        mes_key="np",
        dash_key="np_cuits",
        i18n_label="admin_dashboard_valor_np",
        excel_label="CUIT Nuestra Parte",
    ),
)


def meta_keys_uso() -> tuple[str, ...]:
    return tuple(m.meta_key for m in METRICAS_USO)


def mes_keys_uso() -> tuple[str, ...]:
    return ("cuit",) + tuple(m.mes_key for m in METRICAS_USO)


def meta_key_a_mes_key() -> dict[str, str]:
    return {m.meta_key: m.mes_key for m in METRICAS_USO}


def metricas_dashboard_desde_uso(uso: dict[str, int]) -> dict[str, int]:
    return {m.dash_key: int(uso.get(m.meta_key) or 0) for m in METRICAS_USO}


def fila_uso_mes_desde_bucket(mes: str, mes_fmt: str, bucket: dict[str, Any]) -> dict[str, Any]:
    fila: dict[str, Any] = {"mes": mes, "mes_fmt": mes_fmt, "cuit": max(0, int(bucket.get("cuit") or 0))}
    for m in METRICAS_USO:
        try:
            fila[m.mes_key] = max(0, int(bucket.get(m.mes_key) or 0))
        except (TypeError, ValueError):
            fila[m.mes_key] = 0
    return fila


def fila_uso_mes_vacia(mes: str, mes_fmt: str) -> dict[str, Any]:
    fila: dict[str, Any] = {"mes": mes, "mes_fmt": mes_fmt, "cuit": 0}
    for m in METRICAS_USO:
        fila[m.mes_key] = 0
    return fila
