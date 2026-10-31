"""Gera data.json compacto para a página.

Uso: python pipeline/export.py <td.csv> <params.json> <saida.json> <dir_anbima>
"""
import json, sys, pathlib
import numpy as np, pandas as pd

src, params_path, out, anbima_dir = sys.argv[1], sys.argv[2], sys.argv[3], pathlib.Path(sys.argv[4])
START = "2007-01-01"

P = json.load(open(params_path))
pre = {r[0]: r[1:] for r in P["pre"]}
ipc = {r[0]: r[1:] for r in P["ipca"]}
dates = sorted(d for d in set(pre) | set(ipc) if d >= START)

def cols(m):
    o = {k: [] for k in ("b1", "b2", "b3", "b4", "tmin", "tmax", "rms")}
    for d in dates:
        r = m.get(d)
        for i, k in enumerate(o):
            o[k].append(None if r is None else r[i])
    return o

d = pd.read_csv(src, sep=";", encoding="latin1", decimal=",")
d.columns = ["tipo", "venc", "data", "tc", "tv", "puc", "puv", "pub"]
d["venc"] = pd.to_datetime(d["venc"], dayfirst=True).dt.strftime("%Y-%m-%d")
d["data"] = pd.to_datetime(d["data"], dayfirst=True).dt.strftime("%Y-%m-%d")
d = d[d.data >= START].drop_duplicates(["tipo", "venc", "data"])
tdates = sorted(d.data.unique())
idx = {x: i for i, x in enumerate(tdates)}
last = tdates[-1]
bonds = []
for (tipo, venc), g in d.groupby(["tipo", "venc"]):
    g = g.sort_values("data")
    i0, i1 = idx[g.data.iloc[0]], idx[g.data.iloc[-1]]
    tv = [None] * (i1 - i0 + 1)
    pv = [None] * (i1 - i0 + 1)
    for x, v, p in zip(g.data, g.tv, g.puv):
        if v and v > 0:
            tv[idx[x] - i0] = round(float(v), 2)
        if p and p > 0:
            pv[idx[x] - i0] = round(float(p), 2)
    lastrow = g.iloc[-1]
    bonds.append({
        "tipo": tipo, "venc": venc, "i0": i0, "tv": tv, "pv": pv,
        "ativo": g.data.iloc[-1] == last,
        "tc": round(float(lastrow.tc), 2) if lastrow.tc and lastrow.tc > 0 and g.data.iloc[-1] == last else None,
        "pu": round(float(lastrow.puc), 2) if lastrow.puc and lastrow.puc > 0 and g.data.iloc[-1] == last else None,
    })

# ETTJ oficial mais recente com data até o último dia ajustado
snaps = sorted(f for f in anbima_dir.glob("*.json") if f.stem <= dates[-1])
anbima = json.loads(snaps[-1].read_text()) if snaps else None
from bizdays import Calendar
hol = [h.isoformat() for h in Calendar.load("ANBIMA").holidays if h.weekday() < 5 and 2006 <= h.year <= 2095]
data = {"holidays": hol, "lambdas": P["lambdas"], "dates": dates, "pre": cols(pre), "ipca": cols(ipc),
        "tdates": tdates, "bonds": bonds, "anbima": anbima, "rate": P["rate"]}
s = json.dumps(data, separators=(",", ":"))
open(out, "w").write(s)
print(len(dates), len(tdates), len(bonds), sum(b["ativo"] for b in bonds), f"{len(s)/1e6:.2f} MB", last)
