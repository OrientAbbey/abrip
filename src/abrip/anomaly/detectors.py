"""Les sept détecteurs de la V1.

Principe commun, répété volontairement : aucun détecteur n'affirme qu'un
détournement a eu lieu. Chacun produit un **candidat** assorti des éléments qui
l'ont déclenché, pour qu'un ingénieur puisse trancher lui-même.
"""

from __future__ import annotations

import ipaddress
from datetime import timedelta
from typing import Any, cast

import polars as pl

from abrip.anomaly.base import (
    DetectionContext,
    Detector,
    confidence_from_peers,
    robust_zscore,
)
from abrip.etl.normalize import is_bogon_prefix, is_private_asn
from abrip.models import Confidence, Event, IrrStatus, RpkiStatus
from abrip.reference.anycast import is_anycast_candidate
from abrip.reference.relationships import valley_free_violation


class MoasDetector(Detector):
    """Un même préfixe annoncé avec plusieurs AS d'origine sur la même fenêtre.

    Tous les MOAS ne sont pas suspects : l'anycast, le multihoming entre entités
    d'un même groupe et les relations client-fournisseur directes en produisent
    légitimement. Ces cas sont écartés avant de lever un candidat.
    """

    name = "moas"
    default_weight = 0.30

    def detect(self, context: DetectionContext) -> list[Event]:
        min_peers = int(self.config.get("min_peers_per_origin", 2))
        frame = (
            context.elements.filter(
                (pl.col("elem_type") == "A") & pl.col("origin_asn").is_not_null()
            )
            .group_by(["prefix", "origin_asn"])
            .agg(
                peers=pl.col("peer_asn").n_unique(),
                collectors=pl.col("collector").unique(),
                first_seen=pl.col("ts").min(),
                last_seen=pl.col("ts").max(),
                announcements=pl.len(),
                # Chemins distincts, pour le filtre anycast (L6, filtre 3) :
                # limité à quelques valeurs, la divergence se juge sur un
                # échantillon, pas sur l'exhaustivité.
                paths=pl.col("as_path_dedup").unique().head(5),
            )
            .collect(engine="streaming")
        )
        if frame.is_empty():
            return []

        multi = (
            frame.group_by("prefix")
            .agg(origin_count=pl.col("origin_asn").n_unique())
            .filter(pl.col("origin_count") > 1)
        )
        if multi.is_empty():
            return []

        events: list[Event] = []
        candidates = frame.join(multi, on="prefix", how="inner")

        for prefix, group in candidates.group_by("prefix"):
            prefix_str = prefix[0] if isinstance(prefix, tuple) else prefix
            rows = group.sort("announcements", descending=True).to_dicts()
            incumbent = rows[0]
            challengers = [
                r
                for r in rows[1:]
                if r["peers"] >= min_peers
                and not self._legitimate(context, prefix_str, incumbent, r)
            ]
            if not challengers:
                continue

            for challenger in challengers:
                origins = [int(incumbent["origin_asn"]), int(challenger["origin_asn"])]
                rpki_status = self._rpki(context, prefix_str, int(challenger["origin_asn"]))
                score = self._score(challenger, incumbent, rpki_status)
                collectors = sorted(set(challenger["collectors"]))
                events.append(
                    self.build_event(
                        context=context,
                        prefix=prefix_str,
                        asns=origins,
                        first_seen=challenger["first_seen"],
                        last_seen=challenger["last_seen"],
                        score=score,
                        confidence=confidence_from_peers(int(challenger["peers"]), len(collectors)),
                        collectors=collectors,
                        evidence={
                            "incumbent_origin": int(incumbent["origin_asn"]),
                            "incumbent_peers": int(incumbent["peers"]),
                            "incumbent_announcements": int(incumbent["announcements"]),
                            "competing_origin": int(challenger["origin_asn"]),
                            "competing_peers": int(challenger["peers"]),
                            "competing_announcements": int(challenger["announcements"]),
                            "rpki_status": rpki_status,
                            "collectors": collectors,
                        },
                        explanation=(
                            f"Le préfixe {prefix_str} est annoncé par AS{challenger['origin_asn']} "
                            f"alors que l'origine habituelle sur la fenêtre est "
                            f"AS{incumbent['origin_asn']}. Statut RPKI de l'origine concurrente : "
                            f"{rpki_status}. Candidat à investiguer, pas un détournement confirmé."
                        ),
                    )
                )
        return events

    def _legitimate(
        self, context: DetectionContext, prefix: str, incumbent: dict, challenger: dict
    ) -> bool:
        a, b = int(incumbent["origin_asn"]), int(challenger["origin_asn"])
        if self.config.get("ignore_same_organisation", True) and context.same_organisation(a, b):
            return True
        if self.config.get("ignore_direct_relationship", True) and context.relationships:
            from abrip.models import Relationship

            if context.relationships.get(a, b) is not Relationship.UNKNOWN:
                return True
        # L6 — une origine « concurrente » déjà présente de façon stable avant
        # la fenêtre de détection n'est pas nouvelle : c'est un multihoming
        # ancien que l'absence de donnée AS2Org ne permettait pas de distinguer
        # d'un détournement récent.
        if self.config.get("ignore_stable_origins", True) and context.is_stable_origin(prefix, b):
            return True
        # L4a — même logique que le détecteur de sous-préfixe : une origine
        # explicitement autorisée (ROA multi-origine, ou à défaut objet route
        # IRR cohérent) n'est pas un détournement, qu'un ROA existe ou non.
        if self.config.get("ignore_authorised_origins", True):
            if context.rpki is not None and context.rpki.validate(prefix, b) is RpkiStatus.VALID:
                return True
            if (
                (context.rpki is None or context.rpki.validate(prefix, b) is RpkiStatus.NOT_FOUND)
                and context.irr is not None
                and context.irr.validate(prefix, b) is IrrStatus.CONSISTENT
            ):
                return True
        # L6 — anycast : deux origines aux chemins très divergents, dont le
        # préfixe figure dans un catalogue public d'anycast connu, décrivent
        # une architecture multi-site normale, pas un détournement.
        return bool(
            self.config.get("ignore_known_anycast", True)
            and context.anycast_prefixes
            and is_anycast_candidate(
                prefix, incumbent.get("paths"), challenger.get("paths"), context.anycast_prefixes
            )
        )

    @staticmethod
    def _rpki(context: DetectionContext, prefix: str, asn: int) -> str:
        if context.rpki is None:
            return RpkiStatus.NOT_FOUND.value
        return context.rpki.validate(prefix, asn).value

    @staticmethod
    def _score(challenger: dict, incumbent: dict, rpki_status: str) -> float:
        base = 0.45
        if rpki_status == RpkiStatus.INVALID.value:
            base += 0.35
        elif rpki_status == RpkiStatus.VALID.value:
            base -= 0.25
        base += min(0.15, int(challenger["peers"]) * 0.03)
        if int(challenger["announcements"]) < int(incumbent["announcements"]) * 0.1:
            base += 0.05  # origine marginale et soudaine
        return base


class SubprefixDetector(Detector):
    """Annonce d'un préfixe plus spécifique par un AS non autorisé par le ROA couvrant.

    C'est la forme de détournement la plus efficace, puisque la route la plus
    spécifique l'emporte toujours sur la route couvrante.
    """

    name = "subprefix"
    default_weight = 0.25

    def detect(self, context: DetectionContext) -> list[Event]:
        if context.rpki is None:
            return []
        min_extra = int(self.config.get("min_extra_specificity", 1))
        use_irr = bool(self.config.get("use_irr_fallback", True))

        frame = (
            context.elements.filter(
                (pl.col("elem_type") == "A") & pl.col("origin_asn").is_not_null()
            )
            .group_by(["prefix", "origin_asn"])
            .agg(
                peers=pl.col("peer_asn").n_unique(),
                collectors=pl.col("collector").unique(),
                first_seen=pl.col("ts").min(),
                last_seen=pl.col("ts").max(),
                announcements=pl.len(),
            )
            .collect(engine="streaming")
        )

        events: list[Event] = []
        for row in frame.iter_rows(named=True):
            prefix, origin = row["prefix"], int(row["origin_asn"])
            covering = context.rpki.covering_roas(prefix)

            if not covering:
                # L4a — RPKI muet (`not-found`, majoritaire en zone AFRINIC) :
                # on consulte le référentiel IRR de repli avant de renoncer.
                # C'est un second avis déclaratif, pas une preuve, d'où un
                # score sensiblement plus prudent que la branche RPKI ci-dessous.
                if use_irr and context.irr is not None:
                    event = self._irr_fallback(context, prefix, origin, row)
                    if event:
                        events.append(event)
                continue

            try:
                length = ipaddress.ip_network(prefix, strict=False).prefixlen
            except ValueError:
                continue

            # Une annonce validee par un ROA n'est jamais un detournement de sous-prefixe.
            if context.rpki.validate(prefix, origin) is RpkiStatus.VALID:
                continue
            violating = [
                (roa_prefix, roa_asn, max_len)
                for roa_prefix, roa_asn, max_len in covering
                if length > max_len
                and length - ipaddress.ip_network(roa_prefix).prefixlen >= min_extra
            ]
            if not violating:
                continue

            roa_prefix, roa_asn, max_len = violating[0]
            collectors = sorted(set(row["collectors"]))
            events.append(
                self.build_event(
                    context=context,
                    prefix=prefix,
                    asns=[origin, roa_asn],
                    first_seen=row["first_seen"],
                    last_seen=row["last_seen"],
                    score=0.6 + min(0.25, int(row["peers"]) * 0.05),
                    confidence=confidence_from_peers(int(row["peers"]), len(collectors)),
                    collectors=collectors,
                    evidence={
                        "covering_prefix": roa_prefix,
                        "roa_asn": roa_asn,
                        "roa_max_len": max_len,
                        "observed_prefix_len": length,
                        "announcing_asn": origin,
                        "peers": int(row["peers"]),
                        "source": "rpki",
                    },
                    explanation=(
                        f"{prefix} est plus spécifique que le ROA couvrant {roa_prefix} "
                        f"(maxLength {max_len}, AS autorisé {roa_asn}) et est annoncé par "
                        f"AS{origin}. Un préfixe plus spécifique attire le trafic : à vérifier "
                        f"en priorité."
                    ),
                )
            )
        return events

    def _irr_fallback(
        self, context: DetectionContext, prefix: str, origin: int, row: dict[str, Any]
    ) -> Event | None:
        from abrip.models import IrrStatus

        covering = context.irr.covering_routes(prefix)
        if not covering:
            return None
        try:
            length = ipaddress.ip_network(prefix, strict=False).prefixlen
        except ValueError:
            return None
        min_extra = int(self.config.get("min_extra_specificity", 1))
        violating = [
            (route, asn, source)
            for route, asn, source in covering
            if length > ipaddress.ip_network(route, strict=False).prefixlen
            and origin != asn
            and length - ipaddress.ip_network(route, strict=False).prefixlen >= min_extra
        ]
        if not violating:
            return None
        route, declared_asn, source = violating[0]
        collectors = sorted(set(row["collectors"]))
        return self.build_event(
            context=context,
            prefix=prefix,
            asns=[origin, declared_asn],
            first_seen=row["first_seen"],
            last_seen=row["last_seen"],
            # Score plus prudent qu'en présence d'un ROA : l'IRR est déclaratif,
            # non signé, parfois périmé — un accord de confiance moindre.
            score=0.4 + min(0.15, int(row["peers"]) * 0.03),
            confidence=confidence_from_peers(int(row["peers"]), len(collectors)),
            collectors=collectors,
            evidence={
                "covering_route": route,
                "irr_asn": declared_asn,
                "irr_source": source,
                "observed_prefix_len": length,
                "announcing_asn": origin,
                "peers": int(row["peers"]),
                "source": "irr",
                "irr_status": IrrStatus.INCONSISTENT.value,
            },
            explanation=(
                f"{prefix} est plus spécifique qu'un objet route IRR ({route}, AS{declared_asn}, "
                f"source {source}) et est annoncé par AS{origin}. Aucun ROA ne couvre ce "
                f"préfixe : ce signal s'appuie sur l'IRR, déclaratif et non signé — "
                f"une confirmation directe auprès de l'opérateur reste nécessaire."
            ),
        )


class RpkiInvalidDetector(Detector):
    """Annonces dont la validation d'origine est ``invalid``, vues par plusieurs peers."""

    name = "rpki_invalid"
    default_weight = 0.20

    def detect(self, context: DetectionContext) -> list[Event]:
        if context.rpki is None:
            return []
        min_peers = int(self.config.get("min_peers", 3))

        frame = (
            context.elements.filter(
                (pl.col("elem_type") == "A") & pl.col("origin_asn").is_not_null()
            )
            .group_by(["prefix", "origin_asn"])
            .agg(
                peers=pl.col("peer_asn").n_unique(),
                collectors=pl.col("collector").unique(),
                first_seen=pl.col("ts").min(),
                last_seen=pl.col("ts").max(),
            )
            .filter(pl.col("peers") >= min_peers)
            .collect(engine="streaming")
        )

        events: list[Event] = []
        for row in frame.iter_rows(named=True):
            origin = int(row["origin_asn"])
            if context.rpki.validate(row["prefix"], origin) is not RpkiStatus.INVALID:
                continue
            authorised = sorted(context.rpki.authorised_asns(row["prefix"]))
            collectors = sorted(set(row["collectors"]))
            events.append(
                self.build_event(
                    context=context,
                    prefix=row["prefix"],
                    asns=[origin, *authorised[:3]],
                    first_seen=row["first_seen"],
                    last_seen=row["last_seen"],
                    score=0.45 + min(0.2, int(row["peers"]) * 0.02),
                    confidence=confidence_from_peers(int(row["peers"]), len(collectors)),
                    collectors=collectors,
                    evidence={
                        "authorised_asns": authorised,
                        "observed_origin": origin,
                        "peers": int(row["peers"]),
                    },
                    explanation=(
                        f"{row['prefix']} est annoncé par AS{origin} alors que le ROA autorise "
                        f"{', '.join('AS' + str(a) for a in authorised) or 'aucun de ces AS'}. "
                        f"Peut aussi résulter d'un ROA obsolète : à confronter au détenteur."
                    ),
                )
            )
        return events


class ValleyFreeDetector(Detector):
    """Chemins violant le modèle valley-free — signature d'une fuite de routes."""

    name = "valley_free"
    default_weight = 0.15

    def detect(self, context: DetectionContext) -> list[Event]:
        if context.relationships is None or len(context.relationships) == 0:
            return []
        min_peers = int(self.config.get("min_peers", 2))

        frame = (
            context.elements.filter((pl.col("elem_type") == "A") & (pl.col("as_path_len") >= 3))
            .with_columns(
                pl.col("as_path_dedup").cast(pl.List(pl.Utf8)).list.join(" ").alias("path_str")
            )
            .group_by(["prefix", "path_str"])
            .agg(
                peers=pl.col("peer_asn").n_unique(),
                collectors=pl.col("collector").unique(),
                first_seen=pl.col("ts").min(),
                last_seen=pl.col("ts").max(),
                announcements=pl.len(),
            )
            .collect(engine="streaming")
        )

        # Chaque peer voit un chemin different (son propre ASN en tete) : regrouper
        # par chemin ferait compter 1 peer par violation. On agrege donc par
        # (prefixe, AS fuiteur presume), ce qui reflete l'incident reel.
        grouped: dict[tuple[str, int], dict[str, Any]] = {}
        for row in frame.iter_rows(named=True):
            path = [int(a) for a in row["path_str"].split() if a.isdigit()]
            position = valley_free_violation(path, context.relationships)
            if position is None:
                continue
            key = (row["prefix"], path[position])
            bucket = grouped.setdefault(
                key,
                {
                    "paths": [],
                    "peers": 0,
                    "collectors": set(),
                    "first_seen": row["first_seen"],
                    "last_seen": row["last_seen"],
                    "violation_index": position,
                },
            )
            bucket["paths"].append(path)
            bucket["peers"] += int(row["peers"])
            bucket["collectors"].update(row["collectors"])
            bucket["first_seen"] = min(bucket["first_seen"], row["first_seen"])
            bucket["last_seen"] = max(bucket["last_seen"], row["last_seen"])

        events: list[Event] = []
        min_sources_critical = int(self.config.get("min_sources_for_critical", 2))
        for (prefix_str, leaker), bucket in grouped.items():
            if bucket["peers"] < min_peers:
                continue
            row = {
                "prefix": prefix_str,
                "peers": bucket["peers"],
                "collectors": bucket["collectors"],
                "first_seen": bucket["first_seen"],
                "last_seen": bucket["last_seen"],
            }
            path = bucket["paths"][0]
            position = bucket["violation_index"]
            collectors = sorted(bucket["collectors"])

            # L3 — une relation CAIDA seule (inférée) ne doit pas à elle seule
            # justifier une alerte critique. Confirmée par PeeringDB ou l'IRR,
            # elle le peut. Voir ADR 0003 et docs/limites-et-remediations.md.
            link_sources: frozenset[str] = frozenset({"caida"})
            if position + 1 < len(path):
                link_sources = context.relationships.sources(path[position], path[position + 1])
            score = 0.4 + min(0.2, int(row["peers"]) * 0.04)
            capped = len(link_sources) < min_sources_critical
            if capped:
                score = min(score, 0.55)
            events.append(
                self.build_event(
                    context=context,
                    prefix=row["prefix"],
                    asns=[leaker],
                    first_seen=row["first_seen"],
                    last_seen=row["last_seen"],
                    score=score,
                    confidence=confidence_from_peers(int(row["peers"]), len(collectors)),
                    collectors=collectors,
                    evidence={
                        "as_path": path,
                        "violation_index": position,
                        "suspected_leaker": leaker,
                        "peers": int(row["peers"]),
                        "relationship_source": "caida-inferred",
                        "corroborating_sources": sorted(link_sources),
                        "severity_capped": capped,
                    },
                    explanation=(
                        f"Le chemin {' '.join(str(a) for a in path)} pour {row['prefix']} viole "
                        f"le modèle valley-free au niveau d'AS{leaker}, qui semble réannoncer une "
                        f"route apprise d'un transitaire ou d'un pair. "
                        + (
                            f"Relation corroborée par {', '.join(sorted(link_sources))} : "
                            f"lecture jugée fiable."
                            if not capped
                            else "Relation connue de CAIDA seul (inférée, non déclarée) : "
                            "cette lecture peut être erronée, sévérité plafonnée en conséquence."
                        )
                    ),
                )
            )
        return events


class ChurnSpikeDetector(Detector):
    """Pic de churn au-delà d'un seuil de score z robuste (médiane + MAD)."""

    name = "churn_spike"
    default_weight = 0.05

    def detect(self, context: DetectionContext) -> list[Event]:
        threshold = float(self.config.get("mad_threshold", 6.0))
        minimum = int(self.config.get("min_absolute_updates", 50))

        frame = (
            context.elements.filter(pl.col("elem_type") != "R")
            .sort("ts")
            .group_by_dynamic("ts", every="1h", group_by=["prefix"])
            .agg(
                updates=pl.len(),
                peers=pl.col("peer_asn").n_unique(),
                collectors=pl.col("collector").unique(),
                withdrawals=(pl.col("elem_type") == "W").sum(),
                origin_asn=pl.col("origin_asn").drop_nulls().mode().first(),
            )
            .collect(engine="streaming")
        )
        if frame.is_empty():
            return []

        events: list[Event] = []
        for prefix, group in frame.group_by("prefix"):
            prefix_str = prefix[0] if isinstance(prefix, tuple) else prefix
            if group.height < 6:
                continue
            series = group.get_column("updates").cast(pl.Float64)
            zscores = robust_zscore(series)
            median = float(cast(Any, series.median()) or 0.0)

            for row, z in zip(group.iter_rows(named=True), zscores.to_list(), strict=False):
                if z is None or z < threshold or row["updates"] < minimum:
                    continue
                collectors = sorted(set(row["collectors"]))
                origin = int(row["origin_asn"]) if row["origin_asn"] is not None else None
                events.append(
                    self.build_event(
                        context=context,
                        prefix=prefix_str,
                        asns=[origin] if origin else [],
                        first_seen=row["ts"],
                        last_seen=row["ts"] + timedelta(hours=1),
                        score=min(0.75, 0.25 + z / 40),
                        confidence=confidence_from_peers(int(row["peers"]), len(collectors)),
                        collectors=collectors,
                        evidence={
                            "updates_observed": int(row["updates"]),
                            "withdrawals": int(row["withdrawals"]),
                            "baseline_median": median,
                            "robust_zscore": round(float(z), 2),
                            "threshold": threshold,
                            "window": "1h",
                        },
                        explanation=(
                            f"{prefix_str} a généré {row['updates']} messages sur une heure, "
                            f"contre une médiane de {median:.0f} sur la fenêtre analysée "
                            f"(score z robuste {z:.1f}). Instabilité à corréler avec un "
                            f"événement réseau."
                        ),
                    )
                )
        return events


class VisibilityDropDetector(Detector):
    """Chute de la proportion de peers voyant un préfixe, corroborée par plusieurs collecteurs."""

    name = "visibility_drop"
    default_weight = 0.05

    def detect(self, context: DetectionContext) -> list[Event]:
        if context.rib is None:
            return []
        relative_drop = float(self.config.get("relative_drop", 0.40))
        min_collectors = int(self.config.get("min_collectors", 2))
        min_baseline = float(self.config.get("min_baseline_ratio", 0.30))

        # L7 — un collecteur qui cesse de rapporter (panne de collecte, écart
        # d'ingestion) ne doit pas être confondu avec une vraie perte de
        # visibilité du préfixe : on l'exclut du dénominateur plutôt que de
        # laisser son absence faire chuter artificiellement le ratio.
        rib = self._active_rib(context)

        totals = rib.group_by(["snapshot_ts", "collector"]).agg(
            peers_total=pl.col("peer_asn").n_unique()
        )
        # Un meme ASN peut alimenter plusieurs collecteurs : l'unite de comptage
        # est le couple (collecteur, peer), sinon le ratio est structurellement faux.
        seen = (
            rib.with_columns(
                (pl.col("collector").cast(pl.Utf8) + "/" + pl.col("peer_asn").cast(pl.Utf8)).alias(
                    "vantage"
                )
            )
            .group_by(["snapshot_ts", "prefix"])
            .agg(
                peers_seeing=pl.col("vantage").n_unique(),
                collectors=pl.col("collector").unique(),
                collectors_seeing=pl.col("collector").n_unique(),
                origin_asn=pl.col("origin_asn").mode().first(),
            )
        )
        per_snapshot_total = (
            totals.group_by("snapshot_ts")
            .agg(
                peers_total=pl.col("peers_total").sum(),
                collectors_active=pl.col("collector").n_unique(),
            )
            .collect(engine="streaming")
        )

        if per_snapshot_total.is_empty():
            return []
        # Nombre de collecteurs attendus : le maximum observé sur la fenêtre.
        # Un instantané qui en réunit moins a un dénominateur structurellement
        # réduit — il ne doit ni fonder la référence, ni être jugé en baisse.
        expected_collectors = int(cast(Any, per_snapshot_total["collectors_active"].max()) or 0)
        gap_snapshots = set(
            per_snapshot_total.filter(pl.col("collectors_active") < expected_collectors)
            .get_column("snapshot_ts")
            .to_list()
        )

        frame = (
            seen.join(per_snapshot_total.lazy(), on="snapshot_ts", how="left")
            .with_columns((pl.col("peers_seeing") / pl.col("peers_total")).alias("ratio"))
            .sort("snapshot_ts")
            .collect(engine="streaming")
        )
        if frame.is_empty():
            return []

        events: list[Event] = []
        for prefix, group in frame.group_by("prefix"):
            prefix_str = prefix[0] if isinstance(prefix, tuple) else prefix
            rows = group.sort("snapshot_ts").to_dicts()
            # Les instantanés incomplets ne participent ni à la référence ni à
            # la détection d'une baisse : ils ne racontent rien sur le préfixe,
            # seulement sur l'état de la collecte à cet instant.
            usable = [r for r in rows if r["snapshot_ts"] not in gap_snapshots]
            if len(usable) < 3:
                continue
            ratios = [r["ratio"] for r in usable if r["ratio"] is not None]
            baseline = float(cast(Any, pl.Series(ratios).median()) or 0.0)
            if baseline < min_baseline:
                continue

            for row in usable:
                ratio = row["ratio"] or 0.0
                if ratio >= baseline * (1 - relative_drop):
                    continue
                if (
                    int(row["collectors_seeing"]) > 0
                    and int(row["collectors_seeing"]) < min_collectors
                ):
                    continue
                drop = 1 - (ratio / baseline if baseline else 1)
                origin = int(row["origin_asn"]) if row["origin_asn"] is not None else None
                events.append(
                    self.build_event(
                        context=context,
                        prefix=prefix_str,
                        asns=[origin] if origin else [],
                        first_seen=row["snapshot_ts"],
                        last_seen=row["snapshot_ts"] + timedelta(hours=8),
                        score=min(0.7, 0.3 + drop * 0.5),
                        confidence=(
                            Confidence.MEDIUM
                            if int(row["collectors_seeing"]) >= min_collectors
                            else Confidence.LOW
                        ),
                        collectors=sorted(set(row["collectors"])),
                        evidence={
                            "visibility_ratio": round(ratio, 3),
                            "baseline_ratio": round(baseline, 3),
                            "relative_drop": round(drop, 3),
                            "collectors_seeing": int(row["collectors_seeing"]),
                            "collectors_expected": expected_collectors,
                            "excluded_gap_snapshots": len(rows) - len(usable),
                        },
                        explanation=(
                            f"{prefix_str} n'est plus vu que par {ratio:.0%} des peers contre "
                            f"{baseline:.0%} habituellement (calculé sur les seuls instantanés où "
                            f"tous les collecteurs attendus ont rapporté). Perte de visibilité "
                            f"possible : retrait volontaire, panne, ou simple changement de "
                            f"politique."
                        ),
                    )
                )
        return events

    @staticmethod
    def _active_rib(context: DetectionContext) -> pl.LazyFrame:
        """Écarte les lignes RIB d'un collecteur sans aucun trafic réel sur la fenêtre.

        Croise avec le flux de mises à jour (``context.elements``), indépendant
        du canal RIB : un collecteur peut apparaître dans un instantané RIB par
        artefact (résidu d'ingestion, cache) tout en étant réellement silencieux
        sur les annonces/retraits. Ce croisement écarte ce cas plutôt que de
        laisser un dénominateur gonflé par une donnée qui ne reflète aucune
        activité réelle.
        """
        active = (
            context.elements.group_by("collector")
            .agg(messages=pl.len())
            .filter(pl.col("messages") > 0)
            .select("collector")
        )
        rib = context.rib
        assert rib is not None  # ce détecteur n'est exécuté qu'après calcul de context.rib
        return rib.join(active, on="collector", how="inner")


class BogonDetector(Detector):
    """Annonce d'un préfixe non routable ou origine d'un AS privé ou réservé."""

    name = "bogon"
    default_weight = 0.10

    def detect(self, context: DetectionContext) -> list[Event]:
        frame = (
            context.elements.filter(pl.col("elem_type") == "A")
            .group_by(["prefix", "origin_asn"])
            .agg(
                peers=pl.col("peer_asn").n_unique(),
                collectors=pl.col("collector").unique(),
                first_seen=pl.col("ts").min(),
                last_seen=pl.col("ts").max(),
            )
            .collect(engine="streaming")
        )

        events: list[Event] = []
        for row in frame.iter_rows(named=True):
            origin = int(row["origin_asn"]) if row["origin_asn"] is not None else None
            reasons: list[str] = []
            if is_bogon_prefix(row["prefix"]):
                reasons.append("préfixe non routable sur l'Internet public")
            if origin is not None and is_private_asn(origin):
                reasons.append(f"AS d'origine réservé ou privé (AS{origin})")
            if not reasons:
                continue

            collectors = sorted(set(row["collectors"]))
            events.append(
                self.build_event(
                    context=context,
                    prefix=row["prefix"],
                    asns=[origin] if origin else [],
                    first_seen=row["first_seen"],
                    last_seen=row["last_seen"],
                    score=0.5,
                    confidence=confidence_from_peers(int(row["peers"]), len(collectors)),
                    collectors=collectors,
                    evidence={"reasons": reasons, "peers": int(row["peers"])},
                    explanation=(
                        f"{row['prefix']} apparaît dans la table de routage publique alors que "
                        f"{' et '.join(reasons)}. Signale généralement une erreur de filtrage "
                        f"chez un opérateur."
                    ),
                )
            )
        return events
