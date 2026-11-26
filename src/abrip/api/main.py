"""Fabrique de l'application FastAPI.

Le service est monté sous `/api`. Le frontend compilé, s'il est présent, est
servi à la racine : une seule origine en production, donc pas de CORS à gérer
côté déploiement. En développement, Vite tourne sur un autre port et c'est la
liste `api.cors_origins` qui l'autorise.
"""

from __future__ import annotations

import hashlib
import re
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from abrip import __version__
from abrip.api.deps import api_key_matches, verify_api_key
from abrip.api.metrics import observe, render
from abrip.api.routers import asn_explorer, events, explore, metrics, propagation, system
from abrip.config import Settings, get_settings
from abrip.logging_conf import current_request_id, get_logger, setup_logging

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


# En dessous, compresser coûte plus qu'envoyer : les petites réponses JSON
# (santé, une ligne) partent telles quelles.
GZIP_MIN_SIZE = 1024

# Un identifiant de requête fourni par le client est accepté s'il reste court et
# composé de caractères sans risque ; sinon on en génère un.
REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,64}")

# Réponses volontairement jamais mises en cache : `/health` porte un horodatage
# de génération et doit refléter l'état courant (supervision).
NO_STORE_PATHS = frozenset({"/api/health"})

# La SPA n'a ni script ni style en ligne dans sa source, mais les bibliothèques
# de graphiques injectent des styles à l'exécution : `unsafe-inline` reste
# nécessaire pour style-src. `blob:` et `data:` servent à l'export SVG/PNG.
# La CSP ne s'applique qu'au HTML de la SPA : Swagger UI charge ses propres
# ressources et serait cassé par `script-src 'self'`.
SPA_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "frame-ancestors 'none'"
)


def _weak_etag(body: bytes) -> str:
    """Étiquette faible : le même JSON peut être servi compressé ou non."""
    return f'W/"{hashlib.sha256(body).hexdigest()[:32]}"'


def _etag_matches(header: str | None, etag: str) -> bool:
    if not header:
        return False
    return any(candidate.strip() in {etag, "*"} for candidate in header.split(","))


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.ensure_dirs()
    setup_logging(
        settings.log_level,
        log_path=str(settings.log_path),
        max_bytes=settings.log_max_bytes,
        backup_count=settings.log_backup_count,
    )

    app = FastAPI(
        title="ABRIP API",
        version=__version__,
        description=DESCRIPTION,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        # Une seule porte d'entrée : la clé, quand elle est configurée, protège
        # aussi /api/docs et /api/openapi.json, pas seulement les routeurs.
        dependencies=[Depends(verify_api_key)],
    )

    if settings.api.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.api.cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "OPTIONS"],
            allow_headers=["*"],
        )

    # Les routes de documentation sont créées par FastAPI en dehors des
    # routeurs : les dépendances globales ne s'y appliquent pas. On les protège
    # donc explicitement quand une clé est configurée.
    @app.middleware("http")
    async def protect_docs(request: Request, call_next):
        expected = settings.api.api_key
        if (
            expected
            and request.url.path in {"/api/docs", "/api/openapi.json", "/api/redoc"}
            and not api_key_matches(expected, request.headers.get("x-api-key"))
        ):
            return _error(401, "unauthorized", "Clé API absente ou invalide.")
        return await call_next(request)

    # En-têtes de défense en profondeur : l'API est en lecture seule et le
    # frontend est servi sur la même origine, aucun besoin de frames tierces.
    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        return response

    # ETag + Cache-Control sur les réponses JSON. Le corps est déjà entièrement
    # construit par FastAPI : le relire ici ne coûte qu'une copie mémoire. Le
    # client revalide à chaque fois (`no-cache`) et un 304 lui évite de
    # retélécharger plusieurs kilo-octets identiques.
    @app.middleware("http")
    async def cache_headers(request: Request, call_next):
        response = await call_next(request)
        if request.url.path in NO_STORE_PATHS:
            response.headers["cache-control"] = "no-store"
            return response
        if (
            request.method != "GET"
            or response.status_code != 200
            or not response.headers.get("content-type", "").startswith("application/json")
        ):
            return response
        body = b"".join([chunk async for chunk in response.body_iterator])
        etag = _weak_etag(body)
        headers = dict(response.headers)
        headers["etag"] = etag
        headers["cache-control"] = "private, no-cache"
        headers["vary"] = "Accept-Encoding"
        if _etag_matches(request.headers.get("if-none-match"), etag):
            headers.pop("content-length", None)
            return Response(status_code=304, headers=headers)
        return Response(content=body, status_code=200, headers=headers)

    # Compression ajoutée en dernier : Starlette place chaque middleware en
    # tête de pile, celui-ci devient donc le plus externe. L'ETag reste calculé
    # sur le JSON non compressé, d'où l'étiquette faible (valable quel que soit
    # l'encodage négocié).
    app.add_middleware(GZipMiddleware, minimum_size=GZIP_MIN_SIZE)

    # Observabilité ajoutée après la compression : Starlette la place donc en
    # tête de pile, elle voit le statut final (304 compris) et couvre aussi les
    # erreurs. L'identifiant est propagé aux logs via un ContextVar.
    @app.middleware("http")
    async def observe_request(request: Request, call_next):
        provided = request.headers.get("x-request-id")
        request_id = (
            provided if provided and REQUEST_ID_PATTERN.fullmatch(provided) else uuid.uuid4().hex
        )
        token = current_request_id.set(request_id)
        request.state.request_id = request_id
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            route = request.scope.get("route")
            route_path = getattr(route, "path", None)
            if route_path is None:
                path = "unmatched"
            elif request.url.path.startswith("/api") and not route_path.startswith("/api"):
                # Les routeurs sont montés avec le préfixe `/api`, mais
                # `route.path` reste le chemin relatif au routeur.
                path = f"/api{route_path}"
            else:
                path = route_path
            observe(request.method, path, status, time.perf_counter() - started)
            current_request_id.reset(token)

    for router in (
        system.router,
        # propagation avant explore : `/prefixes/{prefix:path}` avale sinon
        # `/prefixes/<p>/propagation`.
        propagation.router,
        explore.router,
        asn_explorer.router,
        metrics.router,
        events.router,
    ):
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

    # Exposition Prometheus : sous /api pour hériter de la clé API globale, hors
    # schéma OpenAPI car c'est un format d'exploitation, pas un contrat public.
    @app.get("/api/metrics", include_in_schema=False)
    def prometheus_metrics() -> Response:
        return Response(
            content=render(settings),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

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
            return _spa_file(candidate)
        return _spa_file(index)

    log.info("frontend servi depuis %s", static_dir)


def _spa_file(path: Path) -> FileResponse:
    return FileResponse(path, headers={"Content-Security-Policy": SPA_CSP})


app = create_app()
