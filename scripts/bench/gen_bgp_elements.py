"""Jeu synthétique de bgp_elements pour mesurer l'API à grande échelle.

    python scripts/bench/gen_bgp_elements.py 1e7 /tmp/bench_1e7 [--ref DOSSIER_DATA_DEMO]

Même schéma et même partitionnement (date=…/collector=…) que la couche curated,
lignes triées par (prefix, ts) comme `abrip etl curate` les écrit. Les dossiers
reference/ et analytics/ sont copiés de la démonstration (`abrip demo bootstrap`).
Dépendances hors du projet : numpy et polars (`pip install numpy`, dans un
environnement à part : les annotations de numpy gênent mypy sur ce dépôt).
"""
import sys, shutil, time
from pathlib import Path
import numpy as np, polars as pl
rows_total=int(float(sys.argv[1])); out=Path(sys.argv[2])
src=Path(sys.argv[sys.argv.index("--ref") + 1]) if "--ref" in sys.argv else Path("data")
if out.exists(): shutil.rmtree(out)
(out/"curated").mkdir(parents=True)
for d in ("reference","analytics"):
    if (src/d).exists(): shutil.copytree(src/d, out/d)
rng=np.random.default_rng(7)
N_PREFIX=20000
# 20 000 préfixes IPv4 /22 ; une origine chacun parmi 400 AS ; un préfixe « chaud »
pfx_i=np.arange(N_PREFIX); prefixes=np.array([f"{100+(i>>14)}.{(i>>6)&255}.{(i&63)<<2}.0/22" for i in pfx_i])
origin=rng.integers(37000,37400,N_PREFIX).astype(np.uint32)
tier1=np.array([174,3320,6939,2914,3356,1299,4809,3257],dtype=np.uint32)
mids=rng.integers(36000,36300,300).astype(np.uint32)
collectors=["route-views.napafrica","route-views.jinx","route-views.kixp","rrc19","rrc00"]
peer_pool=np.concatenate([tier1,rng.integers(38000,38030,12).astype(np.uint32)])
days=[f"2026-08-{24+i}" for i in range(7)]
per=rows_total//(len(days)*len(collectors)); t0=time.time()
HOT=1234  # préfixe chaud : ~0,5 % des lignes, soit bien plus que la moyenne
for day in days:
    base=np.datetime64(f"{day}T00:00:00","us")
    for ci,col in enumerate(collectors):
        # Zipf léger : quelques préfixes très bavards, mais pas de ligne sans préfixe
        w=1/np.arange(1,N_PREFIX+1)**0.6; w/=w.sum()
        pi=rng.choice(N_PREFIX,size=per,p=w)
        hot=rng.random(per)<0.004; pi[hot]=HOT
        peer=rng.choice(peer_pool,per); mid1=rng.choice(tier1,per); mid2=rng.choice(mids,per)
        org=origin[pi]; long=rng.random(per)<0.3
        p3=pl.concat_list([pl.Series(peer),pl.Series(mid1),pl.Series(org)])
        p4=pl.concat_list([pl.Series(peer),pl.Series(mid1),pl.Series(mid2),pl.Series(org)])
        df=pl.DataFrame({"ts":base+rng.integers(0,86_400_000_000,per).astype("timedelta64[us]"),
            "collector":[col]*per,"peer_asn":peer,"peer_ip":pl.Series(peer).cast(pl.Utf8)+pl.Series(rng.integers(1,6,per)).cast(pl.Utf8),
            "elem_type":np.where(rng.random(per)<0.14,"W","A"),"prefix":prefixes[pi],"prefix_ip_version":np.full(per,4,dtype=np.uint8),
            "prefix_len":np.full(per,22,dtype=np.uint8),"origin_asn":org,
            "as_path":pl.select(pl.when(pl.Series(long)).then(p4).otherwise(p3)).to_series(),
            "next_hop":["0.0.0.0"]*per,"communities":pl.Series([None]*per,dtype=pl.List(pl.Utf8)),
            "med":pl.Series([None]*per,dtype=pl.UInt32),"local_pref":pl.Series([None]*per,dtype=pl.UInt32),"source_file":["bench"]*per})
        df=df.with_columns(pl.col("collector").cast(pl.Categorical),pl.col("as_path").alias("as_path_dedup"),
            pl.col("as_path").list.len().cast(pl.UInt16).alias("as_path_len"),pl.lit(False).alias("has_as_set"),
            pl.col("ts").cast(pl.Datetime("us"))).sort(["prefix","ts"])
        df=df.select(["ts","collector","peer_asn","peer_ip","elem_type","prefix","prefix_ip_version","prefix_len","origin_asn","as_path","as_path_dedup","as_path_len","has_as_set","next_hop","communities","med","local_pref","source_file"])
        d=out/"curated"/"bgp_elements"/f"date={day}"/f"collector={col}"; d.mkdir(parents=True)
        df.write_parquet(d/"part-00000.parquet",compression="zstd",statistics=True,row_group_size=100_000)
print("lignes",per*len(days)*len(collectors),"préfixe chaud",prefixes[HOT],"origine",int(origin[HOT]),"préfixe moyen",prefixes[5000],"durée",round(time.time()-t0),"s")
