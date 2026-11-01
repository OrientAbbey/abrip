"""Journalisation : fichier JSON avec rotation, erreurs HTTP détaillées, UTC.

Ces tests couvrent les corrections 1 et 2 de la reprise : plus aucun
``datetime.utcnow`` (déprécié, fuseau implicite) ; un journal fichier relisible
par un outil ; des échecs réseau journalisés avec type, méthode, URL et statut.
"""

from __future__ import annotations

import ast
import json
import logging
import logging.handlers
from pathlib import Path

import httpx
import pytest

import abrip
from abrip.logging_conf import get_logger, log_http_error, setup_logging


@pytest.fixture
def racine_propre():
    """setup_logging remplace les handlers de la racine : on les restitue."""
    racine = logging.getLogger()
    handlers, niveau = list(racine.handlers), racine.level
    yield racine
    for handler in racine.handlers:
        if handler not in handlers:
            handler.close()
    racine.handlers[:] = handlers
    racine.setLevel(niveau)


def _lire(path: Path) -> list[dict]:
    return [json.loads(ligne) for ligne in path.read_text(encoding="utf-8").splitlines() if ligne]


class TestJournalFichier:
    def test_ecrit_une_ligne_json_par_message(self, racine_propre, tmp_path):
        chemin = tmp_path / "logs" / "abrip.log"  # le dossier n'existe pas encore
        setup_logging("INFO", json_output=False, log_path=str(chemin))
        get_logger("abrip.test").info("collecte terminée", extra={"collector": "rrc19", "files": 3})
        for handler in racine_propre.handlers:
            handler.flush()

        lignes = _lire(chemin)
        assert len(lignes) == 1
        ligne = lignes[0]
        assert ligne["level"] == "INFO"
        assert ligne["logger"] == "abrip.test"
        assert ligne["message"] == "collecte terminée"
        assert ligne["collector"] == "rrc19" and ligne["files"] == 3
        assert "ts" in ligne

    def test_fichier_toujours_en_json_meme_si_console_en_texte(self, racine_propre, tmp_path):
        chemin = tmp_path / "abrip.log"
        setup_logging("INFO", json_output=False, log_path=str(chemin))
        get_logger("abrip.test").warning("à relire avec jq")
        for handler in racine_propre.handlers:
            handler.flush()
        assert _lire(chemin)[0]["message"] == "à relire avec jq"

    def test_rotation_par_taille(self, racine_propre, tmp_path):
        chemin = tmp_path / "abrip.log"
        setup_logging("INFO", log_path=str(chemin), max_bytes=300, backup_count=2)
        journal = get_logger("abrip.test")
        for i in range(60):
            journal.info("message numéro %d avec de quoi remplir le fichier", i)
        for handler in racine_propre.handlers:
            handler.flush()

        assert chemin.exists()
        assert chemin.with_name("abrip.log.1").exists()
        assert chemin.with_name("abrip.log.2").exists()
        # Au plus backup_count sauvegardes : pas de .3
        assert not chemin.with_name("abrip.log.3").exists()

    def test_sans_chemin_pas_de_fichier(self, racine_propre, tmp_path):
        setup_logging("INFO", log_path=None)
        assert not any(
            isinstance(h, logging.handlers.RotatingFileHandler) for h in racine_propre.handlers
        )


class TestLogHttpError:
    @pytest.fixture
    def requete(self):
        return httpx.Request("GET", "https://exemple.org/api/v2/outages?entity=ZA")

    def test_erreur_de_statut_porte_url_methode_et_code(self, requete, caplog):
        reponse = httpx.Response(503, request=requete)
        erreur = httpx.HTTPStatusError("service indisponible", request=requete, response=reponse)
        with caplog.at_level(logging.WARNING):
            log_http_error(get_logger("abrip.test"), "appel IODA échoué", erreur)
        record = caplog.records[-1]
        assert record.getMessage() == "appel IODA échoué"
        assert record.error_type == "HTTPStatusError"
        assert record.method == "GET"
        assert record.url == "https://exemple.org/api/v2/outages?entity=ZA"
        assert record.status_code == 503

    def test_erreur_de_connexion_sans_reponse_pas_de_statut(self, requete, caplog):
        erreur = httpx.ConnectError("connexion refusée", request=requete)
        with caplog.at_level(logging.WARNING):
            log_http_error(get_logger("abrip.test"), "appel échoué", erreur)
        record = caplog.records[-1]
        assert record.error_type == "ConnectError"
        assert record.url.startswith("https://exemple.org/")
        assert not hasattr(record, "status_code")

    def test_exception_sans_requete(self, caplog):
        with caplog.at_level(logging.WARNING):
            log_http_error(get_logger("abrip.test"), "échec", ValueError("format inattendu"))
        record = caplog.records[-1]
        assert record.error_type == "ValueError"
        assert not hasattr(record, "url") and not hasattr(record, "method")

    def test_erreur_httpx_sans_requete_associee(self, caplog):
        # httpx lève RuntimeError sur `.request` quand l'exception n'en a pas.
        with caplog.at_level(logging.WARNING):
            log_http_error(
                get_logger("abrip.test"), "échec", httpx.ConnectError("boom"), url="https://x/y"
            )
        record = caplog.records[-1]
        assert record.error_type == "ConnectError" and record.url == "https://x/y"

    def test_retry_error_deballe_la_derniere_tentative(self, requete, caplog):
        import tenacity

        @tenacity.retry(stop=tenacity.stop_after_attempt(2), reraise=False)
        def appel():
            raise httpx.ConnectError("boom", request=requete)

        with pytest.raises(tenacity.RetryError) as info:
            appel()
        with caplog.at_level(logging.WARNING):
            log_http_error(get_logger("abrip.test"), "échec", info.value)
        record = caplog.records[-1]
        assert record.error_type == "ConnectError"

    def test_champs_supplementaires_conserves(self, requete, caplog):
        erreur = httpx.ConnectError("boom", request=requete)
        with caplog.at_level(logging.WARNING):
            log_http_error(get_logger("abrip.test"), "échec", erreur, collector="rrc00")
        assert caplog.records[-1].collector == "rrc00"


class TestAbsenceDeUtcnow:
    def test_aucun_appel_a_datetime_utcnow(self):
        """`datetime.utcnow()` est déprécié et rend un datetime sans fuseau."""
        fautifs = []
        for fichier in Path(abrip.__file__).parent.rglob("*.py"):
            arbre = ast.parse(fichier.read_text(encoding="utf-8"), filename=str(fichier))
            for noeud in ast.walk(arbre):
                if isinstance(noeud, ast.Attribute) and noeud.attr == "utcnow":
                    fautifs.append(f"{fichier.name}:{noeud.lineno}")
        assert not fautifs, f"datetime.utcnow() trouvé : {fautifs}"
