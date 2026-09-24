"""Fabrique de l'application FastAPI.

Le service est monté sous `/api`. Le frontend compilé, s'il est présent, est
servi à la racine : une seule origine en production, donc pas de CORS à gérer
côté déploiement. En développement, Vite tourne sur un autre port et c'est la
liste `api.cors_origins` qui l'autorise.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from abrip import __version__
from abrip.api.routers import events, explore, metrics, system
from abrip.config import Settings, get_settings
from abrip.logging_conf import get_logger, setup_logging

log = get_logger(__name__)

DESCRIPTION = """
API de lecture de la plateforme ABRIP (African BGP Routing Intelligence Platform).

Toutes les routes sont en lecture seule : la production des données se fait par
la ligne de commande `abrip`. Une route qui renvoie **503** indique que la
couche de données correspondante n'a pas encore été calculée, et précise la
commande à lancer dans `details.run`.
"""


def _error(status_code: int, code: str, message: str, details: dict[str, Any] | None = None):
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details or {}}},
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(
        settings.log_level,
        log_dir=settings.log_dir if settings.logging.to_file else None,
        max_bytes=settings.logging.max_bytes,
        backup_count=settings.logging.backup_count,
    )

    app = FastAPI(
        title="ABRIP API",
        version=__version__,
        description=DESCRIPTION,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )

    if settings.api.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.api.cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "OPTIONS"],
            allow_headers=["*"],
        )

    for router in (system.router, explore.router, metrics.router, events.router):
        app.include_router(router, prefix="/api")

    # --- erreurs normalisées ------------------------------------------------
    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException):
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail:
            return _error(
                exc.status_code,
                str(detail.get("code")),
                str(detail.get("message", "")),
                detail.get("details"),
            )
        return _error(exc.status_code, "http_error", str(detail))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        return _error(
            422,
            "invalid_parameters",
            "Paramètres de requête invalides.",
            {"errors": exc.errors()[:10]},
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        log.exception("erreur non gérée sur %s", request.url.path)
        return _error(500, "internal_error", "Erreur interne du service.")

    # 404 normalisé pour les routes API inconnues. Indispensable aussi quand le
    # frontend n'est pas compilé : sans catch-all, Starlette renvoie son format
    # par défaut ``{"detail": ...}`` au lieu du contrat ``{"error": ...}``.
    @app.get("/api/{path:path}", include_in_schema=False)
    async def api_not_found(path: str):
        return _error(404, "not_found", f"Route inconnue : /api/{path}")

    _mount_frontend(app, settings)
    return app


def _mount_frontend(app: FastAPI, settings: Settings) -> None:
    """Sert le frontend compilé si `frontend/dist` existe.

    L'application React est une SPA : toute route inconnue qui n'est pas sous
    `/api` doit renvoyer `index.html`, sinon un rechargement de page sur
    `/events/xxx` renverrait 404.
    """
    static_dir = Path(settings.api.static_dir)
    if not static_dir.is_absolute():
        static_dir = settings.project_root / static_dir
    index = static_dir / "index.html"
    if not index.exists():
        log.info("frontend non compilé (%s absent) — API seule", index)
        return

    assets = static_dir / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    root = static_dir.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path.startswith("api"):
            return _error(404, "not_found", f"Route inconnue : /{full_path}")
        # C1 — la route SPA ne sert jamais de fichier hors de frontend/dist : on
        # résout le chemin (le `..` décodé par Starlette est normalisé ici) puis
        # on vérifie le confinement avant de mettre un fichier en réponse.
        candidate = (root / full_path).resolve()
        if full_path and root in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)

    log.info("frontend servi depuis %s", static_dir)


app = create_app()
