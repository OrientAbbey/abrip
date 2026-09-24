import { Link, useSearchParams } from "react-router-dom";
import { useApi, useTitle } from "../lib/useApi";
import type { AsnSummary, CountryRow, Page } from "../lib/types";
import { AsyncBlock, EmptyState } from "../components/StateBlock";
import { countryLabel, dec, num } from "../lib/format";

const PAGE_SIZE = 25;

export default function AsnList() {
  useTitle("Systèmes autonomes");
  const [params, setParams] = useSearchParams();
  const country = params.get("country") ?? "";
  const q = params.get("q") ?? "";
  const africanOnly = params.get("all") !== "1";
  const offset = Number(params.get("offset") ?? 0);

  const countries = useApi<CountryRow[]>("/countries");
  const asns = useApi<Page<AsnSummary>>("/asns", {
    country: country || undefined,
    q: q || undefined,
    african_only: africanOnly,
    limit: PAGE_SIZE,
    offset,
  });

  const update = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    next.delete("offset");
    setParams(next);
  };

  return (
    <div className="stack">
      <div className="page-head">
        <h1>Systèmes autonomes</h1>
        <p>
          Les AS observés comme origine d'au moins un préfixe sur la fenêtre chargée. La
          concentration du transit (HHI) vaut 1 quand tout passe par un seul fournisseur, et
          diminue à mesure que les chemins se répartissent.
        </p>
      </div>

      <section className="card">
        <div className="filters">
          <div className="field">
            <label htmlFor="f-country">Pays</label>
            <select id="f-country" value={country} onChange={(e) => update("country", e.target.value)}>
              <option value="">Tous</option>
              {(countries.data ?? []).map((c) => (
                <option key={c.country_iso2} value={c.country_iso2}>
                  {countryLabel(c.country_iso2)}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="f-q">Numéro d'AS</label>
            <input
              id="f-q"
              value={q}
              placeholder="37100"
              inputMode="numeric"
              onChange={(e) => update("q", e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="f-scope">Périmètre</label>
            <select
              id="f-scope"
              value={africanOnly ? "af" : "all"}
              onChange={(e) => update("all", e.target.value === "all" ? "1" : "")}
            >
              <option value="af">AS africains</option>
              <option value="all">Tous les AS observés</option>
            </select>
          </div>
        </div>
      </section>

      <AsyncBlock state={asns} rows={6}>
        {(page) =>
          page.items.length === 0 ? (
            <EmptyState title="Aucun AS ne correspond">
              <p>Essayez d'élargir le périmètre aux AS non africains, ou retirez le filtre pays.</p>
            </EmptyState>
          ) : (
            <section className="card">
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>AS</th>
                      <th>Pays</th>
                      <th className="num">Préfixes</th>
                      <th className="num">Mises à jour</th>
                      <th className="num">Fournisseurs</th>
                      <th>Transit principal</th>
                      <th className="num">HHI</th>
                      <th className="num">Événements</th>
                    </tr>
                  </thead>
                  <tbody>
                    {page.items.map((a) => (
                      <tr key={a.asn}>
                        <td className="mono">
                          <Link to={`/asns/${a.asn}`}>AS{a.asn}</Link>
                        </td>
                        <td>{countryLabel(a.country_iso2)}</td>
                        <td className="num mono">{num(a.prefixes)}</td>
                        <td className="num mono">{num(a.updates)}</td>
                        <td className="num mono">{num(a.upstream_count)}</td>
                        <td className="mono">
                          {a.primary_upstream ? `AS${a.primary_upstream}` : "—"}
                        </td>
                        <td className="num mono">{dec(a.hhi_transit)}</td>
                        <td className="num mono">{num(a.open_events)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="row" style={{ justifyContent: "space-between", marginTop: "0.8rem" }}>
                <span className="muted">
                  {num(page.offset + 1)}–{num(Math.min(page.offset + page.limit, page.total))} sur{" "}
                  {num(page.total)}
                </span>
                <span className="row">
                  <button
                    disabled={page.offset === 0}
                    onClick={() => update("offset", String(Math.max(0, page.offset - PAGE_SIZE)))}
                  >
                    Précédent
                  </button>
                  <button
                    disabled={page.offset + page.limit >= page.total}
                    onClick={() => update("offset", String(page.offset + PAGE_SIZE))}
                  >
                    Suivant
                  </button>
                </span>
              </div>
            </section>
          )
        }
      </AsyncBlock>
    </div>
  );
}
