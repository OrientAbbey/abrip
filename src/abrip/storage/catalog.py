"""Catalogue DuckDB : journal d'ingestion, exécutions, vues sur les Parquet.

Le catalogue est le seul état mutable de la plateforme. Il rend le pipeline
observable et idempotent : on n'y stocke pas de données BGP, uniquement des
métadonnées de traitement.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from abrip.logging_conf import current_run_id, get_logger

log = get_logger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ingestion_log (
    file_url    VARCHAR PRIMARY KEY,
    collector   VARCHAR NOT NULL,
    file_type   VARCHAR NOT NULL,
    file_ts     TIMESTAMP NOT NULL,
    local_path  VARCHAR,
    bytes       BIGINT,
    sha256      VARCHAR,
    status      VARCHAR NOT NULL,
    attempts    INTEGER DEFAULT 0,
    started_at  TIMESTAMP,
    finished_at TIMESTAMP,
    error       VARCHAR
);

CREATE TABLE IF NOT EXISTS runs (
    run_id      VARCHAR PRIMARY KEY,
    stage       VARCHAR NOT NULL,
    params      VARCHAR,
    started_at  TIMESTAMP NOT NULL,
    finished_at TIMESTAMP,
    status      VARCHAR NOT NULL,
    rows_in     BIGINT DEFAULT 0,
    rows_out    BIGINT DEFAULT 0,
    duration_s  DOUBLE,
    notes       VARCHAR
);

CREATE TABLE IF NOT EXISTS curated_partitions (
    partition_key VARCHAR PRIMARY KEY,
    table_name    VARCHAR NOT NULL,
    path          VARCHAR NOT NULL,
    rows          BIGINT,
    bytes         BIGINT,
    run_id        VARCHAR,
    written_at    TIMESTAMP
);
"""


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Catalog:
    """Accès au catalogue. Ouvrir en ``read_only=True`` côté API."""

    def __init__(self, path: Path, read_only: bool = False) -> None:
        self.path = path
        self.read_only = read_only
        path.parent.mkdir(parents=True, exist_ok=True)
        if not read_only:
            with duckdb.connect(str(path)) as con:
                con.execute(SCHEMA_SQL)
        elif not path.exists():
            raise FileNotFoundError(
                f"Catalogue absent : {path}. Lancer `abrip demo bootstrap` ou le pipeline."
            )

    @contextmanager
    def connect(self) -> Iterator[duckdb.DuckDBPyConnection]:
        con = duckdb.connect(str(self.path), read_only=self.read_only)
        try:
            yield con
        finally:
            con.close()

    # --- journal d'ingestion --------------------------------------------
    def is_ingested(self, file_url: str) -> bool:
        with self.connect() as con:
            row = con.execute(
                "SELECT status FROM ingestion_log WHERE file_url = ?", [file_url]
            ).fetchone()
        return bool(row and row[0] == "ok")

    def already_ingested(self, urls: list[str]) -> set[str]:
        if not urls:
            return set()
        with self.connect() as con:
            rows = con.execute(
                "SELECT file_url FROM ingestion_log WHERE status = 'ok' AND file_url IN "
                f"({','.join('?' * len(urls))})",
                urls,
            ).fetchall()
        return {r[0] for r in rows}

    def record_ingestion(
        self,
        *,
        file_url: str,
        collector: str,
        file_type: str,
        file_ts: datetime,
        status: str,
        local_path: str | None = None,
        size_bytes: int | None = None,
        sha256: str | None = None,
        error: str | None = None,
    ) -> None:
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO ingestion_log AS t
                    (file_url, collector, file_type, file_ts, local_path, bytes, sha256,
                     status, attempts, started_at, finished_at, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                ON CONFLICT (file_url) DO UPDATE SET
                    status = excluded.status,
                    local_path = excluded.local_path,
                    bytes = excluded.bytes,
                    sha256 = excluded.sha256,
                    attempts = t.attempts + 1,
                    finished_at = excluded.finished_at,
                    error = excluded.error
                """,
                [
                    file_url,
                    collector,
                    file_type,
                    file_ts,
                    local_path,
                    size_bytes,
                    sha256,
                    status,
                    _utcnow(),
                    _utcnow(),
                    error,
                ],
            )

    def pending_files(self, collector: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM ingestion_log WHERE status <> 'ok'"
        params: list[Any] = []
        if collector:
            sql += " AND collector = ?"
            params.append(collector)
        with self.connect() as con:
            cur = con.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    # --- exécutions ------------------------------------------------------
    def start_run(self, stage: str, params: dict[str, Any] | None = None) -> str:
        run_id = str(uuid.uuid4())
        with self.connect() as con:
            con.execute(
                "INSERT INTO runs (run_id, stage, params, started_at, status) VALUES (?,?,?,?,?)",
                [run_id, stage, json.dumps(params or {}, default=str), _utcnow(), "running"],
            )
        return run_id

    def finish_run(
        self,
        run_id: str,
        status: str = "ok",
        rows_in: int = 0,
        rows_out: int = 0,
        duration_s: float = 0.0,
        notes: str | None = None,
    ) -> None:
        with self.connect() as con:
            con.execute(
                """UPDATE runs SET finished_at = ?, status = ?, rows_in = ?, rows_out = ?,
                          duration_s = ?, notes = ? WHERE run_id = ?""",
                [_utcnow(), status, rows_in, rows_out, duration_s, notes, run_id],
            )

    def register_partition(
        self, table_name: str, path: str, rows: int, size_bytes: int, run_id: str
    ) -> None:
        with self.connect() as con:
            con.execute(
                """INSERT INTO curated_partitions
                       (partition_key, table_name, path, rows, bytes, run_id, written_at)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT (partition_key) DO UPDATE SET
                       rows = excluded.rows, bytes = excluded.bytes,
                       run_id = excluded.run_id, written_at = excluded.written_at""",
                [f"{table_name}:{path}", table_name, path, rows, size_bytes, run_id, _utcnow()],
            )

    def coverage(self) -> dict[str, Any]:
        """Fraîcheur des données, exposée par ``/api/health``."""
        with self.connect() as con:
            ingest = con.execute(
                """SELECT collector, file_type, min(file_ts), max(file_ts), count(*)
                   FROM ingestion_log WHERE status='ok' GROUP BY 1,2 ORDER BY 1,2"""
            ).fetchall()
            last_run = con.execute(
                "SELECT stage, status, finished_at FROM runs ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
        return {
            "ingestion": [
                {
                    "collector": r[0],
                    "file_type": r[1],
                    "from": r[2],
                    "to": r[3],
                    "files": r[4],
                }
                for r in ingest
            ],
            "last_run": (
                {"stage": last_run[0], "status": last_run[1], "finished_at": last_run[2]}
                if last_run
                else None
            ),
        }


class RunContext:
    """Gestionnaire de contexte qui ouvre, journalise et clôture une exécution."""

    def __init__(self, catalog: Catalog, stage: str, **params: Any) -> None:
        self.catalog = catalog
        self.stage = stage
        self.params = params
        self.run_id = ""
        self.rows_in = 0
        self.rows_out = 0
        self._t0 = 0.0
        self._token: Any = None

    def __enter__(self) -> RunContext:
        self.run_id = self.catalog.start_run(self.stage, self.params)
        self._token = current_run_id.set(self.run_id)
        self._t0 = time.perf_counter()
        log.info("étape démarrée", extra={"stage": self.stage, "params": self.params})
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        duration = time.perf_counter() - self._t0
        status = "ok" if exc is None else "failed"
        self.catalog.finish_run(
            self.run_id,
            status,
            self.rows_in,
            self.rows_out,
            duration,
            notes=None if exc is None else f"{exc_type.__name__}: {exc}",
        )
        log.info(
            "étape terminée",
            extra={
                "stage": self.stage,
                "status": status,
                "duration_s": round(duration, 2),
                "rows_out": self.rows_out,
            },
        )
        if self._token is not None:
            current_run_id.reset(self._token)
