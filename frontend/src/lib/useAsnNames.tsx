/** Table de correspondance ASN → nom, chargée une fois pour toute l'application.
 *
 * `ref_as_org` est petite (quelques milliers de lignes au plus) : un seul
 * aller-retour au montage de l'app suffit, plutôt qu'une requête par
 * composant qui affiche un numéro d'AS.
 */

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { apiGet } from "./api";

const AsnNamesContext = createContext<Record<string, string>>({});

export function AsnNamesProvider({ children }: { children: ReactNode }) {
  const [names, setNames] = useState<Record<string, string>>({});

  useEffect(() => {
    const controller = new AbortController();
    apiGet<Record<string, string>>("/asns/names", {}, controller.signal)
      .then(setNames)
      .catch(() => {
        /* silencieux : l'absence de noms ne doit jamais bloquer l'affichage,
           les numéros d'AS restent lisibles seuls. */
      });
    return () => controller.abort();
  }, []);

  return <AsnNamesContext.Provider value={names}>{children}</AsnNamesContext.Provider>;
}

/** Nom connu pour cet ASN, ou `undefined` si absent du référentiel. */
export function useAsnName(asn: number | string | null | undefined): string | undefined {
  const names = useContext(AsnNamesContext);
  if (asn === null || asn === undefined) return undefined;
  return names[String(asn)];
}
