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
from bs4 import BeautifulSoup

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
            print(f"::warning title=Tesouro Direto::falhou {u}: {e}")
    if best is None:
        sys.exit("Nenhuma fonte do Tesouro Direto respondeu.")
    (build / "td.csv").write_bytes(best[1])
    (build / "td_source.txt").write_text(f"{best[2]}\n{best[0].date()}\n")
    print(f"::notice title=Tesouro Direto::dados até {best[0].date()} via {best[2]}")
    return best[0]


def num(s):
    """número no formato brasileiro ("1.008", "-0,0090", "14,3249"); None se não for número"""
    s = str(s).strip().replace("\xa0", "").replace(" ", "")
    if not re.fullmatch(r"-?(\d{1,3}(\.\d{3})+|\d+)(,\d+)?", s):
        return None
    return float(s.replace(".", "").replace(",", "."))


def html_tables(content: bytes):
    """cada <table> como lista de linhas de texto, só com as linhas da própria tabela (não das aninhadas)"""
    soup = BeautifulSoup(content, "html.parser")
    out = []
    for tb in soup.find_all("table"):
        rows = []
        for tr in tb.find_all("tr"):
            if tr.find_parent("table") is not tb:
                continue
            rows.append([c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"]) if c.find_parent("tr") is tr])
        if rows:
            out.append(rows)
    return sorted(out, key=lambda r: sum(len(x) for x in r))


def flat_of(rows):
    return " ".join(str(c) for row in rows for c in row)


def sv(b, t, l1, l2):
    a1 = (1 - np.exp(-l1 * t)) / (l1 * t); a2 = (1 - np.exp(-l2 * t)) / (l2 * t)
    return b[0] + b[1] * a1 + b[2] * (a1 - np.exp(-l1 * t)) + b[3] * (a2 - np.exp(-l2 * t))


def fetch_anbima():
    r = requests.get(ANBIMA_URL, timeout=60, headers=UA)
    r.raise_for_status()
    tabs = html_tables(r.content)
    global DESC
    DESC = " | ".join(f"{len(x)} linhas: {flat_of(x[:2])[:70]}" for x in tabs)[:700]
    params, data_ref, vert = {}, None, None
    # a página aninha tabelas em tabelas de layout: usa a menor que contém cada bloco
    for rows in tabs:
        if "Beta 1" not in flat_of(rows):
            continue
        found = {}
        for row in rows:
            lab = str(row[0]).strip().upper()
            if lab in ("PREFIXADOS", "IPCA"):
                vals = [v for v in (num(x) for x in row[1:]) if v is not None]
                if len(vals) >= 6:
                    found["PRE" if lab == "PREFIXADOS" else "IPCA"] = vals[:6]
        if len(found) == 2:
            params = found
            m = re.search(r"\b(\d{2})/(\d{2})/(\d{4})\b", flat_of(rows))
            if m:
                data_ref = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
            break
    for rows in tabs:
        hdr_i = next((i for i, row in enumerate(rows) if any(re.fullmatch(r"\s*V.rtices\s*", str(c)) for c in row)), None)
        if hdr_i is None:
            continue
        hdr = [str(c).strip() for c in rows[hdr_i]]
        if len(hdr) < 4:
            continue
        try:
            cv = next(i for i, c in enumerate(hdr) if re.fullmatch(r"V.rtices", c))
            ci = next(i for i, c in enumerate(hdr) if c == "ETTJ IPCA")
            cp = next(i for i, c in enumerate(hdr) if c == "ETTJ PRE")
            cf = next(i for i, c in enumerate(hdr) if re.fullmatch(r"Infla..o Impl.cita", c))
        except StopIteration:
            continue
        cand = {"vertices": [], "ipca": [], "pre": [], "impl": []}
        for row in rows[hdr_i + 1:]:
            if len(row) <= max(cv, ci, cp, cf):
                continue
            v, a_, b_, c_ = (num(row[k]) for k in (cv, ci, cp, cf))
            if None in (v, a_, b_, c_):
                continue
            cand["vertices"].append(int(round(v))); cand["ipca"].append(a_); cand["pre"].append(b_); cand["impl"].append(c_)
        if len(cand["vertices"]) >= 10:
            vert = cand
            break
    if not data_ref or len(params) != 2 or not vert or len(vert["vertices"]) < 10:
        raise ValueError(f"layout inesperado (data={data_ref}, params={list(params)}, vértices={len(vert['vertices']) if vert else 0})")
    # checagem: parâmetros reproduzem a tabela
    p = params["PRE"]; i = vert["vertices"].index(1260) if 1260 in vert["vertices"] else 0
    t = vert["vertices"][i] / 252
    if abs(sv(p, t, p[4], p[5]) * 100 - vert["pre"][i]) > 0.05:
        raise ValueError("parâmetros não batem com a tabela de vértices")
    snap = {"data": data_ref, "params": params, **vert}
    (anbima_dir / f"{data_ref}.json").write_text(json.dumps(snap, ensure_ascii=False, indent=1))
    print(f"::notice title=ANBIMA::ETTJ de {data_ref} lida ({len(vert['vertices'])} vértices)")


DESC = "(não lidas)"
fetch_td()
try:
    fetch_anbima()
except Exception as e:  # noqa: BLE001
    print(f"::warning title=ANBIMA::ETTJ indisponível, seguindo sem ela: {type(e).__name__}: {e}. Tabelas: {DESC}")
