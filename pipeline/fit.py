"""Ajusta curvas Svensson (PRE e IPCA) por dia a partir do histórico do Tesouro Direto.

Uso: python3 -I fit.py <csv_tesouro> <saida_dir> [coluna_taxa]
"""
import sys, json, math
import numpy as np, pandas as pd
from scipy.optimize import least_squares
from bizdays import Calendar

src, out = sys.argv[1], sys.argv[2]
RATE = sys.argv[3] if len(sys.argv) > 3 else "venda"

cal = Calendar.load("ANBIMA")
BD = np.array(list(cal.seq("2000-01-01", "2080-12-31")), dtype="datetime64[D]")
def du(d0, d1):
    """dias úteis entre d0 (inclusive) e d1 (exclusive), vetorizado"""
    return np.searchsorted(BD, d1) - np.searchsorted(BD, d0)

d = pd.read_csv(src, sep=";", encoding="latin1", decimal=",")
d.columns = ["tipo", "venc", "data", "tc", "tv", "puc", "puv", "pub"]
d["venc"] = pd.to_datetime(d["venc"], dayfirst=True)
d["data"] = pd.to_datetime(d["data"], dayfirst=True)
d = d.drop_duplicates(["tipo", "venc", "data"]).sort_values(["data", "tipo", "venc"])

TIPOS = {
    "Tesouro Prefixado": ("PRE", "LTN"),
    "Tesouro Prefixado com Juros Semestrais": ("PRE", "NTN-F"),
    "Tesouro IPCA+": ("IPCA", "NTN-B P"),
    "Tesouro IPCA+ com Juros Semestrais": ("IPCA", "NTN-B"),
}
d = d[d.tipo.isin(TIPOS)].copy()
d["curva"] = d.tipo.map(lambda t: TIPOS[t][0])
d["sigla"] = d.tipo.map(lambda t: TIPOS[t][1])
if RATE == "venda":
    d["y"] = d.tv
elif RATE == "compra":
    d["y"] = d.tc.where(d.tc > 0)
else:  # média quando houver as duas
    d["y"] = np.where(d.tc > 0, (d.tc + d.tv) / 2, d.tv)
d = d[d.y > 0]
# taxas obviamente inválidas na fonte (ex.: NTN-F 2021 a 0,06% em 2010)
d = d[~((d.curva == "PRE") & (d.y < 1.5))]

def flows(sigla, venc):
    """datas dos fluxos e valores (por 1 de face/VNA)"""
    if sigla in ("LTN", "NTN-B P"):
        return [venc], [1.0]
    cup = (1.10 ** 0.5 - 1) if sigla == "NTN-F" else (1.06 ** 0.5 - 1)
    dates = []
    x = venc
    while x.year >= 2000:
        dates.append(x)
        x = x - pd.DateOffset(months=6)
    dates = dates[::-1]
    vals = [cup] * len(dates)
    vals[-1] += 1.0
    return dates, vals

FL = {}
for (s, v) in d[["sigla", "venc"]].drop_duplicates().itertuples(index=False):
    ds, vs = flows(s, v)
    FL[(s, v)] = (np.array(ds, dtype="datetime64[D]"), np.array(vs))

LAMBDA = {"PRE": (1.2688, 0.3619), "IPCA": (1.4443, 0.2648)}  # lambdas fixos (ANBIMA 30/10/2026)

def sv(b, t, l1, l2):
    t = np.maximum(t, 1e-6)
    a1 = (1 - np.exp(-l1 * t)) / (l1 * t)
    a2 = (1 - np.exp(-l2 * t)) / (l2 * t)
    return b[0] + b[1] * a1 + b[2] * (a1 - np.exp(-l1 * t)) + b[3] * (a2 - np.exp(-l2 * t))

def prep(rows, day):
    bonds = []
    day64 = np.datetime64(day.date())
    for r in rows.itertuples(index=False):
        ds, vs = FL[(r.sigla, r.venc)]
        m = ds > day64
        if not m.any():
            continue
        t = du(np.full(m.sum(), day64), ds[m]) / 252.0
        if t[-1] <= 0.02:
            continue
        v = vs[m]
        y = r.y / 100
        disc = (1 + y) ** (-t)
        p = (v * disc).sum()
        dur = (v * disc * t).sum() / p
        bonds.append((t, v, p, dur, r.sigla, r.venc, r.y, t[-1]))
    return bonds

def fit(bonds, l1, l2, b0, prior_w):
    def res(b):
        out = []
        for (t, v, p, dur, *_ ) in bonds:
            z = sv(b, t, l1, l2)
            pm = (v * (1 + z) ** (-t)).sum()
            out.append((pm - p) / (p * dur) * 1e4)  # ~ erro em bps
        if prior_w > 0 and b0 is not None:
            out.extend(prior_w * (b - b0) * 1e4)
        return np.array(out)
    start = b0 if b0 is not None else np.array([0.12, -0.01, 0.0, 0.0])
    r = least_squares(res, start, method="lm" if len(bonds) + (4 if prior_w > 0 and b0 is not None else 0) >= 4 else "trf")
    return r.x, res(r.x)[: len(bonds)]

params = {"PRE": [], "IPCA": []}
bondrows = []
prev = {"PRE": None, "IPCA": None}
dates = sorted(d.data.unique())
for i, day in enumerate(dates):
    day = pd.Timestamp(day)
    sub = d[d.data == day]
    for c in ("PRE", "IPCA"):
        rows = sub[sub.curva == c]
        bonds = prep(rows, day)
        if len(bonds) < 2:
            continue
        l1, l2 = LAMBDA[c]
        # poucos títulos -> ancora mais forte no dia anterior
        w = 0.02 if len(bonds) >= 6 else 0.2
        if prev[c] is None:
            w = 0.0 if len(bonds) >= 4 else 0.05
            b0 = np.array([0.12 if c == "PRE" else 0.07, -0.01, 0.0, 0.0])
            bx, err = fit(bonds, l1, l2, b0, w)
        else:
            b0 = prev[c]
            bx, err = fit(bonds, l1, l2, b0, w)
        # uma passada robusta: remove títulos com erro > 40 bps e reajusta
        bad = np.abs(err) > 40
        if bad.any() and (~bad).sum() >= 2:
            bonds = [b for b, k in zip(bonds, bad) if not k]
            bx, err = fit(bonds, l1, l2, b0, max(w, 0.02))
        prev[c] = bx
        tmin = min(b[7] for b in bonds)
        tmax = max(b[7] for b in bonds)
        params[c].append([day.strftime("%Y-%m-%d"), *[round(float(x), 6) for x in bx], round(tmin, 3), round(tmax, 3), round(float(np.sqrt(np.mean(err ** 2))), 2)])
        for b, e in zip(bonds, err):
            bondrows.append([day.strftime("%Y-%m-%d"), b[4], b[5].strftime("%Y-%m-%d"), b[6], round(b[7], 3), round(float(e), 1)])
    if i % 500 == 0:
        print(day.date(), len(params["PRE"]), len(params["IPCA"]), flush=True)

json.dump({"lambdas": LAMBDA, "pre": params["PRE"], "ipca": params["IPCA"], "rate": RATE}, open(f"{out}/params_{RATE}.json", "w"))
pd.DataFrame(bondrows, columns=["data", "sigla", "venc", "taxa", "prazo", "erro_bps"]).to_csv(f"{out}/bonds_{RATE}.csv", index=False)
print("ok", len(params["PRE"]), len(params["IPCA"]))
