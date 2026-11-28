"""Le parseur bgpkit utilise l'API itérable de pybgpkit-parser 0.24."""

from __future__ import annotations

import sys
import types
from pathlib import Path

from abrip.etl.mrt_parser import BgpkitParser


def test_api_iterable_et_to_dict(monkeypatch):
    class FauxElem:
        def to_dict(self):
            return {
                "timestamp": 1_700_000_000.0,
                "peer_asn": 37100,
                "peer_ip": "192.0.2.1",
                "elem_type": "A",
                "prefix": "197.1.0.0/24",
                "as_path": "37100 174",
                "next_hop": "192.0.2.1",
                "communities": ["64500:1"],
                "med": 0,
                "local_pref": 100,
            }

    class FauxParser:
        def __init__(self, url: str):
            self.url = url

        def __iter__(self):
            return iter([FauxElem()])

    module = types.ModuleType("pybgpkit_parser")
    module.Parser = FauxParser
    monkeypatch.setitem(sys.modules, "pybgpkit_parser", module)

    assert BgpkitParser().available()
    records = list(BgpkitParser().parse(Path("updates.2026-11-20.gz"), "rrc19"))
    assert len(records) == 1
    assert records[0]["prefix"] == "197.1.0.0/24"
    assert records[0]["collector"] == "rrc19"
    assert records[0]["as_path_dedup"] == [37100, 174]
