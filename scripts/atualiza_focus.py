#!/usr/bin/env python3
"""Expectativas de mercado (Focus, Banco Central) e indicadores realizados (SGS) -> data/focus.json.

- Expectativas anuais (mediana, base de cálculo 0 = todas as respostas) de IPCA, PIB Total, Câmbio e Selic,
  para o ano corrente e os dois seguintes, na última data de cada semana, nos últimos 400 dias.
- Realizado (SGS): meta Selic (432), IPCA acumulado em 12 meses (13522), taxa de desocupação PNAD (24369),
  câmbio, média mensal de venda (3698).
Uso: python3 -I scripts/atualiza_focus.py <pasta_bruta> <pasta_saida> [--se-mudou]
"""
import json, os, sys, time, datetime, urllib.request, urllib.parse
RAW, OUT = sys.argv[1], sys.argv[2]
SE_MUDOU = "--se-mudou" in sys.argv
HOJE = datetime.date.today()
OUTFILE = os.path.join(OUT, "focus.json")
ANT = json.load(open(OUTFILE)) if os.path.exists(OUTFILE) else None
H = {"User-Agent": "dashboard-credito"}
BASE = "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/"


def get(url, tries=6):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=180) as r:
                return json.loads(r.read())
        except Exception:
            if i == tries - 1: raise
            time.sleep(15 * (i + 1))


IND = {"IPCA": "ipca", "PIB Total": "pib", "Câmbio": "cambio", "Selic": "selic"}
ANOS = [str(HOJE.year + k) for k in range(3)]
ini = (HOJE - datetime.timedelta(days=400)).isoformat()
exp, atual, ref = {}, {}, None
for nome, k in IND.items():
    f = f"Indicador eq '{nome}' and baseCalculo eq 0 and Data ge '{ini}'"
    v = get(BASE + "ExpectativasMercadoAnuais?$format=json&$top=5000&$orderby=Data%20asc&$select=Data,DataReferencia,Mediana,Minimo,Maximo,numeroRespondentes&$filter=" + urllib.parse.quote(f))["value"]
    if not v: raise RuntimeError(f"Focus sem dado para {nome}")
    exp[k], atual[k] = {}, {}
    for a in ANOS:
        pts = [x for x in v if x["DataReferencia"] == a]
        sem = {}
        for x in pts:                                       # última divulgação de cada semana
            d = datetime.date.fromisoformat(x["Data"]); sem[d.isocalendar()[:2]] = x
        s = [{"d": x["Data"], "v": round(x["Mediana"], 4)} for x in sorted(sem.values(), key=lambda x: x["Data"])]
        exp[k][a] = s
        if pts:
            u = pts[-1]; ref = max(ref or u["Data"], u["Data"])
            d4 = (datetime.date.fromisoformat(u["Data"]) - datetime.timedelta(days=28)).isoformat()
            p4 = [x for x in pts if x["Data"] <= d4]
            atual[k][a] = {"d": u["Data"], "v": round(u["Mediana"], 4), "min": u["Minimo"], "max": u["Maximo"], "n": u["numeroRespondentes"],
                           "v4s": round(p4[-1]["Mediana"], 4) if p4 else None}
if SE_MUDOU and ANT and ANT["meta"].get("ref") == ref:
    print(json.dumps({"focus": "sem mudança", "ref": ref})); sys.exit(0)

REAL = {"selic": ("432", "Meta Selic (% a.a.)"), "ipca12": ("13522", "IPCA acumulado em 12 meses (%)"),
        "desemp": ("24369", "Taxa de desocupação, PNAD Contínua (%)"), "cambio": ("3698", "Câmbio, média mensal de venda (R$/US$)")}
real = {}
ini_s = (HOJE - datetime.timedelta(days=365 * 3)).strftime("%d/%m/%Y")
for k, (cod, tit) in REAL.items():
    d = get(f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{cod}/dados?formato=json&dataInicial={ini_s}&dataFinal=31/12/2099")
    pts = {}
    for x in d:                                             # fim de mês (a Selic é diária)
        pts[f"{x['data'][6:10]}-{x['data'][3:5]}"] = float(x["valor"])
    real[k] = {"tit": tit, "cod": cod, "url": f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{cod}/dados?formato=json",
               "p": [{"d": a, "v": round(b, 4)} for a, b in sorted(pts.items())][-36:]}

novo_desde = (ANT or {}).get("meta", {}).get("novo_desde") if (ANT or {}).get("meta", {}).get("ref") == ref else HOJE.isoformat()
out = {"meta": {"ref": ref, "anos": ANOS, "atualizado": HOJE.isoformat(), "novo_desde": novo_desde,
                "fonte": "Banco Central — Sistema de Expectativas de Mercado (Focus), medianas anuais; SGS para o realizado",
                "url": "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/aplicacao#!/recursos/ExpectativasMercadoAnuais"},
       "exp": exp, "atual": atual, "real": real}
tmp = OUTFILE + ".tmp"
json.dump(out, open(tmp, "w"), ensure_ascii=False, separators=(",", ":"))
os.replace(tmp, OUTFILE)
print(json.dumps({"focus": ref, "kb": os.path.getsize(OUTFILE) // 1024}, ensure_ascii=False))
