/** Les trois états qu'un écran de données doit traiter explicitement.
 *
 * Aucun écran n'affiche un tableau vide sans explication : soit les données
 * chargent, soit l'API a dit pourquoi elles manquent, soit le filtre ne
 * ramène rien et on le dit.
 */

import type { ReactNode } from "react";
import { ApiError } from "../lib/api";

export function Loading({ rows = 4, label = "Chargement des données" }: { rows?: number; label?: string }) {
  return (
    <div aria-busy="true" aria-live="polite">
      <span className="visually-hidden">{label}…</span>
      <div className="stack" style={{ gap: "0.45rem" }}>
        {Array.from({ length: rows }, (_, i) => (
          <div key={i} className="skeleton" style={{ width: `${100 - i * 9}%` }} />
        ))}
      </div>
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: ApiError; onRetry?: () => void }) {
  const remedy = error.remedy;
  return (
    <div className="state" role="alert">
      <h3>{error.status === 503 ? "Donnée non encore calculée" : "Requête en échec"}</h3>
      <p>{error.message}</p>
      {remedy && (
        <>
          <p className="muted">Commande à exécuter :</p>
          <pre className="mono">{remedy}</pre>
        </>
      )}
      {onRetry && (
        <p style={{ marginBottom: 0 }}>
          <button onClick={onRetry}>Réessayer</button>
        </p>
      )}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="state">
      <h3>{title}</h3>
      {children}
    </div>
  );
}

/** Enveloppe le trio pour les cas simples. */
export function AsyncBlock<T>({
  state,
  children,
  empty,
  rows,
}: {
  state: { data: T | null; error: ApiError | null; loading: boolean; reload: () => void };
  children: (data: T) => ReactNode;
  empty?: ReactNode;
  rows?: number;
}) {
  if (state.loading && state.data === null) return <Loading rows={rows} />;
  if (state.error) return <ErrorState error={state.error} onRetry={state.reload} />;
  if (state.data === null) return <>{empty ?? <EmptyState title="Aucune donnée" />}</>;
  return <>{children(state.data)}</>;
}
