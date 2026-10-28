"""Aba Qualidade e risco do Dashboard de Crédito.

Uso:
  python3 atualiza_risco.py <pasta_raw> <pasta_saida> [--se-mudou] [--depara=<csv>] [--incorp=<csv>]

Gera <pasta_saida>/risco.json com três blocos:
- scr:   SCR.data (mensal, por segmento e UF do tomador): carteira, inadimplência > 90 dias,
         atraso de 15 a 90 dias e ativo problemático; SFN, bancos e cooperativas; Brasil e MG;
         total, PF, PJ, rural e rural PF; e quebra por modalidade no último mês.
- cosif: balancetes Cosif (mensal): estágios 1, 2 e 3 (e metodologia simplificada), perda esperada
         e carteira de crédito, por cooperativa (doc. 4010) e por conglomerado prudencial (doc. 4060).
- ifd:   IF.data (trimestral): inadimplência, ativos problemáticos e Basileia por instituição.
Escopos (Sicoob, Sicredi, centrais, Sicoob MG, 5 maiores, digitais) somam as instituições.
Cooperativas incorporadas entram na incorporadora em todo o histórico.
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
OUTFILE = os.path.join(OUT, "risco.json")
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


def meses(ini, fim):                     # 'AAAAMM'
    y, m = int(ini[:4]), int(ini[4:]); out = []
    while f"{y}{m:02d}" <= fim:
        out.append(f"{y}{m:02d}"); m += 1
        if m == 13: y, m = y + 1, 1
    return out


# ---------- cadastro, de-para, incorporações ----------
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
    if coop.get(c, {}).get("CLASSE", "Singular") != "Singular": return []      # centrais: fora das somas
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
    ("sicoob_mg", "Sicoob MG", "#2E8F86", "mg"), ("crediminas", "Central Crediminas", "#007A6E", "mg"), ("cecremge", "Central Cecremge", "#5BC2B8", "mg"),
    ("bb", "Banco do Brasil", "#465EFF", "banco"), ("bradesco", "Bradesco", "#CC092F", "banco"), ("itau", "Itaú", "#EC7000", "banco"),
    ("caixa", "Caixa", "#005CA9", "banco"), ("santander", "Santander", "#EC0000", "banco"), ("digitais", "Bancos digitais", "#820AD1", "banco"),
]

# ---------- 1. SCR.data ----------
def scr():
    ano = HOJE.year; dados = {}
    for y in (ano - 2, ano - 1, ano):
        p = f"{RAW}/scrdata_{y}.zip"
        if y >= ano - 1 or not os.path.exists(p):
            if not baixar(f"https://www.bcb.gov.br/pda/desig/scrdata_{y}.zip", p): continue
        z = zipfile.ZipFile(p)
        for name in sorted(z.namelist()):
            d = re.search(r"(\d{6})", name).group(1)
            dados[d] = (p, name)
    ult = sorted(dados)[-25:]
    num = ["carteira_ativa", "vencido_de_15_ate_90_dias", "carteira_inadimplencia", "ativo_problematico"]
    linhas, modal, rural_fin = [], [], []
    for d in ult:
        p, name = dados[d]
        with zipfile.ZipFile(p).open(name) as f:
            df = pd.read_csv(f, sep=";", usecols=["uf", "segmento", "cliente", "modalidade", "submodalidade"] + num, dtype=str, encoding="utf-8-sig")
        for c in num:
            df[c] = pd.to_numeric(df[c].str.replace(".", "", regex=False).str.replace(",", ".", regex=False), errors="coerce").fillna(0)
        df["seg"] = df.segmento.map({"Cooperativa": "coop", "Banco": "bancos"}).fillna("outros")
        df["rural"] = df.modalidade.str.contains("rurais", case=False, na=False)
        sm = df.submodalidade.fillna("")
        df["fin"] = "outros"
        for k, pref in (("custeio", "Custeio"), ("investimento", "Investimento"), ("comercializacao", "Comercializa"), ("industrializacao", "Industrializa")):
            df.loc[df.rural & sm.str.startswith(pref), "fin"] = k
        mes = d[:4] + "-" + d[4:]
        for geo, g in (("BR", df), ("MG", df[df.uf == "MG"])):
            for seg in ("sfn", "bancos", "coop"):
                s_ = g if seg == "sfn" else g[g.seg == seg]
                for corte, ss in (("total", s_), ("PF", s_[s_.cliente == "PF"]), ("PJ", s_[s_.cliente == "PJ"]),
                                  ("rural", s_[s_.rural]), ("rural_PF", s_[s_.rural & (s_.cliente == "PF")])):
                    linhas.append((mes, geo, seg, corte) + tuple(float(ss[c].sum()) for c in num))
            for seg in ("sfn", "bancos", "coop"):
                s_ = g[g.rural] if seg == "sfn" else g[g.rural & (g.seg == seg)]
                for fin, ss in s_.groupby("fin"):
                    rural_fin.append((mes, geo, seg, fin) + tuple(float(ss[c].sum()) for c in num))
            if d in ult[-1:] or d == ult[-13]:
                for seg in ("sfn", "bancos", "coop"):
                    s_ = g if seg == "sfn" else g[g.seg == seg]
                    t = s_.groupby(["cliente", "modalidade"])[num].sum()
                    for (cli, mod), r in t.iterrows():
                        modal.append((mes, geo, seg, cli, mod) + tuple(float(r[c]) for c in num))
    ser = collections.defaultdict(lambda: collections.defaultdict(lambda: collections.defaultdict(list)))
    for mes, geo, seg, corte, cart, v1590, inad, ap in linhas:
        ser[geo][seg][corte].append({"d": mes, "cart": round(cart / 1e9, 2),
                                     "inad": round(inad / cart * 100, 2) if cart else None,
                                     "a15": round(v1590 / cart * 100, 2) if cart else None,
                                     "ap": round(ap / cart * 100, 2) if cart else None})
    md = collections.defaultdict(lambda: collections.defaultdict(list))
    for mes, geo, seg, cli, mod, cart, v1590, inad, ap in modal:
        if cart < 5e8: continue
        md[f"{geo}|{seg}"][mes].append({"cli": cli, "mod": mod, "cart": round(cart / 1e9, 2), "inad": round(inad / cart * 100, 2),
                                        "a15": round(v1590 / cart * 100, 2), "ap": round(ap / cart * 100, 2)})
    rf = collections.defaultdict(lambda: collections.defaultdict(lambda: collections.defaultdict(list)))
    for mes, geo, seg, fin, cart, v1590, inad, ap in rural_fin:
        rf[geo][seg][fin].append({"d": mes, "cart": round(cart / 1e9, 2), "inad": round(inad / cart * 100, 2) if cart else None,
                                  "a15": round(v1590 / cart * 100, 2) if cart else None, "ap": round(ap / cart * 100, 2) if cart else None})
    return {"ref": ult[-1][:4] + "-" + ult[-1][4:], "serie": ser, "modal": md, "rural_fin": rf,
            "fonte": "Banco Central — SCR.data (carteira ativa, vencido de 15 a 90 dias, inadimplência acima de 90 dias e ativo problemático, por segmento e UF do tomador)",
            "url": "https://dadosabertos.bcb.gov.br/dataset/scr_data"}


# ---------- 2. Cosif ----------
CONTAS = {"1600000007": "cart", "3311000002": "e1", "3312000001": "e2", "3313000000": "e3",
          "3314000009": "sn", "3315000008": "sp"}

def cosif_mes(am):
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
        df["v"] = pd.to_numeric(df.SALDO.str.replace(",", ".", regex=False), errors="coerce").abs()
        key = "CNPJ" if tipo == "coop" else "COD_CONGL"
        nomes = df.groupby(key).NOME_CONGL.first() if tipo == "banco" else df.groupby(key).NOME_INSTITUICAO.first()
        t = df.groupby([key, "CONTA"]).v.sum()
        for (k, conta), v in t.items():
            out.setdefault((tipo, k), {"nome": nomes.get(k, k)})[CONTAS[conta]] = float(v)
    return out


def cosif():
    ult = None
    for am in reversed(meses(f"{HOJE.year - 1}01", HOJE.strftime("%Y%m"))):
        if existe(f"{COSIF}/Cooperativas-de-credito/{am}COOPERATIVAS.CSV.ZIP") and existe(f"{COSIF}/Conglomerados-prudenciais/{am}BLOPRUDENCIAL.CSV.ZIP"):
            ult = am; break
    lista = [m for m in meses("202501", ult)][-18:]          # estágios existem desde jan/2025 (Res. CMN 4.966)
    por_mes, inst_ult, nomes = {}, {}, {}
    for am in lista:
        x = cosif_mes(am)
        if x is None: continue
        agg = collections.defaultdict(collections.Counter)
        for (tipo, k), v in x.items():
            if tipo == "coop":
                c = suc(k); sc = escopos_coop(c, v["nome"]); nomes[("coop", c)] = v["nome"]
            else:
                c = k; sc = escopos_banco(k, v["nome"]); nomes[("banco", c)] = v["nome"]
            vals = collections.Counter({kk: vv for kk, vv in v.items() if kk != "nome"})
            for s in sc: agg[s].update(vals)
            if sc: agg["sfn"].update(vals)
            if am == lista[-1] and vals.get("cart", 0) > 0:
                inst_ult.setdefault((tipo, c), collections.Counter()).update(vals)
        por_mes[am] = agg
    def met(v):
        base = sum(v.get(k, 0) for k in ("e1", "e2", "e3", "sn", "sp"))
        cart = v.get("cart", 0); prob = v.get("e3", 0) + v.get("sp", 0)
        return {"cart": round(cart / 1e9, 2),
                "e1": round(v.get("e1", 0) / base * 100, 2) if base else None, "e2": round(v.get("e2", 0) / base * 100, 2) if base else None,
                "e3": round(v.get("e3", 0) / base * 100, 2) if base else None,
                "simp": round((v.get("sn", 0) + v.get("sp", 0)) / base * 100, 1) if base else None,
                "sp": round(v.get("sp", 0) / base * 100, 2) if base else None}
    ser = collections.defaultdict(list)
    for am in sorted(por_mes):
        for s, v in por_mes[am].items():
            ser[s].append({"d": am[:4] + "-" + am[4:], **met(v)})
    inst = []
    for (tipo, c), v in inst_ult.items():
        nm = nomes[(tipo, c)]
        r = {"id": c, "tipo": tipo, "nome": nm, **met(v)}
        if tipo == "coop":
            r.update({"curto": curto(c, nm), "sistema": sistema(c, nm), "central": central(c), "uf": coop.get(c, {}).get("UF", ""),
                      "escopos": escopos_coop(c, nm)})
            if not r["escopos"]: continue
        else:
            r.update({"curto": NOMES_BANCO.get(c) or re.sub(r"\s*-\s*PRUDENCIAL.*$", "", nm).title(), "escopos": escopos_banco(c, nm)})
        inst.append(r)
    inst.sort(key=lambda r: -r["cart"])
    return {"ref": lista[-1][:4] + "-" + lista[-1][4:], "serie": ser, "inst": inst,
            "fonte": "Banco Central — balancetes Cosif (cooperativas, doc. 4010; conglomerados prudenciais, doc. 4060)",
            "url": "https://www.bcb.gov.br/estabilidadefinanceira/balancetesbalancospatrimoniais"}


# ---------- 3. IF.data ----------
B = f"{OLINDA}/IFDATA/versao/v1/odata"
def ifvals(am, rel):
    d = olinda(f"IFDATA/versao/v1/odata/IfDataValores(AnoMes=@AnoMes,TipoInstituicao=@TipoInstituicao,Relatorio=@Relatorio)?@AnoMes={am}&@TipoInstituicao=1&@Relatorio='{rel}'&$format=json")
    out = collections.defaultdict(dict)
    for x in d:
        nm = x["NomeColuna"] or ""
        out[x["CodInst"]][nm.split("\n")[0].strip()] = x["Saldo"]
        cod = re.search(r"\(([a-z]\d*)\)", nm)
        if cod: out[x["CodInst"]]["#" + cod.group(1)] = x["Saldo"]
    return out

def ifdata():
    tri = []; y, m = HOJE.year, (HOJE.month - 1) // 3 * 3
    if m == 0: y, m = y - 1, 12
    for _ in range(8):
        tri.append(f"{y}{m:02d}"); m -= 3
        if m == 0: y, m = y - 1, 12
    ser = collections.defaultdict(list); inst = []; ref = None
    for am in sorted(t for t in tri if t >= "202503"):
        try:
            r16 = ifvals(am, 16)
            if not r16: continue
            r5 = ifvals(am, 5); r2 = ifvals(am, 2)
            cad = {x["CodInst"]: x for x in olinda(f"IFDATA/versao/v1/odata/IfDataCadastro(AnoMes=@AnoMes)?@AnoMes={am}&$format=json")}
        except Exception as e:
            print("IFDATA", am, e); continue
        agg = collections.defaultdict(collections.Counter); ref = am; ult = []
        for cod, v in r16.items():
            ca = cad.get(cod, {}); nome = ca.get("NomeInstituicao") or ""
            vals = collections.Counter({"cart": v.get("Total Geral") or 0, "inad": v.get("Inadimplência") or 0, "ap": v.get("Ativos problemáticos") or 0,
                                        "pr": r5.get(cod, {}).get("Patrimônio de Referência para Comparação com o RWA") or 0,
                                        "rwa": r5.get(cod, {}).get("Ativos Ponderados pelo Risco (RWA)") or 0,
                                        "bruto": abs(r2.get(cod, {}).get("#e1") or 0), "pe": abs(r2.get(cod, {}).get("#e2") or 0)})
            if ca.get("Tcb") == "B3S":
                c = suc(cod); sc = escopos_coop(c, nome); tipo = "coop"
            else:
                c = cod; sc = escopos_banco(cod, nome); tipo = "banco"
            for s in sc: agg[s].update(vals)
            if sc: agg["sfn"].update(vals)
            ult.append((tipo, c, nome, vals, sc))
        for s, v in agg.items():
            c = v["cart"] or 1
            ser[s].append({"d": am[:4] + "-" + am[4:], "cart": round(v["cart"] / 1e9, 2), "inad": round(v["inad"] / c * 100, 2),
                           "ap": round(v["ap"] / c * 100, 2), "basil": round(v["pr"] / v["rwa"] * 100, 1) if v["rwa"] else None,
                           "prov": round(v["pe"] / v["bruto"] * 100, 2) if v["bruto"] else None,
                           "cob": round(v["pe"] / v["ap"] * 100, 1) if v["ap"] else None})
        last = ult
    for tipo, c, nome, v, sc in last:
        if not sc or not v["cart"]: continue
        r = {"id": c, "tipo": tipo, "nome": nome, "cart": round(v["cart"] / 1e9, 3), "inad": round(v["inad"] / v["cart"] * 100, 2),
             "ap": round(v["ap"] / v["cart"] * 100, 2), "basil": round(v["pr"] / v["rwa"] * 100, 1) if v["rwa"] else None, "escopos": sc,
             "prov": round(v["pe"] / v["bruto"] * 100, 2) if v["bruto"] else None, "cob": round(v["pe"] / v["ap"] * 100, 1) if v["ap"] else None}
        if tipo == "coop":
            r.update({"curto": curto(c, nome), "sistema": sistema(c, nome), "central": central(c), "uf": coop.get(c, {}).get("UF", "")})
        else:
            r["curto"] = NOMES_BANCO.get(c) or re.sub(r"\s*-\s*PRUDENCIAL.*$", "", nome).title()
        inst.append(r)
    inst.sort(key=lambda r: -r["cart"])
    return {"ref": ref[:4] + "-" + ref[4:], "serie": ser, "inst": inst,
            "fonte": "Banco Central — IF.data (relatórios 16, carteira por instrumentos financeiros; 2, ativo — perda esperada das operações de crédito; 5, informações de capital)",
            "url": "https://www3.bcb.gov.br/ifdata/"}


# ---------- execução ----------
partes = {}
for nome, fn in (("scr", scr), ("cosif", cosif), ("ifd", ifdata)):
    try:
        partes[nome] = fn()
    except Exception as e:
        print(nome, "ERRO", e)
        partes[nome] = (ANT or {}).get(nome)
refs = {k: (v or {}).get("ref") for k, v in partes.items()}
ant_refs = (ANT or {}).get("meta", {}).get("refs", {})
if SE_MUDOU and ANT and refs == ant_refs:
    print(json.dumps({"risco": "sem mudança", "refs": refs})); sys.exit(0)
novo = {k: (refs[k] != ant_refs.get(k)) or ((ANT or {}).get("meta", {}).get("novo_desde", {}).get(k, HOJE.isoformat()) >= (HOJE - datetime.timedelta(days=7)).isoformat()) for k in refs}
novo_desde = {k: (HOJE.isoformat() if refs[k] != ant_refs.get(k) else (ANT or {}).get("meta", {}).get("novo_desde", {}).get(k, HOJE.isoformat())) for k in refs}
out = {"meta": {"atualizado": HOJE.isoformat(), "refs": refs, "novo_desde": novo_desde,
                "nota": "Cooperativas = singulares (centrais fora das somas). Conglomerado Sicoob/Sicredi = singulares do sistema + banco cooperativo. Bancos = conglomerados prudenciais."},
       "escopos": [{"id": a, "nome": b, "cor": c, "grupo": d} for a, b, c, d in ESCOPOS], **partes}
tmp = OUTFILE + ".tmp"
json.dump(out, open(tmp, "w"), ensure_ascii=False, separators=(",", ":"))
os.replace(tmp, OUTFILE)
print(json.dumps({"risco": refs, "kb": os.path.getsize(OUTFILE) // 1024}, ensure_ascii=False))
