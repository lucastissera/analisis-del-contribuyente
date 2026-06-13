"""Cliente del Cloud Agents API de Cursor (solo servidor; clave en entorno)."""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from typing import Any, Iterator
from urllib.error import HTTPError
from urllib.request import Request, urlopen

_LOG = logging.getLogger(__name__)

API_BASE = "https://api.cursor.com"
_GITHUB_REPO_RE = re.compile(
    r"^https://github\.com/[\w.\-]+/[\w.\-]+/?$",
    re.IGNORECASE,
)
_ENV_API_KEY = ("CURSOR_API_KEY", "CURSOR_CLOUD_API_KEY")
_ENV_REPO_URL = ("CURSOR_REPO_URL", "CURSOR_GITHUB_REPO", "GITHUB_REPO_URL")
_VARS_CURSOR_IDE = frozenset(
    {
        "CURSOR_AGENT",
        "CURSOR_CONVERSATION_ID",
        "CURSOR_EXTENSION_HOST_ROLE",
        "CURSOR_LAYOUT",
        "CURSOR_RIPGREP_PATH",
        "CURSOR_WORKSPACE_LABEL",
        "CURSOR_TRACE_ID",
    }
)
_TERMINAL_RUN = frozenset({"FINISHED", "ERROR", "CANCELLED", "EXPIRED"})
_ACTIVE_RUN = frozenset({"CREATING", "RUNNING"})

_INSTRUCCIONES_GIT = """\
Sos el agente de mantenimiento del proyecto «Análisis Integral del Contribuyente».

Pedido del administrador:
{pedido}

Instrucciones obligatorias de entrega:
- Implementá el cambio en el repositorio clonado.
- Verificá que el proyecto sigue siendo coherente (imports, sintaxis básica).
- Hacé commit con un mensaje claro en español.
- Hacé push al remoto (origin). No preguntes si debés pushear: commit + push forman parte del trabajo.
- Si abrís PR automático, dejá el código listo para revisión.
- Si git falla, explicá el error concreto en la respuesta final.
"""


class CursorCloudError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status: int = 502,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


def _limpiar_valor_env(val: str | None) -> str:
    v = (val or "").strip().lstrip("\ufeff")
    if len(v) >= 2 and v[0] == v[-1] and v[0] in '"\'':
        v = v[1:-1].strip()
    return v


def _leer_env_primero(*nombres: str) -> str:
    for nombre in nombres:
        v = _limpiar_valor_env(os.environ.get(nombre))
        if v:
            return v
    return ""


def _vars_cursor_en_entorno() -> list[str]:
    return sorted(
        k
        for k in os.environ
        if k.upper().startswith("CURSOR_") and k.upper() not in _VARS_CURSOR_IDE
    )


def normalizar_repo_url(raw: str | None) -> str | None:
    u = _limpiar_valor_env(raw)
    if not u:
        return None
    if u.startswith("git@github.com:"):
        u = "https://github.com/" + u.split(":", 1)[1]
    elif u.startswith("github.com/"):
        u = "https://" + u
    elif u.startswith("http://github.com/"):
        u = "https://" + u[len("http://") :]
    u = u.rstrip("/")
    if u.lower().endswith(".git"):
        u = u[:-4]
    if _GITHUB_REPO_RE.match(u):
        return u
    return None


def _api_key() -> str:
    return _leer_env_primero(*_ENV_API_KEY)


def _env_bool(name: str, default: bool = False) -> bool:
    v = (os.environ.get(name) or "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on")


def configurado() -> bool:
    return bool(_api_key())


def requiere_repo() -> bool:
    return _env_bool("CURSOR_REQUIERE_REPO", True)


def config_publica() -> dict[str, Any]:
    repo_raw = _leer_env_primero(*_ENV_REPO_URL)
    repo = normalizar_repo_url(repo_raw)
    branch = _leer_env_primero("CURSOR_REPO_BRANCH") or "main"
    model = _leer_env_primero("CURSOR_MODEL")
    auto_pr = _env_bool("CURSOR_AUTO_CREATE_PR", True)
    push_direct = _env_bool("CURSOR_PUSH_DIRECT", False)
    key = _api_key()
    return {
        "configured": bool(key),
        "repo_url": repo,
        "repo_url_raw": repo_raw or None,
        "branch": branch,
        "model": model or None,
        "auto_create_pr": auto_pr,
        "push_direct": push_direct,
        "requiere_repo": requiere_repo(),
        "diagnostico": {
            "api_key_len": len(key),
            "api_key_fuente": next(
                (n for n in _ENV_API_KEY if _limpiar_valor_env(os.environ.get(n))),
                None,
            ),
            "repo_raw_len": len(repo_raw),
            "repo_normalizada": bool(repo),
            "vars_cursor": _vars_cursor_en_entorno(),
        },
    }


def _auth_headers(*, accept: str | None = None) -> dict[str, str]:
    key = _api_key()
    token = base64.b64encode(f"{key}:".encode("utf-8")).decode("ascii")
    headers = {"Authorization": f"Basic {token}"}
    if accept:
        headers["Accept"] = accept
    return headers


def _extraer_error_api(data: Any) -> tuple[str | None, str]:
    if not isinstance(data, dict):
        return None, str(data)[:500]
    code = data.get("code")
    msg: Any = data.get("message") or data.get("error")
    if isinstance(msg, dict):
        code = code or msg.get("code")
        msg = msg.get("message") or msg.get("error") or msg
    err = data.get("error")
    if isinstance(err, dict):
        code = code or err.get("code")
        msg = msg or err.get("message") or err.get("error")
    if msg is None:
        return code if isinstance(code, str) else None, json.dumps(
            data, ensure_ascii=False
        )[:500]
    return (str(code) if code else None), str(msg)


def _parse_error_body(raw: bytes) -> tuple[str | None, str]:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        text = raw.decode("utf-8", errors="replace")[:500]
        return None, text
    code, msg = _extraer_error_api(data)
    return code, msg


def _request_json(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    accept: str = "application/json",
    timeout: int = 120,
) -> Any:
    if not configurado():
        raise CursorCloudError(
            "Cursor Cloud no está configurado (falta CURSOR_API_KEY).",
            status=503,
            code="not_configured",
        )
    headers = _auth_headers(accept=accept)
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    req = Request(f"{API_BASE}{path}", data=data, method=method, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except HTTPError as exc:
        code, detail = _parse_error_body(exc.read())
        raise CursorCloudError(
            detail or f"Cursor API HTTP {exc.code}",
            status=exc.code,
            code=code,
        ) from exc
    except OSError as exc:
        raise CursorCloudError(
            f"No se pudo contactar a Cursor Cloud: {exc}",
            status=502,
            code="network",
        ) from exc
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CursorCloudError(
            "Respuesta inválida de Cursor Cloud.",
            status=502,
            code="bad_json",
        ) from exc


def envolver_prompt_usuario(texto: str) -> str:
    pedido = (texto or "").strip()
    extra = (os.environ.get("CURSOR_PROMPT_PREFIX") or "").strip()
    base = _INSTRUCCIONES_GIT.format(pedido=pedido)
    if extra:
        return extra + "\n\n" + base
    return base


def _payload_agente(texto: str) -> dict[str, Any]:
    cfg = config_publica()
    body: dict[str, Any] = {
        "prompt": {"text": envolver_prompt_usuario(texto)},
        "mode": "agent",
    }
    if cfg["model"]:
        body["model"] = {"id": cfg["model"]}
    if cfg["repo_url"]:
        body["repos"] = [
            {
                "url": cfg["repo_url"],
                "startingRef": cfg["branch"],
            }
        ]
        if cfg["auto_create_pr"]:
            body["autoCreatePR"] = True
        if cfg["push_direct"]:
            body["workOnCurrentBranch"] = True
    return body


def _payload_run(texto: str) -> dict[str, Any]:
    return {
        "prompt": {"text": envolver_prompt_usuario(texto)},
        "mode": "agent",
    }


def run_publico(data: dict[str, Any]) -> dict[str, Any]:
    git = data.get("git") if isinstance(data.get("git"), dict) else {}
    branches_raw = git.get("branches") or []
    branches: list[dict[str, str | None]] = []
    for b in branches_raw:
        if not isinstance(b, dict):
            continue
        repo_url = b.get("repoUrl") or b.get("repo_url")
        branch = b.get("branch")
        pr_url = b.get("prUrl") or b.get("pr_url")
        gh_url = None
        if repo_url and branch:
            gh_url = f"https://{repo_url}/tree/{branch}"
        branches.append(
            {
                "repo": str(repo_url) if repo_url else None,
                "branch": str(branch) if branch else None,
                "pr_url": str(pr_url) if pr_url else None,
                "branch_url": gh_url,
            }
        )
    status = str(data.get("status") or "")
    return {
        "id": data.get("id"),
        "agent_id": data.get("agentId") or data.get("agent_id"),
        "status": status,
        "terminal": status in _TERMINAL_RUN,
        "activo": status in _ACTIVE_RUN,
        "result": data.get("result"),
        "duration_ms": data.get("durationMs"),
        "branches": branches,
    }


def verificar_enlace(*, probar_api: bool = False) -> dict[str, Any]:
    cfg = config_publica()
    checks: list[dict[str, Any]] = []
    diag = cfg.get("diagnostico") or {}

    def add(cid: str, ok: bool, mensaje: str, *, critico: bool = True) -> None:
        checks.append(
            {"id": cid, "ok": ok, "mensaje": mensaje, "critico": critico}
        )

    key_len = int(diag.get("api_key_len") or 0)
    if key_len:
        fuente = diag.get("api_key_fuente") or "CURSOR_API_KEY"
        add(
            "api_key",
            True,
            f"{fuente} detectada ({key_len} caracteres)",
        )
    else:
        msg = "Falta CURSOR_API_KEY en el proceso del servidor"
        vars_c = diag.get("vars_cursor") or []
        if vars_c:
            msg += f" (hay otras vars: {', '.join(vars_c)})"
        add("api_key", False, msg)

    repo_raw = cfg.get("repo_url_raw")
    repo_ok = bool(cfg.get("repo_url"))
    if cfg["requiere_repo"]:
        if repo_ok:
            add(
                "repo_url",
                True,
                f"Repo GitHub: {cfg['repo_url']} (rama {cfg['branch']})",
            )
        elif repo_raw:
            add(
                "repo_url",
                False,
                "CURSOR_REPO_URL tiene valor pero formato inválido. "
                f"Recibido: «{repo_raw[:100]}». "
                "Use https://github.com/usuario/repo (sin comillas; .git opcional)",
            )
        else:
            add(
                "repo_url",
                False,
                "Falta CURSOR_REPO_URL (necesaria para editar y pushear código)",
            )
    elif repo_ok:
        add(
            "repo_url",
            True,
            f"Repo GitHub: {cfg['repo_url']}",
            critico=False,
        )
    else:
        add(
            "repo_url",
            True,
            "Sin repo: solo chat, sin cambios en GitHub",
            critico=False,
        )

    if repo_raw and not repo_ok:
        add(
            "repo_github",
            False,
            "Normalizá la URL del repo (https + usuario/repo)",
        )
    elif repo_ok:
        add("repo_github", True, "URL de repo válida para Cursor Cloud")

    add(
        "auto_pr",
        cfg["auto_create_pr"] or cfg["push_direct"],
        "PR automático activo"
        if cfg["auto_create_pr"]
        else (
            "Push directo a rama base"
            if cfg["push_direct"]
            else "Sin PR automático (solo rama cursor/…)"
        ),
        critico=False,
    )

    if probar_api and cfg["configured"]:
        try:
            _request_json("GET", "/v1/models", timeout=30)
            add("api_conexion", True, "Conexión con Cursor Cloud OK")
        except CursorCloudError as exc:
            add("api_conexion", False, f"Cursor API: {exc}")

    listo = all(c["ok"] for c in checks if c.get("critico", True))
    return {**cfg, "checks": checks, "ready": listo}


def crear_agente(texto: str) -> dict[str, Any]:
    data = _request_json("POST", "/v1/agents", _payload_agente(texto))
    agent = data.get("agent") or {}
    run = data.get("run") or {}
    return {
        "agent_id": agent.get("id"),
        "run_id": run.get("id"),
        "agent_url": agent.get("url"),
        "agent_name": agent.get("name"),
    }


def crear_run(agent_id: str, texto: str) -> dict[str, Any]:
    aid = (agent_id or "").strip()
    if not aid:
        raise CursorCloudError("Falta agent_id.", status=400, code="missing_agent")
    data = _request_json(
        "POST",
        f"/v1/agents/{aid}/runs",
        _payload_run(texto),
    )
    run = data.get("run") or {}
    agent = obtener_agente(aid)
    return {
        "agent_id": aid,
        "run_id": run.get("id"),
        "agent_url": agent.get("url"),
    }


def obtener_agente(agent_id: str) -> dict[str, Any]:
    aid = (agent_id or "").strip()
    if not aid:
        raise CursorCloudError("Falta agent_id.", status=400)
    data = _request_json("GET", f"/v1/agents/{aid}")
    return {
        "id": data.get("id"),
        "name": data.get("name"),
        "status": data.get("status"),
        "url": data.get("url"),
        "latest_run_id": data.get("latestRunId"),
    }


def obtener_run(agent_id: str, run_id: str) -> dict[str, Any]:
    aid = (agent_id or "").strip()
    rid = (run_id or "").strip()
    if not aid or not rid:
        raise CursorCloudError("Faltan agent_id o run_id.", status=400)
    return _request_json("GET", f"/v1/agents/{aid}/runs/{rid}")


def cancelar_run(agent_id: str, run_id: str) -> dict[str, Any]:
    aid = (agent_id or "").strip()
    rid = (run_id or "").strip()
    if not aid or not rid:
        raise CursorCloudError("Faltan agent_id o run_id.", status=400)
    return _request_json(
        "POST",
        f"/v1/agents/{aid}/runs/{rid}/cancel",
        {},
    )


def listar_agentes(limit: int = 10) -> list[dict[str, Any]]:
    lim = max(1, min(int(limit), 50))
    data = _request_json("GET", f"/v1/agents?limit={lim}&includeArchived=false")
    items = data.get("items") or []
    return [
        {
            "id": it.get("id"),
            "name": it.get("name"),
            "status": it.get("status"),
            "url": it.get("url"),
            "latest_run_id": it.get("latestRunId"),
            "updated_at": it.get("updatedAt"),
        }
        for it in items
        if isinstance(it, dict)
    ]


def stream_run(
    agent_id: str,
    run_id: str,
    last_event_id: str | None = None,
) -> Iterator[bytes]:
    aid = (agent_id or "").strip()
    rid = (run_id or "").strip()
    if not aid or not rid:
        raise CursorCloudError("Faltan agent_id o run_id.", status=400)
    if not configurado():
        raise CursorCloudError(
            "Cursor Cloud no está configurado.",
            status=503,
            code="not_configured",
        )
    headers = _auth_headers(accept="text/event-stream")
    if last_event_id:
        headers["Last-Event-ID"] = last_event_id
    req = Request(
        f"{API_BASE}/v1/agents/{aid}/runs/{rid}/stream",
        method="GET",
        headers=headers,
    )
    try:
        resp = urlopen(req, timeout=300)
    except HTTPError as exc:
        code, detail = _parse_error_body(exc.read())
        raise CursorCloudError(
            detail or f"Cursor stream HTTP {exc.code}",
            status=exc.code,
            code=code,
        ) from exc
    except OSError as exc:
        raise CursorCloudError(
            f"No se pudo abrir stream de Cursor: {exc}",
            status=502,
            code="network",
        ) from exc

    try:
        while True:
            chunk = resp.read(4096)
            if not chunk:
                break
            yield chunk
    finally:
        resp.close()
