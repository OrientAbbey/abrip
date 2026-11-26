"""Limitation de débit par adresse client, en mémoire et par processus."""

from __future__ import annotations

import math
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable


class RateLimiter:
    """Fenêtre glissante : au plus `limit` requêtes par `window` secondes.

    L'état est local au processus, comme le cache et les compteurs Prometheus :
    avec plusieurs workers, chaque processus applique sa propre limite. La clé
    est l'adresse vue par uvicorn ; derrière un proxy, configurer celui-ci pour
    transmettre la bonne adresse ou utiliser un limiter partagé.
    """

    def __init__(
        self, limit: int, window: float = 60.0, clock: Callable[[], float] | None = None
    ) -> None:
        if limit < 1:
            raise ValueError("La limite doit être au moins 1")
        self.limit = limit
        self.window = window
        self._clock = clock or time.monotonic
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> tuple[bool, int]:
        """Autorise ou refuse, avec le délai avant nouvel essai en secondes."""
        now = self._clock()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                retry = max(1, math.ceil(self.window - (now - hits[0])))
                return False, retry
            hits.append(now)
            return True, 0
