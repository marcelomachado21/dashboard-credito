"""Aba Mapa de posicionamento do Dashboard de Crédito.

Uso:
  python3 atualiza_posicao.py <pasta_raw> <pasta_saida> [--se-mudou] [--depara=<csv>] [--incorp=<csv>]

Gera <pasta_saida>/posicao.json: indicadores trimestrais por instituição (cooperativas singulares e
conglomerados prudenciais) e por escopo, a partir de jun/2025 menos 3 trimestres (início da Res. 4.966):
- IF.data: carteira (rel. 16), crescimento em 12 meses, inadimplência, ativos problemáticos, provisão e cobertura
  (rel. 2), Basileia (rel. 5), ROE, ROA, eficiência e composição da receita (rel. 1 e 4), captações.
- Cosif (balancete do mês do trimestre): estágios 2 e 3 e participação do crédito rural na carteira.
Cooperativas incorporadas são somadas na incorporadora em todos os trimestres.
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
OUTFILE = os.path.join(OUT, "posicao.json")
ANT = json.load(open(OUTFILE)) if os.path.exists(OUTFILE) else None
HOJE = datetime.date.today()
UA = {"User-Agent": "Mozilla/5.0 dashboard-credito"}
OLINDA = "https://olinda.bcb.gov.br/olinda/servico"
COSIF = "https://www.bcb.gov.br/content/estabilidadefinanceira/cosif"


def req(url, method="GET", timeout=600):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA, method=method), timeout=timeout)


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


# ---------- cadastro, de-para, incorporações (mesmas regras da aba de risco) ----------
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
    ("sfn", "SFN", "#2B2F33", "agregado"), ("bancos", "Bancos", "#8A9097", "agregado"), ("coop", "Cooperativas", "#56606A", "agregado"),
    ("cong_sicoob", "Conglomerado Sicoob", "#003641", "conglomerado"), ("cong_sicredi", "Conglomerado Sicredi", "#3FA110", "conglomerado"),
    ("sicoob", "Sicoob (cooperativas)", "#00AE9D", "sistema"), ("sicredi", "Sicredi (cooperativas)", "#7CC35A", "sistema"),
    ("cresol", "Cresol", "#6E5A9E", "sistema"), ("unicred", "Unicred", "#9C7A3C", "sistema"), ("outras", "Outras cooperativas", "#A3ACA8", "sistema"),
    ("coop_mg", "Cooperativas de MG", "#4F7F7A", "mg"), ("sicoob_mg", "Sicoob MG", "#2E8F86", "mg"),
    ("crediminas", "Central Crediminas", "#007A6E", "mg"), ("cecremge", "Central Cecremge", "#5BC2B8", "mg"),
    ("bb", "Banco do Brasil", "#465EFF", "banco"), ("bradesco", "Bradesco", "#CC092F", "banco"), ("itau", "Itaú", "#EC7000", "banco"),
    ("caixa", "Caixa", "#005CA9", "banco"), ("santander", "Santander", "#EC0000", "banco"), ("top5", "5 maiores bancos", "#465EFF", "banco"),
    ("digitais", "Bancos digitais", "#820AD1", "banco"),
]

METRICAS = [
    ("cart", "Carteira de crédito", "R$ bi", "neutro", "Total da carteira de instrumentos financeiros (IF.data, rel. 16)."),
    ("cresc", "Crescimento da carteira em 12 meses", "%", "alto", "Variação da carteira sobre o mesmo trimestre do ano anterior; só a partir de mar/26, para não misturar critérios de antes da Res. 4.966."),
    ("inad", "Inadimplência > 90 dias", "%", "baixo", "Inadimplência sobre a carteira (IF.data, rel. 16)."),
    ("ap", "Ativos problemáticos", "%", "baixo", "Ativos problemáticos sobre a carteira (IF.data, rel. 16)."),
    ("e2", "Estágio 2", "%", "baixo", "Ativos em estágio 2 sobre os ativos financeiros classificados (Cosif, contas 3311 a 3315)."),
    ("e3", "Estágio 3", "%", "baixo", "Ativos em estágio 3 sobre os ativos financeiros classificados (Cosif)."),
    ("prov", "Provisão sobre a carteira", "%", "neutro", "Perda esperada sobre o valor bruto das operações de crédito (IF.data, rel. 2)."),
    ("cob", "Cobertura dos ativos problemáticos", "%", "alto", "Perda esperada das operações de crédito sobre ativos problemáticos."),
    ("basil", "Índice de Basileia", "%", "alto", "Patrimônio de referência sobre ativos ponderados pelo risco (IF.data, rel. 5)."),
    ("roe", "ROE anualizado", "%", "alto", "Lucro ou sobras do período anualizado sobre o patrimônio líquido do fim do período."),
    ("roa", "ROA anualizado", "%", "alto", "Lucro ou sobras do período anualizado sobre o ativo total."),
    ("efic", "Índice de eficiência", "%", "baixo", "Despesas de pessoal e administrativas sobre receitas (intermediação antes da perda esperada, serviços, tarifas, transações de pagamento e outras receitas)."),
    ("rural", "Crédito rural na carteira", "%", "neutro", "Financiamentos rurais (conta 1630) sobre operações de crédito (conta 1600), Cosif."),
    ("rec_cred", "Receita de crédito na receita total", "%", "neutro", "Rendas de operações de crédito sobre a receita bruta (crédito, aplicações, títulos, arrendamento, serviços, tarifas, transações de pagamento e outras receitas)."),
    ("capt_cresc", "Crescimento das captações em 12 meses", "%", "alto", "Variação das captações sobre o mesmo trimestre do ano anterior (IF.data, rel. 1); a partir de mar/26."),
]


# ---------- IF.data ----------
def ifvals(am, rel):
    d = olinda(f"IFDATA/versao/v1/odata/IfDataValores(AnoMes=@AnoMes,TipoInstituicao=@TipoInstituicao,Relatorio=@Relatorio)?@AnoMes={am}&@TipoInstituicao=1&@Relatorio='{rel}'&$format=json")
    out = collections.defaultdict(dict)
    for x in d:
        nm = x["NomeColuna"] or ""
        out[x["CodInst"]][nm.split("\n")[0].strip()] = x["Saldo"] or 0
        cod = re.search(r"\(([a-z]{1,2}\d*)\)", nm)
        if cod: out[x["CodInst"]]["#" + cod.group(1)] = x["Saldo"] or 0
    return out

tri = []; y, m = HOJE.year, (HOJE.month - 1) // 3 * 3
if m == 0: y, m = y - 1, 12
while f"{y}{m:02d}" >= "202503":
    tri.append(f"{y}{m:02d}"); m -= 3
    if m == 0: y, m = y - 1, 12
tri.sort()

BASE = {}            # (trimestre, id) -> Counter de valores brutos
INFO = {}            # id -> (tipo, nome)
validos = []
for am in tri:
    try:
        r16 = ifvals(am, 16)
        if not r16: continue
        r1, r2, r4, r5 = ifvals(am, 1), ifvals(am, 2), ifvals(am, 4), ifvals(am, 5)
        cad = {x["CodInst"]: x for x in olinda(f"IFDATA/versao/v1/odata/IfDataCadastro(AnoMes=@AnoMes)?@AnoMes={am}&$format=json")}
    except Exception as e:
        print("IFDATA", am, e); continue
    validos.append(am)
    for cod, v16 in r16.items():
        ca = cad.get(cod, {}); nome = ca.get("NomeInstituicao") or ""
        tipo = "coop" if ca.get("Tcb") == "B3S" else "banco"
        c = suc(cod) if tipo == "coop" else cod
        v1, v2, v4, v5 = r1.get(cod, {}), r2.get(cod, {}), r4.get(cod, {}), r5.get(cod, {})
        g = lambda d, k: float(d.get(k) or 0)
        receita = (g(v4, "#k") - g(v4, "#f")) + g(v4, "#l") + g(v4, "#m") + g(v4, "#n") + g(v4, "#t")
        val = collections.Counter({
            "cart": g(v16, "Total Geral"), "inad": g(v16, "Inadimplência"), "ap": g(v16, "Ativos problemáticos"),
            "bruto": abs(g(v2, "#e1")), "pe": abs(g(v2, "#e2")), "pr": g(v5, "#e"), "rwa": g(v5, "#j"),
            "pl": g(v1, "Patrimônio Líquido"), "ativo": g(v1, "Ativo Total"), "lucro": g(v1, "Lucro Líquido"), "capt": g(v1, "Captações"),
            "desp_adm": abs(g(v4, "#o")) + abs(g(v4, "#p")), "receita": receita, "rec_cred": g(v4, "#c"), "rec_bruta": sum(max(0.0, g(v4, k)) for k in ("#c", "#a", "#b", "#d", "#e", "#l1", "#m", "#n", "#t")),
            "rec_tes": g(v4, "#a") + g(v4, "#b"), "rec_serv": g(v4, "#m") + g(v4, "#n") + g(v4, "#l"), "rec_out": g(v4, "#t")})
        BASE.setdefault((am, c), collections.Counter()).update(val)
        if tipo == "coop" and c not in INFO: INFO[c] = ("coop", coop.get(c, {}).get("NOME_INSTITUICAO") or nome)
        elif tipo == "banco": INFO[c] = ("banco", nome)

# ---------- Cosif: estágios e rural no mês de cada trimestre ----------
CONTAS = {"1600000007": "cos_cart", "1630000008": "cos_rural", "3311000002": "e1", "3312000001": "e2", "3313000000": "e3",
          "3314000009": "sn", "3315000008": "sp"}
COS = {}
for am in validos:
    for pasta, arq, doc, tipo in (("Cooperativas-de-credito", f"{am}COOPERATIVAS.CSV.ZIP", "4010", "coop"),
                                  ("Conglomerados-prudenciais", f"{am}BLOPRUDENCIAL.CSV.ZIP", "4060", "banco")):
        p = f"{RAW}/{arq}"
        if not os.path.exists(p) and not baixar(f"{COSIF}/{pasta}/{arq}", p): continue
        with zipfile.ZipFile(p) as z:
            with z.open(z.namelist()[0]) as f:
                txt = io.TextIOWrapper(f, encoding="latin1")
                for _ in range(3): next(txt)
                df = pd.read_csv(txt, sep=";", dtype=str)
        df.columns = [c.lstrip("#") for c in df.columns]
        df = df[(df.DOCUMENTO == doc) & df.CONTA.isin(CONTAS)]
        df["v"] = pd.to_numeric(df.SALDO.str.replace(",", ".", regex=False), errors="coerce").abs()
        key = "CNPJ" if tipo == "coop" else "COD_CONGL"
        for (k, conta), v in df.groupby([key, "CONTA"]).v.sum().items():
            c = suc(k) if tipo == "coop" else k
            COS.setdefault((am, c), collections.Counter())[CONTAS[conta]] += float(v)


# ---------- métricas ----------
def ano_atras(am): return f"{int(am[:4]) - 1}{am[4:]}"
r2 = lambda x, d=2: None if x is None else round(x, d)

def met(am, v, vant, cs):
    fat = 2 if am[4:] in ("06", "12") else 4               # lucro de jun/dez é semestral; de mar/set, trimestral
    cart = v["cart"]; base = sum(cs.get(k, 0) for k in ("e1", "e2", "e3", "sn", "sp")) if cs else 0
    out = {"cart": r2(cart / 1e9, 3),
           "inad": r2(v["inad"] / cart * 100) if cart else None, "ap": r2(v["ap"] / cart * 100) if cart else None,
           "prov": r2(v["pe"] / v["bruto"] * 100) if v["bruto"] else None, "cob": r2(v["pe"] / v["ap"] * 100, 1) if v["ap"] else None,
           "basil": r2(v["pr"] / v["rwa"] * 100, 1) if v["rwa"] else None,
           "roe": r2(v["lucro"] * fat / v["pl"] * 100, 1) if v["pl"] > 0 else None,
           "roa": r2(v["lucro"] * fat / v["ativo"] * 100) if v["ativo"] else None,
           "efic": r2(v["desp_adm"] / v["receita"] * 100, 1) if v["receita"] > 0 else None,
           "rec_cred": r2(v["rec_cred"] / v["rec_bruta"] * 100, 1) if v["rec_bruta"] > 0 else None,
           "e2": r2(cs.get("e2", 0) / base * 100) if base else None, "e3": r2(cs.get("e3", 0) / base * 100) if base else None,
           "simp": r2((cs.get("sn", 0) + cs.get("sp", 0)) / base * 100, 0) if base else None,
           "rural": r2(cs.get("cos_rural", 0) / cs["cos_cart"] * 100, 1) if cs and cs.get("cos_cart") else None,
           "cresc": r2((cart / vant["cart"] - 1) * 100, 1) if vant and vant["cart"] > 0 and cart > 0 else None,
           "capt_cresc": r2((v["capt"] / vant["capt"] - 1) * 100, 1) if vant and vant["capt"] > 0 else None,
           "lucro": r2(v["lucro"] / 1e6, 1), "pl": r2(v["pl"] / 1e9, 3)}
    return out

inst = []
for c, (tipo, nome) in INFO.items():
    sc = escopos_coop(c, nome) if tipo == "coop" else escopos_banco(c, nome)
    if not sc: continue
    s = {}
    for am in validos:
        v = BASE.get((am, c))
        if not v or not v["cart"]: continue
        s[am[:4] + "-" + am[4:]] = met(am, v, BASE.get((ano_atras(am), c)), COS.get((am, c), {}))
    if not s or max(x["cart"] for x in s.values()) < 0.01: continue
    r = {"id": c, "tipo": tipo, "nome": nome, "escopos": sc, "s": s}
    if tipo == "coop":
        r.update({"curto": curto(c, nome), "sistema": sistema(c, nome), "central": central(c), "uf": coop.get(c, {}).get("UF", "")})
        if DP.get(c, {}).get("numero"): r["numero"] = DP[c]["numero"]
    else:
        r["curto"] = NOMES_BANCO.get(c) or re.sub(r"\s*-\s*PRUDENCIAL.*$", "", nome, flags=re.I).title()
    inst.append(r)

agg = {}
for e, *_ in ESCOPOS:
    s = {}
    for am in validos:
        tot, tant, tcs = collections.Counter(), collections.Counter(), collections.Counter()
        for r in inst:
            if e != "sfn" and e not in r["escopos"]: continue
            if (am, r["id"]) in BASE: tot.update(BASE[(am, r["id"])])
            if (ano_atras(am), r["id"]) in BASE: tant.update(BASE[(ano_atras(am), r["id"])])
            tcs.update(COS.get((am, r["id"]), {}))
        if tot["cart"]: s[am[:4] + "-" + am[4:]] = met(am, tot, tant if tant["cart"] else None, tcs)
    agg[e] = s

ref = validos[-1][:4] + "-" + validos[-1][4:]
if SE_MUDOU and ANT and ANT["meta"].get("ref") == ref:
    print(json.dumps({"posicao": "sem mudança", "ref": ref})); sys.exit(0)
novo_desde = (ANT or {}).get("meta", {}).get("novo_desde") if (ANT or {}).get("meta", {}).get("ref") == ref else HOJE.isoformat()
out = {"meta": {"ref": ref, "trimestres": [t[:4] + "-" + t[4:] for t in validos], "atualizado": HOJE.isoformat(), "novo_desde": novo_desde,
                "fonte_ifd": "Banco Central — IF.data (relatórios 1, 2, 4, 5 e 16)", "url_ifd": "https://www3.bcb.gov.br/ifdata/",
                "fonte_cosif": "Banco Central — balancetes Cosif (doc. 4010 e 4060)", "url_cosif": "https://www.bcb.gov.br/estabilidadefinanceira/balancetesbalancospatrimoniais"},
       "escopos": [{"id": a, "nome": b, "cor": c, "grupo": d} for a, b, c, d in ESCOPOS],
       "metricas": [{"id": a, "nome": b, "un": c, "melhor": d, "desc": e} for a, b, c, d, e in METRICAS],
       "inst": inst, "agg": agg}
tmp = OUTFILE + ".tmp"
json.dump(out, open(tmp, "w"), ensure_ascii=False, separators=(",", ":"))
os.replace(tmp, OUTFILE)
print(json.dumps({"posicao": ref, "trimestres": len(validos), "instituicoes": len(inst), "kb": os.path.getsize(OUTFILE) // 1024}, ensure_ascii=False))
