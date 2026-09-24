import { Suspense, lazy } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Loading } from "./components/StateBlock";
import Overview from "./pages/Overview";

// Les pages autres que l'accueil sont chargées à la demande : la bibliothèque
// de graphiques ne pèse ainsi que sur les écrans qui en ont besoin, et le
// premier rendu reste rapide sur une connexion lente.
const Events = lazy(() => import("./pages/Events"));
const EventDetail = lazy(() => import("./pages/EventDetail"));
const AsnList = lazy(() => import("./pages/AsnList"));
const AsnDetail = lazy(() => import("./pages/AsnDetail"));
const PrefixList = lazy(() => import("./pages/Prefixes").then((m) => ({ default: m.PrefixList })));
const PrefixDetail = lazy(() =>
  import("./pages/Prefixes").then((m) => ({ default: m.PrefixDetail })),
);
const Countries = lazy(() => import("./pages/Countries"));
const About = lazy(() => import("./pages/About"));

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<Overview />} />
        <Route
          path="*"
          element={
            <Suspense fallback={<Loading rows={5} label="Chargement de la page" />}>
              <Routes>
                <Route path="events" element={<Events />} />
                <Route path="events/:eventId" element={<EventDetail />} />
                <Route path="asns" element={<AsnList />} />
                <Route path="asns/:asn" element={<AsnDetail />} />
                <Route path="prefixes" element={<PrefixList />} />
                {/* Un préfixe CIDR contient une barre oblique : la route doit
                    capturer le reste du chemin, pas un segment unique. */}
                <Route path="prefixes/*" element={<PrefixDetail />} />
                <Route path="countries" element={<Countries />} />
                <Route path="about" element={<About />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </Suspense>
          }
        />
      </Route>
    </Routes>
  );
}
