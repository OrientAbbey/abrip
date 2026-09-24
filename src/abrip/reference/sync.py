"""Rafraîchissement des référentiels externes.

Chaque source est téléchargée dans un instantané **daté et immuable**. Un
résultat d'analyse doit rester rejouable avec le référentiel en vigueur au moment
des faits : écraser le référentiel rendrait toute enquête a posteriori fausse.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from abrip.config import Settings
from abrip.logging_conf import get_logger
from abrip.reference.anycast import build_anycast_reference, fetch_anycast_reference
from abrip.reference.as2org import parse_as2org
from abrip.reference.irr import RipeDbClient, build_irr_reference
from abrip.reference.peeringdb import PeeringDbClient, build_relationship_evidence
from abrip.reference.relationships import parse_as_rel
from abrip.reference.rir import build_ref_asn
from abrip.reference.rpki import parse_roa_payload, roas_to_frame
from abrip.storage.catalog import Catalog, RunContext
from abrip.storage.parquet import write_frame

log = get_logger(__name__)


def _download(url: str, destination: Path, settings: Settings) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": settings.ingestion.user_agent}
    with httpx.Client(timeout=settings.ingestion.request_timeout, follow_redirects=True) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
        destination.write_bytes(response.content)
    log.info("référentiel téléchargé", extra={"url": url, "bytes": destination.stat().st_size})
    return destination


def sync_rir(settings: Settings, snapshot: date) -> int:
    """Construit ``ref_asn`` à partir des fichiers delegated-extended des RIR."""
    staging = settings.reference_dir / "_staging" / snapshot.isoformat()
    urls = {"afrinic": settings.reference.afrinic_delegated_url}
    urls.update(settings.reference.rir_delegated_urls)

    files: dict[str, Path] = {}
    for rir, url in urls.items():
        if not url:
            continue
        try:
            files[rir] = _download(url, staging / f"delegated-{rir}.txt", settings)
        except Exception as exc:
            log.warning("source RIR indisponible", extra={"rir": rir, "error": str(exc)})

    if not files:
        return 0
    frame = build_ref_asn(files, settings.reference.extra_african_asns, snapshot)
    write_frame(frame, settings.reference_dir / "ref_asn")
    write_frame(frame, settings.reference_dir / "history" / "ref_asn" / f"date={snapshot}")
    return frame.height


def sync_rpki(settings: Settings, snapshot: date) -> int:
    url = settings.reference.rpki_url
    if not url:
        return 0
    staging = settings.reference_dir / "_staging" / snapshot.isoformat() / "rpki.json"
    try:
        _download(url, staging, settings)
    except Exception as exc:
        log.warning("export RPKI indisponible", extra={"error": str(exc)})
        return 0

    with staging.open(encoding="utf-8") as handle:
        entries = parse_roa_payload(json.load(handle))
    frame = roas_to_frame(entries, snapshot)
    write_frame(frame, settings.reference_dir / "ref_roa")
    write_frame(frame, settings.reference_dir / "history" / "ref_roa" / f"date={snapshot}")
    return frame.height


def sync_caida(settings: Settings, snapshot: date, filename: str | None = None) -> int:
    """Charge les relations d'AS depuis un fichier déjà présent, ou le télécharge.

    Le répertoire CAIDA est indexé par mois ; à défaut de fichier explicite, on
    utilise le dernier instantané local pour éviter de deviner une URL.
    """
    local = settings.reference_dir / "_staging" / "as-rel"
    candidates = sorted(local.glob("*.bz2")) + sorted(local.glob("*.txt"))

    if filename:
        url = settings.reference.caida_as_rel_base.rstrip("/") + "/" + filename
        try:
            candidates = [_download(url, local / filename, settings)]
        except Exception as exc:
            log.warning("fichier CAIDA indisponible", extra={"error": str(exc)})

    if not candidates:
        log.warning(
            "aucun fichier de relations AS. Le déposer dans data/reference/_staging/as-rel/ "
            "ou passer --filename YYYYMM.as-rel2.txt.bz2"
        )
        return 0

    frame = parse_as_rel(candidates[-1], snapshot)
    write_frame(frame, settings.reference_dir / "ref_as_rel")
    write_frame(frame, settings.reference_dir / "history" / "ref_as_rel" / f"date={snapshot}")
    return frame.height


def sync_as2org(settings: Settings, snapshot: date, filename: str | None = None) -> int:
    """Charge CAIDA AS2Org (L6) — donne au filtre « même organisation » du
    détecteur MOAS des données réelles à consulter (voir ``reference.as2org``)."""
    local = settings.reference_dir / "_staging" / "as-org"
    candidates = sorted(local.glob("*.txt.gz")) + sorted(local.glob("*.txt"))

    if filename:
        url = settings.reference.caida_as_org_base.rstrip("/") + "/" + filename
        try:
            candidates = [_download(url, local / filename, settings)]
        except Exception as exc:
            log.warning("fichier AS2Org indisponible", extra={"error": str(exc)})

    if not candidates:
        log.warning(
            "aucun fichier AS2Org. Le déposer dans data/reference/_staging/as-org/ "
            "ou passer --filename YYYYMMDD.as-org2info.txt.gz"
        )
        return 0

    frame = parse_as2org(candidates[-1], snapshot)
    write_frame(frame, settings.reference_dir / "ref_as_org")
    write_frame(frame, settings.reference_dir / "history" / "ref_as_org" / f"date={snapshot}")
    return frame.height


def sync_irr(settings: Settings, snapshot: date, prefixes: list[str] | None = None) -> int:
    """Interroge l'IRR (via RIPE DB REST) sur les préfixes annoncés — L4a.

    Sans liste explicite, interroge les préfixes africains les plus récemment
    curés : c'est un repli utile quand RPKI répond ``not-found``, pas une
    vérité à elle seule — voir ``reference.irr`` et
    ``docs/limites-et-remediations.md``.
    """
    if prefixes is None:
        prefixes = _recent_curated_prefixes(settings)
    if not prefixes:
        log.warning("aucun préfixe à interroger sur l'IRR — curer des données d'abord")
        return 0

    with RipeDbClient(
        settings.enrichment.ripedb_base_url, settings.enrichment.request_timeout
    ) as client:
        frame = build_irr_reference(client, prefixes, snapshot)

    if frame.is_empty():
        log.info("IRR : aucun objet route trouvé pour les préfixes interrogés")
        return 0
    write_frame(frame, settings.reference_dir / "ref_irr_route")
    write_frame(frame, settings.reference_dir / "history" / "ref_irr_route" / f"date={snapshot}")
    return frame.height


def sync_relationship_evidence(settings: Settings, snapshot: date) -> int:
    """Corrobore les relations CAIDA par PeeringDB et l'IRR — L3.

    Se limite aux AS déjà connus de ``ref_as_rel`` : ce n'est pas un appel à
    exécuter à haute fréquence (une requête réseau par lien à corroborer), mais
    un rafraîchissement périodique, au même rythme que la synchronisation CAIDA.
    """
    from abrip.analytics.metrics import _load_reference

    caida = _load_reference(settings, "ref_as_rel")
    if caida.is_empty():
        log.warning("ref_as_rel absent — lancer `abrip reference sync --sources caida` d'abord")
        return 0

    with (
        PeeringDbClient(
            settings.enrichment.peeringdb_base_url, settings.enrichment.request_timeout
        ) as peeringdb,
        RipeDbClient(
            settings.enrichment.ripedb_base_url, settings.enrichment.request_timeout
        ) as irr,
    ):
        frame = build_relationship_evidence(caida, peeringdb, irr, snapshot)

    if frame.is_empty():
        return 0
    write_frame(frame, settings.reference_dir / "ref_as_rel_evidence")
    write_frame(
        frame, settings.reference_dir / "history" / "ref_as_rel_evidence" / f"date={snapshot}"
    )
    return frame.height


def _recent_curated_prefixes(settings: Settings, limit: int = 300) -> list[str]:
    """Préfixes africains distincts vus dans les partitions curées les plus récentes."""
    from abrip.storage.parquet import read_partitions

    base = settings.curated_dir / "bgp_elements"
    if not base.exists():
        return []
    try:
        frame = read_partitions(settings.curated_dir, "bgp_elements")
    except FileNotFoundError:
        return []
    prefixes = (
        frame.select("prefix")
        .unique()
        .limit(limit)
        .collect(engine="streaming")
        .get_column("prefix")
        .to_list()
    )
    return prefixes


def sync_anycast(settings: Settings, snapshot: date) -> int:
    """Télécharge le catalogue public d'anycast (bgp.tools/anycatch) — L6 filtre 3.

    Source ouverte, mise à jour en continu par le projet ``bgp.tools`` ; voir
    ``reference.anycast``. Un échec réseau ne fait pas échouer la
    synchronisation globale : le filtre anycast se contente alors de rester
    inactif, comme documenté dans ``docs/limites-et-remediations.md``.
    """
    prefixes = fetch_anycast_reference(settings.enrichment.request_timeout)
    if not prefixes:
        log.warning("catalogue anycast vide ou indisponible")
        return 0
    frame = build_anycast_reference(prefixes, snapshot)
    write_frame(frame, settings.reference_dir / "ref_anycast")
    write_frame(frame, settings.reference_dir / "history" / "ref_anycast" / f"date={snapshot}")
    return frame.height


def sync_references(
    settings: Settings, catalog: Catalog, sources: list[str], snapshot: date | None = None
) -> dict[str, Any]:
    snapshot = snapshot or date.today()
    handlers = {
        "afrinic": sync_rir,
        "rir": sync_rir,
        "rpki": sync_rpki,
        "caida": sync_caida,
        "as2org": sync_as2org,
        "irr": sync_irr,
        "peeringdb": sync_relationship_evidence,
        "anycast": sync_anycast,
    }
    written: dict[str, Any] = {}

    with RunContext(catalog, "reference.sync", sources=sources, snapshot=str(snapshot)) as run:
        for source in sources or list(handlers):
            handler = handlers.get(source)
            if handler is None:
                log.warning("source inconnue ignorée", extra={"source": source})
                continue
            written[source] = handler(settings, snapshot)
        run.rows_out = sum(v for v in written.values() if isinstance(v, int))

    return {"snapshot": snapshot.isoformat(), "rows": written}
