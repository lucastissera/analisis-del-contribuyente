#!/usr/bin/env python3
"""Ventana de testing para Ventas y Liquidaciones — grabación manual de clics.

Guarda en tiempo real en build/vl_grabacion/<timestamp>/clicks.json

Uso típico:
  python tools/grabar_vl.py --cuit-login 20123456789 --cuit-representado 30987654321
  explorar_vl.bat

Con --auto-vl abre el servicio con el flujo automático actual.
Con --solo-login (default) deja el navegador en el portal tras el login para grabar
el camino manual hasta liquidaciones recibidas.
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
  if (window.__vlClickBound) return;
  window.__vlClickBound = true;
  document.addEventListener('click', (ev) => {
    const el = ev.target && ev.target.closest
      ? ev.target.closest('a, button, tr, input, select, label, [role="button"], [role="row"], [role="link"], [role="option"], [role="menuitem"], .accesoPrincipal')
      : ev.target;
    if (!el || typeof window._vlLogClick !== 'function') return;
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
    window._vlLogClick({
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
    p = argparse.ArgumentParser(description="Grabar clics en Ventas y Liquidaciones")
    p.add_argument("--cuit-login", help="CUIT de ingreso a ARCA (11 dígitos)")
    p.add_argument("--cuit-representado", help="CUIT representado (si difiere del login)")
    p.add_argument("--clave", help="Clave fiscal")
    p.add_argument(
        "--auto-vl",
        action="store_true",
        help="Tras login, abrir Liquidaciones primarias de granos con el flujo automático",
    )
    return p.parse_args()


def _pagina_lpg(context) -> object | None:
    for pg in context.pages:
        if pg.is_closed():
            continue
        url = (pg.url or "").lower()
        if "liquidacion" in url or "grano" in url or "lpg" in url:
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
    from cuit_en_arca.stealth import pausa_humana
    from cuit_en_arca.vl_automation import _abrir_lpg, _seleccionar_contribuyente_lpg
    from playwright.sync_api import sync_playwright

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = ROOT / "build" / "vl_grabacion" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    clicks_path = out_dir / "clicks.json"
    meta = {
        "timestamp": stamp,
        "cuit_login": cuit_login,
        "cuit_representado": cuit_repr,
        "modo": "auto_vl" if args.auto_vl else "solo_login",
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
    print("Cerrá con Ctrl+C en esta consola cuando termines.\n")

    browser = None
    try:
        with sync_playwright() as p:
            browser, context = _nuevo_contexto_stealth(p, headless=False)
            context.expose_binding("_vlLogClick", on_click)
            context.add_init_script(CLICK_INIT)
            page = context.new_page()
            page.set_default_timeout(60_000)

            page.goto(LOGIN_URL, wait_until="domcontentloaded")
            pausa_humana(0.5, 1.0)
            _llenar_cuit_y_avanzar(page, cuit_login)
            _login_clave_fiscal(page, clave, cuit_login)
            page.evaluate(CLICK_INIT)

            vl = page
            if args.auto_vl:
                print("Abriendo Liquidaciones primarias de granos (flujo automático)…")
                vl = _abrir_lpg(page)
                try:
                    (out_dir / "index_contribuyentes.html").write_text(
                        vl.content(), encoding="utf-8", errors="replace"
                    )
                    print(f"  HTML guardado: {out_dir / 'index_contribuyentes.html'}")
                except Exception:
                    pass
                _seleccionar_contribuyente_lpg(vl, cuit_repr, on_log=print)
            else:
                print(
                    "Login listo. Realizá manualmente: LPG → contribuyente → "
                    "Consulta liquidaciones recibidas (todos los clics se guardan)."
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
                    lpg_pg = _pagina_lpg(context)
                    if lpg_pg:
                        url = lpg_pg.url or ""
                        try:
                            lpg_pg.evaluate(CLICK_INIT)
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

            snap = _pagina_lpg(context) or (page if not page.is_closed() else None)
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
            print("Compartí esa carpeta o el archivo clicks.json para afinar selectores.")
            return 0 if clicks else 2
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
