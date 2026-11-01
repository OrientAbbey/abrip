/** Bornes de dates disponibles (couche `bgp_elements`), pour initialiser et
 *  contraindre le sélecteur de plage. */

import { useMemo } from "react";
import { useApi } from "./useApi";
import type { Health } from "./types";
import type { DateRange } from "../components/DateRangeSelector";

export function useDataBounds(): { min: string; max: string } | null {
  const health = useApi<Health>("/health");
  return useMemo(() => {
    const layer = health.data?.layers.find((l) => l.name === "bgp_elements" && l.oldest && l.newest);
    return layer ? { min: layer.oldest as string, max: layer.newest as string } : null;
  }, [health.data]);
}

/** Plage par défaut : les 7 derniers jours disponibles, ou toute la plage si
 *  elle est plus courte — un choix qui reste pertinent une fois l'historique
 *  réel bien plus long qu'en démonstration. */
export function defaultRange(bounds: { min: string; max: string } | null): DateRange {
  if (!bounds) return { from: "", to: "" };
  const max = bounds.max.slice(0, 10);
  const maxDate = new Date(`${max}T00:00:00Z`);
  const start = new Date(maxDate);
  start.setUTCDate(start.getUTCDate() - 6);
  const min = bounds.min.slice(0, 10);
  const from = start.toISOString().slice(0, 10);
  return { from: from < min ? min : from, to: max };
}
