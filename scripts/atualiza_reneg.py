#!/usr/bin/env python3
"""Renegociação de dívidas rurais por instituição (microdados do SICOR) -> data/reneg.json

Fonte: Banco Central, microdados do SICOR (Matriz de Dados do Crédito Rural):
  SICOR_OPERACAO_BASICA_RENEGOCIACAO  operações novas geradas pela renegociação (instituição, UF, programa, emissão, vencimento, valor)
  SICOR_LISTA_RENEGOCIACAO            contratos renegociados: valor, base legal (CD_BASE_LEGAL) e a operação original
A tabela que dá o nome de cada base legal (BaseLegalRenegociacao) não está disponível para download; o painel mostra o código e
o período em que ele aparece. Nome de norma só entra quando houver a tabela oficial (NOME_BASE abaixo, vazio por padrão).
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
# nomes das bases legais: scripts/bases_legais_reneg.csv (cod;norma;confirmado;nota). Código novo entra sozinho no painel,
# com o número e o período; até ganhar nome no arquivo, a rodada registra um alerta que aparece na tela.
import csv
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bases_legais_reneg.csv"), encoding="utf-8") as fh:
    NOME_BASE = {r["cod"]: r for r in csv.DictReader(fh, delimiter=";")}
DESDE = "2024-07-01"      # séries a partir da safra 2024/25
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

# agregação por instituição primeiro (rápida) e depois por recorte
gi = o.groupby(["CNPJ_IF", "BLG"]).agg(v=("VL", "sum"), n=("VL", "size"), norig=("NORIG", "sum"), pz=("PRAZO", lambda s: 0)).reset_index()
pzv = o.assign(pzv=o.PRAZO * o.VL).groupby(["CNPJ_IF", "BLG"]).pzv.sum()
gm = o.groupby(["CNPJ_IF", "BLG", "MES"]).agg(v=("VL", "sum"), n=("VL", "size")).reset_index()
gu = o.groupby(["CNPJ_IF", "BLG", "CD_ESTADO"]).VL.sum().reset_index()
gp = o.groupby(["CNPJ_IF", "BLG", "PROG"]).VL.sum().reset_index()
go = l.groupby(["CNPJ_IF", "BLG", "ORIG"]).VR.sum().reset_index()

ac = lambda: collections.defaultdict(lambda: collections.defaultdict(float))
TOT = collections.defaultdict(lambda: collections.defaultdict(lambda: [0.0, 0, 0, 0.0]))     # esc -> bl -> [valor, ops, contratos, prazo×valor]
MES = collections.defaultdict(lambda: collections.defaultdict(lambda: collections.defaultdict(lambda: [0.0, 0])))
UF, PG, OR = collections.defaultdict(ac), collections.defaultdict(ac), collections.defaultdict(ac)
for r in gi.itertuples():
    for e in esc_de(r.CNPJ_IF):
        for b in (r.BLG, "todas"):
            t = TOT[e][b]; t[0] += r.v; t[1] += r.n; t[2] += r.norig; t[3] += pzv[(r.CNPJ_IF, r.BLG)]
for r in gm.itertuples():
    for e in esc_de(r.CNPJ_IF):
        for b in (r.BLG, "todas"): x = MES[e][b][r.MES]; x[0] += r.v; x[1] += r.n
for r in gu.itertuples():
    for e in esc_de(r.CNPJ_IF):
        for b in (r.BLG, "todas"): UF[e][b][r.CD_ESTADO] += r.VL
for r in gp.itertuples():
    for e in esc_de(r.CNPJ_IF):
        for b in (r.BLG, "todas"): PG[e][b][int(r.PROG)] += r.VL
for r in go.itertuples():
    for e in esc_de(r.CNPJ_IF):
        for b in (r.BLG, "todas"): OR[e][b][r.ORIG] += r.VR

serie = {}
for e, bs in TOT.items():
    serie[e] = {}
    for b, t in bs.items():
        serie[e][b] = {"v": r2(t[0]), "ops": int(t[1]), "contratos": int(t[2]), "prazo": round(t[3] / t[0], 2) if t[0] else None,
                       "mes": [[m, r2(x[0]), x[1]] for m, x in sorted(MES[e][b].items())],
                       "uf": {u: r2(v) for u, v in sorted(UF[e][b].items(), key=lambda z: -z[1]) if v >= 5e4},
                       "prog": [r2(PG[e][b].get(i, 0)) for i in range(3)],
                       "origem": {k: r2(v) for k, v in sorted(OR[e][b].items(), key=lambda z: -z[1]) if v >= 5e4}}
inst = []
for c, g in gi.groupby("CNPJ_IF"):
    d = {b: [r2(r.v), int(r.n), round(pzv[(c, b)] / r.v, 2) if r.v else None] for r in g.itertuples() for b in [r.BLG]}
    tv = sum(x[0] for x in d.values())
    if tv < 0.5: continue                                           # menos de R$ 500 mil no período
    inst.append({"cnpj": c, **NOME.get(c, {"nome": c}), "escopos": [e for e in esc_de(c) if e != "sfn"], "bl": d, "v": round(tv, 2)})
inst.sort(key=lambda x: -x["v"])

bases = [{"cod": b, "nome": (NOME_BASE.get(b) or {}).get("norma") or None, "confirmado": (NOME_BASE.get(b) or {}).get("confirmado") == "sim",
          "nota": (NOME_BASE.get(b) or {}).get("nota") or None, "ini": tb.loc[b, "ini"], "fim": tb.loc[b, "fim"], "v": r2(tb.loc[b, "v"]), "ops": int(tb.loc[b, "n"])} for b in BASES]
lim_novo = (pd.Timestamp(REF) - pd.DateOffset(months=6)).strftime("%Y-%m")
novos = [b for b in bases if not b["nome"] and b["ini"] >= lim_novo]
ALERTA = ("Nova base legal de renegociação sem nome no painel: " + ", ".join(f"{b['cod']} (desde {b['ini']}, R$ {b['v']:,.0f} mi)".replace(",", ".") for b in novos)) if novos else ""
novo_desde = (ANT or {}).get("meta", {}).get("novo_desde") if (ANT or {}).get("meta", {}).get("ref") == REF else HOJE.isoformat()
out = {"meta": {"ref": REF, "desde": DESDE, "atualizado": HOJE.isoformat(), "novo_desde": novo_desde, "unidade": "R$ milhões",
                "fonte": "Banco Central — microdados do SICOR: operações de renegociação e lista de renegociações", "url": URL,
                "alerta": ALERTA, "sem_instituicao_pct": round(o[~o.CNPJ_IF.isin(ESC)].VL.sum() / o.VL.sum() * 100, 2) if o.VL.sum() else None},
       "bases": bases, "escopos": SAF["escopos"], "serie": serie, "inst": inst}
tmp = OUTFILE + ".tmp"
json.dump(out, open(tmp, "w"), ensure_ascii=False, separators=(",", ":"))
os.replace(tmp, OUTFILE)
print(json.dumps({"reneg": REF, "bases": [b["cod"] for b in bases], "instituicoes": len(inst), "kb": os.path.getsize(OUTFILE) // 1024}, ensure_ascii=False))
