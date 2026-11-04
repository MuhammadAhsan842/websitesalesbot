"""Serve the public demo assets without exposing the project or runtime data."""

from fastapi import HTTPException
from fastapi.staticfiles import StaticFiles

PUBLIC_FILES = frozenset({
    "index.html", "services.html", "staff.html", "styles.css", "widget.css",
    "widget.js", "voice-client.js", "staff.js", "store.js", "favicon.svg",
    "js/session.js", "js/graph.js", "js/knowledge.js",
})


class PublicSite(StaticFiles):
    async def get_response(self, path, scope):
        if path not in PUBLIC_FILES and path not in {"", "."}:
            raise HTTPException(404, "Not found")
        return await super().get_response(path, scope)
