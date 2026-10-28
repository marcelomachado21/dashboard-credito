# Dashboard de Crédito — SFN, SNCC e Agro

Painel público de crédito com dados do Banco Central: SFN, bancos, bancos digitais, cooperativas (Sicoob, Sicredi, Cresol, Unicred), Minas Gerais e crédito rural (SICOR).

**Painel:** https://marcelomachado21.github.io/dashboard-credito/

## Como funciona

- `site/` — o painel (`index.html`) e os dados (`data/*.json`). Publicado pelo GitHub Pages.
- `scripts/` — cinco scripts Python que baixam e processam as bases públicas do Banco Central (SICOR, SCR.data, SGS, balancetes Cosif, IF.data), a tabela de-para das cooperativas e a tabela de incorporações.
- `scripts/atualiza_tudo.py` — orquestrador: roda os scripts numa pasta temporária, valida cada arquivo e só substitui o que passou. Grava `site/data/status.json`.
- `.github/workflows/atualiza.yml` — rotina toda segunda-feira às 4h22 (Brasília). Também pode ser disparada à mão em Actions → "Atualizar dados do Banco Central" → Run workflow.

Só dados públicos. Nenhum dado interno de cooperativas ou centrais.
