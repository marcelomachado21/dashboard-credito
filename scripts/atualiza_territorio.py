#!/usr/bin/env python3
"""Crédito rural por território, Brasil e cada UF (todo o SFN) -> data/territorio.json + data/territorio_uf/<UF>.json.

Fonte: Matriz de Dados do Crédito Rural (SICOR), API Olinda do Banco Central:
  CusteioMunicipioProduto (traz o código IBGE do município) e InvestMunicipioProduto (código do cadastro do SICOR,
  convertido em IBGE pela correspondência codCadMu -> codIbge do próprio custeio).
Não há corte por instituição nessa base; a comercialização só é publicada por UF e fica fora.
Uma UF por vez. UF cuja consulta falhar mantém o arquivo anterior e fica marcada em meta.ufs (situacao "mantido").
territorio.json: Brasil por UF (mesma estrutura dos municípios, com a UF no lugar do município) e a situação de cada UF.
territorio_uf/<UF>.json: municípios da UF, regiões do IBGE (scripts/ibge_regioes_br.csv).
Uso: python3 -I scripts/atualiza_territorio.py <pasta_bruta> <pasta_saida> [--se-mudou]
"""
import json, os, sys, time, datetime, urllib.request, urllib.parse, collections, csv
from concurrent.futures import ThreadPoolExecutor, as_completed

RAW, OUT = sys.argv[1], sys.argv[2]
SE_MUDOU = "--se-mudou" in sys.argv
HOJE = datetime.date.today()
OUTFILE = os.path.join(OUT, "territorio.json")
DIRUF = os.path.join(OUT, "territorio_uf")
ANT = json.load(open(OUTFILE)) if os.path.exists(OUTFILE) else None
if ANT and "ufs" not in ANT.get("meta", {}): ANT = None          # arquivo antigo, só de MG
H = {"User-Agent": "dashboard-credito"}
B = "https://olinda.bcb.gov.br/olinda/servico/SICOR/versao/v2/odata/"
URL = "https://olinda.bcb.gov.br/olinda/servico/SICOR/versao/v2/aplicacao#!/recursos"
# código de UF do SICOR (ordem das siglas). Conferido na própria resposta pelo prefixo do código IBGE dos municípios.
COD_UF = {"01": "AC", "02": "AL", "03": "AM", "04": "AP", "05": "BA", "06": "CE", "07": "DF", "08": "ES", "09": "GO", "10": None,
          "11": "MA", "12": "MG", "13": "MS", "14": "MT", "15": "PA", "16": "PB", "17": "PE", "18": "PI", "19": "PR", "20": "RJ",
          "21": "RN", "22": "RO", "23": "RR", "24": "RS", "25": "SC", "26": "SE", "27": "SP", "28": "TO"}
IBGE_UF = {"11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO", "21": "MA", "22": "PI", "23": "CE", "24": "RN",
           "25": "PB", "26": "PE", "27": "AL", "28": "SE", "29": "BA", "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR", "42": "SC",
           "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF"}
UF_IBGE = {v: k for k, v in IBGE_UF.items()}


T0 = time.time()
LIMITE = float(os.environ.get("TERR_LIMITE_MIN", "150")) * 60     # passado o limite, as UFs que faltam ficam com o dado anterior


def get(url, tries=5):
    for i in range(tries):
        if time.time() - T0 > LIMITE: raise RuntimeError("tempo da rotina esgotado antes desta consulta")
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=240) as r:
                return json.loads(r.read())["value"]
        except Exception:
            if i == tries - 1: raise
            time.sleep(min(30 * (i + 1), 90))


def baixa(ep, cod, ano, top=200000):
    """A API falha com $skip; consulta UF e ano de uma vez e, se falhar, mês a mês."""
    q = lambda f: f"{B}{ep}?$format=json&$top={top}&$filter=" + urllib.parse.quote(f)
    try:
        v = get(q(f"cdEstado eq '{cod}' and AnoEmissao eq '{ano}'"), tries=4)
        if len(v) >= top: raise RuntimeError("resposta truncada")
        return v
    except Exception:
        out = []
        for m in range(1, 13):
            if ano == HOJE.year and m > HOJE.month: break
            v = get(q(f"cdEstado eq '{cod}' and AnoEmissao eq '{ano}' and MesEmissao eq '{m:02d}'"))
            if len(v) >= top: raise RuntimeError("resposta truncada")
            out += v
        return out


S_HOJE = HOJE.year + 1 if HOJE.month >= 7 else HOJE.year              # safra pelo ano final (jul a jun)
ANOS = sorted({a for a in range(S_HOJE - 2, HOJE.year + 1)})
d_lim = HOJE - datetime.timedelta(days=20)                            # mês corrente e recém-encerrado ainda recebem registros
ULT_OK = (d_lim.replace(day=1) - datetime.timedelta(days=1)).strftime("%Y-%m")
mes = lambda x: f"{x['AnoEmissao']}-{x['MesEmissao']}"

# checagem barata de mudança: o mês mais recente publicado para MG
if SE_MUDOU and ANT:
    try:
        v = get(f"{B}CusteioMunicipioProduto?$format=json&$top=1&$orderby=AnoEmissao desc,MesEmissao desc&$select=AnoEmissao,MesEmissao&$filter="
                + urllib.parse.quote(f"cdEstado eq '12' and AnoEmissao eq '{HOJE.year}'"), tries=3)
        ref_novo = min(ULT_OK, mes(v[0])) if v else None
    except Exception:
        ref_novo = None
    falhas_ant = [u for u, x in ANT["meta"]["ufs"].items() if x.get("situacao") != "ok"]
    if ref_novo and ref_novo == ANT["meta"]["ref"] and not falhas_ant:
        print(json.dumps({"territorio": "sem mudança", "ref": ref_novo})); sys.exit(0)


def baixa_uf(cod):
    cus, inv = [], []
    for a in ANOS:
        cus += baixa("CusteioMunicipioProduto", cod, a)
        inv += baixa("InvestMunicipioProduto", cod, a)
    return cod, cus, inv


# MG primeiro: define o mês de referência; as demais UFs seguem, três consultas por vez (a API não aguenta muito mais)
ERROS = {}
for _t in range(3):                      # MG define a referência: até três tentativas antes de desistir da rodada
    try:
        _, CUS_MG, INV_MG = baixa_uf("12"); break
    except Exception as e:
        if _t == 2: raise
        print(f"aviso: MG falhou na tentativa {_t + 1} ({e}); nova tentativa em 3 minutos", file=sys.stderr); time.sleep(180)
if not CUS_MG: raise RuntimeError("API do SICOR sem custeio para MG")
REF = min(ULT_OK, max(mes(x) for x in CUS_MG + INV_MG))
if ANT and REF < ANT["meta"]["ref"]: REF = ANT["meta"]["ref"]
ry, rm = int(REF[:4]), int(REF[5:])
S = ry + 1 if rm >= 7 else ry
LIM = (rm - 7) % 12
def safra(x): y, m = int(x["AnoEmissao"]), int(x["MesEmissao"]); return y + 1 if m >= 7 else y
def pos(x): return (int(x["MesEmissao"]) - 7) % 12                # 0 = julho
pg_i = lambda x: 0 if x.get("cdPrograma") == "0001" else 1 if x.get("cdPrograma") == "0050" else 2
r3 = lambda v: round(v / 1e6, 3)

REG = {}
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ibge_regioes_br.csv"), encoding="utf-8") as f_:
    for x in csv.DictReader(f_, delimiter=";"):
        REG[x["cod_ibge"]] = {"n": x["municipio"], "uf": x["uf"], "mi": x["microrregiao"], "me": x["mesorregiao"], "ri": x["regiao_imediata"], "rt": x["regiao_intermediaria"]}


def agrega(cus, inv, chave):
    """chave(x, j) -> território ou None. Devolve mun, mun_p, prod, prog, mensal e o valor sem território."""
    M = collections.defaultdict(lambda: [0.0] * 6)          # [custeio, investimento] na safra até o mês (a), mesmo ponto (p), anterior inteira (t)
    MP = collections.defaultdict(lambda: [0.0] * 18)        # por programa: Pronaf, Pronamp e demais, 6 campos cada
    PR = collections.defaultdict(collections.Counter)
    PG = collections.defaultdict(lambda: [0.0, 0.0, 0.0])
    MEN = {str(S - 1): [0.0] * 12, str(S): [0.0] * 12}
    sem = [0.0, 0.0]
    for lst, vl, j in ((cus, "VlCusteio", 0), (inv, "VlInvest", 1)):
        for x in lst:
            if mes(x) > REF: continue
            v = float(x.get(vl) or 0); s_ = safra(x)
            if str(s_) in MEN: MEN[str(s_)][pos(x)] += v
            k = chave(x, j)
            if not k:
                sem[j] += v if s_ in (S, S - 1) else 0; continue
            if s_ == S and pos(x) <= LIM:
                M[k][j] += v; MP[k][6 * pg_i(x) + j] += v
                PR[k][x.get("nomeProduto", "").strip('"')] += v
                PG[k][pg_i(x)] += v
            if s_ == S - 1:
                M[k][4 + j] += v; MP[k][6 * pg_i(x) + 4 + j] += v
                if pos(x) <= LIM: M[k][2 + j] += v; MP[k][6 * pg_i(x) + 2 + j] += v
    tot_ok = sum(v[0] + v[1] for v in M.values()) + sum(v[4] + v[5] for v in M.values())
    return {"mun": {k: [r3(x) for x in v] for k, v in M.items() if any(v)},
            "mun_p": {k: [r3(x) for x in v] for k, v in MP.items() if any(v)},
            "prod": {k: [[n.capitalize() if n.isupper() else n, r3(v)] for n, v in c.most_common(6)] for k, c in PR.items()},
            "prog": {k: [r3(x) for x in v] for k, v in PG.items()},
            "mensal": {s_: [r3(x) for x in v] for s_, v in MEN.items()},
            "sem_municipio_pct": round((sem[0] + sem[1]) / (tot_ok + sem[0] + sem[1]) * 100, 2) if tot_ok + sem[0] + sem[1] else None}


os.makedirs(DIRUF, exist_ok=True)
ufs_meta, uf_de, LINHAS = {}, {}, [0]
BR = {"mun": {}, "mun_p": {}, "prod": {}, "prog": {}, "mensal": {str(S - 1): [0.0] * 12, str(S): [0.0] * 12}}


def processa(c, cus, inv):
    """Grava territorio_uf/<UF>.json e soma a UF no Brasil."""
    cnt = collections.Counter(IBGE_UF.get(str(x.get("codIbge") or "")[:2]) for x in cus); cnt.pop(None, None)
    if not cnt: return
    uf = cnt.most_common(1)[0][0]; uf_de[c] = uf
    if uf != COD_UF[c]: print(f"aviso: código {c} do SICOR é {uf}, não {COD_UF[c]}", file=sys.stderr)
    pre = UF_IBGE[uf]
    cad = {str(x["codCadMu"]): str(x["codIbge"])[:7] for x in cus if x.get("codCadMu") and x.get("codIbge")}
    def chave(x, j):
        k = str(x.get("codIbge") or "")[:7] if j == 0 else cad.get(str(x.get("cdMunicipio")), "")
        return k if k.startswith(pre) else None
    a = agrega(cus, inv, chave)
    regs = {k: {kk: v for kk, v in r.items() if kk != "uf"} for k, r in REG.items() if r["uf"] == uf}
    if len(a["mun"]) < 0.4 * len(regs) and uf not in ("DF", "AP", "RR", "AM", "AC"):
        ERROS[c] = f"só {len(a['mun'])} de {len(regs)} municípios com operação"; return
    novo_desde = HOJE.isoformat()
    try:
        old = json.load(open(os.path.join(DIRUF, uf + ".json")))
        if old["meta"]["ref"] == REF: novo_desde = old["meta"].get("novo_desde") or novo_desde
    except Exception: pass
    d = {"meta": {"uf": uf, "ref": REF, "safra": S, "mes_limite": LIM, "atualizado": HOJE.isoformat(), "novo_desde": novo_desde,
                  "sem_municipio_pct": a.pop("sem_municipio_pct"), "campos": ["custeio_a", "invest_a", "custeio_p", "invest_p", "custeio_t", "invest_t"],
                  "fonte": "Banco Central — Matriz de Dados do Crédito Rural (SICOR), custeio e investimento por município", "url": URL},
         "mun_reg": regs, **a}
    with open(os.path.join(DIRUF, uf + ".json.tmp"), "w") as fh: json.dump(d, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(os.path.join(DIRUF, uf + ".json.tmp"), os.path.join(DIRUF, uf + ".json"))
    ufs_meta[uf] = {"situacao": "ok", "ref": REF, "municipios": len(d["mun"])}
    b = agrega(cus, inv, lambda x, j: uf)                        # a UF inteira, para o mapa do Brasil
    for k in ("mun", "mun_p", "prod", "prog"): BR[k].update(b[k])
    for s_, v in b["mensal"].items(): BR["mensal"][s_] = [round(p + q, 3) for p, q in zip(BR["mensal"][s_], v)]
    LINHAS[0] += len(cus) + len(inv)


processa("12", CUS_MG, INV_MG); del CUS_MG, INV_MG
with ThreadPoolExecutor(max_workers=3) as ex:
    fut = {ex.submit(baixa_uf, c): c for c in COD_UF if c != "12"}
    for f in as_completed(fut):
        c = fut[f]
        try:
            _, cus, inv = f.result()
            if cus or inv: processa(c, cus, inv)
        except Exception as e:
            ERROS[c] = str(e)[:200]
            print(f"aviso: SICOR por município falhou para o código de UF {c} ({COD_UF[c]}): {e}", file=sys.stderr)

# UFs que falharam: fica o arquivo anterior, com aviso
for c, e in ERROS.items():
    uf = (ANT or {}).get("meta", {}).get("cod_uf", {}).get(c) or COD_UF[c]
    if not uf or uf in ufs_meta: continue
    try:
        old = json.load(open(os.path.join(DIRUF, uf + ".json")))
        ufs_meta[uf] = {"situacao": "mantido", "ref": old["meta"]["ref"], "motivo": e, "municipios": len(old["mun"])}
    except Exception:
        ufs_meta[uf] = {"situacao": "sem dado", "ref": None, "motivo": e}

# Brasil: a UF faz o papel do município. UF mantida entra com os números do arquivo anterior.
br = BR
for uf, m in ufs_meta.items():
    if m["situacao"] == "mantido" and ANT:
        for k in ("mun", "mun_p", "prod", "prog"):
            if uf in ANT.get(k, {}): br[k][uf] = ANT[k][uf]
out = {"meta": {"ref": REF, "safra": S, "mes_limite": LIM, "atualizado": HOJE.isoformat(),
                "novo_desde": (ANT or {}).get("meta", {}).get("novo_desde") if (ANT or {}).get("meta", {}).get("ref") == REF else HOJE.isoformat(),
                "ufs": dict(sorted(ufs_meta.items())), "cod_uf": {c: uf_de.get(c, COD_UF[c]) for c in COD_UF if uf_de.get(c, COD_UF[c])},
                "campos": ["custeio_a", "invest_a", "custeio_p", "invest_p", "custeio_t", "invest_t"],
                "fonte": "Banco Central — Matriz de Dados do Crédito Rural (SICOR), custeio e investimento por município", "url": URL},
       "mun": br["mun"], "mun_p": br["mun_p"], "prod": br["prod"], "prog": br["prog"], "mensal": br["mensal"]}
tmp = OUTFILE + ".tmp"
json.dump(out, open(tmp, "w"), ensure_ascii=False, separators=(",", ":"))
os.replace(tmp, OUTFILE)
print(json.dumps({"territorio": REF, "ufs_ok": sum(1 for x in ufs_meta.values() if x["situacao"] == "ok"),
                  "ufs_mantidas": [u for u, x in ufs_meta.items() if x["situacao"] != "ok"], "linhas": LINHAS[0]}, ensure_ascii=False))
