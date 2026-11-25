from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from abrip.ingestion import broker as broker_module
from abrip.ingestion.broker import BrokerClient


def _client() -> BrokerClient:
    settings = SimpleNamespace(
        ingestion=SimpleNamespace(
            broker_url="https://example.invalid/broker",
            request_timeout=1,
            user_agent="test",
        )
    )
    return BrokerClient(settings)  # type: ignore[arg-type]


def _item(n: int) -> dict:
    return {"url": f"https://example.invalid/{n}.gz", "ts_start": 1_700_000_000 + n}


def test_parcourt_toutes_les_pages(monkeypatch):
    monkeypatch.setattr(broker_module, "PAGE_SIZE", 2)
    client = _client()
    pages = {
        1: {"data": [_item(1), _item(2)], "total": 5},
        2: {"data": [_item(3), _item(4)], "total": 5},
        3: {"data": [_item(5)], "total": 5},
    }
    calls: list[int] = []

    def fake_query(params):
        page = int(params["page"])
        calls.append(page)
        return pages[page]

    monkeypatch.setattr(client, "_query", fake_query)
    raw = client._search_pages(
        SimpleNamespace(name="rrc19", project="riperis"),  # type: ignore[arg-type]
        datetime(2026, 8, 24),
        datetime(2026, 8, 25),
        "updates",
    )
    assert [item["url"] for item in raw] == [f"https://example.invalid/{n}.gz" for n in range(1, 6)]
    assert calls == [1, 2, 3]


def test_s_arrete_sur_une_page_incomplete_sans_total(monkeypatch):
    monkeypatch.setattr(broker_module, "PAGE_SIZE", 2)
    client = _client()
    pages = {
        1: {"data": [_item(1), _item(2)]},
        2: {"data": [_item(3)]},
    }
    calls: list[int] = []

    def fake_query(params):
        page = int(params["page"])
        calls.append(page)
        return pages[page]

    monkeypatch.setattr(client, "_query", fake_query)
    raw = client._search_pages(
        SimpleNamespace(name="rrc19", project="riperis"),  # type: ignore[arg-type]
        datetime(2026, 8, 24),
        datetime(2026, 8, 25),
        "updates",
    )
    assert len(raw) == 3
    assert calls == [1, 2]


def test_deduplique_les_urls_entre_pages(monkeypatch):
    monkeypatch.setattr(broker_module, "PAGE_SIZE", 2)
    client = _client()
    pages = {
        1: {"data": [_item(1), _item(2)], "total": 3},
        2: {"data": [_item(2), _item(3)], "total": 3},
    }
    monkeypatch.setattr(client, "_query", lambda params: pages[int(params["page"])])
    raw = client._search_pages(
        SimpleNamespace(name="rrc19", project="riperis"),  # type: ignore[arg-type]
        datetime(2026, 8, 24),
        datetime(2026, 8, 25),
        "updates",
    )
    assert [item["url"] for item in raw] == [f"https://example.invalid/{n}.gz" for n in (1, 2, 3)]
