"""Safe local tools: ``fs.*`` inside a temporary directory and a canned ``web.search``.

Agents (and policy) see *virtual* paths that start with ``/workspace``. The
:class:`Workspace` maps them to a real temporary directory, so nothing outside it can
be touched, even if a policy mistake let a call through.
"""

from __future__ import annotations

import json
import posixpath
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures" / "search_results.json"
VIRTUAL_ROOT = "/workspace"

ToolFn = Callable[[dict[str, Any]], str]

SEED_FILES = {
    "README.md": "# Demo project\n\nA tiny service that needs a rate limiter.\n",
    "app.py": "def handle(request):\n    return 'ok'\n",
    ".env": "API_KEY=demo-not-a-real-secret\n",
}

TOOL_DOCS = {
    "fs.list": 'List a directory. args: {"path": "/workspace"}',
    "fs.read": 'Read a file. args: {"path": "/workspace/app.py"}',
    "fs.write": 'Write a file. args: {"path": "/workspace/x.py", "content": "..."}',
    "web.search": 'Search the web. args: {"query": "..."}',
    "web.fetch": 'Fetch a page. args: {"url": "https://..."}',
}


class Workspace:
    """A temporary directory seeded with a few files, addressed by virtual paths."""

    def __init__(self, root: Path | None = None) -> None:
        self._owned = root is None
        self._tmp = tempfile.TemporaryDirectory(prefix="castellan-team-") if self._owned else None
        self.root = Path(self._tmp.name) if self._tmp else Path(root or ".")
        for name, text in SEED_FILES.items():
            (self.root / name).write_text(text)

    def close(self) -> None:
        """Delete the temporary directory (if this object created it)."""
        if self._tmp is not None:
            self._tmp.cleanup()

    def resolve(self, virtual: str) -> Path:
        """Map ``/workspace/...`` to a real path.

        Raises:
            ValueError: if the path is outside ``/workspace``.
        """
        clean = posixpath.normpath(virtual)
        if clean != VIRTUAL_ROOT and not clean.startswith(VIRTUAL_ROOT + "/"):
            raise ValueError(f"path {virtual!r} is outside {VIRTUAL_ROOT}")
        return self.root / clean[len(VIRTUAL_ROOT) :].lstrip("/")


def build_tools(workspace: Workspace) -> dict[str, ToolFn]:
    """Return the tool implementations, keyed by namespaced tool name."""
    fixture = json.loads(FIXTURES.read_text())

    def fs_list(args: dict[str, Any]) -> str:
        path = workspace.resolve(str(args.get("path", VIRTUAL_ROOT)))
        return "\n".join(sorted(p.name for p in path.iterdir()))

    def fs_read(args: dict[str, Any]) -> str:
        return workspace.resolve(str(args.get("path", ""))).read_text()

    def fs_write(args: dict[str, Any]) -> str:
        path = workspace.resolve(str(args.get("path", "")))
        content = str(args.get("content", ""))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return f"wrote {len(content)} bytes to {args.get('path')}"

    def web_search(args: dict[str, Any]) -> str:
        words = {w for w in str(args.get("query", "")).lower().split() if len(w) > 2}
        hits = [
            r
            for r in fixture["results"]
            if words & set((r["title"] + " " + r["snippet"]).lower().replace(".", " ").split())
        ]
        if not hits:
            return "no results"
        return "\n".join(f"{r['title']} <{r['url']}>: {r['snippet']}" for r in hits[:3])

    def web_fetch(args: dict[str, Any]) -> str:
        page = fixture["pages"].get(str(args.get("url", "")))
        return page if page is not None else "404: page not in the canned fixture"

    return {
        "fs.list": fs_list,
        "fs.read": fs_read,
        "fs.write": fs_write,
        "web.search": web_search,
        "web.fetch": web_fetch,
    }
