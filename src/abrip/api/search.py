"""Aides pour les recherches SQL littérales.

Les filtres de l'API utilisent `LIKE ... ESCAPE '\\'` pour les préfixes ; sans
échappement, un `%` ou un `_` saisi par l'utilisateur se comporterait comme un
joker et renverrait des résultats sans rapport avec la recherche.
"""


def escape_like(term: str) -> str:
    """Échappe les trois caractères spéciaux de `LIKE` (anti-slash compris)."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
