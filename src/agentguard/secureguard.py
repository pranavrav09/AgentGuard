from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from agentguard.models import Job

ToolHandler = Callable[[Mapping[str, Any]], Awaitable[dict[str, Any]]]


class SecureGuard:
    """Constrained execution boundary for approved jobs.

    Production tool adapters can be registered explicitly. Unknown tools never fall
    through to shell execution or dynamic imports.
    """

    def __init__(self, handlers: Mapping[str, ToolHandler] | None = None) -> None:
        self._handlers = dict(handlers or default_handlers())

    async def execute(self, job: Job) -> dict[str, Any]:
        handler = self._handlers.get(job.tool_name)
        if handler is None:
            raise ValueError(f"SecureGuard has no registered handler for {job.tool_name!r}")
        return await handler(job.arguments)


def default_handlers() -> dict[str, ToolHandler]:
    async def search_query(arguments: Mapping[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query", "")).strip()
        if not query:
            raise ValueError("search.query requires a non-empty query")
        return {
            "ok": True,
            "mode": "demo",
            "message": "Approved search accepted by SecureGuard",
            "query": query,
        }

    async def calendar_read(arguments: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "mode": "demo",
            "message": "Approved calendar read accepted by SecureGuard",
            "range": arguments.get("range", "today"),
        }

    async def filesystem_read(arguments: Mapping[str, Any]) -> dict[str, Any]:
        # The demo adapter proves routing without granting filesystem access.
        return {
            "ok": True,
            "mode": "demo",
            "message": "Approved file read accepted; attach a sandboxed adapter in production",
            "path": arguments.get("path"),
        }

    async def approved_mutation(arguments: Mapping[str, Any]) -> dict[str, Any]:
        # Human-approved writes are recorded but deliberately not performed by the demo.
        return {
            "ok": True,
            "mode": "demo",
            "message": "Human-approved mutation delivered to SecureGuard",
            "argument_keys": sorted(arguments),
        }

    return {
        "search.query": search_query,
        "calendar.read": calendar_read,
        "filesystem.read": filesystem_read,
        "filesystem.write": approved_mutation,
        "email.send": approved_mutation,
        "shell.execute": approved_mutation,
    }
