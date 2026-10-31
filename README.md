# Curvas de juros Brasil

Curva prefixada, curva real (IPCA+) e inflação implícita dos títulos públicos federais, ajustadas dia a dia desde 2007 com o modelo Svensson sobre as taxas do Tesouro Direto.

- Curvas por data, comparando várias datas, por prazo ou por vencimento, com extrapolação opcional
- Histórico por vértice (prefixada, real, implícita e inclinações)
- Tabela dos títulos com taxa ou preço (PU) e histórico de cada um
- Validação contra a ETTJ oficial da ANBIMA

Página: https://agamemnon140.github.io/curvas-juros-brasil/

## Atualização automática

O workflow `Atualizar dados` (`.github/workflows/atualizar.yml`) roda de terça a sábado às 07:17 (Brasília), baixa o fechamento do dia útil anterior, refaz o ajuste e faz commit de `index.html` só quando há dado novo. Também pode ser disparado à mão na aba Actions.

## Pipeline

```
pipeline/atualizar.sh        # roda tudo
  fetch.py   -> build/td.csv, data/anbima/AAAA-MM-DD.json
  fit.py     -> build/params_venda.json   (Svensson diário, PRE e IPCA)
  export.py  -> build/data.json           (dados compactos da página)
  build.py   -> index.html                (src/template.html + dados)
```

Para rodar localmente: `pip install -r requirements.txt && bash pipeline/atualizar.sh` (cerca de 1,5 min).

- **Taxas:** Tesouro Transparente, "Taxas dos Títulos Ofertados pelo Tesouro Direto" (taxa de venda da manhã). Se o site do Tesouro não responder, usa a cópia em `ghostnetrn/bot-tesouro-direto`; entre as duas, fica a mais recente.
- **Modelo:** para cada dia, ajuste por preço dos títulos prefixados (LTN, NTN-F) e IPCA+ (NTN-B Principal, NTN-B), fluxo a fluxo em dias úteis/252 pelo calendário ANBIMA. Lambdas fixos nos valores da ANBIMA (`LAMBDA` em `fit.py`), título com erro acima de 40 bps descartado.
- **Referência:** a ETTJ oficial da ANBIMA de cada dia é salva em `data/anbima/` (histórico a partir de 30/10/2026) e usada no gráfico e na tabela de validação. Se a ANBIMA estiver fora do ar ou mudar o layout, o pipeline segue sem ela.

Arquivo único (`index.html`) com os dados embutidos; usa Plotly e Google Fonts por CDN.
