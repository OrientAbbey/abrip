/** Définitions des indicateurs, écrites une seule fois.
 *
 *  Les mêmes textes alimentent les infobulles des en-têtes de colonnes
 *  (composant `Term`) et le glossaire affiché en clair sur les pages Pays et
 *  À propos : une définition ne peut donc pas diverger d'un endroit à l'autre.
 *  Chaque entrée dit ce que l'indicateur mesure, comment le lire, et ce qu'il
 *  ne dit pas.
 */

export interface GlossaryEntry {
  label: string;
  hint: string;
}

export const GLOSSARY = {
  hhi: {
    label: "Concentration du transit (HHI)",
    hint:
      "Indice de Herfindahl-Hirschman appliqué aux fournisseurs de transit d'un AS : de 0 " +
      "(trafic réparti entre de nombreux fournisseurs) à 1 (un seul fournisseur). Proche de 1, " +
      "un seul incident chez ce fournisseur coupe l'AS : c'est un point de défaillance unique.",
  },
  dependency: {
    label: "Dépendance au transit étranger",
    hint:
      "Part des observations pour lesquelles le fournisseur de transit principal d'un AS du pays " +
      "est situé hors d'Afrique. 1 = tout le transit quitte le continent dès le premier saut ; " +
      "0 = tout le transit reste en Afrique. Mesure une fragilité structurelle, pas la qualité de service.",
  },
  visibility: {
    label: "Visibilité",
    hint:
      "Part des points de vue (couples collecteur / pair BGP) qui voient les préfixes du pays. " +
      "100 % = visibles de partout ; une chute signale une perte de propagation, pas forcément " +
      "une panne (voir la couverture d'observation).",
  },
  upstreams: {
    label: "Fournisseurs (moy.)",
    hint: "Nombre moyen de fournisseurs de transit distincts par AS du pays, observés dans les chemins.",
  },
  coverage: {
    label: "Couverture d'observation",
    hint:
      "Part des AS alloués au pays par AFRINIC effectivement vus depuis nos collecteurs. Un " +
      "chiffre bas relativise tous les autres indicateurs de la ligne : on ne voit alors qu'une " +
      "fraction du pays.",
  },
  roa: {
    label: "Couverture ROA",
    hint:
      "Part des préfixes annoncés par le pays couverts par un ROA RPKI valide. Un chiffre bas " +
      "ne signale rien d'anormal : c'est l'adoption encore partielle de RPKI dans la région.",
  },
  asnsObserved: {
    label: "AS observés",
    hint: "Nombre d'AS du pays vus comme origine d'au moins un préfixe sur la période.",
  },
  prefixesVisible: {
    label: "Préfixes visibles",
    hint: "Nombre de préfixes du pays vus par au moins un point de vue sur la période.",
  },
  windows: {
    label: "Fenêtres",
    hint: "Nombre de fenêtres de calcul (heures) sur lesquelles ce fournisseur principal a été observé.",
  },
} satisfies Record<string, GlossaryEntry>;

export type GlossaryKey = keyof typeof GLOSSARY;
