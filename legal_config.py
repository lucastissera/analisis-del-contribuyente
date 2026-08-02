"""Configuración de documentos legales (TyC, privacidad). Revisar con abogado antes de producción."""

from __future__ import annotations

import os

# Incrementar al publicar cambios sustanciales en TyC o privacidad.
LEGAL_VERSION = "2026-08-02-v2"

LEGAL_DOCUMENTOS = ("terminos", "privacidad")


def titular_razon_social() -> str:
    return (os.environ.get("LEGAL_TITULAR_RAZON_SOCIAL") or "Lucas Tissera Laplagne").strip()


def titular_cuit() -> str:
    return (os.environ.get("LEGAL_TITULAR_CUIT") or "").strip()


def titular_email() -> str:
    return (
        os.environ.get("LEGAL_TITULAR_EMAIL")
        or os.environ.get("AUTH_ADMIN_NOTIFY_EMAIL")
        or ""
    ).strip()


def titular_domicilio() -> str:
    return (os.environ.get("LEGAL_TITULAR_DOMICILIO") or "República Argentina").strip()


def jurisdiccion() -> str:
    return (
        os.environ.get("LEGAL_JURISDICCION")
        or "Tribunales Ordinarios de la Ciudad de Córdoba, Provincia de Córdoba"
    ).strip()


PROVEEDORES_TRANSFERENCIA_INTERNACIONAL: tuple[dict[str, str], ...] = (
    {
        "nombre": "Render Services, Inc.",
        "servicio": "Hosting de la aplicación web (servidor)",
        "ubicacion": "Estados Unidos de América",
        "finalidad": "Ejecución del servicio SaaS",
    },
    {
        "nombre": "Neon, Inc.",
        "servicio": "Base de datos PostgreSQL (usuarios, suscripciones, métricas)",
        "ubicacion": "Estados Unidos de América / Unión Europea (según región del proyecto)",
        "finalidad": "Persistencia de datos de cuenta y configuración",
    },
    {
        "nombre": "Resend, Inc.",
        "servicio": "Envío de correos transaccionales (opcional)",
        "ubicacion": "Estados Unidos de América",
        "finalidad": "Notificaciones de alta, recuperación de clave, avisos al administrador",
    },
)
