"""Nombre comercial y rutas técnicas del producto (exe, logs)."""

from __future__ import annotations

APP_NAME = "Análisis Integral del Contribuyente"
APP_EXE_BASENAME = "AnalisisIntegralContribuyente"
APP_LOG_FILENAME = f"{APP_EXE_BASENAME}_error.log"
# Versión comercial / telemetría de integridad (bump al publicar portable).
APP_VERSION = "2026.8.1"

# Despliegue (Render + GitHub)
GITHUB_REPO_URL = "https://github.com/lucastissera/analisis-del-contribuyente"
GITHUB_REPO_BRANCH = "main"
RENDER_SERVICE_NAME = "analisisdelcontribuyente"
RENDER_PUBLIC_URL = "https://analisisdelcontribuyente.onrender.com"
AUTH_USERS_API_URL = f"{RENDER_PUBLIC_URL}/api/auth-users"
