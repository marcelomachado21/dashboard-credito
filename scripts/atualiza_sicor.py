"""Aba Safra (SICOR) do Dashboard de Crédito.

Uso:
  python3 atualiza_sicor.py <pasta_raw> <pasta_saida> [--se-mudou]

Baixa os microdados de operações do SICOR (Matriz de Dados do Crédito Rural, Banco Central),
as tabelas auxiliares e o cadastro de instituições, e grava <pasta_saida>/safra.json.
Com --se-mudou, só processa se o arquivo do ano corrente tiver Last-Modified diferente do último uso.

Convenções:
- Safra = julho a junho. Rótulo "2025/26" = jul/2025 a jun/2026.
- "Mesmo ponto da safra anterior" = mesmas datas de emissão, um ano antes.
- Valor = VL_PARC_CREDITO (valor contratado da operação), em R$ milhões.
- Operações = quantidade de #REF_BACEN distintos.
- UF = CD_ESTADO da operação (local do empreendimento), não a sede da instituição.
- Cooperativas = singulares e centrais (sem Banco Sicoob e Banco Sicredi, que ficam em "Bancos e demais").
- Conglomerado Sicoob/Sicredi = cooperativas e centrais do sistema + banco cooperativo do sistema.
  Bancos: conglomerado prudencial do IF.data.
- Nomes de cooperativas: tabela de-para do projeto (de_para_cooperativas.csv, --depara=<arquivo>).
- Incorporações: operações de instituição incorporada vão para a incorporadora em todo o histórico
  (incorporacoes.csv, --incorp=<arquivo>), para comparar bases iguais.
- Safras selecionáveis: as três mais recentes. Na corrente, compara até a data de referência;
  nas anteriores, safra fechada contra a safra fechada anterior.
"""
import json, os, sys, re, time, datetime, urllib.request, collections
import pandas as pd

RAW, OUT = sys.argv[1], sys.argv[2]
SE_MUDOU = "--se-mudou" in sys.argv
INCORP = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--incorp=")),
              os.path.join(os.path.dirname(os.path.abspath(__file__)), "incorporacoes.csv"))
DEPARA = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--depara=")),
              os.path.join(os.path.dirname(os.path.abspath(__file__)), "de_para_cooperativas.csv"))
os.makedirs(RAW, exist_ok=True); os.makedirs(OUT, exist_ok=True)
SICOR = "https://www.bcb.gov.br/htms/sicor"
OLINDA = "https://olinda.bcb.gov.br/olinda/servico"
UA = {"User-Agent": "Mozilla/5.0 dashboard-credito"}
HOJE = datetime.date.today()
OUTFILE = os.path.join(OUT, "safra.json")
ANT = json.load(open(OUTFILE)) if os.path.exists(OUTFILE) else None


def req(url, method="GET", timeout=600):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA, method=method), timeout=timeout)


def baixar(url, path):
    for i in range(4):
        try:
            with req(url) as r, open(path + ".tmp", "wb") as f:
                while True:
                    b = r.read(1 << 20)
                    if not b: break
                    f.write(b)
            os.replace(path + ".tmp", path); return
        except Exception as e:
            err = e
    raise RuntimeError(f"{url}: {err}")


def olinda(path):
    with req(f"{OLINDA}/{path}", timeout=180) as r:
        return json.loads(r.read())["value"]


# ---------- 1. arquivos ----------
s_atual = HOJE.year + 1 if HOJE.month >= 7 else HOJE.year           # rótulo pelo ano final
anos = list(range(s_atual - 4, HOJE.year + 1))                       # cobre 4 safras (3 selecionáveis + base de comparação)
url_ano = lambda y: f"{SICOR}/DadosBrutos/SICOR_OPERACAO_BASICA_ESTADO_{y}.gz"
lm = req(url_ano(HOJE.year), "HEAD", 60).headers.get("Last-Modified", "")
if SE_MUDOU and ANT and ANT["meta"].get("arquivo_last_modified") == lm:
    print(json.dumps({"safra": "sem mudança", "last_modified": lm})); sys.exit(0)
for y in anos:
    p = f"{RAW}/op_{y}.gz"
    if y >= HOJE.year - 1 or not os.path.exists(p):               # ano corrente e anterior sempre rebaixados
        baixar(url_ano(y), p)
for t in ("Empreendimento", "Programa", "FonteRecursos", "CategoriaEmitente"):
    baixar(f"{SICOR}/{t}.csv", f"{RAW}/{t}.csv")

# ---------- 2. operações ----------
cols = ["#REF_BACEN", "CNPJ_IF", "DT_EMISSAO", "CD_ESTADO", "CD_FONTE_RECURSO", "CD_PROGRAMA",
        "CD_EMPREENDIMENTO", "CD_CATEG_EMITENTE", "VL_PARC_CREDITO"]
dfs = []
for y in anos:
    d = pd.read_csv(f"{RAW}/op_{y}.gz", sep=";", usecols=cols, dtype=str, encoding="latin1")
    d["VL"] = pd.to_numeric(d.pop("VL_PARC_CREDITO"), errors="coerce").fillna(0)
    d["dt"] = pd.to_datetime(d.pop("DT_EMISSAO"), format="%d/%m/%Y", errors="coerce")
    dfs.append(d)
df = pd.concat(dfs, ignore_index=True).rename(columns={"#REF_BACEN": "REF"})
df = df[df.dt.notna()]
df["safra"] = df.dt.dt.year.where(df.dt.dt.month < 7, df.dt.dt.year + 1)
REF = df.dt.max().date()
S = REF.year + 1 if REF.month >= 7 else REF.year                     # safra corrente dos dados
SAFRAS = [S - 3, S - 2, S - 1, S]
SHOW = [S - 2, S - 1, S]
df = df[df.safra.isin(SAFRAS)].copy()
INC = {}
if os.path.exists(INCORP):
    import csv
    INC = {r["cnpj_incorporada"]: r["cnpj_incorporadora"] for r in csv.DictReader(open(INCORP, encoding="utf-8"), delimiter=";")}
def sucessor(c, n=0):
    return sucessor(INC[c], n + 1) if c in INC and n < 10 else c
mapa_inc = {c: sucessor(c) for c in df.CNPJ_IF.unique() if c in INC}
df["CNPJ_IF"] = df.CNPJ_IF.replace(mapa_inc)
df["m"] = (df.dt.dt.month - 7) % 12

emp = pd.read_csv(f"{RAW}/Empreendimento.csv", sep=";", dtype=str, encoding="latin1").rename(columns={"#CODIGO": "CD_EMPREENDIMENTO"})
emp = emp.drop_duplicates("CD_EMPREENDIMENTO")
df = df.merge(emp[["CD_EMPREENDIMENTO", "FINALIDADE", "ATIVIDADE", "PRODUTO"]], how="left")
sem_emp = df.FINALIDADE.isna().sum()
FIN = {"Custeio": "c", "Investimento": "i", "Comercialização": "m", "Industrialização": "n"}
df["fin"] = df.FINALIDADE.map(FIN).fillna("x")

# "mesmo ponto": até a data de referência, na safra corrente e um ano antes na anterior
try: REF_P = REF.replace(year=REF.year - 1)
except ValueError: REF_P = REF.replace(year=REF.year - 1, day=28)


def prog(c):
    return {"0001": "pronaf", "0050": "pronamp", "0999": "sem_programa"}.get(c, "outros")
FONTE = {"0201": "obrig", "0303": "poup_livre", "0430": "lca", "0431": "lca_eq", "0300": "poup_eq", "0505": "bndes_eq",
         "0506": "bndes", "0501": "fundos", "0502": "fundos", "0503": "fundos", "0800": "funcafe", "0100": "tesouro",
         "0402": "livres", "0403": "livres_eq", "0850": "livres"}
df["prog"] = df.CD_PROGRAMA.map(prog)
df["fonte"] = df.CD_FONTE_RECURSO.map(FONTE).fillna("outras")
df["porte"] = df.CD_CATEG_EMITENTE.map({"2222": "pequeno", "3333": "medio", "4444": "grande"}).fillna("outros")
MAQ = re.compile(r"TRATOR|M[ÁA]QUINA|COLHE|PLANTADEIRA|PULVERIZ|IMPLEMENT|CAMINH|SEMEADEIRA|ROÇADEIRA|DRONE|AERONAVE", re.I)
ARM = re.compile(r"ARMAZ|SILO|GALP|PAIOL|ESTUFA|SECADOR", re.I)
def produto(p):
    p = str(p or "").strip()
    if MAQ.search(p): return "Máquinas e equipamentos"
    if ARM.search(p): return "Armazenagem e benfeitorias"
    if p in ("AÇUCAR", "CANA-DE-AÇUCAR"): return "Cana-de-açúcar"
    if p.upper().startswith("AQUISIÇÃO DE INSUMOS PARA FORNECIMENTO"): return "Insumos para cooperados"
    if p.upper().startswith("TERRAÇOS"): return "Cercas, currais e terraços"
    if p.upper().startswith("BENEFICIAMENTO E INDUSTRIALIZA"): return "Beneficiamento e estocagem"
    p = p.split(",")[0].strip()
    return p.capitalize() if p.isupper() else p
df["prod"] = df.PRODUTO.map(produto)
df["geo"] = "BR"

# ---------- 3. instituições ----------
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from cadastro import sedes_coop   # cadastro protegido contra falhas do BC
from escopos import lista as lista_escopos, saida as saida_escopos, sistema_de as _sis, escopos_cooperativa, uf_do_escopo, SISTEMAS, UFS
coop = pd.DataFrame(list(sedes_coop(olinda).values()))
banc = pd.DataFrame(olinda("Instituicoes_em_funcionamento/versao/v1/odata/SedesBancoComMultCE?$format=json"))
cad = []
am = HOJE.year * 100 + (HOJE.month - 1) // 3 * 3
for _ in range(6):
    if am % 100 == 0: am = (am // 100 - 1) * 100 + 12
    try:
        cad = olinda(f"IFDATA/versao/v1/odata/IfDataCadastro(AnoMes=@AnoMes)?@AnoMes={am}&$format=json")
        if cad: break
    except Exception: pass
    am -= 3
cad = {x["CodInst"]: x for x in cad}
CO = {r.CNPJ: r for r in coop.itertuples()}
DP = {}
if os.path.exists(DEPARA):
    import csv
    DP = {r["cnpj"]: r for r in csv.DictReader(open(DEPARA, encoding="utf-8"), delimiter=";")}
BANCO_SISTEMA = {"02038232": "sicoob", "01181521": "sicredi"}
BA = {r.CNPJ: r for r in banc.itertuples()}

BANCO_CURTO = {"00000000": "Banco do Brasil", "60746948": "Bradesco", "60701190": "Itaú", "00360305": "Caixa",
               "90400888": "Santander", "07237373": "BNB", "04902979": "Banco da Amazônia", "01181521": "Banco Sicredi",
               "02038232": "Banco Sicoob", "58160789": "Safra", "92702067": "Banrisul", "92816560": "BRDE",
               "33657248": "BNDES", "30306294": "BTG Pactual", "15114366": "BBM", "28195667": "ABC Brasil",
               "91884981": "John Deere", "02992446": "CNH Capital", "05040481": "De Lage Landen"}
TOP5 = {"00000000": "bb", "60746948": "bradesco", "60701190": "itau", "00360305": "caixa", "90400888": "santander"}
DIGITAIS = re.compile(r"\bNU (FINANCEIRA|PAGAMENTOS)|NUBANK|BANCO INTER\b|\bC6\b|PAGSEGURO|PAGBANK|MERCADO PAGO|MERCADO CR[ÉE]DITO|BTG PACTUAL", re.I)
SIGLAS = {"MG", "SP", "RJ", "RS", "SC", "PR", "GO", "MT", "MS", "BA", "ES", "DF", "TO", "PA", "CE", "PE", "AL", "SE", "RN",
          "PB", "PI", "MA", "RO", "AC", "AM", "AP", "RR", "BH", "UNI", "SUL", "CO"}


CONECT = {"DE", "DO", "DA", "E", "DOS", "DAS", "EM", "NO", "NA"}


def bonito(s):
    out = []
    for w in re.split(r"(\s+|/|-)", s.strip()):
        u = w.upper()
        if u in SIGLAS and u not in ("UNI", "SUL", "CO"): out.append(u)
        elif u in CONECT: out.append(w.lower())
        elif w.strip() and w not in "/-": out.append(w.capitalize())
        else: out.append(w)
    t = "".join(out)
    return t[0].upper() + t[1:] if t else t


MARCA = re.compile(r"\b(SICOOB|SICREDI|CRESOL|UNICRED)\b", re.I)
LTDA = re.compile(r"\s*\bLTDA\b\.?\s*", re.I)
PREFIXO = re.compile(r"^COOPERATIVA\s+(DE\s+)?(CR[ÉE]DITO|ECONOMIA)(\s+E\s+(INVESTIMENTO|ECONOMIA|CR[ÉE]DITO\s+M[ÚU]TUO))?(\s+RURAL)?"
                     r"(\s*,[^,]*?(?=\s+(DE|DO|DA)\s)|\s+DE\s+PRODUTORES\s+RURAIS\s+E)?(\s+DE\s+LIVRE\s+ADMISS[ÃA]O)?(\s+DE\s+ASSOCIADOS)?\s*", re.I)


def curto_coop(nome):
    n = re.sub(r"\s+", " ", nome).strip()
    m = MARCA.search(n)
    if m:
        t = n[m.start():]
        if m.start() == 0 and " - " in t: t = t.split(" - ")[0]
        t = re.sub(r"^(\w+)\s*-\s*", r"\1 ", t)                    # "SICOOB - CREDIAL" -> "SICOOB CREDIAL"
        t = t.split(" - ")[0]
        t = re.sub(r"\s+COOPERATIVA\s+DE\s+CR[ÉE]DITO.*$", "", t, flags=re.I)
        if t.strip().upper() not in ("SICOOB", "SICREDI", "CRESOL", "UNICRED"):
            return bonito(LTDA.sub(" ", t).strip(" -."))
    if " - " in n:
        return bonito(LTDA.sub(" ", n.split(" - ")[-1]).strip(" -."))
    t = LTDA.sub(" ", PREFIXO.sub("", n)).strip(" -.,")
    t = re.sub(r"\s+(CR[ÉE]DITO\s+RURAL\s+)?COOPERATIVA$", "", t, flags=re.I)
    t = re.sub(r"^(DE|DO|DA|DOS|DAS)\s+", "", t, flags=re.I)
    t = bonito(t)
    return t if " " not in t else "Coop. " + t


sistema_de = _sis


def info(cnpj):
    c, b, k = CO.get(cnpj), BA.get(cnpj), cad.get(cnpj, {})
    nome = (c.NOME_INSTITUICAO if c is not None else b.NOME_INSTITUICAO if b is not None else k.get("NomeInstituicao") or f"CNPJ {cnpj}").strip()
    is_coop = c is not None or str(k.get("Tcb", "")).startswith("B3S")
    fil = (c.FILIACAO or "") if c is not None else ""
    uf = c.UF if c is not None else b.UF if b is not None else k.get("Uf") or ""
    r = {"cnpj": cnpj, "nome": nome, "tipo": "coop" if is_coop else "banco", "uf": uf}
    if is_coop:
        r["sistema"] = sistema_de(fil + " " + nome)
        r["central"] = "crediminas" if "CREDIMINAS" in fil.upper() else "cecremge" if "CECREMGE" in fil.upper() else ""
        dp = DP.get(cnpj, {})
        r["curto"] = dp.get("nome_curto") or curto_coop(nome)
        if dp.get("numero"):
            r["numero"] = dp["numero"]
            r["curto"] = dp["numero"] + " " + re.sub(r"^Sicoob[\s/-]+", "", r["curto"], flags=re.I).strip()
        r["cong"] = r["sistema"] if r["sistema"] != "outras" else cnpj
    else:
        r["curto"] = BANCO_CURTO.get(cnpj) or ("BDMG" if "DESENVOLVIMENTO DE MINAS" in nome.upper() else "") or bonito(re.sub(r"\b(BANCO|BCO|S\.?/?A\.?|S\.A)\b\.?", "", nome, flags=re.I).strip(" -.,"))[:32]
    if not is_coop:
        r["cong"] = BANCO_SISTEMA.get(cnpj) or k.get("CodConglomeradoPrudencial") or cnpj
    sc = ["sfn", "coop" if is_coop else "bancos"]
    if r["cong"] in ("sicoob", "sicredi"): sc.append("cong_" + r["cong"])
    if is_coop:   # solteira: singular sem central no cadastro do BC
        sing = str(getattr(c, "CLASSE", "Singular") or "Singular") == "Singular" if c is not None else False
        sc += [e for e in escopos_cooperativa(r["sistema"], uf, fil if c is not None else "x", sing) if e not in sc]
    if cnpj in TOP5: sc.append(TOP5[cnpj]); sc.append("top5")
    if not is_coop and DIGITAIS.search(nome): sc.append("digitais")
    r["escopos"] = sc
    return r


INST = {c: info(c) for c in df.CNPJ_IF.unique()}
INC_REV = collections.defaultdict(list)
for velho, novo in mapa_inc.items():
    INC_REV[novo].append({"cnpj": velho, "nome": (CO[velho].NOME_INSTITUICAO if velho in CO else (cad.get(velho) or {}).get("NomeInstituicao") or velho)})
digitais_achados = sorted({INST[c]["curto"] for c in INST if "digitais" in INST[c]["escopos"]})
MAP = pd.DataFrame([(c, s) for c, r in INST.items() for s in r["escopos"]], columns=["CNPJ_IF", "esc"])

ESCOPOS = lista_escopos()
ids_validos = {e[0] for e in ESCOPOS} | {"top5"}   # top5: recorte extra da ficha de grupo
PRESENTES = set(MAP.esc)


def guarda(esc, geo):
    """Recorte nacional: todas as UFs de operação. Recorte de UF: Brasil e a própria UF."""
    u = uf_do_escopo(esc)
    return u is None or geo in ("BR", u)


def destino(esc, geo):
    """'' = arquivo principal (Brasil e MG); 'SP' etc. = arquivo da UF, carregado sob demanda."""
    u = uf_do_escopo(esc)
    if u is None: return "" if geo in ("BR", "MG") else geo
    return "" if u == "MG" else u


# ---------- 4. agregados ----------
both = df          # cada operação conta duas vezes: no Brasil (geo) e na UF da operação (CD_ESTADO); agrupado em duas passadas para não duplicar a tabela
del df
GEOS = set(UFS) | {"BR"}


def gb(keys, fn, base=None):
    """Agrupa por keys, onde "geo" vale Brasil numa passada e a UF da operação na outra."""
    b = both if base is None else base
    partes = []
    for col in ("geo", "CD_ESTADO"):
        kk = [col if k == "geo" else k for k in keys]
        g = fn(b.groupby(kk, observed=True))
        g.index = g.index.set_names(keys)
        partes.append(g)
    r = pd.concat(partes)
    return r[r.index.get_level_values("geo").isin(GEOS)]


# instituições com o mesmo conjunto de recortes formam uma classe: soma-se por classe e só depois se abre por recorte
# (abrir por instituição × UF × recorte estoura a memória)
_cl = {}
CLS = {c: _cl.setdefault(tuple(sorted(r["escopos"])), len(_cl)) for c, r in INST.items()}
CLSMAP = pd.DataFrame([(k, e) for t, k in _cl.items() for e in t], columns=["cls", "esc"])
both["cls"] = both.CNPJ_IF.map(CLS).fillna(-1).astype("int32")


def por_escopo(keys, val="VL"):
    g = gb(["cls"] + keys, lambda x: x[val].sum()).reset_index()
    return g.merge(CLSMAP, on="cls").groupby(["esc"] + keys, observed=True)[val].sum()


def ops_por_escopo(keys):
    g = gb(["cls"] + keys, lambda x: x.REF.nunique()).reset_index()     # #REF_BACEN é de uma instituição só: soma por classe = soma por instituição
    return g.merge(CLSMAP, on="cls").groupby(["esc"] + keys, observed=True).REF.sum()


r1 = lambda v: round(float(v) / 1e6, 1)
FINS = ["c", "i", "m", "n"]
FIDX = {f: i for i, f in enumerate(FINS)}

mes = por_escopo(["geo", "safra", "m", "fin"])
mes_q = ops_por_escopo(["geo", "safra", "m"])
serie = collections.defaultdict(lambda: collections.defaultdict(dict))
NAC = [e for e in ids_validos if uf_do_escopo(e) is None]
base_eg = {(e, g) for e in NAC for g in ("BR", "MG")}
for esc, geo in sorted({(e, g) for e, g, *_ in mes.index if e in ids_validos and guarda(e, g)} | base_eg):
        for s in SAFRAS:
            rows = []
            for m in range(12):
                v = [r1(mes.get((esc, geo, s, m, f), 0)) for f in FINS]
                rows.append(v + [int(mes_q.get((esc, geo, s, m), 0))])
            serie[esc][geo][str(s)] = rows

DIMS = ("prog", "fonte", "porte", "prod")
ref_ts, refp_ts = pd.Timestamp(REF), pd.Timestamp(REF_P)
K_REF = (REF.month - 7) % 12                 # índice (0 = julho) do mês da data de referência na safra corrente


def calc(s, meses):
    """Safra s nos meses da safra indicados (0 = julho): "a" na safra s, "p" nos mesmos meses da safra anterior.
    Na safra corrente, "a" vai até a data de referência e "p" até o mesmo dia um ano antes (mesmo ponto)."""
    cur = s == S
    na = both.m.isin(list(meses))
    both["ytd"] = ""
    both.loc[na & (both.safra == s) & ((both.dt <= ref_ts) | (not cur)), "ytd"] = "a"
    both.loc[na & (both.safra == s - 1) & ((both.dt <= refp_ts) | (not cur)), "ytd"] = "p"
    ytd = por_escopo(["geo", "ytd", "fin"])
    ytd_q = ops_por_escopo(["geo", "ytd"])
    cs = collections.defaultdict(dict)
    for esc, geo in sorted({(e, g) for e, g, *_ in ytd.index if e in ids_validos and guarda(e, g)} | base_eg):
            cs[esc][geo] = {k: [r1(ytd.get((esc, geo, k, f), 0)) for f in FINS] + [int(ytd_q.get((esc, geo, k), 0))] for k in ("a", "p")}
    cd = {}
    for dim in DIMS:
        t = por_escopo(["geo", "ytd", dim])
        d = collections.defaultdict(lambda: collections.defaultdict(dict))
        for (esc, geo, k, cat), v in t.items():
            if k in ("a", "p") and esc in ids_validos and guarda(esc, geo):
                d[esc][geo].setdefault(cat, [0, 0])[0 if k == "a" else 1] = r1(v)
        if dim == "prod":   # mantém os 12 maiores produtos de cada escopo/UF
            for esc in d:
                for geo in d[esc]:
                    it = sorted(d[esc][geo].items(), key=lambda x: -x[1][0])
                    top, rest = it[:12], it[12:]
                    d[esc][geo] = dict(top) | ({"Demais produtos": [round(sum(x[1][0] for x in rest), 1), round(sum(x[1][1] for x in rest), 1)]} if rest else {})
        cd[dim] = d
    pi = gb(["CNPJ_IF", "geo", "ytd", "fin"], lambda x: x.VL.sum())
    pq = gb(["CNPJ_IF", "geo"], lambda x: x.REF.nunique(), both[both.ytd == "a"])
    acc = collections.defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, 0.0])
    for (c, geo, k, f), v in pi.items():
        if k == "a" and f in FIDX: acc[(c, geo)][FIDX[f]] += v
        elif k == "p": acc[(c, geo)][4] += v
    ie = collections.defaultdict(dict)
    for (c, geo), v in acc.items():
        a = [r1(x) for x in v[:4]]; p = round(v[4] / 1e6, 1)
        if sum(a) or p:
            ie[c][geo] = {"a": a, "p": p, "q": int(pq.get((c, geo), 0))}
    return cs, cd, ie


comp, cortes = {}, {dim: {} for dim in DIMS}
IN = collections.defaultdict(lambda: collections.defaultdict(dict))
for s in SHOW:
    cs, cd, ie = calc(s, range(12))
    comp[str(s)] = cs
    for dim in DIMS: cortes[dim][str(s)] = cd[dim]
    for c, g in ie.items():
        for geo, v in g.items(): IN[c][geo][str(s)] = v

# trimestres e semestres da safra (jul–set, out–dez, jan–mar, abr–jun; jul–dez, jan–jun), cada um contra o mesmo período da safra anterior
PERIODOS = {"t1": range(0, 3), "t2": range(3, 6), "t3": range(6, 9), "t4": range(9, 12), "s1": range(0, 6), "s2": range(6, 12)}
per = {}
for k, meses in PERIODOS.items():
    P = {"comp": {}, "cortes": {dim: {} for dim in DIMS}, "inst": collections.defaultdict(lambda: collections.defaultdict(dict))}
    for s in SHOW:
        if s == S and meses[0] > K_REF: continue          # período ainda não começou na safra corrente
        cs, cd, ie = calc(s, meses)
        P["comp"][str(s)] = cs
        for dim in DIMS: P["cortes"][dim][str(s)] = cd[dim]
        for c, g in ie.items():
            for geo, v in g.items(): P["inst"][INST[c]["cnpj"]][geo][str(s)] = v
    per[k] = P

inst = []
for c, r in INST.items():
    if "BR" not in IN[c]: continue
    o = {k: r[k] for k in ("cnpj", "curto", "nome", "tipo", "uf", "cong") if k in r}
    o.update({k: r[k] for k in ("sistema", "central", "numero") if r.get(k)})
    o["escopos"] = [e for e in r["escopos"] if e != "sfn"]
    o.update(IN[c])
    if c in INC_REV: o["incorporou"] = INC_REV[c]
    inst.append(o)
inst.sort(key=lambda x: -sum(x["BR"].get(str(S), {"a": [0]})["a"]))

cong_nomes = {s: n for _, s, n, _c in SISTEMAS}
for r in INST.values():
    cg = r.get("cong", "")
    if cg.startswith("C0") and cg not in cong_nomes:
        lider = (cad.get(cg) or {}).get("CnpjInstituicaoLider") or ""
        bruto = re.sub(r"\s*-\s*PRUDENCIAL.*$", "", (cad.get(cg) or {}).get("NomeInstituicao") or cg, flags=re.I)
        cong_nomes[cg] = BANCO_CURTO.get(lider) or bonito(re.sub(r"\b(BANCO|BCO)\b", "", bruto).strip(" -."))
lm_hist = (ANT or {}).get("meta", {})
novo_desde = lm_hist.get("novo_desde") if lm_hist.get("ref") == REF.isoformat() else HOJE.isoformat()
meta = {
    "ref": REF.isoformat(), "ref_anterior": REF_P.isoformat(), "safras": SAFRAS, "safra_atual": S,
    "atualizado": HOJE.isoformat(), "novo_desde": novo_desde, "arquivo_last_modified": lm,
    "fonte": "Banco Central — Matriz de Dados do Crédito Rural (SICOR), microdados de operações",
    "url": "https://www.bcb.gov.br/estabilidadefinanceira/micrrural",
    "url_dados": url_ano(HOJE.year),
    "cadastro": f"Banco Central — Relação de instituições em funcionamento e IF.data cadastro ({am})",
    "sem_empreendimento": int(sem_emp), "digitais_com_operacao": digitais_achados,
    "cong_nomes": cong_nomes, "depara": os.path.basename(DEPARA) if DP else "", "safras_sel": SHOW,
    "incorporacoes_aplicadas": len(mapa_inc),
}
UFD = collections.defaultdict(lambda: {"serie": {}, "comp": {}, "cortes": {}, "per": {}, "inst_geo": {}})


def parte(d_eg, caminho):
    """d_eg[esc][geo] -> fica no principal o que é de Brasil/MG; o resto vai para o arquivo da UF, no mesmo caminho."""
    principal = {}
    for esc, gs in d_eg.items():
        for geo, v in gs.items():
            u = destino(esc, geo)
            if not u: principal.setdefault(esc, {})[geo] = v
            else:
                n = UFD[u]
                for k in caminho: n = n.setdefault(k, {})
                n.setdefault(esc, {})[geo] = v
    return principal


serie = parte(serie, ["serie"])
comp = {s: parte(v, ["comp", s]) for s, v in comp.items()}
cortes = {dim: {s: parte(v, ["cortes", dim, s]) for s, v in x.items()} for dim, x in cortes.items()}
for k, P in per.items():
    P["comp"] = {s: parte(v, ["per", k, "comp", s]) for s, v in P["comp"].items()}
    P["cortes"] = {dim: {s: parte(v, ["per", k, "cortes", dim, s]) for s, v in x.items()} for dim, x in P["cortes"].items()}
    for cn, gs in P["inst"].items():
        for geo in [g for g in gs if g not in ("BR", "MG")]:
            UFD[geo]["per"].setdefault(k, {}).setdefault("inst", {}).setdefault(cn, {})[geo] = gs.pop(geo)
for o in inst:
    for geo in [g for g in o if g in UFS and g != "MG"]:
        UFD[geo]["inst_geo"].setdefault(o["cnpj"], {})[geo] = o.pop(geo)
DIRUF = os.path.join(OUT, "safra_uf"); os.makedirs(DIRUF, exist_ok=True)
for u, d in UFD.items():
    d["meta"] = {"uf": u, "ref": REF.isoformat()}
    with open(os.path.join(DIRUF, u + ".json.tmp"), "w") as fh: json.dump(d, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(os.path.join(DIRUF, u + ".json.tmp"), os.path.join(DIRUF, u + ".json"))
meta["ufs_operacao"] = sorted(UFD) + ["MG"]
out = {"meta": meta, "escopos": saida_escopos(ESCOPOS, PRESENTES),
       "serie": serie, "comp": comp, "cortes": cortes, "inst": inst, "per": per}
tmp = OUTFILE + ".tmp"
json.dump(out, open(tmp, "w"), ensure_ascii=False, separators=(",", ":"))
os.replace(tmp, OUTFILE)
print(json.dumps({"safra": REF.isoformat(), "instituicoes": len(inst), "kb": os.path.getsize(OUTFILE) // 1024,
                  "digitais": digitais_achados, "sem_empreendimento": int(sem_emp)}, ensure_ascii=False))

