#!/usr/bin/env python3
"""Ventana de testing para DFE — grabación manual de clics.

Guarda en tiempo real en build/dfe_grabacion/<timestamp>/clicks.json

Uso típico (representado distinto al CUIT de login):
  python tools/grabar_dfe.py --cuit-login 20123456789 --cuit-representado 30987654321
  explorar_dfe.bat

Con --auto-dfe abre la ventanilla con el flujo automático actual (solo login = representado).
Con --solo-login (default) deja el navegador en el portal tras el login para que grabes
el camino manual hasta las comunicaciones.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
import threading
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CLICK_INIT = """
(() => {
  if (window.__dfeClickBound) return;
  window.__dfeClickBound = true;
  document.addEventListener('click', (ev) => {
    const el = ev.target && ev.target.closest
      ? ev.target.closest('a, button, tr, input, select, label, [role="button"], [role="row"], [role="link"], [role="option"], [role="menuitem"], .accesoPrincipal')
      : ev.target;
    if (!el || typeof window._dfeLogClick !== 'function') return;
    const path = [];
    let n = el;
    for (let i = 0; i < 8 && n; i++) {
      let s = n.tagName.toLowerCase();
      if (n.id) s += '#' + n.id;
      else if (n.className && typeof n.className === 'string') {
        const c = n.className.trim().split(/\\s+/).slice(0, 3).join('.');
        if (c) s += '.' + c;
      }
      path.unshift(s);
      n = n.parentElement;
    }
    window._dfeLogClick({
      ts: new Date().toISOString(),
      url: location.href,
      tag: el.tagName,
      text: (el.innerText || el.textContent || el.value || '').trim().slice(0, 200),
      href: el.getAttribute && el.getAttribute('href'),
      title: el.getAttribute && el.getAttribute('title'),
      ariaLabel: el.getAttribute && el.getAttribute('aria-label'),
      id: el.id || null,
      path: path.join(' > ')
    });
  }, true);
})();
"""


def _parse_args():
    p = argparse.ArgumentParser(description="Grabar clics en DFE (flujo manual)")
    p.add_argument("--cuit-login", help="CUIT de ingreso a ARCA (11 dígitos)")
    p.add_argument("--cuit-representado", help="CUIT representado (si difiere del login)")
    p.add_argument("--clave", help="Clave fiscal")
    p.add_argument(
        "--auto-dfe",
        action="store_true",
        help="Tras login, abrir DFE con el flujo automático actual (CUIT login = representado)",
    )
    return p.parse_args()


def _pagina_dfe(context) -> object | None:
    for pg in context.pages:
        if pg.is_closed():
            continue
        url = (pg.url or "").lower()
        if "ve.cloud" in url or "domicilio" in url:
            return pg
    return None


def main() -> int:
    args = _parse_args()
    cuit_login = (args.cuit_login or input("CUIT login (ingreso ARCA): ").strip()).replace("-", "")
    cuit_repr = (args.cuit_representado or input(
        f"CUIT representado [{cuit_login}]: "
    ).strip() or cuit_login).replace("-", "")
    clave = args.clave or getpass.getpass("Clave fiscal: ")
    if not cuit_login or not clave:
        print("Faltan CUIT de login o clave.", file=sys.stderr)
        return 1

    from cuit_en_arca.automation_playwright import (
        LOGIN_URL,
        _llenar_cuit_y_avanzar,
        _login_clave_fiscal,
        _nuevo_contexto_stealth,
    )
    from cuit_en_arca.dfe_automation import _abrir_dfe, _cerrar_popup_dfe
    from cuit_en_arca.stealth import pausa_humana
    from playwright.sync_api import sync_playwright

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = ROOT / "build" / "dfe_grabacion" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    clicks_path = out_dir / "clicks.json"
    meta = {
        "timestamp": stamp,
        "cuit_login": cuit_login,
        "cuit_representado": cuit_repr,
        "modo": "auto_dfe" if args.auto_dfe else "solo_login",
    }
    clicks: list[dict] = []
    lock = threading.Lock()

    def persist(url: str = "") -> None:
        with lock:
            payload = {
                **meta,
                "url_final": url,
                "total_clicks": len(clicks),
                "clicks": list(clicks),
            }
            clicks_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    def on_click(_source, payload: dict) -> None:
        with lock:
            clicks.append(payload)
        persist()

    persist()
    print(f"Grabando en: {out_dir}")
    print(f"  CUIT login:        {cuit_login}")
    print(f"  CUIT representado: {cuit_repr}")
    if cuit_repr != cuit_login:
        print("  Modo recomendado: navegá manualmente el flujo de representación hasta DFE.")
    print("Cerrá con Ctrl+C en esta consola cuando termines.\n")

    browser = None
    try:
        with sync_playwright() as p:
            browser, context = _nuevo_contexto_stealth(p, headless=False)
            context.expose_binding("_dfeLogClick", on_click)
            context.add_init_script(CLICK_INIT)
            page = context.new_page()
            page.set_default_timeout(60_000)

            page.goto(LOGIN_URL, wait_until="domcontentloaded")
            pausa_humana(0.5, 1.0)
            _llenar_cuit_y_avanzar(page, cuit_login)
            _login_clave_fiscal(page, clave, cuit_login)
            page.evaluate(CLICK_INIT)

            ve = page
            if args.auto_dfe:
                print("Abriendo DFE (flujo automático actual)…")
                ve = _abrir_dfe(page)
                _cerrar_popup_dfe(ve, on_log=print)
            else:
                print(
                    "Login listo. Realizá manualmente: elegir representado → DFE → "
                    "comunicaciones (todos los clics se guardan)."
                )

            context.on("page", lambda pg: pg.evaluate(CLICK_INIT))
            for pg in context.pages:
                try:
                    pg.evaluate(CLICK_INIT)
                except Exception:
                    pass

            try:
                while browser.is_connected():
                    url = ""
                    dfe_pg = _pagina_dfe(context)
                    if dfe_pg:
                        url = dfe_pg.url or ""
                        try:
                            dfe_pg.evaluate(CLICK_INIT)
                        except Exception:
                            pass
                    elif not page.is_closed():
                        url = page.url or ""
                        try:
                            page.evaluate(CLICK_INIT)
                        except Exception:
                            pass
                    if clicks:
                        persist(url)
                    pausa_humana(1.0, 1.5)
            except KeyboardInterrupt:
                print("\nGrabación detenida.")

            snap = _pagina_dfe(context) or (page if not page.is_closed() else None)
            if snap:
                try:
                    (out_dir / "pagina.html").write_text(
                        snap.content(), encoding="utf-8", errors="replace"
                    )
                    snap.screenshot(path=str(out_dir / "pantalla.png"), full_page=True)
                except Exception:
                    pass
            persist(snap.url if snap else "")
            print(f"\nListo: {clicks_path} ({len(clicks)} clics)")
            print("Compartí esa carpeta o el archivo clicks.json para implementar el flujo.")
            return 0 if clicks else 2
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
