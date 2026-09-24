import { NavLink, Outlet } from "react-router-dom";
import { useApi } from "../lib/useApi";
import type { Health } from "../lib/types";
import { day } from "../lib/format";

const LINKS: Array<[string, string]> = [
  ["/", "Vue d'ensemble"],
  ["/events", "Événements"],
  ["/asns", "Systèmes autonomes"],
  ["/prefixes", "Préfixes"],
  ["/countries", "Pays"],
  ["/about", "À propos"],
];

export function Layout() {
  const health = useApi<Health>("/health");
  const window_ = health.data?.layers.find((l) => l.name === "bgp_elements");

  return (
    <div className="shell">
      <header className="topbar">
        <div className="topbar-inner">
          <NavLink to="/" className="brand">
            ABRIP<span>routage BGP africain</span>
          </NavLink>
          <nav className="nav" aria-label="Navigation principale">
            {LINKS.map(([to, label]) => (
              <NavLink key={to} to={to} end={to === "/"}>
                {label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>

      <main>
        <Outlet />
      </main>

      <footer>
        <div className="inner row" style={{ justifyContent: "space-between" }}>
          <span>
            Données RouteViews, RIPE RIS, AFRINIC, RPKI et CAIDA — plan de contrôle uniquement.
          </span>
          <span className="mono">
            {health.data ? `v${health.data.version}` : "…"}
            {window_?.newest ? ` · données jusqu'au ${day(window_.newest)}` : ""}
          </span>
        </div>
      </footer>
    </div>
  );
}
