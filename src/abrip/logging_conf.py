"""Journalisation structurée en JSON, avec propagation du ``run_id``."""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from typing import Any

current_run_id: ContextVar[str | None] = ContextVar("current_run_id", default=None)

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        run_id = current_run_id.get()
        if run_id:
            payload["run_id"] = run_id
        for key, value in record.__dict__.items():
            if key not in _RESERVED:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def setup_logging(
    level: str = "INFO",
    json_output: bool = True,
    log_path: str | None = None,
    max_bytes: int = 10_000_000,
    backup_count: int = 5,
) -> None:
    formatter = (
        JsonFormatter()
        if json_output
        else logging.Formatter("%(asctime)s %(levelname)-7s %(name)s :: %(message)s")
    )
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)

    if log_path:
        from logging.handlers import RotatingFileHandler
        from pathlib import Path

        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        # Toujours en JSON dans le fichier, même si la console est en texte
        # simple : un fichier de log est fait pour être relu par un outil
        # (grep, jq) plus tard, pas seulement par un oeil humain immédiat.
        file_handler = RotatingFileHandler(
            log_path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        file_handler.setFormatter(JsonFormatter())
        root.addHandler(file_handler)

    root.setLevel(level.upper())
    logging.getLogger("httpx").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.LoggerAdapter | logging.Logger:
    return logging.getLogger(name)


def log_http_error(
    logger: logging.Logger | logging.LoggerAdapter[Any],
    message: str,
    exc: Exception,
    **extra: Any,
) -> None:
    """Journalise un échec réseau avec assez de détail pour diagnostiquer sans
    reproduire le problème : type d'exception, méthode et URL demandées, code
    de statut si une réponse a été reçue. ``str(exc)`` seul (utilisé
    auparavant) tronque souvent ces informations, notamment côté RequestError
    (ConnectError, TimeoutException) où aucun ``response`` n'existe.
    """
    # tenacity enveloppe l'échec réel dans RetryError : c'est la dernière tentative qui renseigne.
    last_attempt = getattr(exc, "last_attempt", None)
    if last_attempt is not None and last_attempt.exception() is not None:
        exc = last_attempt.exception()
    details: dict[str, Any] = {"error_type": type(exc).__name__, "error": str(exc)}
    try:
        request = getattr(exc, "request", None)
    except RuntimeError:  # httpx lève RuntimeError si l'exception n'a pas de requête associée
        request = None
    if request is not None:
        details["url"] = str(request.url)
        details["method"] = request.method
    response = getattr(exc, "response", None)
    if response is not None:
        details["status_code"] = response.status_code
    details.update(extra)
    logger.warning(message, extra=details)
