"""Marque des tests qui lisent le jeu de démonstration du répertoire de données.

Ces tests sont écrits contre les valeurs de la démonstration (16 événements, AS37100,
196.60.0.0/18 et son unique objet route RADB…). Si le répertoire contient aussi autre
chose — une vraie synchronisation de référentiels, des archives MRT, la démo d'une
ancienne version — ils échouent de façon trompeuse : un objet RADB bien réel apparaît
pour un préfixe censé n'en avoir aucun. On les ignore donc, avec la raison, plutôt que
de les laisser échouer ; `abrip demo check` dit ce qui cloche.
"""

from __future__ import annotations

import pytest

from abrip.config import get_settings
from abrip.demo.bootstrap import dataset_state

STATE = dataset_state(get_settings())
DEMO_READY = STATE["state"] == "demo"

if STATE["state"] == "empty":
    REASON = "jeu de démonstration absent — lancer `abrip demo bootstrap`"
else:
    REASON = (
        f"le répertoire de données n'est pas le jeu de démonstration intact "
        f"(état : {STATE['state']}) — lancer `abrip demo check`, puis "
        "`abrip demo bootstrap --force` ou pointer ABRIP_DATA_DIR vers un dossier dédié"
    )

requires_demo = pytest.mark.skipif(not DEMO_READY, reason=REASON)
