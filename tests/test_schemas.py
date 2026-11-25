from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from abrip.api.schemas import Health, LayerStatus, Series, TimePoint


def test_les_datetimes_naifs_sont_serialises_en_utc_explicite():
    point = TimePoint(ts=datetime(2026, 8, 24, 13, 30), values={"n": 1})
    assert point.model_dump(mode="json")["ts"] == "2026-08-24T13:30:00Z"


def test_les_datetimes_deja_fuses_sont_ramenes_en_utc():
    paris = timezone(timedelta(hours=2))
    point = TimePoint(ts=datetime(2026, 8, 24, 15, 30, tzinfo=paris), values={})
    assert point.model_dump(mode="json")["ts"] == "2026-08-24T13:30:00Z"


def test_la_serialisation_descend_dans_les_objets_imbriques():
    series = Series(
        metric="churn",
        granularity="hour",
        subject="test",
        points=[TimePoint(ts=datetime(2026, 8, 24, 1), values={})],
    )
    body = series.model_dump(mode="json")
    assert body["points"][0]["ts"] == "2026-08-24T01:00:00Z"


def test_health_serialise_generated_at_et_last_run():
    health = Health(
        status="ok",
        version="0.1.0",
        generated_at=datetime(2026, 8, 24, 12, tzinfo=UTC),
        layers=[LayerStatus(name="events", present=True)],
        last_run={"stage": "etl.curate", "finished_at": datetime(2026, 8, 24, 11)},
    )
    body = health.model_dump(mode="json")
    assert body["generated_at"] == "2026-08-24T12:00:00Z"
    assert body["last_run"]["finished_at"] == "2026-08-24T11:00:00Z"
