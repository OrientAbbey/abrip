"""Rejeu de propagation — voir analytics/replay.py."""

from datetime import UTC, datetime, timedelta

from abrip.analytics.replay import ReplayEvent, effective_step, orient_path, replay

T0 = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)
STEP = timedelta(minutes=15)
PEER_A = ("rrc00", "10.0.0.1")
PEER_B = ("rrc00", "10.0.0.2")


def ev(minutes: int, kind: str, peer, *path: int) -> ReplayEvent:
    return ReplayEvent(T0 + timedelta(minutes=minutes), kind, peer, tuple(path))


class TestOrientPath:
    def test_inverse_le_chemin(self):
        assert orient_path([174, 3320, 37100]) == (37100, 3320, 174)

    def test_chemin_vide_ou_mauvaise_origine(self):
        assert orient_path([]) is None
        assert orient_path([174, 37100], origin=45090) is None

    def test_troncature_a_la_premiere_cible_depuis_l_origine(self):
        assert orient_path([174, 3320, 6939, 37100], targets={3320, 174}) == (37100, 6939, 3320)


class TestEffectiveStep:
    def test_pas_conserve_si_peu_de_tranches(self):
        assert effective_step(timedelta(hours=2), STEP, 200) == STEP

    def test_pas_elargi_au_dela_du_maximum(self):
        step = effective_step(timedelta(days=7), STEP, 200)
        assert step > STEP
        assert (timedelta(days=7) / step) <= 200


class TestReplay:
    def frames(self, events, minutes=60, **kw):
        return replay(events, T0, T0 + timedelta(minutes=minutes), STEP, **kw)

    def test_apparition_puis_disparition(self):
        frames = self.frames([ev(20, "A", PEER_A, 174, 37100), ev(50, "W", PEER_A)])
        assert [len(f.paths) for f in frames] == [0, 0, 1, 1, 0]
        assert (frames[2].announcements, frames[4].withdrawals) == (1, 1)

    def test_un_evenement_anterieur_amorce_l_etat(self):
        # Sans amorçage, le pair serait absent de la première tranche.
        frames = self.frames([ev(-120, "A", PEER_A, 174, 37100)])
        assert all(f.paths == frozenset({(37100, 174)}) for f in frames)
        assert frames[0].announcements == 0

    def test_une_annonce_remplace_le_chemin_du_meme_pair(self):
        frames = self.frames([ev(-5, "A", PEER_A, 174, 37100), ev(10, "A", PEER_A, 3320, 37100)])
        assert frames[0].paths == frozenset({(37100, 174)})
        assert frames[1].paths == frozenset({(37100, 3320)})

    def test_filtre_origine_applique_apres_l_etat(self):
        # Le pair passe de l'origine 37100 à 45090 : avec le filtre 37100,
        # son ancien chemin ne doit PAS survivre au changement d'origine.
        events = [ev(-5, "A", PEER_A, 174, 37100), ev(10, "A", PEER_A, 174, 45090)]
        frames = self.frames(events, origin=37100)
        assert frames[0].paths == frozenset({(37100, 174)})
        assert frames[1].paths == frozenset()

    def test_retrait_d_un_pair_inconnu_sans_effet(self):
        frames = self.frames([ev(5, "W", PEER_B)])
        assert frames[1].paths == frozenset() and frames[1].withdrawals == 1

    def test_union_des_pairs(self):
        frames = self.frames(
            [ev(1, "A", PEER_A, 174, 37100), ev(2, "A", PEER_B, 3320, 37100)], minutes=15
        )
        assert frames[-1].paths == frozenset({(37100, 174), (37100, 3320)})

    def test_derniere_tranche_tronquee_a_la_fin(self):
        frames = self.frames([], minutes=20)
        assert [f.ts - T0 for f in frames] == [timedelta(0), STEP, timedelta(minutes=20)]
