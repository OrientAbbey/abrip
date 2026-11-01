"""Chronomètre les endpoints de l'API sur un jeu produit par gen_bgp_elements.py.

    python scripts/bench/run_endpoints.py DOSSIER PREFIXE_CHAUD PREFIXE_MOYEN ASN_ORIGINE

(la commande `gen_bgp_elements.py` affiche ces trois valeurs). Pour chaque endpoint :
premier appel, puis médiane de deux appels suivants ; pic de mémoire en fin de liste.
"""
import os, sys, time, statistics, resource, json, urllib.parse as u
os.environ["ABRIP_DATA_DIR"]=sys.argv[1]
hot,avg,asn=sys.argv[2],sys.argv[3],sys.argv[4]
from fastapi.testclient import TestClient
from abrip.api.main import create_app
c=TestClient(create_app())
q=lambda p: u.quote(p,safe="")
E=[("/overview",None),("/prefixes",{"limit":25}),("/events",{"limit":25}),
 (f"/prefixes/{q(hot)}",None),("/metrics/churn",{"prefix":hot}),
 (f"/prefixes/{q(hot)}/propagation",None),(f"/prefixes/{q(hot)}/propagation",{"min_observations":25}),
 (f"/prefixes/{q(hot)}/propagation/replay",None),(f"/prefixes/{q(hot)}/upstreams",None),
 (f"/prefixes/{q(avg)}/propagation",None),(f"/prefixes/{q(avg)}/propagation/replay",None),(f"/prefixes/{q(avg)}/upstreams",None),
 (f"/asns/{asn}",None),(f"/asns/{asn}/prefixes",None),(f"/asns/{asn}/prefixes/timeseries",None),
 (f"/asns/{asn}/neighbours",None),(f"/asns/{asn}/neighbours/timeseries",None),("/asns",{"limit":25}),("/search",{"q":"37030"})]
rows=[]
for path,params in E:
    t=[];code=0;size=0
    for i in range(3):
        t0=time.perf_counter(); r=c.get("/api"+path,params=params); t.append(time.perf_counter()-t0); code=r.status_code; size=len(r.content)
    tag=("hot " if hot in path or "hot" in path else "")+path.replace(q(hot),"HOT").replace(q(avg),"AVG")+(f" {params}" if params else "")
    rows.append((tag,code,t[0],statistics.median(t[1:]),size))
print(f"{'endpoint':72s} {'code':>4s} {'1er appel':>10s} {'ensuite':>9s} {'taille':>9s}")
for tag,code,cold,warm,size in rows: print(f"{tag[:72]:72s} {code:4d} {cold:9.2f}s {warm:8.2f}s {size/1024:8.0f}K")
print("RSS max :",round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024),"Mo")
