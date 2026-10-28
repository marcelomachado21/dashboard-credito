"""Aba Resultados do Dashboard de Crédito.

Uso:
  python3 atualiza_resultados.py <pasta_raw> <pasta_saida> [--se-mudou] [--depara=<csv>] [--incorp=<csv>]

Fonte: balancetes Cosif mensais (cooperativas, doc. 4010; conglomerados prudenciais, doc. 4060), a partir de jan/2025.
As contas de resultado são acumuladas no semestre; o script converte em fluxo mensal e soma 12 meses.

Blocos (contas Cosif):
  Receita de crédito     7110 + 7120 + 7160
  Tesouraria (líquida)   7140 + 7150 + 7198600009 (ingressos de depósitos intercooperativos) - 8150 - 8198600008,
                         mais câmbio, valor justo, hedge e venda de ativos financeiros, líquidos (receitas 7199100003, 7199300009,
                         7199400002, 7191600006, 7191500003, 7191700009, 7194000005; despesas 8199100002, 8199300008, 8199400001,
                         8191600005, 8191500002)
  Serviços e tarifas     7170
  Outras receitas        7180 + 7190 + 7300, sem intercooperativos, reversão de provisão e recuperação de baixados
  Captação               8110 + 8120 + 8130
  Provisão (líquida)     8199200005 - 7199200006 - 7192000007
  Pessoal                817270, 817300, 817330, 817360, 817370 (benefícios, encargos, proventos, treinamento, estagiários) + 817180 (honorários)
  Administrativas        8170 - pessoal - 8176900005
  Depreciação            8180 (amortização, depreciação e redução ao valor recuperável)
  Tributos               8176900005 + 8192500001 + 8193000005 + 8193300004 + IR/CS (7940 + 8940)
  Lucro ou sobras        7000 + 8000 + 8195600001 (juros ao capital das cooperativas somados de volta, como no IF.data)
Cooperativas incorporadas são somadas na incorporadora.
"""
import json, os, sys, re, io, zipfile, datetime, urllib.request, collections, csv
import pandas as pd

RAW, OUT = sys.argv[1], sys.argv[2]
SE_MUDOU = "--se-mudou" in sys.argv
AQUI = os.path.dirname(os.path.abspath(__file__))
arg = lambda k, d: next((a.split("=", 1)[1] for a in sys.argv if a.startswith(f"--{k}=")), d)
DEPARA = arg("depara", os.path.join(AQUI, "de_para_cooperativas.csv"))
INCORP = arg("incorp", os.path.join(AQUI, "incorporacoes.csv"))
os.makedirs(RAW, exist_ok=True); os.makedirs(OUT, exist_ok=True)
OUTFILE = os.path.join(OUT, "resultados.json")
ANT = json.load(open(OUTFILE)) if os.path.exists(OUTFILE) else None
HOJE = datetime.date.today()
UA = {"User-Agent": "Mozilla/5.0 dashboard-credito"}
OLINDA = "https://olinda.bcb.gov.br/olinda/servico"
COSIF = "https://www.bcb.gov.br/content/estabilidadefinanceira/cosif"


def req(url, method="GET", timeout=600):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA, method=method), timeout=timeout)

def existe(url):
    try:
        with req(url, "HEAD", 60) as r: return r.status == 200
    except Exception: return False

def baixar(url, path, tries=4):
    for i in range(tries):
        try:
            with req(url) as r, open(path + ".tmp", "wb") as f:
                while True:
                    b = r.read(1 << 20)
                    if not b: break
                    f.write(b)
            os.replace(path + ".tmp", path); return True
        except Exception as e:
            err = e
    print("falha", url, err); return False

def olinda(path, tries=4):
    for i in range(tries):
        try:
            with req(f"{OLINDA}/{path}", timeout=300) as r:
                return json.loads(r.read())["value"]
        except Exception as e:
            err = e
    raise RuntimeError(f"{path}: {err}")

def meses(ini, fim):
    y, m = int(ini[:4]), int(ini[4:]); out = []
    while f"{y}{m:02d}" <= fim:
        out.append(f"{y}{m:02d}"); m += 1
        if m == 13: y, m = y + 1, 1
    return out


# ---------- cadastro (mesmas regras das outras abas) ----------
coop = {x["CNPJ"]: x for x in olinda("Instituicoes_em_funcionamento/versao/v1/odata/SedesCooperativas?$format=json")}
DP = {r["cnpj"]: r for r in csv.DictReader(open(DEPARA, encoding="utf-8"), delimiter=";")} if os.path.exists(DEPARA) else {}
INC = {r["cnpj_incorporada"]: r["cnpj_incorporadora"] for r in csv.DictReader(open(INCORP, encoding="utf-8"), delimiter=";")} if os.path.exists(INCORP) else {}
def suc(c, n=0): return suc(INC[c], n + 1) if c in INC and n < 10 else c

def sistema(c, nome=""):
    x = coop.get(c, {}); t = ((x.get("FILIACAO") or "") + " " + (x.get("NOME_INSTITUICAO") or "") + " " + nome).upper()
    for k, s in (("SICOOB", "sicoob"), ("SICREDI", "sicredi"), ("CRESOL", "cresol"), ("UNICRED", "unicred")):
        if k in t: return s
    return "outras"

def central(c):
    f = (coop.get(c, {}).get("FILIACAO") or "").upper()
    return "crediminas" if "CREDIMINAS" in f else "cecremge" if "CECREMGE" in f else ""

def curto(c, nome):
    d = DP.get(c, {})
    if d.get("numero"):
        return d["numero"] + " " + re.sub(r"^Sicoob[\s/-]+", "", d.get("nome_curto", ""), flags=re.I).strip()
    if d.get("nome_curto"): return d["nome_curto"]
    n = nome.split(" - ")[-1] if " - " in nome else nome
    return n.title()[:40]

def escopos_coop(c, nome=""):
    if coop.get(c, {}).get("CLASSE", "Singular") != "Singular": return []
    s = sistema(c, nome); out = ["coop", s]
    if s in ("sicoob", "sicredi"): out.append("cong_" + s)
    if s == "sicoob" and coop.get(c, {}).get("UF") == "MG": out.append("sicoob_mg")
    if central(c): out.append(central(c))
    if coop.get(c, {}).get("UF") == "MG": out.append("coop_mg")
    return out

TOP5 = {"C0080329": "bb", "C0080075": "bradesco", "C0080099": "itau", "C0080738": "caixa", "C0080185": "santander"}
SIS_BANCO = {"C0080879": "cong_sicoob", "C0080745": "cong_sicredi"}
DIGITAIS = re.compile(r"\bNU\b|NUBANK|\bINTER\b|\bC6\b|PAGSEGURO|PAGBANK|MERCADO\s*PAGO|MERCADO\s*CR[ÉE]DITO|BTG", re.I)
NOMES_BANCO = {"C0080329": "Banco do Brasil", "C0080075": "Bradesco", "C0080099": "Itaú", "C0080738": "Caixa", "C0080185": "Santander",
               "C0080879": "Banco Sicoob", "C0080745": "Banco Sicredi"}

def escopos_banco(cod, nome):
    out = ["bancos"]
    if cod in TOP5: out.append(TOP5[cod]); out.append("top5")
    if cod in SIS_BANCO: out.append(SIS_BANCO[cod])
    if DIGITAIS.search(nome or ""): out.append("digitais")
    return out

ESCOPOS = [
    ("sfn", "Total (coop. + bancos)", "#2B2F33", "agregado"), ("bancos", "Bancos", "#8A9097", "agregado"), ("coop", "Cooperativas", "#56606A", "agregado"),
    ("cong_sicoob", "Conglomerado Sicoob", "#003641", "conglomerado"), ("cong_sicredi", "Conglomerado Sicredi", "#3FA110", "conglomerado"),
    ("sicoob", "Sicoob (cooperativas)", "#00AE9D", "sistema"), ("sicredi", "Sicredi (cooperativas)", "#7CC35A", "sistema"),
    ("cresol", "Cresol", "#6E5A9E", "sistema"), ("unicred", "Unicred", "#9C7A3C", "sistema"), ("outras", "Outras cooperativas", "#A3ACA8", "sistema"),
    ("coop_mg", "Cooperativas de MG", "#4F7F7A", "mg"), ("sicoob_mg", "Sicoob MG", "#2E8F86", "mg"),
    ("crediminas", "Central Crediminas", "#007A6E", "mg"), ("cecremge", "Central Cecremge", "#5BC2B8", "mg"),
    ("bb", "Banco do Brasil", "#465EFF", "banco"), ("bradesco", "Bradesco", "#CC092F", "banco"), ("itau", "Itaú", "#EC7000", "banco"),
    ("caixa", "Caixa", "#005CA9", "banco"), ("santander", "Santander", "#EC0000", "banco"), ("digitais", "Bancos digitais", "#820AD1", "banco"),
]

# ---------- contas ----------
PESSOAL = ["8172700003", "8173000001", "8173300000", "8173600009", "8173700002", "8171800007"]
TRIB = ["8176900005", "8192500001", "8193000005", "8193300004", "7940000008", "8940000007"]
CONTAS = ["7000000003", "8000000002", "7110000003", "7120000000", "7160000008", "7140000004", "7150000001", "7198600009",
          "8150000000", "8198600008", "7170000005", "7180000002", "7190000009", "7300000002", "7199200006", "7192000007",
          "8110000002", "8120000009", "8130000006", "8199200005", "8170000004", "8180000001", "8195600001",
          "1000000009", "2000000008", "6000000004"] + PESSOAL + TRIB
SALDO = {"1000000009", "2000000008", "6000000004"}
# câmbio, valor justo, hedge, venda de ativos financeiros e aplicações no exterior: entram líquidos na tesouraria
TES_R = ["7199100003", "7199300009", "7199400002", "7191600006", "7191500003", "7194000005", "7191700009"]
TES_D = ["8199100002", "8199300008", "8199400001", "8191600005", "8191500002"]
CONTAS += TES_R + TES_D         # contas patrimoniais (não acumulam)


def blocos(v):
    g = lambda k: v.get(k, 0.0)
    pess = -sum(g(k) for k in PESSOAL)
    trib_adm = -g("8176900005")
    cred = g("7110000003") + g("7120000000") + g("7160000008")
    tes = g("7140000004") + g("7150000001") + g("7198600009") + g("8150000000") + g("8198600008") + sum(g(k) for k in TES_R + TES_D)
    serv = g("7170000005")
    out_r = g("7180000002") + g("7190000009") + g("7300000002") - g("7198600009") - g("7199200006") - g("7192000007") - sum(g(k) for k in TES_R)
    capt = -(g("8110000002") + g("8120000009") + g("8130000006"))
    prov = -g("8199200005") - g("7199200006") - g("7192000007")
    adm = -g("8170000004") - pess - trib_adm
    depr = -g("8180000001")
    trib = -sum(g(k) for k in TRIB if k != "7940000008") - g("7940000008")
    jcp = -g("8195600001")
    lucro = g("7000000003") + g("8000000002") + jcp
    rec = cred + max(tes, 0) + serv + max(out_r, 0)
    tes_neg = 0 if tes >= 0 else -tes
    outras_d = rec - capt - prov - pess - adm - depr - trib - lucro - (0 if tes >= 0 else -tes) - (0 if out_r >= 0 else -out_r)
    return {"cred": cred, "tes": tes, "serv": serv, "out_r": out_r, "rec": rec, "capt": capt, "prov": prov, "pess": pess,
            "adm": adm, "depr": depr, "trib": trib, "out_d": outras_d, "lucro": lucro}


def ler_mes(am):
    out = {}
    for pasta, arq, doc, tipo in (("Cooperativas-de-credito", f"{am}COOPERATIVAS.CSV.ZIP", "4010", "coop"),
                                  ("Conglomerados-prudenciais", f"{am}BLOPRUDENCIAL.CSV.ZIP", "4060", "banco")):
        p = f"{RAW}/{arq}"
        if not os.path.exists(p) and not baixar(f"{COSIF}/{pasta}/{arq}", p): return None
        with zipfile.ZipFile(p) as z:
            with z.open(z.namelist()[0]) as f:
                txt = io.TextIOWrapper(f, encoding="latin1")
                for _ in range(3): next(txt)
                df = pd.read_csv(txt, sep=";", dtype=str)
        df.columns = [c.lstrip("#") for c in df.columns]
        df = df[(df.DOCUMENTO == doc) & df.CONTA.isin(CONTAS)]
        df["v"] = pd.to_numeric(df.SALDO.str.replace(",", ".", regex=False), errors="coerce").fillna(0)
        key = "CNPJ" if tipo == "coop" else "COD_CONGL"
        nomes = (df.groupby(key).NOME_CONGL.first() if tipo == "banco" else df.groupby(key).NOME_INSTITUICAO.first()).to_dict()
        for (k, conta), v in df.groupby([key, "CONTA"]).v.sum().items():
            c = suc(k) if tipo == "coop" else k
            d = out.setdefault((tipo, c), {"_nome": nomes.get(k, k)})
            d[conta] = d.get(conta, 0.0) + float(v)
    return out


ult = None
for am in reversed(meses("202501", HOJE.strftime("%Y%m"))):
    if existe(f"{COSIF}/Cooperativas-de-credito/{am}COOPERATIVAS.CSV.ZIP") and existe(f"{COSIF}/Conglomerados-prudenciais/{am}BLOPRUDENCIAL.CSV.ZIP"):
        ult = am; break
LISTA = meses("202501", ult)
ref = ult[:4] + "-" + ult[4:]
if SE_MUDOU and ANT and ANT["meta"].get("ref") == ref:
    print(json.dumps({"resultados": "sem mudança", "ref": ref})); sys.exit(0)

YTD = {}          # am -> {(tipo,id): {conta: valor}}
for am in LISTA:
    x = ler_mes(am)
    if x is not None: YTD[am] = x
LISTA = [m for m in LISTA if m in YTD]

INFO = {}
for am in LISTA:
    for (tipo, c), v in YTD[am].items():
        INFO[(tipo, c)] = v["_nome"] if tipo == "banco" or c not in INFO else INFO[(tipo, c)]

def fluxo(chave, am):
    v = YTD[am].get(chave, {})
    i = LISTA.index(am)
    if am[4:] in ("01", "07") or i == 0:
        return {k: (x if k not in SALDO else 0.0) for k, x in v.items() if not k.startswith("_")}
    vp = YTD[LISTA[i - 1]].get(chave, {})
    return {k: v.get(k, 0.0) - (vp.get(k, 0.0) if k not in SALDO else 0.0) for k in set(v) | set(vp) if not k.startswith("_") and k not in SALDO}

def soma(dicts):
    t = collections.Counter()
    for d in dicts: t.update(d)
    return t

r = lambda x, d=2: None if x is None else round(x, d)

def indic(fl12, pl_med, at_med):
    b = blocos(fl12); R = b["rec"] or None
    pct = lambda k: r(b[k] / R * 100, 1) if R else None
    adm_tot = b["pess"] + b["adm"] + b["depr"]
    margem = b["cred"] + b["tes"] - b["capt"] + b["serv"] + b["out_r"]
    return {"lucro": r(b["lucro"] / 1e6, 1), "rec": r(b["rec"] / 1e6, 1),
            "roe": r(b["lucro"] / pl_med * 100, 1) if pl_med and pl_med > 0 else None,
            "roa": r(b["lucro"] / at_med * 100, 2) if at_med else None,
            "efic": r(adm_tot / margem * 100, 1) if margem > 0 else None,
            "r_cred": pct("cred"), "r_tes": pct("tes"), "r_serv": pct("serv"), "r_out": pct("out_r"),
            "d_capt": pct("capt"), "d_prov": pct("prov"), "d_pess": pct("pess"), "d_adm": pct("adm"), "d_depr": pct("depr"),
            "d_trib": pct("trib"), "d_out": pct("out_d"), "d_lucro": pct("lucro")}

FIM12 = [m for m in LISTA if LISTA.index(m) >= 11]
SEMS = [m for m in LISTA if m[4:] in ("06", "12")]

def serie_para(chaves):
    """chaves: lista de (tipo,id). Devolve r12 por mês, semestres e lucro mensal."""
    out12, sem, mens = [], [], []
    fl = {am: soma(fluxo(k, am) for k in chaves) for am in LISTA}
    sal = {am: soma({kk: YTD[am].get(k, {}).get(kk, 0.0) for kk in SALDO} for k in chaves) for am in LISTA}
    for am in LISTA:
        mens.append({"d": am[:4] + "-" + am[4:], "lucro": r(blocos(fl[am])["lucro"] / 1e6, 1)})
    for am in FIM12:
        i = LISTA.index(am); jan = LISTA[i - 11:i + 1]
        f12 = soma(fl[m] for m in jan)
        pl = sum(sal[m]["6000000004"] for m in jan) / len(jan)
        at = sum(sal[m]["1000000009"] + sal[m]["2000000008"] for m in jan) / len(jan)
        out12.append({"d": am[:4] + "-" + am[4:], **indic(f12, pl, at)})
    for am in SEMS:
        v = soma(YTD[am].get(k, {}) for k in chaves)
        b = blocos({k: x for k, x in v.items() if not k.startswith("_")})
        sem.append({"s": ("1S" if am[4:] == "06" else "2S") + am[2:4], "d": am[:4] + "-" + am[4:], "lucro": r(b["lucro"] / 1e6, 1), "rec": r(b["rec"] / 1e6, 1)})
    return out12, sem, mens

membros = collections.defaultdict(list); inst = []
for (tipo, c), nome in INFO.items():
    sc = escopos_coop(c, nome) if tipo == "coop" else escopos_banco(c, nome)
    if not sc: continue
    for s in sc + ["sfn"]: membros[s].append((tipo, c))
    o12, sem, mens = serie_para([(tipo, c)])
    if not o12 or not o12[-1]["rec"] or o12[-1]["rec"] < 1: continue
    rr = {"id": c, "tipo": tipo, "nome": nome, "escopos": sc, "r12": o12[-1], "r12_ini": o12[0], "sem": sem}
    if tipo == "coop":
        rr.update({"curto": curto(c, nome), "sistema": sistema(c, nome), "central": central(c), "uf": coop.get(c, {}).get("UF", "")})
    else:
        rr["curto"] = NOMES_BANCO.get(c) or re.sub(r"\s*-\s*PRUDENCIAL.*$", "", nome, flags=re.I).title()
    inst.append(rr)

agg = {}
for e, *_ in ESCOPOS + [("top5",)]:      # top5: recorte extra da ficha de grupo
    o12, sem, mens = serie_para(membros[e])
    agg[e] = {"r12": o12, "sem": sem, "mens": mens, "n": len(membros[e])}

novo_desde = (ANT or {}).get("meta", {}).get("novo_desde") if (ANT or {}).get("meta", {}).get("ref") == ref else HOJE.isoformat()
out = {"meta": {"ref": ref, "meses": [m[:4] + "-" + m[4:] for m in LISTA], "atualizado": HOJE.isoformat(), "novo_desde": novo_desde,
                "fonte": "Banco Central — balancetes Cosif (cooperativas, doc. 4010; conglomerados prudenciais, doc. 4060)",
                "url": "https://www.bcb.gov.br/estabilidadefinanceira/balancetesbalancospatrimoniais"},
       "escopos": [{"id": a, "nome": b, "cor": c, "grupo": d} for a, b, c, d in ESCOPOS], "agg": agg, "inst": inst}
tmp = OUTFILE + ".tmp"
json.dump(out, open(tmp, "w"), ensure_ascii=False, separators=(",", ":"))
os.replace(tmp, OUTFILE)
print(json.dumps({"resultados": ref, "meses": len(LISTA), "instituicoes": len(inst), "kb": os.path.getsize(OUTFILE) // 1024}, ensure_ascii=False))
