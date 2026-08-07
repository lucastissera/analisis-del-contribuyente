"""Grupos de usuarios registrados (configuración acotada por grupo).

Al agregar un parámetro solo para un grupo (ej. Estudio DyC):

1. Leer con ``parametro_grupo(GRUPO_ESTUDIO_DYC, "clave", default_global)``.
2. Aplicar solo si ``aplica_a_grupo(username, GRUPO_ESTUDIO_DYC)`` (nunca admin ni otros usuarios).
3. Persistir con ``establecer_parametro_grupo`` desde panel admin o migración.

Los miembros del catálogo se sincronizan en ``meta["grupo"]`` al iniciar la app.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

GRUPO_ESTUDIO_DYC = "estudio_dyc"
NOMBRE_GRUPO_ESTUDIO_DYC = "Estudio DyC"

# DFE: asuntos que Estudio DyC no debe descargar (coincidencia exacta, sin distinguir mayúsculas).
ASUNTOS_DFE_EXCLUIDOS_ESTUDIO_DYC: tuple[str, ...] = (
    "SIM - Servicios Extraordinarios",
    "SICNEA",
    "Libro de sueldos digital - Aviso de emisión",
    "Sistema Informático Malvina",
)

_MIEMBROS_ESTUDIO_DYC: tuple[str, ...] = (
    "sofiaa",
    "matiasl",
    "carlosc",
    "milenaa",
    "santiagop",
    "soniam",
    "rominao",
    "alejandrab",
    "rodrigob",
    "victoriab",
    "soniam2",
)


@dataclass(frozen=True)
class GrupoUsuarios:
    id: str
    nombre: str
    miembros: tuple[str, ...]


GRUPOS: dict[str, GrupoUsuarios] = {
    GRUPO_ESTUDIO_DYC: GrupoUsuarios(
        id=GRUPO_ESTUDIO_DYC,
        nombre=NOMBRE_GRUPO_ESTUDIO_DYC,
        miembros=_MIEMBROS_ESTUDIO_DYC,
    ),
}


def normalizar_grupo_id(val: str | None) -> str | None:
    gid = (val or "").strip().lower()
    if not gid:
        return None
    return gid if gid in GRUPOS else None


def listar_grupos() -> list[GrupoUsuarios]:
    return list(GRUPOS.values())


def nombre_grupo(grupo_id: str | None) -> str:
    gid = normalizar_grupo_id(grupo_id)
    if not gid:
        return ""
    return GRUPOS[gid].nombre


def miembros_catalogo(grupo_id: str) -> tuple[str, ...]:
    gid = normalizar_grupo_id(grupo_id)
    if not gid:
        return ()
    return GRUPOS[gid].miembros


def resolver_clave_miembro_grupo(nombre: str) -> str | None:
    from auth_registro import cargar_usuarios_overlay

    return _resolver_clave_miembro(nombre, cargar_usuarios_overlay())


def _resolver_clave_miembro(nombre: str, overlay_keys: dict[str, Any]) -> str | None:
    from auth_registro import resolver_clave_overlay

    clave = resolver_clave_overlay(nombre)
    if clave:
        return clave
    raw = (nombre or "").strip()
    if raw in overlay_keys:
        return raw
    raw_lower = raw.lower()
    for k in overlay_keys:
        if k.lower() == raw_lower:
            return k
    return None


def usuario_en_catalogo_grupo(username: str, grupo_id: str) -> bool:
    gid = normalizar_grupo_id(grupo_id)
    if not gid:
        return False
    from auth_registro import resolver_clave_usuario_overlay

    u = resolver_clave_usuario_overlay(username)
    if not u:
        return False
    miembros = miembros_catalogo(gid)
    if u in miembros:
        return True
    ul = u.lower()
    return any(m.lower() == ul for m in miembros)


def grupo_desde_meta(username: str, meta: dict[str, Any] | None) -> str | None:
    """Grupo a partir de meta ya cargada (sin releer overlay)."""
    from auth_registro import meta_es_admin

    if not isinstance(meta, dict) or meta_es_admin(meta):
        return None
    gid = normalizar_grupo_id(meta.get("grupo"))
    if gid:
        return gid
    u = (username or "").strip()
    if not u:
        return None
    ul = u.lower()
    for grupo in GRUPOS.values():
        if any(m.lower() == ul for m in grupo.miembros):
            return grupo.id
    return None


def grupo_de_usuario(username: str) -> str | None:
    """Grupo del usuario (meta o catálogo). None si no pertenece a ninguno o es admin."""
    from auth import es_administrador
    from auth_registro import cargar_usuarios_overlay, resolver_clave_usuario_overlay

    u_raw = (username or "").strip()
    if not u_raw or es_administrador(u_raw):
        return None
    u = resolver_clave_usuario_overlay(u_raw)
    if not u:
        return None
    return grupo_desde_meta(u, cargar_usuarios_overlay().get(u))


def aplica_a_grupo(username: str, grupo_id: str) -> bool:
    """True si el usuario pertenece al grupo (nunca admin ni otros grupos)."""
    gid = normalizar_grupo_id(grupo_id)
    if not gid:
        return False
    return grupo_de_usuario(username) == gid


def aplica_a_estudio_dyc(username: str) -> bool:
    return aplica_a_grupo(username, GRUPO_ESTUDIO_DYC)


def _normalizar_asunto_dfe(asunto: str) -> str:
    return " ".join((asunto or "").split()).casefold()


def asunto_dfe_excluido_estudio_dyc(asunto: str) -> bool:
    """True si el asunto está en la lista de exclusión de Estudio DyC."""
    norm = _normalizar_asunto_dfe(asunto)
    if not norm:
        return False
    for exc in ASUNTOS_DFE_EXCLUIDOS_ESTUDIO_DYC:
        if norm == _normalizar_asunto_dfe(exc):
            return True
    return False


def parametro_grupo(grupo_id: str, clave: str, default: Any = None) -> Any:
    from auth_registro import leer_parametro_grupo_overlay

    return leer_parametro_grupo_overlay(grupo_id, clave, default)


def establecer_parametro_grupo(grupo_id: str, clave: str, valor: Any) -> bool:
    from auth_registro import guardar_parametro_grupo_overlay

    return guardar_parametro_grupo_overlay(grupo_id, clave, valor)
