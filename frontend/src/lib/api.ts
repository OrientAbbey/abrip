/** Client HTTP de l'API ABRIP.
 *
 * Deux règles tiennent tout le reste :
 *   1. toute erreur remonte comme `ApiError` porteuse du code métier, jamais
 *      comme une exception réseau anonyme ;
 *   2. un 503 conserve la commande à lancer (`details.run`), pour que l'écran
 *      puisse dire quoi faire plutôt qu'afficher « une erreur est survenue ».
 */

import type { ApiErrorBody } from "./types";

const BASE = "/api";
const API_KEY_STORAGE = "abrip_api_key";

/** Clé API optionnelle, conservée dans le navigateur pour les déploiements
 *  qui activent `api.api_key` côté serveur. Stockage best-effort : en mode
 *  privé ou hors navigateur, la clé reste simplement vide. */
export function getApiKey(): string | null {
  try {
    return globalThis.localStorage?.getItem(API_KEY_STORAGE) ?? null;
  } catch {
    return null;
  }
}

export function setApiKey(key: string): void {
  try {
    if (key) globalThis.localStorage?.setItem(API_KEY_STORAGE, key);
    else globalThis.localStorage?.removeItem(API_KEY_STORAGE);
  } catch {
    /* navigateur sans stockage : la clé ne peut pas être mémorisée */
  }
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message || `Erreur HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code;
    this.details = body.details ?? {};
  }

  /** Commande CLI suggérée par l'API quand une couche de données manque. */
  get remedy(): string | null {
    const run = this.details.run;
    return typeof run === "string" ? run : null;
  }
}

export type QueryValue = string | number | boolean | null | undefined | Array<string | number>;

export function buildQuery(params: Record<string, QueryValue> = {}): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === "") continue;
    if (Array.isArray(value)) {
      value.forEach((v) => search.append(key, String(v)));
    } else {
      search.append(key, String(value));
    }
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

export async function apiGet<T>(
  path: string,
  params: Record<string, QueryValue> = {},
  signal?: AbortSignal,
): Promise<T> {
  let response: Response;
  try {
    const key = getApiKey();
    response = await fetch(`${BASE}${path}${buildQuery(params)}`, {
      signal,
      headers: {
        Accept: "application/json",
        ...(key ? { "X-API-Key": key } : {}),
      },
    });
  } catch (cause) {
    if ((cause as Error).name === "AbortError") throw cause;
    throw new ApiError(0, {
      code: "network_error",
      message: "Le service est injoignable. Vérifiez que `abrip api serve` tourne.",
      details: {},
    });
  }

  if (!response.ok) {
    let body: ApiErrorBody = {
      code: "http_error",
      message: `Erreur HTTP ${response.status}`,
      details: {},
    };
    try {
      const payload = await response.json();
      if (payload?.error) body = payload.error as ApiErrorBody;
    } catch {
      /* réponse non JSON : on garde le message générique */
    }
    if (response.status === 401 || response.status === 403) {
      body = {
        code: "unauthorized",
        message: "Clé API absente ou invalide — renseignez-la dans la page À propos.",
        details: body.details,
      };
    }
    throw new ApiError(response.status, body);
  }

  return (await response.json()) as T;
}
