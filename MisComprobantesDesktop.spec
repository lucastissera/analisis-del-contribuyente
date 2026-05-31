# -*- mode: python ; coding: utf-8 -*-
# PyInstaller: carpeta de salida dist/MisComprobantesAnalisis/ con MisComprobantesAnalisis.exe

from PyInstaller.utils.hooks import collect_all

block_cipher = None

_pw_datas, _pw_binaries, _pw_hidden = collect_all("playwright")
_gr_datas, _gr_binaries, _gr_hidden = collect_all("greenlet")

a = Analysis(
    ["run_desktop.py"],
    pathex=[],
    binaries=_pw_binaries + _gr_binaries,
    datas=[
        ("templates", "templates"),
        ("auth_users.example.json", "."),
    ]
    + _pw_datas
    + _gr_datas,
    hiddenimports=[
        "pandas",
        "openpyxl",
        "flask",
        "jinja2",
        "werkzeug",
        "auth",
        "sumar_imp_total",
        "plantillas_imputacion",
        "i18n",
        "cuit_en_arca",
        "cuit_en_arca.validacion",
        "cuit_en_arca.errores",
        "cuit_en_arca.credenciales",
        "cuit_en_arca.descarga",
        "cuit_en_arca.planilla_lote",
        "cuit_en_arca.lote",
        "cuit_en_arca.empaquetado",
        "cuit_en_arca.stealth",
        "cuit_en_arca.automation_playwright",
        "cuit_en_arca.service",
        "cuit_en_arca.playwright_env",
        "playwright",
        "playwright.sync_api",
        "playwright._impl",
        "greenlet",
    ]
    + _pw_hidden
    + _gr_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MisComprobantesAnalisis",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="MisComprobantesAnalisis",
)
