import { Link, useSearchParams } from "react-router-dom";
import { useApi, useTitle } from "../lib/useApi";
import type { EventOut, Facets, Page } from "../lib/types";
import { AsyncBlock, EmptyState } from "../components/StateBlock";
import { ScoreBar, SeverityBadge } from "../components/Badges";
import { countryLabel, detectorLabel, dt, num } from "../lib/format";

const PAGE_SIZE = 25;

export default function Events() {
  useTitle("Événements");
  const [params, setParams] = useSearchParams();
  const detector = params.get("detector") ?? "";
  const severity = params.get("severity") ?? "";
  const country = params.get("country") ?? "";
  const sort = params.get("sort") ?? "score";
  const offset = Number(params.get("offset") ?? 0);

  const facets = useApi<Facets>("/events/facets");
  const events = useApi<Page<EventOut>>("/events", {
    detector: detector || undefined,
    severity: severity || undefined,
    country: country || undefined,
    sort,
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

  const goto = (newOffset: number) => {
    const next = new URLSearchParams(params);
    next.set("offset", String(Math.max(0, newOffset)));
    setParams(next);
  };

  const options = (map: Record<string, number> | undefined, labeller?: (k: string) => string) =>
    Object.entries(map ?? {})
      .sort((a, b) => b[1] - a[1])
      .map(([key, count]) => (
        <option key={key} value={key}>
          {(labeller ? labeller(key) : key)} ({count})
        </option>
      ));

  return (
    <div className="stack">
      <div className="page-head">
        <h1>Événements</h1>
        <p>
          Chaque ligne est une observation anormale accompagnée de son score et de son niveau de
          confiance. Un score élevé signifie que le signal est net, pas qu'un incident est avéré :
          la page de détail donne les preuves pour trancher.
        </p>
      </div>

      <section className="card">
        <div className="filters">
          <div className="field">
            <label htmlFor="f-detector">Détecteur</label>
            <select
              id="f-detector"
              value={detector}
              onChange={(e) => update("detector", e.target.value)}
            >
              <option value="">Tous</option>
              {options(facets.data?.detector, detectorLabel)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="f-severity">Sévérité</label>
            <select
              id="f-severity"
              value={severity}
              onChange={(e) => update("severity", e.target.value)}
            >
              <option value="">Toutes</option>
              {options(facets.data?.severity)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="f-country">Pays</label>
            <select id="f-country" value={country} onChange={(e) => update("country", e.target.value)}>
              <option value="">Tous</option>
              {options(facets.data?.country_iso2, countryLabel)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="f-sort">Tri</label>
            <select id="f-sort" value={sort} onChange={(e) => update("sort", e.target.value)}>
              <option value="score">Score décroissant</option>
              <option value="recent">Plus récents</option>
              <option value="oldest">Plus anciens</option>
            </select>
          </div>
          {(detector || severity || country) && (
            <button onClick={() => setParams(new URLSearchParams({ sort }))}>
              Réinitialiser
            </button>
          )}
        </div>
      </section>

      <AsyncBlock state={events} rows={6}>
        {(page) =>
          page.items.length === 0 ? (
            <EmptyState title="Aucun événement pour ces filtres">
              <p>Élargissez la sélection, ou relancez la détection sur une fenêtre plus large.</p>
            </EmptyState>
          ) : (
            <section className="card">
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Détecteur</th>
                      <th>Préfixe</th>
                      <th>AS impliqués</th>
                      <th>Pays</th>
                      <th>Sévérité</th>
                      <th>Score</th>
                      <th>Première observation</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {page.items.map((e) => (
                      <tr key={e.event_id}>
                        <td>{detectorLabel(e.detector)}</td>
                        <td className="mono">
                          {e.prefix ? (
                            <Link to={`/prefixes/${encodeURIComponent(e.prefix)}`}>{e.prefix}</Link>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td className="mono">
                          {e.asns_involved.slice(0, 3).map((asn) => (
                            <Link key={asn} to={`/asns/${asn}`} style={{ marginRight: "0.4rem" }}>
                              {asn}
                            </Link>
                          ))}
                          {e.asns_involved.length > 3 && (
                            <span className="muted">+{e.asns_involved.length - 3}</span>
                          )}
                        </td>
                        <td>{countryLabel(e.country_iso2)}</td>
                        <td>
                          <SeverityBadge severity={e.severity} />
                        </td>
                        <td>
                          <ScoreBar score={e.score} />
                        </td>
                        <td className="mono">{dt(e.first_seen)}</td>
                        <td>
                          <Link to={`/events/${e.event_id}`}>détail</Link>
                        </td>
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
                  <button disabled={page.offset === 0} onClick={() => goto(page.offset - page.limit)}>
                    Précédent
                  </button>
                  <button
                    disabled={page.offset + page.limit >= page.total}
                    onClick={() => goto(page.offset + page.limit)}
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
