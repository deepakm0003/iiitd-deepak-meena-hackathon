"""One process for the whole product: the engine's API under /api and the built website (frontend/dist) at /.

Used by `python -m tripwire demo`, which points it at a copy of the committed demo snapshot, so the dashboard runs on
real collected data without our server, a GPU, API keys or Node.js.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, PlainTextResponse

from tripwire.api.app import create_app

ROOT = Path(__file__).resolve().parents[3]
DIST = ROOT / "frontend" / "dist"


def create_site(store=None, analyzer_preload: bool | None = None, dist: Path = DIST) -> FastAPI:
    site = FastAPI(title="Tripwire", docs_url=None, redoc_url=None)
    site.mount("/api", create_app(store, analyzer_preload=analyzer_preload))

    @site.get("/{path:path}", include_in_schema=False)
    def website(path: str):
        if not (dist / "index.html").exists():
            return PlainTextResponse("The website is not built: run `npm run build` in frontend/.", status_code=503)
        file = (dist / path).resolve()
        if path and file.is_file() and dist.resolve() in file.parents:
            return FileResponse(file)
        return FileResponse(dist / "index.html")  # client-side routes (/app, /product, ...)

    return site
