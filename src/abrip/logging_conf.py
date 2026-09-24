"""Journalisation structurée en JSON, avec propagation du ``run_id``."""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path

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
    log_dir: Path | None = None,
    max_bytes: int = 10_000_000,
    backup_count: int = 5,
) -> None:
    """Configure le logger racine.

    La console suit ``json_output`` (JSON pour un service, texte lisible pour
    la CLI interactive). Le fichier, lui, est **toujours** en JSON structuré
    quand ``log_dir`` est fourni : c'est ce qui le rend explicite et
    exploitable (chaque appel ``log.info(..., extra={...})`` du projet y
    conserve tout son contexte), indépendamment de ce qu'affiche la console.
    """
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    handlers[0].setFormatter(
        JsonFormatter()
        if json_output
        else logging.Formatter("%(asctime)s %(levelname)-7s %(name)s :: %(message)s")
    )

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / "abrip.log", maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        file_handler.setFormatter(JsonFormatter())
        handlers.append(file_handler)

    root = logging.getLogger()
    root.handlers.clear()
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(level.upper())
    logging.getLogger("httpx").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.LoggerAdapter | logging.Logger:
    return logging.getLogger(name)
