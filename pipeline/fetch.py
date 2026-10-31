"""Baixa as fontes do dia.

- Taxas do Tesouro Direto (Tesouro Transparente; se falhar, usa o espelho no GitHub).
  Entre as fontes que responderem, fica a com a data base mais recente.
- ETTJ da ANBIMA do último fechamento (opcional: se falhar, segue sem ela).

Uso: python pipeline/fetch.py <dir_build> <dir_anbima>
"""
import io, json, re, sys, pathlib
import numpy as np
import pandas as pd
import requests

build = pathlib.Path(sys.argv[1]); build.mkdir(parents=True, exist_ok=True)
anbima_dir = pathlib.Path(sys.argv[2]); anbima_dir.mkdir(parents=True, exist_ok=True)

UA = {"User-Agent": "Mozilla/5.0 (curvas-juros-brasil; +https://github.com/agamemnon140/curvas-juros-brasil)"}
TD_URLS = [
    "https://www.tesourotransparente.gov.br/ckan/dataset/df56aa42-484a-4a59-8184-7676580c81e3/resource/796d2059-14e9-44e3-80c9-2d9e30b405c1/download/precotaxatesourodireto.csv",
    "https://raw.githubusercontent.com/ghostnetrn/bot-tesouro-direto/main/PrecoTaxaTesouroDireto.csv",
]
ANBIMA_URL = "https://www.anbima.com.br/informacoes/est-termo/CZ.asp"


def max_date(content: bytes):
    d = pd.read_csv(io.BytesIO(content), sep=";", encoding="latin1", usecols=[2])
    return pd.to_datetime(d.iloc[:, 0], dayfirst=True).max()


def fetch_td():
    best = None
    for u in TD_URLS:
        try:
            r = requests.get(u, timeout=300, headers=UA)
            r.raise_for_status()
            if b"Tipo Titulo" not in r.content[:400] or len(r.content) < 1_000_000:
                raise ValueError("conteúdo inesperado")
            md = max_date(r.content)
            print(f"TD ok: {u} (até {md.date()}, {len(r.content)/1e6:.1f} MB)")
            if best is None or md > best[0]:
                best = (md, r.content, u)
        except Exception as e:  # noqa: BLE001
            print(f"TD falhou: {u}: {e}")
    if best is None:
        sys.exit("Nenhuma fonte do Tesouro Direto respondeu.")
    (build / "td.csv").write_bytes(best[1])
    (build / "td_source.txt").write_text(f"{best[2]}\n{best[0].date()}\n")
    return best[0]


def num(x):
    if isinstance(x, (int, float, np.integer, np.floating)):
        return float(x)
    s = str(x).strip().replace("\xa0", "")
    if not re.fullmatch(r"-?[\d.]+(,\d+)?", s):
        return None
    return float(s.replace(".", "").replace(",", "."))


def rows_of(df):
    head = [" ".join(str(c) for c in (col if isinstance(col, tuple) else (col,))) for col in df.columns]
    return [head] + [[str(v) if not isinstance(v, (int, float)) else v for v in r] for r in df.values.tolist()]


def sv(b, t, l1, l2):
    a1 = (1 - np.exp(-l1 * t)) / (l1 * t); a2 = (1 - np.exp(-l2 * t)) / (l2 * t)
    return b[0] + b[1] * a1 + b[2] * (a1 - np.exp(-l1 * t)) + b[3] * (a2 - np.exp(-l2 * t))


def fetch_anbima():
    r = requests.get(ANBIMA_URL, timeout=60, headers=UA)
    r.raise_for_status()
    html = r.content.decode("latin1", errors="replace")
    tables = pd.read_html(io.StringIO(html), thousands=".", decimal=",")
    params, data_ref, vert = {}, None, None
    for t in tables:
        rows = rows_of(t)
        flat = " ".join(str(c) for row in rows for c in row)
        if "PREFIXADOS" in flat and "IPCA" in flat and not params:
            m = re.search(r"\b(\d{2})/(\d{2})/(\d{4})\b", flat)
            if m:
                data_ref = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
            for row in rows:
                lab = str(row[0]).strip().upper()
                if lab in ("PREFIXADOS", "IPCA"):
                    vals = [num(v) for v in row[1:]]
                    vals = [v for v in vals if v is not None]
                    if len(vals) >= 6:
                        params["PRE" if lab == "PREFIXADOS" else "IPCA"] = vals[:6]
        if re.search(r"V.rtices", flat) and "ETTJ PRE" in flat and vert is None:
            hdr_i = next(i for i, row in enumerate(rows) if any(re.search(r"V.rtices", str(c)) for c in row))
            hdr = [str(c) for c in rows[hdr_i]]
            ci = next(i for i, c in enumerate(hdr) if "ETTJ IPCA" in c)
            cp = next(i for i, c in enumerate(hdr) if "ETTJ PRE" in c)
            cf = next(i for i, c in enumerate(hdr) if re.search(r"Infla", c))
            vert = {"vertices": [], "ipca": [], "pre": [], "impl": []}
            for row in rows[hdr_i + 1:]:
                v, a, b, c = num(row[0]), num(row[ci]), num(row[cp]), num(row[cf])
                if v is None or a is None or b is None or c is None:
                    continue
                vert["vertices"].append(int(round(v))); vert["ipca"].append(a); vert["pre"].append(b); vert["impl"].append(c)
    if not data_ref or len(params) != 2 or not vert or len(vert["vertices"]) < 10:
        raise ValueError(f"layout inesperado (data={data_ref}, params={list(params)}, vértices={len(vert['vertices']) if vert else 0})")
    # checagem: parâmetros reproduzem a tabela
    p = params["PRE"]; i = vert["vertices"].index(1260) if 1260 in vert["vertices"] else 0
    t = vert["vertices"][i] / 252
    if abs(sv(p, t, p[4], p[5]) * 100 - vert["pre"][i]) > 0.05:
        raise ValueError("parâmetros não batem com a tabela de vértices")
    snap = {"data": data_ref, "params": params, **vert}
    (anbima_dir / f"{data_ref}.json").write_text(json.dumps(snap, ensure_ascii=False, indent=1))
    print(f"ANBIMA ok: {data_ref}, {len(vert['vertices'])} vértices")


fetch_td()
try:
    fetch_anbima()
except Exception as e:  # noqa: BLE001
    print(f"ANBIMA indisponível, seguindo sem a ETTJ do dia: {e}")
