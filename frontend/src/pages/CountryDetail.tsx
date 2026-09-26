import { Link, useParams } from "react-router-dom";
import { useApi, useTitle } from "../lib/useApi";
import { AsyncBlock } from "../components/StateBlock";
import { AsLink } from "../components/Badges";
import { AsnPrefixesPanel } from "../components/AsnPrefixesPanel";
import { AsnNeighborsPanel } from "../components/AsnNeighborsPanel";
import { countryLabel, num } from "../lib/format";

interface CountryAsns {
  country_iso2: string;
  items: Array<{ asn: number; as_name: string | null; prefixes: number }>;
}

export default function CountryDetail() {
  const { iso2 = "" } = useParams<{ iso2: string }>();
  useTitle(`Pays — ${countryLabel(iso2)}`);
  const asns = useApi<CountryAsns>(`/countries/${iso2}/asns`);
  const basePath = `/countries/${iso2}`;

  return (
    <div className="stack">
      <div className="page-head">
        <h1>
          {countryLabel(iso2)} <span className="muted mono">{iso2.toUpperCase()}</span>
        </h1>
        <p>
          <Link to="/countries">← Tous les pays</Link>
        </p>
      </div>

      <AsyncBlock state={asns} rows={3}>
        {(body) => (
          <section className="card">
            <h2>Systèmes autonomes membres</h2>
            {body.items.length === 0 ? (
              <p className="muted">Aucun AS connu pour ce pays.</p>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>AS</th>
                      <th className="num">Préfixes annoncés</th>
                    </tr>
                  </thead>
                  <tbody>
                    {body.items.map((item) => (
                      <tr key={item.asn}>
                        <td>
                          <AsLink asn={item.asn} name={item.as_name} />
                        </td>
                        <td className="num mono">{num(item.prefixes)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        )}
      </AsyncBlock>

      <AsnPrefixesPanel
        basePath={basePath}
        contextLabel="Pays"
        contextValue={`${countryLabel(iso2)} (${iso2.toUpperCase()})`}
        showOrigin
      />
      <AsnNeighborsPanel basePath={basePath} showMember />
    </div>
  );
}
