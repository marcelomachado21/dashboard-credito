"""Abas Carteira e Crédito rural do Dashboard de Crédito.

Uso:
  python3 atualiza_carteira.py <pasta_raw> <pasta_saida> [--se-mudou] [--depara=<csv>] [--incorp=<csv>]

Gera <pasta_saida>/carteira.json com:
- sgs: saldo e concessões do SFN (SGS, Banco Central), mensais, com soma de 12 meses e variação sobre os 12 meses anteriores,
       por PF/PJ e por modalidade; inadimplência rural (SGS 21136, 21146, 21147, 21148).
- cosif: composição da carteira (empréstimos, financiamentos, rural, imobiliário, outros) e carteira rural por fonte de recursos
         (livres, exigibilidade à vista, poupança rural, LCA, fontes públicas), por escopo (mensal) e por instituição (último mês e
         mesmo mês do ano anterior), dos balancetes Cosif (cooperativas, doc. 4010; conglomerados prudenciais, doc. 4060).
O rural por finalidade (SCR.data) fica em risco.json (bloco scr.rural_fin), gerado por atualiza_risco.py.
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
OUTFILE = os.path.join(OUT, "carteira.json")
ANT = json.load(open(OUTFILE)) if os.path.exists(OUTFILE) else None
HOJE = datetime.date.today()
UA = {"User-Agent": "Mozilla/5.0 dashboard-credito", "Accept": "application/json"}
OLINDA = "https://olinda.bcb.gov.br/olinda/servico"
COSIF = "https://www.bcb.gov.br/content/estabilidadefinanceira/cosif"


def req(url, method="GET", timeout=300):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA, method=method), timeout=timeout)

def existe(url):
    try:
        with req(url, "HEAD", 60) as r: return r.status == 200
    except Exception: return False

def baixar(url, path, tries=4):
    for i in range(tries):
        try:
            with req(url, timeout=600) as r, open(path + ".tmp", "wb") as f:
                while True:
                    b = r.read(1 << 20)
                    if not b: break
                    f.write(b)
            os.replace(path + ".tmp", path); return True
        except Exception as e:
            err = e
    print("falha", url, err); return False

def getjson(url, tries=5):
    for i in range(tries):
        try:
            with req(url) as r: return json.loads(r.read())
        except Exception as e:
            err = e
    raise RuntimeError(f"{url}: {err}")

def meses(ini, fim):
    y, m = int(ini[:4]), int(ini[4:]); out = []
    while f"{y}{m:02d}" <= fim:
        out.append(f"{y}{m:02d}"); m += 1
        if m == 13: y, m = y + 1, 1
    return out


# ---------- 1. SGS ----------
SGS = {
    "20539": ("Saldo — total", "saldo"), "20540": ("Saldo — pessoas jurídicas", "saldo"), "20541": ("Saldo — pessoas físicas", "saldo"),
    "20631": ("Concessões — total", "conc"), "20632": ("Concessões — pessoas jurídicas", "conc"), "20633": ("Concessões — pessoas físicas", "conc"),
    "20662": ("PF livres — total", "conc_pf"), "20671": ("PF livres — consignado", "conc_pf"), "20672": ("PF livres — crédito pessoal total", "conc_pf"),
    "20673": ("PF livres — aquisição de veículos", "conc_pf"), "20682": ("PF livres — cartão de crédito", "conc_pf"),
    "20698": ("PF direcionados — total", "conc_pf"), "20701": ("PF direcionados — crédito rural", "conc_pf"), "20704": ("PF direcionados — financiamento imobiliário", "conc_pf"),
    "20686": ("PJ direcionados — total", "conc_pj"), "20689": ("PJ direcionados — crédito rural", "conc_pj"),
    "20642": ("PJ livres — capital de giro", "conc_pj"), "20656": ("PJ livres — cartão de crédito", "conc_pj"),
    "21148": ("Inadimplência rural PF total", "inad_rural"), "21146": ("Inadimplência rural PF — taxas de mercado", "inad_rural"),
    "21147": ("Inadimplência rural PF — taxas reguladas", "inad_rural"), "21136": ("Inadimplência rural PJ total", "inad_rural"),
}
def sgs(cod):
    ini = (HOJE - datetime.timedelta(days=365 * 5)).strftime("%d/%m/%Y")
    d = getjson(f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{cod}/dados?formato=json&dataInicial={ini}&dataFinal=31/12/2099")
    return [(f"{x['data'][6:10]}-{x['data'][3:5]}", float(x["valor"])) for x in d]

series, erros = {}, []
for cod, (tit, grp) in SGS.items():
    try:
        series[cod] = sgs(cod)
    except Exception as e:
        erros.append(f"SGS {cod}: {e}")
# derivadas: PJ livres = PJ total - PJ direcionados; PF crédito pessoal não consignado = pessoal total - consignado
def deriva(a, b, nome, grp, cod):
    if a in series and b in series:
        db = dict(series[b]); series[cod] = [(d, v - db[d]) for d, v in series[a] if d in db]
        SGS[cod] = (nome, grp)
deriva("20632", "20686", "PJ livres — total (PJ total − PJ direcionados)", "conc_pj", "pj_livres")
deriva("20672", "20671", "PF livres — crédito pessoal não consignado (pessoal total − consignado)", "conc_pf", "pf_nao_consig")

sg = {}
for cod, pts in series.items():
    tit, grp = SGS[cod]
    o = {"tit": tit, "grp": grp, "url": f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{cod}/dados?formato=json" if cod.isdigit() else "", "p": [{"d": d, "v": round(v, 2)} for d, v in pts[-49:]]}
    if grp.startswith("conc"):
        vals = [v for _, v in pts]; ds = [d for d, _ in pts]; r12 = []
        for i in range(23, len(vals)):
            a12, b12 = sum(vals[i - 11:i + 1]), sum(vals[i - 23:i - 11])
            r12.append({"d": ds[i], "s12": round(a12, 0), "yoy12": round((a12 / b12 - 1) * 100, 2) if b12 else None,
                        "mes_yoy": round((vals[i] / vals[i - 12] - 1) * 100, 2) if vals[i - 12] else None})
        o["r12"] = r12[-25:]
    sg[cod] = o
sgs_ref = max(p[-1][0] for c, p in series.items() if SGS[c][1] in ("saldo", "conc"))


# ---------- 2. Cosif ----------
coop = {x["CNPJ"]: x for x in getjson(f"{OLINDA}/Instituicoes_em_funcionamento/versao/v1/odata/SedesCooperativas?$format=json")["value"]}
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
    if d.get("numero"): return d["numero"] + " " + re.sub(r"^Sicoob[\s/-]+", "", d.get("nome_curto", ""), flags=re.I).strip()
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
CONTAS = {"1600000007": "tot", "1610000004": "emp", "1620000001": "fin", "1630000008": "rur", "1640000005": "imo",
          "1630500003": "r_livres", "1631500002": "r_avista", "1632500001": "r_poup", "1633500000": "r_lca", "1634500009": "r_pub"}

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
            d[CONTAS[conta]] = d.get(CONTAS[conta], 0.0) + float(v)
    return out

ult = None
for am in reversed(meses("202501", HOJE.strftime("%Y%m"))):
    if existe(f"{COSIF}/Cooperativas-de-credito/{am}COOPERATIVAS.CSV.ZIP") and existe(f"{COSIF}/Conglomerados-prudenciais/{am}BLOPRUDENCIAL.CSV.ZIP"):
        ult = am; break
LISTA = meses("202501", ult)
cos_ref = ult[:4] + "-" + ult[4:]
refs = {"sgs": sgs_ref, "cosif": cos_ref}
if SE_MUDOU and ANT and ANT["meta"].get("refs") == refs:
    print(json.dumps({"carteira": "sem mudança", "refs": refs})); sys.exit(0)
M = {}
for am in LISTA:
    x = ler_mes(am)
    if x is not None: M[am] = x
LISTA = [m for m in LISTA if m in M]
ult = LISTA[-1]; ant = f"{int(ult[:4]) - 1}{ult[4:]}"

r = lambda x, d=2: round(x, d) + 0.0   # + 0.0 evita "-0.0" no JSON
def comp(v):
    tot = v.get("tot", 0); rur = v.get("rur", 0)
    o = {"tot": r(tot / 1e9, 3), "rur": r(rur / 1e9, 3)}
    if tot:
        outros = tot - v.get("emp", 0) - v.get("fin", 0) - rur - v.get("imo", 0)
        o.update({"p_emp": r(v.get("emp", 0) / tot * 100, 1), "p_fin": r(v.get("fin", 0) / tot * 100, 1), "p_rur": r(rur / tot * 100, 1),
                  "p_imo": r(v.get("imo", 0) / tot * 100, 1), "p_out": r(outros / tot * 100, 1)})
    if rur:
        for k in ("r_livres", "r_avista", "r_poup", "r_lca", "r_pub"): o["f_" + k[2:]] = r(v.get(k, 0) / rur * 100, 1)
    return o

membros = collections.defaultdict(set); INFO = {}
for am in LISTA:
    for (tipo, c), v in M[am].items():
        sc = escopos_coop(c, v["_nome"]) if tipo == "coop" else escopos_banco(c, v["_nome"])
        if not sc: continue
        INFO[(tipo, c)] = (v["_nome"], sc)
        for s in sc + ["sfn"]: membros[s].add((tipo, c))
cos_ser = {}
for e, *_ in ESCOPOS + [("top5",)]:      # top5: recorte extra da ficha de grupo
    s = []
    for am in LISTA:
        t = collections.Counter()
        for k in membros[e]: t.update({kk: vv for kk, vv in M[am].get(k, {}).items() if not kk.startswith("_")})
        if t.get("tot"): s.append({"d": am[:4] + "-" + am[4:], **comp(t)})
    cos_ser[e] = s
inst = []
for (tipo, c), (nome, sc) in INFO.items():
    v = M[ult].get((tipo, c))
    if not v or not v.get("tot"): continue
    va = M.get(ant, {}).get((tipo, c)) if ant in M else None
    o = {"id": c, "tipo": tipo, "nome": nome, "escopos": sc, **comp(v)}
    if va and va.get("tot"):
        o["cresc"] = r((v["tot"] / va["tot"] - 1) * 100, 1)
        if va.get("rur"): o["cresc_rur"] = r((v.get("rur", 0) / va["rur"] - 1) * 100, 1)
    if tipo == "coop":
        o.update({"curto": curto(c, nome), "sistema": sistema(c, nome), "central": central(c), "uf": coop.get(c, {}).get("UF", "")})
    else:
        o["curto"] = NOMES_BANCO.get(c) or re.sub(r"\s*-\s*PRUDENCIAL.*$", "", nome, flags=re.I).title()
    inst.append(o)
inst.sort(key=lambda o: -o["tot"])

novo = (ANT or {}).get("meta", {})
novo_desde = {k: (novo.get("novo_desde", {}).get(k) if novo.get("refs", {}).get(k) == refs[k] else HOJE.isoformat()) or HOJE.isoformat() for k in refs}
out = {"meta": {"refs": refs, "novo_desde": novo_desde, "atualizado": HOJE.isoformat(), "erros": erros, "ant": ant[:4] + "-" + ant[4:],
                "fonte_sgs": "Banco Central — SGS (estatísticas monetárias e de crédito)", "url_sgs": "https://api.bcb.gov.br/dados/serie/bcdata.sgs.20631/dados?formato=json",
                "fonte_cosif": "Banco Central — balancetes Cosif (doc. 4010 e 4060)", "url_cosif": "https://www.bcb.gov.br/estabilidadefinanceira/balancetesbalancospatrimoniais"},
       "escopos": [{"id": a, "nome": b, "cor": c, "grupo": d} for a, b, c, d in ESCOPOS], "sgs": sg, "cosif": cos_ser, "inst": inst}
tmp = OUTFILE + ".tmp"
json.dump(out, open(tmp, "w"), ensure_ascii=False, separators=(",", ":"))
os.replace(tmp, OUTFILE)
print(json.dumps({"carteira": refs, "instituicoes": len(inst), "erros": erros, "kb": os.path.getsize(OUTFILE) // 1024}, ensure_ascii=False))
