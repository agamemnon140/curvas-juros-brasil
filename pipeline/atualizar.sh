#!/usr/bin/env bash
# Baixa as fontes, ajusta as curvas e regera index.html.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p build
python pipeline/fetch.py build data/anbima
python pipeline/fit.py build/td.csv build venda
python pipeline/export.py build/td.csv build/params_venda.json build/data.json data/anbima
python pipeline/build.py src/template.html build/data.json index.html
echo "Dados até: $(sed -n 2p build/td_source.txt) (fonte: $(sed -n 1p build/td_source.txt))"
