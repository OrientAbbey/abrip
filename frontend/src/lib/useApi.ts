/** Chargement de données sans bibliothèque de cache.
 *
 * Un `useEffect` avec `AbortController` suffit ici : les écrans sont peu
 * nombreux, les réponses déjà mises en cache côté API, et une dépendance de
 * plus coûterait au budget de bundle sans rien apporter de visible.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, apiGet, type QueryValue } from "./api";

export interface AsyncState<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  reload: () => void;
}

export function useApi<T>(
  path: string | null,
  params: Record<string, QueryValue> = {},
): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState<boolean>(path !== null);
  const [nonce, setNonce] = useState(0);
  // Sérialiser les paramètres évite de relancer la requête à chaque rendu
  // simplement parce que l'objet littéral a une nouvelle identité.
  const key = JSON.stringify(params);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    if (path === null) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    apiGet<T>(path, JSON.parse(key), controller.signal)
      .then((payload) => {
        if (!controller.signal.aborted) {
          setData(payload);
          setLoading(false);
        }
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setError(
          cause instanceof ApiError
            ? cause
            : new ApiError(0, {
                code: "unknown_error",
                message: String(cause),
                details: {},
              }),
        );
        setLoading(false);
      });
    return () => controller.abort();
  }, [path, key, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { data, error, loading, reload };
}

/** Met à jour le titre du document — utile pour l'historique du navigateur. */
export function useTitle(title: string): void {
  useEffect(() => {
    document.title = `${title} — ABRIP`;
  }, [title]);
}
