"""Boucle de qualification humaine (L5).

Les verdicts sont stockés dans le catalogue, jamais écrits depuis l'API : la
lecture seule du service web reste intacte. La liste d'exemptions versionnée
`configs/allowlist.yaml` permet de taire les cas connus comme légitimes.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import yaml
from pydantic import BaseModel

from abrip.config import get_settings

VERDICTS = ("legitimate", "misconfiguration", "malicious", "unknown")


class AllowlistEntry(BaseModel):
    asn: int | None = None
    prefix: str | None = None
    detector: str | None = None
    reason: str = ""


class Allowlist(BaseModel):
    entries: list[AllowlistEntry] = []


def load_allowlist(path: Path | None = None) -> Allowlist:
    """Charge la liste versionnée ; un fichier absent vaut liste vide."""
    target = path or get_settings().project_root / "configs" / "allowlist.yaml"
    if not target.exists():
        return Allowlist()
    payload = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    return Allowlist.model_validate(payload)


def _matches(
    entry: AllowlistEntry, *, prefix: str | None, asns: list[int], detectors: list[str]
) -> bool:
    if entry.detector and entry.detector not in detectors:
        return False
    if entry.prefix and entry.prefix != prefix:
        return False
    if entry.asn and entry.asn not in asns:
        return False
    # Une entrée qui ne porte que détecteur n'exempte rien à elle seule.
    return entry.asn is not None or entry.prefix is not None


def is_allowed(
    allowlist: Allowlist, *, prefix: str | None, asns: list[int], detectors: list[str]
) -> bool:
    return any(
        _matches(entry, prefix=prefix, asns=asns, detectors=detectors)
        for entry in allowlist.entries
    )


def precision_by_detector(events: list[dict], feedback: list[dict]) -> list[dict]:
    """Part d'événements qualifiés *non* légitimes, par détecteur.

    `precision = 1 - légitimes / qualifiés`. Les verdicts `unknown` sont exclus
    du dénominateur : ils ne disent rien sur la justesse du détecteur.
    """
    verdicts = {row["event_id"]: row["verdict"] for row in feedback}
    totals: dict[str, dict[str, int]] = defaultdict(
        lambda: {"qualified": 0, "legitimate": 0, "confirmed": 0}
    )
    for event in events:
        verdict = verdicts.get(event["event_id"])
        if not verdict or verdict == "unknown":
            continue
        stats = totals[event["detector"]]
        stats["qualified"] += 1
        if verdict == "legitimate":
            stats["legitimate"] += 1
        else:
            stats["confirmed"] += 1

    result = []
    for detector, stats in sorted(totals.items()):
        qualified = stats["qualified"]
        result.append(
            {
                "detector": detector,
                **stats,
                "false_positive_rate": round(stats["legitimate"] / qualified, 4),
                "precision": round(stats["confirmed"] / qualified, 4),
            }
        )
    return result
