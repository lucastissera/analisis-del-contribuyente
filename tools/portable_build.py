#!/usr/bin/env python3
"""
Compila el portable con PyInstaller, genera ``auth_users.enc`` (cifrado) e instala Chromium
en ``dist/AnalisisIntegralContribuyente/ms-playwright`` para descarga ARCA en el .exe.

Uso: desde la raíz del proyecto
  python tools/portable_build.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_branding import APP_EXE_BASENAME

DIST_DIR = ROOT / "dist" / APP_EXE_BASENAME
SPEC = ROOT / "MisComprobantesDesktop.spec"
AUTH_SRC_JSON = ROOT / "auth_users.json"
AUTH_SRC_ENC = ROOT / "auth_users.enc"
BROWSERS_DIR = DIST_DIR / "ms-playwright"
LOGO_PNG = ROOT / "static" / "logo.png"
LOGO_ICO = ROOT / "static" / "logo.ico"
ISOTIPO_PNG = ROOT / "static" / "isotipo.png"


def _preparar_logo() -> None:
    """Regenera logo.ico desde static/isotipo.png (marca Vórtice) para el icono del .exe."""
    fuente = ISOTIPO_PNG if ISOTIPO_PNG.is_file() else LOGO_PNG
    if not fuente.is_file():
        return
    try:
        from PIL import Image

        img = Image.open(fuente).convert("RGBA")
        # Recorte cuadrado al contenido visible (isotipo / isologo)
        bbox = img.getbbox()
        if bbox:
            img = img.crop(bbox)
        lado = max(img.size)
        cuadrado = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
        ox = (lado - img.width) // 2
        oy = (lado - img.height) // 2
        cuadrado.paste(img, (ox, oy), img)
        cuadrado.save(
            LOGO_ICO,
            format="ICO",
            sizes=[(s, s) for s in (16, 32, 48, 64, 128, 256)],
        )
    except Exception as exc:
        print(f"Aviso: no se pudo regenerar {LOGO_ICO}: {exc}", file=sys.stderr)


def _instalar_chromium_portable() -> int:
    BROWSERS_DIR.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(BROWSERS_DIR)
    print(f"Instalando Chromium para ARCA en {BROWSERS_DIR}…", flush=True)
    r = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        env=env,
        cwd=str(ROOT),
    )
    if r.returncode != 0:
        print(
            "AVISO: falló playwright install chromium. "
            "La descarga ARCA no funcionará en el .exe hasta reinstalarlo.",
            file=sys.stderr,
        )
    return r.returncode


def _copiar_usuarios_portable() -> None:
    """Solo ``auth_users.enc`` en dist (nunca JSON en claro)."""
    import json

    from auth_crypto import escribir_archivo_cifrado, leer_archivo_usuarios

    dest = DIST_DIR / "auth_users.enc"
    if AUTH_SRC_ENC.is_file():
        shutil.copy2(AUTH_SRC_ENC, dest)
        print(f"Usuarios cifrados copiados: {dest}", flush=True)
        return
    if AUTH_SRC_JSON.is_file():
        try:
            with open(AUTH_SRC_JSON, encoding="utf-8-sig") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"ERROR leyendo {AUTH_SRC_JSON}: {exc}", file=sys.stderr)
            return
        if isinstance(data, dict):
            escribir_archivo_cifrado(dest, data)
            print(f"Usuarios cifrados generados: {dest}", flush=True)
            return
    print(
        "Aviso: no hay auth_users.enc ni auth_users.json en la raíz.\n"
        "  • Neon/web: python tools/setup_auth_portable.py --token … -> auth_remote.enc\n"
        "  • Local: python tools/encrypt_auth_users.py",
        flush=True,
    )


def main() -> int:
    if not SPEC.is_file():
        print(f"ERROR: no se encuentra {SPEC}", file=sys.stderr)
        return 1
    _preparar_logo()
    print("Ejecutando PyInstaller…", flush=True)
    r = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", str(SPEC)],
        cwd=str(ROOT),
    )
    if r.returncode != 0:
        return r.returncode
    if not DIST_DIR.is_dir():
        print(f"ERROR: no existe {DIST_DIR} tras compilar.", file=sys.stderr)
        return 1
    ejemplo_remoto = ROOT / "auth_remote.example.txt"
    if ejemplo_remoto.is_file():
        shutil.copy2(ejemplo_remoto, DIST_DIR / "auth_remote.example.txt")
    _copiar_usuarios_portable()
    _instalar_chromium_portable()
    # Authenticode antes del manifiesto: el hash del .exe debe incluir la firma.
    if _intentar_firma_authenticode() != 0:
        return 1
    if _generar_manifest_firmado() != 0:
        print(
            "AVISO: manifiesto no firmado (el portable igual se generó; "
            "definí AUTH_ENTITLEMENT_PRIVATE_KEY para firmar).",
            file=sys.stderr,
        )
    print(
        f"\nListo: {DIST_DIR}\n"
        "Distribuí la carpeta completa (exe + _internal + ms-playwright + manifest.signed.json).\n"
        "IMPORTANTE cupo: generá auth_remote.enc con setup_auth_portable.py --token …\n"
        "  (sync Neon). Sin esto el cupo NO se descuenta en el servidor.\n"
        "Firma Authenticode: docs/FIRMA_AUTHENTICODE.md "
        "(AIC_SIGN_PFX; AIC_SIGN_REQUIRED=1 para fallar sin cert).\n",
        flush=True,
    )
    return 0


def _generar_manifest_firmado() -> int:
    """Hashes + firma Ed25519 del dist (Fase 2.1)."""
    script = ROOT / "tools" / "generar_manifest_portable.py"
    if not script.is_file():
        print(f"Aviso: no está {script}", file=sys.stderr)
        return 1
    print("Generando manifest.signed.json…", flush=True)
    r = subprocess.run(
        [sys.executable, str(script), "--dist", str(DIST_DIR)],
        cwd=str(ROOT),
    )
    return r.returncode


def _intentar_firma_authenticode() -> int:
    """Si hay AIC_SIGN_PFX, firma el .exe. Con AIC_SIGN_REQUIRED=1 falla sin cert."""
    pfx = (os.environ.get("AIC_SIGN_PFX") or "").strip()
    required = (os.environ.get("AIC_SIGN_REQUIRED") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if not pfx:
        msg = (
            "Authenticode: omitido (definí AIC_SIGN_PFX; ver docs/FIRMA_AUTHENTICODE.md)."
        )
        if required:
            print(f"ERROR: {msg} AIC_SIGN_REQUIRED=1.", file=sys.stderr)
            return 1
        print(msg, flush=True)
        return 0
    ps1 = ROOT / "tools" / "firmar_portable.ps1"
    if not ps1.is_file():
        print(f"Aviso: no está {ps1}", file=sys.stderr)
        return 1 if required else 0
    exe = DIST_DIR / f"{APP_EXE_BASENAME}.exe"
    env = os.environ.copy()
    env.setdefault("AIC_SIGN_EXE", str(exe))
    print("Authenticode: ejecutando firmar_portable.ps1…", flush=True)
    r = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ps1),
        ],
        cwd=str(ROOT),
        env=env,
    )
    if r.returncode != 0:
        print(
            "ERROR: falló la firma Authenticode."
            if required
            else "AVISO: falló la firma Authenticode (el build del portable igual quedó).",
            file=sys.stderr,
        )
        return 1 if required else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
