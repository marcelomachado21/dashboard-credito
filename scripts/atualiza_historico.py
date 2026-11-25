"""Histórico anual da Ficha da instituição (evolução por ano, variação em 1, 3 e 5 anos).

Uso:
  python3 atualiza_historico.py <pasta_raw> <pasta_saida> [--se-mudou] [--incorp=<csv>]

Gera <pasta_saida>/historico.json com os valores de junho e dezembro de cada ano, desde dez/2020, por instituição
(cooperativas singulares e conglomerados prudenciais, mesmos identificadores da base de posição) e por recorte
(soma das instituições do recorte), em R$ milhões:
  at   ativo total                        IF.data, relatório 1 (Resumo)
  cart carteira de crédito                até dez/24: "Carteira de Crédito Classificada" (Resumo); desde jun/25: carteira de
                                          instrumentos financeiros (relatório 16), a mesma das outras abas, lida da base de
                                          posição. O conceito mudou em jan/25 (Res. CMN 4.966): a tela não compara através da quebra.
  capt captações                          Resumo
  pl   patrimônio líquido                 Resumo
  luc  lucro ou sobras do semestre        Resumo (em junho, o 1º semestre; em dezembro, o 2º)
  bas  índice de Basileia, %              instituição: PR / RWA; recorte: soma do PR / soma do RWA (relatório 5)
Cooperativas incorporadas entram na incorporadora em todos os semestres (incorporacoes.csv), como nas outras bases.
Os recortes (escopos) e a lista de instituições vêm da base de posição publicada (posicao.json, na mesma pasta de saída).
"""
import json, os, sys, time, datetime, urllib.request, collections, csv

RAW, OUT = sys.argv[1], sys.argv[2]
SE_MUDOU = "--se-mudou" in sys.argv
AQUI = os.path.dirname(os.path.abspath(__file__))
arg = lambda k, d: next((a.split("=", 1)[1] for a in sys.argv if a.startswith(f"--{k}=")), d)
INCORP = arg("incorp", os.path.join(AQUI, "incorporacoes.csv"))
os.makedirs(OUT, exist_ok=True)
OUTFILE = os.path.join(OUT, "historico.json")
ANT = json.load(open(OUTFILE)) if os.path.exists(OUTFILE) else None
POS = json.load(open(os.path.join(OUT, "posicao.json")))
HOJE = datetime.date.today()
UA = {"User-Agent": "Mozilla/5.0 dashboard-credito"}
OLINDA = "https://olinda.bcb.gov.br/olinda/servico"
INICIO = "202012"
QUEBRA = "202501"           # Res. CMN 4.966: carteira com outro conceito a partir de jan/25


def olinda(path, tries=6):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{OLINDA}/{path}", headers=UA), timeout=300) as r:
                return json.loads(r.read())["value"]
        except Exception as e:
            err = e
            time.sleep(15 * (i + 1))             # o Olinda devolve 500 intermitente; espera crescente
    raise RuntimeError(f"{path}: {err}")


def ifvals(am, rel):
    d = olinda(f"IFDATA/versao/v1/odata/IfDataValores(AnoMes=@AnoMes,TipoInstituicao=@TipoInstituicao,Relatorio=@Relatorio)?@AnoMes={am}&@TipoInstituicao=1&@Relatorio='{rel}'&$format=json")
    out = collections.defaultdict(dict)
    for x in d:
        out[x["CodInst"]][(x["NomeColuna"] or "").split("\n")[0].strip()] = x["Saldo"]
    return out


INC = {r["cnpj_incorporada"]: r["cnpj_incorporadora"] for r in csv.DictReader(open(INCORP, encoding="utf-8"), delimiter=";")} if os.path.exists(INCORP) else {}
def suc(c, n=0): return suc(INC[c], n + 1) if c in INC and n < 10 else c


# ---------- semestres: de dez/20 até o último junho ou dezembro publicado no IF.data ----------
def semestres_ate(am):
    y, m = int(am[:4]), int(am[4:]); out = []
    while f"{y}{m:02d}" >= INICIO:
        out.append(f"{y}{m:02d}"); y, m = (y, 6) if m == 12 else (y - 1, 12)
    return sorted(out)

cand = f"{HOJE.year}{'06' if HOJE.month >= 7 else '12'}" if HOJE.month >= 7 else f"{HOJE.year - 1}12"
ult = None
for am in semestres_ate(cand)[::-1][:3]:            # o semestre mais recente pode ainda não estar publicado
    if olinda(f"IFDATA/versao/v1/odata/IfDataValores(AnoMes=@AnoMes,TipoInstituicao=@TipoInstituicao,Relatorio=@Relatorio)?@AnoMes={am}&@TipoInstituicao=1&@Relatorio='1'&$top=5&$format=json"):
        ult = am; break
if not ult: raise SystemExit("IF.data sem semestre publicado nas três últimas datas")
ref = ult[:4] + "-" + ult[4:]
if SE_MUDOU and ANT and ANT.get("meta", {}).get("ref") == ref and ANT["meta"].get("versao") == 1:
    print(json.dumps({"historico": "sem mudança", "ref": ref})); sys.exit(0)

DATAS = semestres_ate(ult)
TIPO = {i["id"]: i["tipo"] for i in POS["inst"]}
POS_CART = {(i["id"], t.replace("-", "")): v.get("cart") for i in POS["inst"] for t, v in i.get("s", {}).items()}   # R$ bi, relatório 16
CAMPOS = ["at", "cart", "capt", "pl", "luc", "pr", "rwa"]
V = collections.defaultdict(lambda: {k: [None] * len(DATAS) for k in CAMPOS})
for j, am in enumerate(DATAS):
    for tentativa in range(3):
        try:
            r1, r5 = ifvals(am, 1), ifvals(am, 5); break
        except Exception as e:
            print("IFDATA", am, "tentativa", tentativa + 1, e, file=sys.stderr); time.sleep(60)
    else:
        raise SystemExit(f"IF.data {am} não respondeu")
    soma = collections.defaultdict(collections.Counter); tem = collections.defaultdict(set)
    for cod, v1 in r1.items():
        c = suc(cod)
        if c not in TIPO: continue                 # instituição que não está mais no painel (encerrada ou fora do universo)
        v5 = r5.get(cod, {})
        g = lambda d, k: d.get(k) if k in d else next((d[x] for x in d if x.startswith(k)), None)   # nomes longos vêm cortados em alguns semestres
        cart = g(v1, "Carteira de Crédito Classificada") if am < QUEBRA else None
        for k, x in (("at", g(v1, "Ativo Total")), ("capt", g(v1, "Captações")), ("pl", g(v1, "Patrimônio Líquido")), ("luc", g(v1, "Lucro Líquido")),
                     ("pr", g(v1, "Patrimônio de Referência para Comparação") if g(v1, "Patrimônio de Referência para Comparação") is not None else g(v5, "Patrimônio de Referência para Comparação")),
                     ("rwa", g(v5, "Ativos Ponderados pelo Risco (RWA)")), ("cart", cart)):
            if x is not None: soma[c][k] += float(x); tem[c].add(k)
    for c, s in soma.items():
        for k in CAMPOS:
            if k in tem[c]: V[c][k][j] = round(s[k] / 1e6, 1)
    if am >= QUEBRA:                               # carteira desde jun/25: a do relatório 16, igual às outras abas
        for c in TIPO:
            x = POS_CART.get((c, am))
            if x is not None and c in V: V[c]["cart"][j] = round(x * 1000, 1)
    print(am, len(soma), "instituições", file=sys.stderr)

# ---------- recortes: soma das instituições (Basileia pelo PR e pelo RWA somados) ----------
membros = collections.defaultdict(list)
for i in POS["inst"]:
    for e in i.get("escopos", []): membros[e].append(i["id"])
    membros["sfn"].append(i["id"])
AGG = {}
for e, ids in membros.items():
    a = {k: [None] * len(DATAS) for k in CAMPOS}
    for j in range(len(DATAS)):
        for k in CAMPOS:
            vs = [V[c][k][j] for c in ids if c in V and V[c][k][j] is not None]
            if vs: a[k][j] = round(sum(vs), 1)
        if a["pr"][j] is not None and a["rwa"][j]:            # Basileia só com PR e RWA das mesmas instituições
            par = [(V[c]["pr"][j], V[c]["rwa"][j]) for c in ids if c in V and V[c]["pr"][j] is not None and V[c]["rwa"][j]]
            a["pr"][j], a["rwa"][j] = round(sum(p for p, _ in par), 1), round(sum(r for _, r in par), 1)
    AGG[e] = a

INST = {}
for c, v in V.items():
    o = {k: v[k] for k in ("at", "cart", "capt", "pl", "luc")}
    o["bas"] = [round(p / r * 100, 2) if p is not None and r else None for p, r in zip(v["pr"], v["rwa"])]
    if any(x is not None for x in o["at"]): INST[c] = o

dts = [d[:4] + "-" + d[4:] for d in DATAS]
novo_desde = ANT["meta"]["novo_desde"] if ANT and ANT.get("meta", {}).get("ref") == ref else HOJE.isoformat()
out = {"meta": {"versao": 1, "ref": ref, "datas": dts, "atualizado": HOJE.isoformat(), "novo_desde": novo_desde, "quebra_carteira": "2025-01",
                "unidade": "R$ mi", "url_ifd": "https://www3.bcb.gov.br/ifdata/",
                "fonte": "IF.data, Banco Central: relatórios 1 (Resumo) e 5 (Informações de Capital), conglomerados prudenciais e instituições independentes; carteira desde jun/25 pelo relatório 16"},
       "inst": INST, "agg": AGG}
tmp = OUTFILE + ".tmp"
with open(tmp, "w", encoding="utf-8") as f: json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
os.replace(tmp, OUTFILE)
print(json.dumps({"historico": ref, "semestres": len(dts), "instituicoes": len(INST), "kb": os.path.getsize(OUTFILE) // 1024}, ensure_ascii=False))
