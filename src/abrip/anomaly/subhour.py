"""Détecteur d'incidents courts : retrait massif puis retour rapide à la normale.

Les détecteurs historiques raisonnent par jour ; un incident de quelques
minutes peut disparaître dans un agrégat quotidien. Celui-ci travaille sur des
fenêtres glissantes de 15 minutes par défaut, avec comparaison à la fenêtre
précédente et exigence de rétablissement dans l'heure qui suit.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Any

import polars as pl

from abrip.anomaly.base import DetectionContext, Detector, confidence_from_peers
from abrip.models import Event

Row = dict[str, Any]


class SubHourWithdrawalDetector(Detector):
    name = "subhour_withdrawal"
    default_weight = 0.1

    def detect(self, context: DetectionContext) -> list[Event]:
        window = max(1, int(self.config.get("window_minutes", 15)))
        min_peers = max(2, int(self.config.get("min_peers", 6)))
        ratio = max(1.5, float(self.config.get("ratio", 3.0)))
        max_duration = max(window, int(self.config.get("max_duration_minutes", 60)))

        rows = (
            context.elements.filter(pl.col("elem_type") == "W")
            .with_columns(pl.col("ts").dt.truncate(f"{window}m").alias("bucket"))
            .group_by(["prefix", "origin_asn", "bucket"])
            .agg(
                pl.len().alias("withdrawals"),
                pl.col("peer_asn").n_unique().alias("peers"),
            )
            .sort(["prefix", "origin_asn", "bucket"])
            .collect(engine="streaming")
            .to_dicts()
        )

        groups: dict[tuple[str | None, int | None], list[Row]] = defaultdict(list)
        for row in rows:
            groups[(row["prefix"], row["origin_asn"])].append(row)

        events: list[Event] = []
        for (prefix, asn), group in groups.items():
            for index, row in enumerate(group):
                if row["peers"] < min_peers:
                    continue
                baseline = group[index - 1]["withdrawals"] if index else 0
                expected = max(min_peers, int(baseline * ratio))
                if row["withdrawals"] < expected:
                    continue
                following = group[index + 1] if index + 1 < len(group) else None
                if following is None:
                    continue  # pas de fin d'incident observée within bounds
                duration = (following["bucket"] - row["bucket"]).total_seconds() / 60
                if duration > max_duration:
                    continue
                recovered = following["withdrawals"] <= max(baseline, row["withdrawals"] // 4)
                if not recovered:
                    continue
                start = row["bucket"]
                end = min(
                    following["bucket"],
                    start + timedelta(minutes=max_duration),
                )
                score = min(1.0, 0.35 + 0.5 * row["peers"] / min_peers)
                events.append(
                    self.build_event(
                        context=context,
                        prefix=prefix,
                        asns=[int(asn)] if asn is not None else [],
                        first_seen=start,
                        last_seen=end,
                        score=score,
                        confidence=confidence_from_peers(row["peers"]),
                        evidence={
                            "window_minutes": window,
                            "withdrawals": row["withdrawals"],
                            "baseline_withdrawals": baseline,
                            "peers": row["peers"],
                            "duration_minutes": round(duration, 1),
                        },
                        explanation=(
                            f"Retraits massifs sur {prefix or 'un préfixe'} en {window} min "
                            f"({row['withdrawals']} retraits, {row['peers']} peers, "
                            f"contre {baseline} juste avant), puis retour à la normale "
                            f"en {duration:.0f} min."
                        ),
                    )
                )
        return events
