"""Une connexion DuckDB par thread, réutilisée entre les requêtes."""

from __future__ import annotations

import threading

from abrip.api.deps import DataAccess
from abrip.config import get_settings


def _acces() -> DataAccess:
    return DataAccess(get_settings())


def test_connexion_reutilisee_dans_le_meme_thread():
    data = _acces()
    assert data.query("SELECT 1 AS valeur") == [{"valeur": 1}]
    premiere = data._local.con
    assert data.query("SELECT 2 AS valeur") == [{"valeur": 2}]
    assert data._local.con is premiere


def test_connexions_distinctes_entre_threads():
    data = _acces()
    assert data.query("SELECT 1 AS valeur") == [{"valeur": 1}]
    connexion_principale = data._local.con

    connexions: list[object] = []

    def requete() -> None:
        data.query("SELECT 1 AS valeur")
        connexions.append(data._local.con)

    thread = threading.Thread(target=requete)
    thread.start()
    thread.join()

    assert connexions and connexions[0] is not connexion_principale
