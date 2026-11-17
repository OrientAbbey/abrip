"""Classification de présence partagée par tous les explorateurs.

Une entité (préfixe, voisin, relation, objet de référentiel) est observée sur
une suite de jours de collecte. Cette module qualifie sa présence sur la plage
choisie avec une seule règle, utilisée par les tableaux, les compteurs
d'onglets et les graphiques :

- ``stable`` — présente à chaque jour de collecte de la plage ;
- ``new`` — absente au premier jour de collecte, présente au dernier ;
- ``left`` — l'inverse ;
- ``unstable`` — au moins une réapparition après une absence intermédiaire, ou
  apparition puis disparition entièrement à l'intérieur de la plage.

Les jours sans collecte ne comptent pas comme des absences : ils ne figurent
pas dans ``all_dates``. C'est la différence avec un simple calendrier, et elle
est essentielle quand un collecteur a été arrêté un jour.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime


def _day(value: date | datetime | str) -> date:
    """Normalise un jour, un horodatage ou une chaîne ISO en `date`."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def count_reappearances(
    seen: Iterable[date | datetime | str], all_dates: Iterable[date | datetime | str]
) -> int:
    """Nombre de retours après une absence, sur les jours de collecte."""
    seen_days = {_day(value) for value in seen}
    count = 0
    was_present = False
    gap_since_present = False
    for value in all_dates:
        present = _day(value) in seen_days
        if was_present and not present:
            gap_since_present = True
        elif gap_since_present and present:
            count += 1
            gap_since_present = False
        was_present = present
    return count


def classify_presence(
    seen: Iterable[date | datetime | str], all_dates: Iterable[date | datetime | str]
) -> str:
    """``stable`` / ``new`` / ``left`` / ``unstable`` à partir des jours vus.

    ``all_dates`` est la liste ordonnée des jours de collecte de la plage, pas
    le calendrier complet : un trou de collecte n'est pas une absence.
    """
    days = [_day(value) for value in all_dates]
    if not days:
        return "stable"
    seen_days = {_day(value) for value in seen}
    if all(day in seen_days for day in days):
        return "stable"
    if count_reappearances(seen_days, days) >= 1:
        return "unstable"
    present_start, present_end = days[0] in seen_days, days[-1] in seen_days
    if not present_start and present_end:
        return "new"
    if present_start and not present_end:
        return "left"
    return "unstable"  # apparue puis disparue entièrement dans la fenêtre
