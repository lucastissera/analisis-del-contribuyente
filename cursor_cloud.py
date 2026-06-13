"""Cliente del Cloud Agents API de Cursor (solo servidor; clave en entorno)."""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any, Iterator
from urllib.error import HTTPError
from urllib.request import Request, urlopen

_LOG = logging.getLogger(__name__)

API_BASE = "https://api.cursor.com"


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


def _api_key() -> str:
    return (os.environ.get("CURSOR_API_KEY") or "").strip()


def configurado() -> bool:
    return bool(_api_key())


def config_publica() -> dict[str, Any]:
    repo = (os.environ.get("CURSOR_REPO_URL") or "").strip()
    branch = (os.environ.get("CURSOR_REPO_BRANCH") or "main").strip() or "main"
    model = (os.environ.get("CURSOR_MODEL") or "").strip()
    auto_pr = (os.environ.get("CURSOR_AUTO_CREATE_PR") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    return {
        "configured": configurado(),
        "repo_url": repo or None,
        "branch": branch,
        "model": model or None,
        "auto_create_pr": auto_pr,
    }


def _auth_headers(*, accept: str | None = None) -> dict[str, str]:
    key = _api_key()
    token = base64.b64encode(f"{key}:".encode("utf-8")).decode("ascii")
    headers = {"Authorization": f"Basic {token}"}
    if accept:
        headers["Accept"] = accept
    return headers


def _parse_error_body(raw: bytes) -> str:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return raw.decode("utf-8", errors="replace")[:500]
    if isinstance(data, dict):
        msg = data.get("message") or data.get("error")
        if msg:
            return str(msg)
        return json.dumps(data, ensure_ascii=False)[:500]
    return str(data)[:500]


def _request_json(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    accept: str = "application/json",
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
        with urlopen(req, timeout=120) as resp:
            raw = resp.read()
    except HTTPError as exc:
        detail = _parse_error_body(exc.read())
        code = None
        try:
            payload = json.loads(detail) if detail.startswith("{") else {}
            if isinstance(payload, dict):
                code = payload.get("code")
                detail = str(payload.get("message") or payload.get("error") or detail)
        except json.JSONDecodeError:
            pass
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


def _payload_agente(texto: str) -> dict[str, Any]:
    cfg = config_publica()
    body: dict[str, Any] = {
        "prompt": {"text": texto},
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
    return body


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
        {"prompt": {"text": texto}, "mode": "agent"},
    )
    run = data.get("run") or {}
    return {
        "agent_id": aid,
        "run_id": run.get("id"),
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
        detail = _parse_error_body(exc.read())
        raise CursorCloudError(
            detail or f"Cursor stream HTTP {exc.code}",
            status=exc.code,
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
