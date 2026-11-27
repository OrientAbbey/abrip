"""Mode lecture distante : manifeste HTTPS et accès DuckDB sans fichiers locaux."""

from __future__ import annotations

from types import SimpleNamespace

from abrip.api.deps import DataAccess, DataUnavailable
from abrip.config import get_settings
from abrip.storage.remote import file_url, load_manifest

BASE = "https://huggingface.co/datasets/user/abrip-data/resolve/main"


def test_construction_des_urls():
    assert file_url(BASE, "manifest.json") == f"{BASE}/manifest.json"
    assert file_url(BASE + "/", "/curated/date=2026-11-20/part-00000.parquet") == (
        f"{BASE}/curated/date=2026-11-20/part-00000.parquet"
    )


def test_chargement_du_manifest(monkeypatch):
    appels: list[dict] = []

    class FauxClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, headers=None):
            appels.append({"url": url, "headers": headers or {}})
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {
                    "tables": {
                        "bgp_elements": ["curated/bgp_elements/date=2026-11-20/part-00000.parquet"]
                    }
                },
            )

    monkeypatch.setattr("abrip.storage.remote.httpx.Client", FauxClient)
    manifeste = load_manifest(BASE, token="secret")
    assert appels[0]["url"] == f"{BASE}/manifest.json"
    assert appels[0]["headers"]["Authorization"] == "Bearer secret"
    assert manifeste["bgp_elements"] == [
        f"{BASE}/curated/bgp_elements/date=2026-11-20/part-00000.parquet"
    ]


def test_table_distante_sans_fichier_local():
    settings = get_settings().model_copy(deep=True)
    settings.remote_data_url = BASE
    url = f"{BASE}/curated/bgp_elements/date=2026-11-20/part-00000.parquet"
    data = DataAccess(settings, manifest={"bgp_elements": [url]})

    assert data.remote_base == BASE
    assert data.exists("bgp_elements")
    assert not data.exists("events")
    assert data.table("bgp_elements") == f"read_parquet(['{url}'], union_by_name=true)"
    try:
        data.table("events")
    except DataUnavailable:
        pass
    else:
        raise AssertionError("une table absente doit lever DataUnavailable")


def test_mode_local_reste_identique():
    settings = get_settings().model_copy(deep=True)
    data = DataAccess(settings)
    assert data.remote_base is None
    assert data.table("bgp_elements").startswith("read_parquet('")
