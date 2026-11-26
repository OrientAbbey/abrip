"""Test de charge reproductible de l'API ABRIP.

    uv run --locked abrip api serve --port 8010
    uv run --locked python scripts/bench/run_charge.py --url http://127.0.0.1:8010 --users 10 --duration 30

Le service doit déjà tourner (le script ne le démarre pas). Plusieurs
utilisateurs virtuels parcourent le même mélange d'endpoints en boucle, sans
temps de pause par défaut : on mesure donc le débit maximal, pas un comportement
humain. `--think 0.5` ajoute une pause entre deux requêtes.

Les réponses ne sont pas mises en cache côté client : chaque requête atteint
l'API. Un ETag est renvoyé mais httpx ne le réutilise pas, ce qui évite de mesurer
des 304 à la place du calcul réel.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import time
from dataclasses import dataclass, field
from urllib.parse import quote

import httpx


@dataclass
class Mesures:
    latences: list[float] = field(default_factory=list)
    statuts: dict[int, int] = field(default_factory=dict)
    erreurs: int = 0


def percentile(values: list[float], part: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(part * len(ordered)) - 1)]


async def discover(client: httpx.AsyncClient) -> list[tuple[str, dict[str, object]]]:
    """Construit le mélange à partir des données réellement présentes."""
    routes: list[tuple[str, dict[str, object]]] = [
        ("/api/health", {}),
        ("/api/overview", {}),
        ("/api/asns", {"limit": 25}),
        ("/api/prefixes", {"limit": 25}),
        ("/api/events", {"limit": 25}),
        ("/api/countries", {}),
    ]
    prefixes = (await client.get("/api/prefixes", params={"limit": 1})).json().get("items", [])
    if prefixes:
        prefix = quote(prefixes[0]["prefix"], safe="")
        routes += [
            (f"/api/prefixes/{prefix}", {}),
            (f"/api/prefixes/{prefix}/propagation", {}),
            (f"/api/prefixes/{prefix}/propagation/replay", {}),
        ]
    asns = (await client.get("/api/asns", params={"limit": 1})).json().get("items", [])
    if asns:
        asn = asns[0]["asn"]
        routes += [(f"/api/asns/{asn}", {}), (f"/api/asns/{asn}/prefixes", {})]
    return routes


async def worker(
    client: httpx.AsyncClient,
    routes: list[tuple[str, dict[str, object]]],
    deadline: float,
    think: float,
    results: dict[str, Mesures],
) -> None:
    index = 0
    while time.perf_counter() < deadline:
        path, params = routes[index % len(routes)]
        index += 1
        start = time.perf_counter()
        try:
            response = await client.get(path, params=params)
            elapsed = time.perf_counter() - start
            record = results.setdefault(path, Mesures())
            record.latences.append(elapsed)
            record.statuts[response.status_code] = record.statuts.get(response.status_code, 0) + 1
        except httpx.HTTPError:
            results.setdefault(path, Mesures()).erreurs += 1
        if think:
            await asyncio.sleep(think)


async def run(args: argparse.Namespace) -> dict[str, Mesures]:
    limits = httpx.Limits(max_connections=args.users, max_keepalive_connections=args.users)
    async with httpx.AsyncClient(
        base_url=args.url, timeout=60.0, limits=limits, follow_redirects=True
    ) as client:
        routes = await discover(client)
        # Préchauffage : construit les index RPKI/IRR et le cache de l'API avant
        # de chronométrer, pour ne pas mesurer le coût d'une installation vierge.
        for path, params in routes:
            await client.get(path, params=params)

        results: dict[str, Mesures] = {}
        deadline = time.perf_counter() + args.duration
        await asyncio.gather(
            *(worker(client, routes, deadline, args.think, results) for _ in range(args.users))
        )
        return results


def report(results: dict[str, Mesures], users: int, duration: float) -> dict[str, object]:
    all_latencies = [value for record in results.values() for value in record.latences]
    requests = len(all_latencies)
    errors = sum(record.erreurs for record in results.values())
    unexpected = sum(
        count
        for record in results.values()
        for status, count in record.statuts.items()
        if status != 200
    )
    print(
        f"{users} utilisateurs, {duration:g} s, {requests} requêtes, "
        f"{requests / duration:.1f} req/s, {errors} erreurs réseau, {unexpected} réponses non-200"
    )
    print(f"{'endpoint':72s} {'n':>5s} {'p50':>7s} {'p95':>7s} {'p99':>7s} {'max':>7s}")
    for path, record in sorted(results.items()):
        values = record.latences
        print(
            f"{path[:72]:72s} {len(values):5d} "
            f"{statistics.median(values):7.3f} {percentile(values, 0.95):7.3f} "
            f"{percentile(values, 0.99):7.3f} {max(values, default=0):7.3f}"
        )
    print(
        f"{'GLOBAL':72s} {requests:5d} "
        f"{statistics.median(all_latencies):7.3f} {percentile(all_latencies, 0.95):7.3f} "
        f"{percentile(all_latencies, 0.99):7.3f} {max(all_latencies, default=0):7.3f}"
    )
    return {
        "users": users,
        "duration": duration,
        "requests": requests,
        "rps": requests / duration,
        "network_errors": errors,
        "unexpected_statuses": unexpected,
        "global": {
            "p50": statistics.median(all_latencies),
            "p95": percentile(all_latencies, 0.95),
            "p99": percentile(all_latencies, 0.99),
        },
        "endpoints": {
            path: {
                "n": len(record.latences),
                "p95": percentile(record.latences, 0.95),
                "statuses": record.statuts,
            }
            for path, record in results.items()
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8010", help="URL de base de l'API")
    parser.add_argument("--users", type=int, default=10, help="utilisateurs concurrents")
    parser.add_argument("--duration", type=float, default=30.0, help="durée de mesure en secondes")
    parser.add_argument("--think", type=float, default=0.0, help="pause entre deux requêtes")
    parser.add_argument("--json", dest="json_path", help="fichier de sortie JSON")
    args = parser.parse_args()
    if args.users < 1 or args.duration <= 0:
        parser.error("--users doit être >= 1 et --duration > 0")

    results = asyncio.run(run(args))
    summary = report(results, args.users, args.duration)
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as output:
            json.dump(summary, output, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
