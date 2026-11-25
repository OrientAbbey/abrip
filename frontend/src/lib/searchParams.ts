/** Construction des paramètres d'URL des listes paginées.
 *
 * Deux gestes distincts, faciles à confondre :
 *   - changer un filtre repart de la première page ;
 *   - changer de page conserve tous les filtres.
 */

export function withFilter(params: URLSearchParams, key: string, value: string): URLSearchParams {
  const next = new URLSearchParams(params);
  if (value) next.set(key, value);
  else next.delete(key);
  if (key !== "offset") next.delete("offset");
  return next;
}

export function withOffset(params: URLSearchParams, offset: number): URLSearchParams {
  const next = new URLSearchParams(params);
  if (offset > 0) next.set("offset", String(offset));
  else next.delete("offset");
  return next;
}
