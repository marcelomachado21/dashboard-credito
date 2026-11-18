#!/usr/bin/env python3
"""Renegociação de dívidas rurais por instituição (microdados do SICOR) -> data/reneg.json

Fonte: Banco Central, microdados do SICOR (Matriz de Dados do Crédito Rural):
  SICOR_OPERACAO_BASICA_RENEGOCIACAO  operações novas geradas pela renegociação (instituição, UF, programa, emissão, vencimento, valor)
  SICOR_LISTA_RENEGOCIACAO            contratos renegociados: valor, base legal (CD_BASE_LEGAL) e a operação original
  Base_Legal_Renegociacao.csv         tabela de domínio do SICOR com a norma de cada código (CODIGO_BLR;DESCRICAO_BLR), baixada a cada rodada
Código novo entra sozinho no painel com a descrição oficial. Se o código ainda não estiver na tabela do BC, entra com o número e o
período, e a rodada registra um alerta. scripts/bases_legais_reneg.csv só guarda um rótulo curto e uma nota de contexto (opcionais).
Recortes (sistemas, centrais, UFs da sede) vêm da base da safra (safra.json, gerada antes na mesma rodada), pelo CNPJ.
Uso: python3 -I scripts/atualiza_reneg.py <pasta_bruta> <pasta_saida> [--se-mudou]
"""
import json, os, sys, datetime, urllib.request, collections
import pandas as pd

RAW, OUT = sys.argv[1], sys.argv[2]
SE_MUDOU = "--se-mudou" in sys.argv
HOJE = datetime.date.today()
OUTFILE = os.path.join(OUT, "reneg.json")
URL = "https://www.bcb.gov.br/estabilidadefinanceira/micrrural"
BASE = "https://www.bcb.gov.br/htms/sicor/DadosBrutos/"
ARQ = {"op": "SICOR_OPERACAO_BASICA_RENEGOCIACAO.gz", "lista": "SICOR_LISTA_RENEGOCIACAO.gz"}
# rótulo curto e nota de contexto por código (opcionais): scripts/bases_legais_reneg.csv (cod;curto;nota)
import csv, io
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bases_legais_reneg.csv"), encoding="utf-8") as fh:
    APELIDO = {r["cod"]: r for r in csv.DictReader(fh, delimiter=";")}
URL_BL = "https://www.bcb.gov.br/htms/sicor/Base_Legal_Renegociacao.csv"
DESDE = "2023-07-01"      # séries a partir da safra 2023/24 (a 2024/25 já tem com o que comparar)
os.makedirs(RAW, exist_ok=True)
ANT = json.load(open(OUTFILE)) if os.path.exists(OUTFILE) else None


def baixa(nome):
    p = os.path.join(RAW, nome)
    req = urllib.request.Request(BASE + nome, headers={"User-Agent": "dashboard-credito"})
    with urllib.request.urlopen(req, timeout=900) as r, open(p + ".tmp", "wb") as f:
        while True:
            b = r.read(1 << 20)
            if not b: break
            f.write(b)
    if os.path.getsize(p + ".tmp") < 100_000: raise RuntimeError(f"{nome} veio com {os.path.getsize(p + '.tmp')} bytes")
    os.replace(p + ".tmp", p)
    return p


po, pl = baixa(ARQ["op"]), baixa(ARQ["lista"])
# tabela oficial de bases legais; se falhar, mantém as descrições da rodada anterior
try:
    with urllib.request.urlopen(urllib.request.Request(URL_BL, headers={"User-Agent": "dashboard-credito"}), timeout=120) as r:
        txt = r.read().decode("latin1")
    OFICIAL = {x["#CODIGO_BLR"].strip(): " ".join(x["DESCRICAO_BLR"].split()) for x in csv.DictReader(io.StringIO(txt), delimiter=";") if x.get("#CODIGO_BLR")}
    if len(OFICIAL) < 30: raise RuntimeError(f"tabela de bases legais com {len(OFICIAL)} códigos")
    OFICIAL_OK = True
except Exception as e:
    print("aviso: tabela de bases legais indisponível:", e, file=sys.stderr)
    OFICIAL = {b["cod"]: b["oficial"] for b in ((json.load(open(OUTFILE)) if os.path.exists(OUTFILE) else {}).get("bases") or []) if b.get("oficial")}
    OFICIAL_OK = False
o = pd.read_csv(po, sep=";", dtype=str, encoding="latin1",
                usecols=["#REF_BACEN", "NU_ORDEM", "CNPJ_IF", "DT_EMISSAO", "DT_VENCIMENTO", "CD_ESTADO", "CD_PROGRAMA", "VL_PARC_CREDITO"])
l = pd.read_csv(pl, sep=";", dtype=str, encoding="latin1")
o = o.rename(columns={"#REF_BACEN": "REF"}); l = l.rename(columns={"#REF_BACEN": "REF"})
for c in ("DT_EMISSAO", "DT_VENCIMENTO"): o[c] = pd.to_datetime(o[c], format="%d/%m/%Y", errors="coerce")
o["VL"] = pd.to_numeric(o.VL_PARC_CREDITO, errors="coerce").fillna(0)
l["VR"] = pd.to_numeric(l.VL_RENEG, errors="coerce").fillna(0)
o = o[o.DT_EMISSAO.notna() & (o.DT_EMISSAO <= pd.Timestamp(HOJE))]
REF = o.DT_EMISSAO.max().date().isoformat()
if SE_MUDOU and ANT and ANT["meta"]["ref"] == REF:
    print(json.dumps({"reneg": "sem mudança", "ref": REF})); sys.exit(0)

# base legal da operação nova (a da primeira linha da lista; uma operação nova raramente junta bases diferentes)
bl = l.groupby(["REF", "NU_ORDEM"]).CD_BASE_LEGAL.agg(lambda s: s.dropna().iloc[0] if s.notna().any() else "sem código").rename("BL")
nori = l.groupby(["REF", "NU_ORDEM"]).size().rename("NORIG")
o = o.join(bl, on=["REF", "NU_ORDEM"]).join(nori, on=["REF", "NU_ORDEM"])
o["BL"] = o.BL.fillna("sem código"); o["NORIG"] = o.NORIG.fillna(0)
o["PRAZO"] = (o.DT_VENCIMENTO - o.DT_EMISSAO).dt.days / 365.25
o["PROG"] = o.CD_PROGRAMA.map(lambda p: 0 if p == "0001" else 1 if p == "0050" else 2)
o["MES"] = o.DT_EMISSAO.dt.strftime("%Y-%m")

# origem da dívida renegociada (pela lista): renegociação anterior registrada no SICOR, outra operação do SICOR, ou sem refBacen
reneg_bl = o.set_index("REF").BL.to_dict()
l = l.join(bl, on=["REF", "NU_ORDEM"])
l["ORIG"] = [("rn:" + reneg_bl[r]) if isinstance(r, str) and r in reneg_bl else "op" if isinstance(r, str) and r.strip() else "sem"
             for r in l.REF_BACEN_ORIGINAL]
l = l.merge(o[["REF", "NU_ORDEM", "CNPJ_IF", "DT_EMISSAO"]], on=["REF", "NU_ORDEM"], how="inner")

# recortes por CNPJ: os mesmos da safra
SAF = json.load(open(os.path.join(OUT, "safra.json")))
ESC = {i["cnpj"]: ["sfn"] + i.get("escopos", []) for i in SAF["inst"]}
NOME = {i["cnpj"]: {k: i[k] for k in ("nome", "curto", "numero", "tipo", "sistema", "uf") if i.get(k)} for i in SAF["inst"]}
ids_ok = {e["id"] for e in SAF["escopos"]} | {"top5"}
esc_de = lambda c: [e for e in ESC.get(c, ["sfn"]) if e in ids_ok]

o = o[o.DT_EMISSAO >= DESDE]; l = l[l.DT_EMISSAO >= DESDE]
# bases legais relevantes no período: as que somam ao menos R$ 100 mi
tb = o.groupby("BL").agg(v=("VL", "sum"), n=("VL", "size"), ini=("MES", "min"), fim=("MES", "max")).sort_values("v", ascending=False)
BASES = [b for b, r in tb.iterrows() if r.v >= 1e8]
o["BLG"] = o.BL.where(o.BL.isin(BASES), "outras")
l["BLG"] = l.BL.where(l.BL.isin(BASES), "outras")
GRUPOS = BASES + (["outras"] if (o.BLG == "outras").any() else [])
r2 = lambda v: round(float(v) / 1e6, 2)            # R$ milhões

# safra (jul–jun, rotulada pelo ano em que termina) e trimestre da safra: t1 jul–set, t2 out–dez, t3 jan–mar, t4 abr–jun
o["Q"] = [f"{y + (m >= 7)}t{(m - 7) % 12 // 3 + 1}" for y, m in zip(o.DT_EMISSAO.dt.year, o.DT_EMISSAO.dt.month)]
l = l.merge(o[["REF", "NU_ORDEM", "Q"]], on=["REF", "NU_ORDEM"], how="left")
o["PZV"] = o.PRAZO.fillna(0) * o.VL

# por instituição e mês (valor, operações, contratos originais, prazo×valor); trimestre para UF, programa e origem
gm = o.groupby(["CNPJ_IF", "BLG", "MES"]).agg(v=("VL", "sum"), n=("VL", "size"), c=("NORIG", "sum"), p=("PZV", "sum")).reset_index()
gu = o.groupby(["CNPJ_IF", "BLG", "Q", "CD_ESTADO"]).VL.sum().reset_index()
gp = o.groupby(["CNPJ_IF", "BLG", "Q", "PROG"]).VL.sum().reset_index()
go = l.groupby(["CNPJ_IF", "BLG", "Q", "ORIG"]).VR.sum().reset_index()

dd = lambda f: collections.defaultdict(f)
MES = dd(lambda: dd(lambda: dd(lambda: [0.0, 0, 0, 0.0])))          # esc -> bl -> mês -> [valor, ops, contratos, prazo×valor]
UF, PG, OR = (dd(lambda: dd(lambda: dd(lambda: dd(float)))) for _ in range(3))   # esc -> bl -> trimestre -> chave -> valor
for r in gm.itertuples():
    for e in esc_de(r.CNPJ_IF):
        for b in (r.BLG, "todas"): x = MES[e][b][r.MES]; x[0] += r.v; x[1] += r.n; x[2] += r.c; x[3] += r.p
for r in gu.itertuples():
    for e in esc_de(r.CNPJ_IF):
        for b in (r.BLG, "todas"): UF[e][b][r.Q][r.CD_ESTADO] += r.VL
for r in gp.itertuples():
    for e in esc_de(r.CNPJ_IF):
        for b in (r.BLG, "todas"): PG[e][b][r.Q][int(r.PROG)] += r.VL
for r in go.itertuples():
    for e in esc_de(r.CNPJ_IF):
        for b in (r.BLG, "todas"): OR[e][b][r.Q][r.ORIG] += r.VR

serie = {}
for e, bs in MES.items():
    serie[e] = {}
    for b, ms in bs.items():
        qs = sorted(set(UF[e][b]) | set(PG[e][b]) | set(OR[e][b]))
        serie[e][b] = {"mes": [[m, r2(x[0]), int(x[1]), int(x[2]), r2(x[3])] for m, x in sorted(ms.items())],
                       "q": {q: {"uf": {u: r2(v) for u, v in sorted(UF[e][b][q].items(), key=lambda z: -z[1]) if v >= 5e4},
                                 "prog": [r2(PG[e][b][q].get(i, 0)) for i in range(3)],
                                 "origem": {k: r2(v) for k, v in sorted(OR[e][b][q].items(), key=lambda z: -z[1]) if v >= 5e4}} for q in qs}}
inst = []
for c, g in gm.groupby("CNPJ_IF"):
    tv = g.v.sum() / 1e6
    if tv < 0.5: continue                                           # menos de R$ 500 mil no período todo
    d = {b: [[r.MES, r2(r.v), int(r.n), r2(r.p)] for r in gb.sort_values("MES").itertuples()] for b, gb in g.groupby("BLG")}
    inst.append({"cnpj": c, **NOME.get(c, {"nome": c}), "escopos": [e for e in esc_de(c) if e != "sfn"], "bl": d, "v": round(tv, 2)})
inst.sort(key=lambda x: -x["v"])

def base(b):
    a = APELIDO.get(b) or {}
    return {"cod": b, "oficial": OFICIAL.get(b), "curto": a.get("curto") or None, "nota": a.get("nota") or None,
            "ini": tb.loc[b, "ini"], "fim": tb.loc[b, "fim"], "v": r2(tb.loc[b, "v"]), "ops": int(tb.loc[b, "n"])}
bases = [base(b) for b in BASES]
outras = [base(b) for b in tb.index if b not in BASES]          # códigos abaixo de R$ 100 mi, somados em "outras"
sem = [b for b in bases + outras if not b["oficial"] and b["cod"] != "sem código"]
ALERTA = ("Base legal de renegociação sem descrição na tabela do BC: " + ", ".join(f"{b['cod']} (desde {b['ini']})" for b in sem)) if sem else ""
if not OFICIAL_OK: ALERTA = ("Tabela de bases legais do BC indisponível nesta rodada; descrições mantidas da anterior. " + ALERTA).strip()
novo_desde = (ANT or {}).get("meta", {}).get("novo_desde") if (ANT or {}).get("meta", {}).get("ref") == REF else HOJE.isoformat()
out = {"meta": {"ref": REF, "desde": DESDE, "atualizado": HOJE.isoformat(), "novo_desde": novo_desde, "unidade": "R$ milhões",
                "fonte": "Banco Central — microdados do SICOR: operações de renegociação e lista de renegociações", "url": URL,
                "alerta": ALERTA, "sem_instituicao_pct": round(o[~o.CNPJ_IF.isin(ESC)].VL.sum() / o.VL.sum() * 100, 2) if o.VL.sum() else None},
       "bases": bases, "outras": outras, "url_bases": URL_BL, "escopos": SAF["escopos"], "serie": serie, "inst": inst}
tmp = OUTFILE + ".tmp"
json.dump(out, open(tmp, "w"), ensure_ascii=False, separators=(",", ":"))
os.replace(tmp, OUTFILE)
print(json.dumps({"reneg": REF, "bases": [b["cod"] for b in bases], "instituicoes": len(inst), "kb": os.path.getsize(OUTFILE) // 1024}, ensure_ascii=False))
