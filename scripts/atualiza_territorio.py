#!/usr/bin/env python3
"""Crédito rural por município em Minas Gerais (todo o SFN) -> data/territorio.json.

Fonte: Matriz de Dados do Crédito Rural (SICOR), API Olinda do Banco Central:
  CusteioMunicipioProduto (traz o código IBGE do município) e InvestMunicipioProduto (código do cadastro do SICOR,
  convertido em IBGE pela correspondência codCadMu -> codIbge do próprio custeio).
Não há corte por instituição nessa base; a comercialização só é publicada por UF e fica fora.
Regiões (micro, meso, imediata, intermediária): API de localidades do IBGE; se falhar, reaproveita o último arquivo.
Uso: python3 -I scripts/atualiza_territorio.py <pasta_bruta> <pasta_saida> [--se-mudou]
"""
import json, os, sys, time, datetime, urllib.request, urllib.parse, collections
RAW, OUT = sys.argv[1], sys.argv[2]
SE_MUDOU = "--se-mudou" in sys.argv
HOJE = datetime.date.today()
OUTFILE = os.path.join(OUT, "territorio.json")
ANT = json.load(open(OUTFILE)) if os.path.exists(OUTFILE) else None
H = {"User-Agent": "dashboard-credito"}
B = "https://olinda.bcb.gov.br/olinda/servico/SICOR/versao/v2/odata/"
UF_MG = "12"           # código de UF do SICOR para Minas Gerais


def get(url, tries=8):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=600) as r:
                return json.loads(r.read())["value"]
        except Exception:
            if i == tries - 1: raise
            time.sleep(min(30 * (i + 1), 180))


def baixa(ep, ano, top=200000):
    """A API falha com $skip; consulta UF e ano de uma vez e, se falhar, mês a mês."""
    q = lambda f: f"{B}{ep}?$format=json&$top={top}&$filter=" + urllib.parse.quote(f)
    try:
        v = get(q(f"cdEstado eq '{UF_MG}' and AnoEmissao eq '{ano}'"), tries=4)
        if len(v) >= top: raise RuntimeError("resposta truncada")
        return v
    except Exception:
        out = []
        for m in range(1, 13):
            if ano == HOJE.year and m > HOJE.month: break
            v = get(q(f"cdEstado eq '{UF_MG}' and AnoEmissao eq '{ano}' and MesEmissao eq '{m:02d}'"))
            if len(v) >= top: raise RuntimeError("resposta truncada")
            out += v
        return out


S = HOJE.year + 1 if HOJE.month >= 7 else HOJE.year              # safra pelo ano final (jul a jun)
anos = sorted({a for a in range(S - 2, HOJE.year + 1)})
cus, inv = [], []
for a in anos:
    cus += baixa("CusteioMunicipioProduto", a)
    inv += baixa("InvestMunicipioProduto", a)
if not cus: raise RuntimeError("API do SICOR sem custeio para MG")
mes = lambda x: f"{x['AnoEmissao']}-{x['MesEmissao']}"
ref = max(max(mes(x) for x in cus), max(mes(x) for x in inv) if inv else "")
if SE_MUDOU and ANT and ANT["meta"].get("ref") == ref:
    print(json.dumps({"territorio": "sem mudança", "ref": ref})); sys.exit(0)
# safra corrente até o mês de referência e o mesmo ponto da anterior
ry, rm = int(ref[:4]), int(ref[5:])
S = ry + 1 if rm >= 7 else ry
def safra(x): y, m = int(x["AnoEmissao"]), int(x["MesEmissao"]); return y + 1 if m >= 7 else y
def pos(x): return (int(x["MesEmissao"]) - 7) % 12                # 0 = julho
lim = (rm - 7) % 12
cad = {}
for x in cus:
    if x.get("codCadMu") and x.get("codIbge"): cad[str(x["codCadMu"])] = str(x["codIbge"])[:7]
nome_de = {}
def k_c(x): return str(x.get("codIbge") or "")[:7]
def k_i(x): return cad.get(str(x.get("cdMunicipio")), "")
# [custeio, investimento] na safra até o mês (a), mesmo ponto anterior (p) e safra anterior inteira (t)
M = collections.defaultdict(lambda: [0.0] * 6)
PR = collections.defaultdict(lambda: collections.Counter())
PG = collections.defaultdict(lambda: [0.0, 0.0, 0.0])
sem = [0.0, 0.0]
for lst, kf, vl, j in ((cus, k_c, "VlCusteio", 0), (inv, k_i, "VlInvest", 1)):
    for x in lst:
        k = kf(x); v = float(x.get(vl) or 0); s_ = safra(x)
        if not k.startswith("31"):
            sem[j] += v if s_ in (S, S - 1) else 0; continue
        nome_de[k] = x.get("Municipio", "")
        if s_ == S and pos(x) <= lim:
            M[k][j] += v
            PR[k][x.get("nomeProduto", "").strip('"')] += v
            p = x.get("cdPrograma"); PG[k][0 if p == "0001" else 1 if p == "0050" else 2] += v
        if s_ == S - 1:
            M[k][4 + j] += v
            if pos(x) <= lim: M[k][2 + j] += v
tot_ok = sum(v[0] + v[1] for v in M.values()); tot_sem = sem[0] + sem[1]
r3 = lambda v: round(v / 1e6, 3)
mun = {k: [r3(x) for x in v] for k, v in M.items() if any(v)}
prod = {k: [[n.capitalize() if n.isupper() else n, r3(v)] for n, v in c.most_common(6)] for k, c in PR.items()}
prog = {k: [r3(x) for x in v] for k, v in PG.items()}
reg, reg_fonte = {}, ""
try:
    with urllib.request.urlopen(urllib.request.Request("https://servicodados.ibge.gov.br/api/v1/localidades/estados/31/municipios", headers=H), timeout=120) as r:
        for x in json.loads(r.read()):
            mi = x.get("microrregiao") or {}; ri = x.get("regiao-imediata") or {}
            reg[str(x["id"])] = {"n": x["nome"], "mi": mi.get("nome", ""), "me": (mi.get("mesorregiao") or {}).get("nome", ""),
                                 "ri": ri.get("nome", ""), "rt": (ri.get("regiao-intermediaria") or {}).get("nome", "")}
    reg_fonte = "IBGE, API de localidades"
except Exception as e:
    reg = (ANT or {}).get("mun_reg", {}); reg_fonte = ((ANT or {}).get("meta", {}).get("regioes_fonte") or "") + (" (cópia anterior)" if reg else "")
    if not reg: reg = {k: {"n": n.title()} for k, n in nome_de.items()}; reg_fonte = "sem regiões: API do IBGE indisponível"
    print(f"aviso: regiões do IBGE indisponíveis ({e})", file=sys.stderr)
novo_desde = (ANT or {}).get("meta", {}).get("novo_desde") if (ANT or {}).get("meta", {}).get("ref") == ref else HOJE.isoformat()
out = {"meta": {"ref": ref, "safra": S, "mes_limite": lim, "atualizado": HOJE.isoformat(), "novo_desde": novo_desde,
                "sem_municipio_pct": round(tot_sem / (tot_ok + tot_sem) * 100, 2) if tot_ok + tot_sem else None, "regioes_fonte": reg_fonte,
                "campos": ["custeio_a", "invest_a", "custeio_p", "invest_p", "custeio_t", "invest_t"],
                "fonte": "Banco Central — Matriz de Dados do Crédito Rural (SICOR), custeio e investimento por município",
                "url": "https://olinda.bcb.gov.br/olinda/servico/SICOR/versao/v2/aplicacao#!/recursos"},
       "mun_reg": reg, "mun": mun, "prod": prod, "prog": prog}
tmp = OUTFILE + ".tmp"
json.dump(out, open(tmp, "w"), ensure_ascii=False, separators=(",", ":"))
os.replace(tmp, OUTFILE)
print(json.dumps({"territorio": ref, "municipios": len(mun), "linhas": len(cus) + len(inv), "kb": os.path.getsize(OUTFILE) // 1024}, ensure_ascii=False))
