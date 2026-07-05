"""Normalización de razón social para comparar Excel vs pantalla ARCA.

Criterio de selección:
1. Primero coincide por **nombre** (sin tipo societario).
2. Si hay duplicados, desempata por **tipo societario** (SA, SRL, etc.) solo si
   el usuario lo indicó en la planilla.
"""

from __future__ import annotations

import re
import unicodedata

# Formas societarias frecuentes → token canónico (sin puntos).
_SUFIJOS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bsociedad\s+de\s+responsabilidad\s+limitada\b", re.I), "srl"),
    (re.compile(r"\bsociedad\s+anonima\b", re.I), "sa"),
    (re.compile(r"\bsociedad\s+an[oó]nima\b", re.I), "sa"),
    (re.compile(r"\bsociedad\s+colectiva\b", re.I), "sc"),
    (re.compile(r"\bsociedad\s+comandita\b", re.I), "sca"),
    (re.compile(r"\bsociedad\s+por\s+acciones\s+simplificada\b", re.I), "sas"),
    (re.compile(r"\bs\.?\s*r\.?\s*l\.?\b", re.I), "srl"),
    (re.compile(r"\bs\.?\s*a\.?\s*s\.?\b", re.I), "sas"),
    (re.compile(r"\bs\.?\s*c\.?\s*a\.?\b", re.I), "sca"),
    (re.compile(r"\bs\.?\s*c\.?\s*s\.?\b", re.I), "scs"),
    (re.compile(r"\bs\.?\s*h\.?\b", re.I), "sh"),
    (re.compile(r"\bs\.?\s*a\.?\b", re.I), "sa"),
    (re.compile(r"\bsa\b", re.I), "sa"),
    (re.compile(r"\bsrl\b", re.I), "srl"),
    (re.compile(r"\bsas\b", re.I), "sas"),
    (re.compile(r"\bsca\b", re.I), "sca"),
    (re.compile(r"\bscs\b", re.I), "scs"),
    (re.compile(r"\bsh\b", re.I), "sh"),
    (re.compile(r"\bltda\b", re.I), "ltda"),
    (re.compile(r"\binc\b", re.I), "inc"),
    (re.compile(r"\bcia\b", re.I), "cia"),
    (re.compile(r"\bcía\b", re.I), "cia"),
    (re.compile(r"\by\s+cia\b", re.I), "cia"),
    (re.compile(r"\be\s+hijos\b", re.I), "ehijos"),
)


def _sin_acentos(texto: str) -> str:
    nf = unicodedata.normalize("NFD", texto)
    return "".join(c for c in nf if unicodedata.category(c) != "Mn")


def _preparar_texto(nombre: str) -> str:
    s = (nombre or "").strip().lower()
    if not s:
        return ""
    s = _sin_acentos(s)
    s = s.replace("&", " y ")
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def extraer_tipo_societario(nombre: str) -> str | None:
    """Devuelve el tipo societario canónico (sa, srl, …) o None si no hay."""
    s = _preparar_texto(nombre)
    if not s:
        return None
    for patron, canon in _SUFIJOS:
        if patron.search(s):
            return canon
    return None


def nombre_base_razon_social(nombre: str) -> str:
    """Nombre comercial sin tipo societario ni puntuación."""
    s = _preparar_texto(nombre)
    if not s:
        return ""
    for patron, _canon in _SUFIJOS:
        s = patron.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def normalizar_razon_social(nombre: str) -> str:
    """Nombre base + tipo (compatibilidad)."""
    base = nombre_base_razon_social(nombre)
    tipo = extraer_tipo_societario(nombre)
    if base and tipo:
        return f"{base} {tipo}"
    return base or (tipo or "")


def coinciden_nombre_base(a: str, b: str) -> bool:
    """True si el nombre comercial (sin tipo societario) coincide."""
    na = nombre_base_razon_social(a)
    nb = nombre_base_razon_social(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if len(na) >= 5 and (na in nb or nb in na):
        return True
    wa = na.split()
    wb = nb.split()
    if not wa or not wb:
        return False
    corto, largo = (wa, wb) if len(wa) <= len(wb) else (wb, wa)
    if len(corto) >= 2 and all(palabra in largo for palabra in corto):
        return True
    return False


def coinciden_razones_social(a: str, b: str) -> bool:
    """Compatibilidad: nombre base + tipo si ambos lo tienen."""
    if not coinciden_nombre_base(a, b):
        return False
    ta = extraer_tipo_societario(a)
    tb = extraer_tipo_societario(b)
    if ta and tb:
        return ta == tb
    return True


class AmbiguedadRazonSocialError(Exception):
    """Varias empresas con el mismo nombre base."""

    def __init__(self, nombre_buscado: str, candidatos: list[str], *, falta_tipo: bool):
        self.nombre_buscado = nombre_buscado
        self.candidatos = candidatos
        self.falta_tipo = falta_tipo
        if falta_tipo:
            msg = (
                f"Varias empresas llamadas «{nombre_buscado}» (mismo nombre). "
                f"Indicá el tipo societario en la planilla (SA, SRL, SAS, etc.). "
                f"Opciones: {', '.join(candidatos[:8])}."
            )
        else:
            msg = (
                f"Varias empresas coinciden con «{nombre_buscado}»: "
                f"{', '.join(candidatos[:8])}."
            )
        super().__init__(msg)


def resolver_razon_social(nombre_buscado: str, opciones: list[str]) -> str | None:
    """
    Elige la opción que coincide con nombre_buscado.

    1. Filtra por nombre base.
    2. Si hay duplicados, filtra por tipo societario (si viene en la planilla).
    """
    nombre = (nombre_buscado or "").strip()
    if not nombre:
        return None

    visibles = [(o or "").strip() for o in opciones if (o or "").strip()]
    por_nombre = [o for o in visibles if coinciden_nombre_base(o, nombre)]
    if not por_nombre:
        return None
    if len(por_nombre) == 1:
        return por_nombre[0]

    tipo_bus = extraer_tipo_societario(nombre)
    if not tipo_bus:
        raise AmbiguedadRazonSocialError(nombre, por_nombre, falta_tipo=True)

    por_tipo = [o for o in por_nombre if extraer_tipo_societario(o) == tipo_bus]
    if len(por_tipo) == 1:
        return por_tipo[0]
    if len(por_tipo) > 1:
        raise AmbiguedadRazonSocialError(nombre, por_tipo, falta_tipo=False)
    raise AmbiguedadRazonSocialError(nombre, por_nombre, falta_tipo=False)
