from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Protocol
from urllib.parse import urlparse

import yaml
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route


DEFAULT_GUARD_URL = "http://127.0.0.1:8010/mcp"
DEFAULT_TRUEFORGE_URL = "http://localhost:8790"
DEFAULT_RESEARCH_URL = "http://127.0.0.1:8020/mcp"


class GuardReader(Protocol):
    async def read(self) -> tuple[dict[str, Any], dict[str, Any]]: ...


class McpGuardReader:
    def __init__(self, url: str, *, timeout: float = 4.0) -> None:
        self.url = url
        self.timeout = timeout

    async def read(self) -> tuple[dict[str, Any], dict[str, Any]]:
        async with streamablehttp_client(
            self.url,
            timeout=self.timeout,
            sse_read_timeout=self.timeout,
        ) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                mandate_result, session_result = await asyncio.gather(
                    session.call_tool("get_mandate", {}),
                    session.call_tool("get_session_state", {}),
                )
        return _tool_payload(mandate_result), _tool_payload(session_result)


def _tool_payload(result: Any) -> dict[str, Any]:
    if getattr(result, "isError", False):
        raise RuntimeError("guard returned an MCP tool error")
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        payload = structured.get("result", structured)
        if isinstance(payload, dict):
            return payload
    for content in getattr(result, "content", []):
        text = getattr(content, "text", None)
        if not isinstance(text, str):
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise RuntimeError("guard returned no JSON object")


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RuntimeError(f"cannot read mandate: {type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("mandate must be a YAML object")
    return payload


def _read_journal(path: Path, *, limit: int = 100) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RuntimeError(f"cannot read journal: {type(exc).__name__}") from exc
    for line_number, line in enumerate(lines[-limit:], start=max(1, len(lines) - limit + 1)):
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"invalid journal entry at line {line_number}") from exc
        if isinstance(item, dict):
            entries.append(item)
    return entries


async def _service_status(name: str, url: str) -> dict[str, Any]:
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if host is None:
        return {"name": name, "url": url, "ok": False}
    try:
        _reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=0.8)
        writer.close()
        await writer.wait_closed()
    except (OSError, TimeoutError):
        return {"name": name, "url": url, "ok": False}
    return {"name": name, "url": url, "ok": True}


async def build_snapshot(
    *,
    guard: GuardReader,
    mandate_path: Path,
    journal_path: Path,
    service_urls: dict[str, str],
) -> dict[str, Any]:
    errors: list[str] = []
    local_mandate: dict[str, Any] = {}
    local_journal: list[dict[str, Any]] = []
    try:
        local_mandate = _read_yaml(mandate_path)
    except RuntimeError as exc:
        errors.append(str(exc))
    try:
        local_journal = _read_journal(journal_path)
    except RuntimeError as exc:
        errors.append(str(exc))

    statuses_task = asyncio.gather(
        *(_service_status(name, url) for name, url in service_urls.items())
    )
    source = "live"
    try:
        mandate_state, session_state = await guard.read()
    except Exception as exc:  # The UI must remain useful while a local service restarts.
        source = "degraded"
        errors.append(f"guard unavailable: {type(exc).__name__}")
        mandate_state = {
            "mandate": local_mandate,
            "as_of": None,
            "market_is_open": False,
            "usage": {},
            "headroom": {},
            "wake_triggers": [],
            "active_predecisions": [],
        }
        session_state = {
            "as_of": None,
            "account": {},
            "market": {"is_open": False},
            "positions": {},
            "orders_today": 0,
            "pending_orders": [],
            "journal": local_journal,
        }

    services = await statuses_task
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "paper_only": True,
        "agent_url": service_urls["trueforge"],
        "mandate": mandate_state,
        "session": session_state,
        "services": services,
        "errors": errors,
    }


def _default_paths() -> tuple[Path, Path, Path]:
    mandate_root = Path(__file__).resolve().parents[3]
    dist = Path(os.environ.get("MANDATE_DASHBOARD_DIST", mandate_root / "app" / "dist"))
    mandate_path = Path(os.environ.get("MANDATE_PATH", mandate_root / "mandates" / "example.yaml"))
    journal_path = Path(os.environ.get("MANDATE_JOURNAL_PATH", mandate_root / "logs" / "session.jsonl"))
    return dist, mandate_path, journal_path


def create_dashboard(
    *,
    guard: GuardReader | None = None,
    dist_path: Path | None = None,
    mandate_path: Path | None = None,
    journal_path: Path | None = None,
    service_urls: dict[str, str] | None = None,
) -> Starlette:
    default_dist, default_mandate, default_journal = _default_paths()
    urls = service_urls or {
        "trueforge": os.environ.get("TRUEFORGE_BASE_URL", DEFAULT_TRUEFORGE_URL),
        "guard": os.environ.get("MANDATE_GUARD_URL", DEFAULT_GUARD_URL),
        "research": os.environ.get("MANDATE_RESEARCH_URL", DEFAULT_RESEARCH_URL),
    }
    reader = guard or McpGuardReader(urls["guard"])
    web_root = dist_path or default_dist
    active_mandate = mandate_path or default_mandate
    active_journal = journal_path or default_journal

    async def snapshot(_request: Request) -> Response:
        payload = await build_snapshot(
            guard=reader,
            mandate_path=active_mandate,
            journal_path=active_journal,
            service_urls=urls,
        )
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})

    async def index(request: Request) -> Response:
        requested = request.path_params.get("path", "")
        candidate = (web_root / requested).resolve()
        root = web_root.resolve()
        if requested and candidate.is_relative_to(root) and candidate.is_file():
            return FileResponse(candidate)
        index_file = root / "index.html"
        if index_file.is_file():
            return FileResponse(index_file, headers={"Cache-Control": "no-store"})
        return JSONResponse(
            {"error": "dashboard assets are not built", "hint": "cd mandate/app && npm run build"},
            status_code=503,
        )

    routes = [
        Route("/api/snapshot", snapshot),
        Route("/{path:path}", index),
    ]
    return Starlette(routes=routes)


def main() -> None:
    import uvicorn

    host = os.environ.get("MANDATE_DASHBOARD_HOST", "127.0.0.1")
    port = int(os.environ.get("MANDATE_DASHBOARD_PORT", "8030"))
    uvicorn.run(create_dashboard(), host=host, port=port)


if __name__ == "__main__":
    main()
