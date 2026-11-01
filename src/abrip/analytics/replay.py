"""Rejeu de la propagation d'un préfixe sur une tranche de temps.

Le graphe de propagation (ADR 0004) est un instantané agrégé sur une
fenêtre. Ici on le déroule dans le temps : la fenêtre est découpée en
tranches, et chaque tranche porte l'**état** du graphe à sa fin — pas
seulement les événements qu'elle contient.

L'état d'un pair (collecteur, adresse) est son dernier chemin annoncé, tant
qu'il ne l'a pas retiré ; le graphe d'une tranche est l'union des chemins
courants de tous les pairs. Un retrait n'a pas de chemin (donc pas
d'origine) : c'est pourquoi l'état est tenu pour *toutes* les origines et le
filtre par origine n'est appliqué qu'à la construction de chaque tranche —
filtrer avant, ce serait rater qu'un pair est passé d'une origine à une
autre, et garder à tort son ancien chemin.

Module pur (pas d'accès aux données) pour rester testable sans DuckDB.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

Path = tuple[int, ...]
Peer = tuple[str, str]


@dataclass(frozen=True)
class ReplayEvent:
    ts: datetime
    kind: str  # "A" (annonce) ou "W" (retrait)
    peer: Peer
    path: Path  # collecteur -> origine ; vide pour un retrait


@dataclass(frozen=True)
class Frame:
    ts: datetime
    paths: frozenset[Path]  # origine -> collecteur, sens de propagation
    announcements: int  # événements du préfixe dans la tranche, toutes origines
    withdrawals: int


def orient_path(
    raw: Iterable[int], origin: int | None = None, targets: set[int] | None = None
) -> Path | None:
    """Chemin brut (collecteur -> origine) vers le sens de propagation.

    ``None`` si le chemin est vide ou n'a pas l'origine demandée. Avec
    ``targets``, le chemin est tronqué à la première cible rencontrée depuis
    l'origine : au-delà, il n'apporte rien de nouveau (ADR 0004).
    """
    path = tuple(raw)
    if not path or (origin is not None and path[-1] != origin):
        return None
    ordered = tuple(reversed(path))
    if targets:
        cut = next((i for i, asn in enumerate(ordered) if asn in targets), None)
        if cut is not None:
            ordered = ordered[: cut + 1]
    return ordered


def effective_step(span: timedelta, step: timedelta, max_frames: int) -> timedelta:
    """Pas réellement utilisé : ``step``, élargi si la fenêtre donnerait plus
    de ``max_frames`` tranches (à la minute supérieure)."""
    if span <= timedelta(0) or math.ceil(span / step) <= max_frames:
        return step
    return timedelta(minutes=math.ceil(span.total_seconds() / 60 / max_frames))


def replay(
    events: Iterable[ReplayEvent],
    start: datetime,
    end: datetime,
    step: timedelta,
    origin: int | None = None,
    targets: set[int] | None = None,
) -> list[Frame]:
    """Une tranche initiale (état à ``start``) puis une par ``step``.

    Les événements antérieurs ou égaux à ``start`` servent uniquement à
    amorcer l'état : sans eux, un pair qui n'a rien annoncé depuis le début
    de la fenêtre serait absent de la première tranche. Chaque tranche
    couvre ``(précédente, fin]`` ; la dernière est tronquée à ``end``.
    """
    ordered = sorted(events, key=lambda e: e.ts)
    state: dict[Peer, Path] = {}
    i = 0

    def apply(event: ReplayEvent) -> None:
        if event.kind == "W":
            state.pop(event.peer, None)
        elif event.path:
            state[event.peer] = event.path

    def snapshot() -> frozenset[Path]:
        return frozenset(
            p for raw in state.values() if (p := orient_path(raw, origin, targets)) is not None
        )

    while i < len(ordered) and ordered[i].ts <= start:
        apply(ordered[i])
        i += 1
    frames = [Frame(start, snapshot(), 0, 0)]

    if end <= start:
        return frames
    for k in range(1, math.ceil((end - start) / step) + 1):
        bucket_end = min(start + k * step, end)
        announcements = withdrawals = 0
        while i < len(ordered) and ordered[i].ts <= bucket_end:
            apply(ordered[i])
            if ordered[i].kind == "W":
                withdrawals += 1
            else:
                announcements += 1
            i += 1
        frames.append(Frame(bucket_end, snapshot(), announcements, withdrawals))
    return frames
