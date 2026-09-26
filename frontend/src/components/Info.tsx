/** Icône ⓘ avec une définition au survol/focus — pour les termes techniques
 *  qui ne se comprennent pas d'eux-mêmes (HHI transit, Dépendance…voir la
 *  page Pays). Utilise l'attribut `title` natif : pas de dépendance
 *  supplémentaire, et accessible au clavier par construction. */
export function Info({ text }: { text: string }) {
  return (
    <span className="info-icon" title={text} tabIndex={0} aria-label={text}>
      ⓘ
    </span>
  );
}
