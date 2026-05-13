from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.api.routes import build_api_router
from backend.config import ROOT, configure_logging, load_settings
from backend.services.container import build_services
from backend.web import frontend_dist_root, legacy_redirects


LOGGER = logging.getLogger("xcg_internal.app")


def create_app() -> FastAPI:
    settings = load_settings()
    services = build_services()
    app = FastAPI(title="XC Gradient Internal", version="1.0.0")
    app.state.settings = settings
    app.state.services = services
    app.state.runtime = services.runtime

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    app.include_router(build_api_router(services))

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    dist_root = frontend_dist_root()
    assets_dir = dist_root / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/")
    @app.get("/task-creator")
    @app.get("/okr-creator")
    @app.get("/meeting-creator")
    @app.get("/claude-usage")
    def serve_index():
        index_path = dist_root / "index.html"
        return FileResponse(index_path) if index_path.exists() else FileResponse(ROOT / "frontend" / "index.html")

    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str):
        request_path = "/" + full_path
        if request_path.startswith("/api/"):
            raise HTTPException(status_code=404, detail="Not found")
        if request_path in legacy_redirects():
            return RedirectResponse(url=legacy_redirects()[request_path])
        candidate = (dist_root / full_path).resolve()
        if candidate.is_file() and str(candidate).startswith(str(dist_root.resolve())):
            return FileResponse(candidate)
        index_path = dist_root / "index.html"
        return FileResponse(index_path) if index_path.exists() else FileResponse(ROOT / "frontend" / "index.html")

    return app


app = create_app()


def main() -> None:
    configure_logging()
    settings = load_settings()
    import uvicorn

    uvicorn.run("backend.app:app", host=settings.internal_host, port=settings.internal_port, reload=False)


if __name__ == "__main__":
    main()
