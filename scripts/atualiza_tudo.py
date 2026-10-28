#!/usr/bin/env python3
"""Orquestrador da atualização do Dashboard de Crédito.

Roda os cinco scripts numa cópia temporária de site/data, valida cada arquivo que mudou
e só então substitui o arquivo publicado. Arquivo reprovado fica como estava (último dado válido).
Grava site/data/status.json com o resultado de cada base, lido pela aba Fontes e metodologia.

Uso: python3 -I scripts/atualiza_tudo.py [--forcar]
  --forcar  roda os scripts sem --se-mudou (reprocessa tudo; usado no teste de paridade).
Variáveis: RAW_DIR (padrão: raw) para os arquivos brutos baixados do Banco Central.
"""
import json, os, sys, shutil, subprocess, time, datetime, urllib.request, tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
DATA = os.path.join(RAIZ, "site", "data")
RAW = os.path.abspath(os.environ.get("RAW_DIR", os.path.join(RAIZ, "raw")))
FORCAR = "--forcar" in sys.argv
HOJE = datetime.date.today().isoformat()

BASES = [  # (arquivo, script, pasta de brutos)
    ("safra", "atualiza_sicor.py", os.path.join(RAW, "sicor")),
    ("risco", "atualiza_risco.py", os.path.join(RAW, "bcb")),
    ("posicao", "atualiza_posicao.py", os.path.join(RAW, "bcb")),
    ("resultados", "atualiza_resultados.py", os.path.join(RAW, "bcb")),
    ("carteira", "atualiza_carteira.py", os.path.join(RAW, "bcb")),
]


def ler(p):
    try:
        with open(p, encoding="utf-8") as f: return json.load(f)
    except Exception: return None


def getjson(url, tries=5):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "dashboard-credito"}), timeout=120) as r:
                return json.load(r)
        except Exception:
            if i == tries - 1: raise
            time.sleep(10 * (i + 1))


def sgs_ultimos(cod, n=3):
    d = getjson(f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{cod}/dados/ultimos/{n}?formato=json")
    return {f"{x['data'][6:10]}-{x['data'][3:5]}": float(x["valor"]) for x in d}


# ---------------- checagens (as mesmas que a rotina do Claude fazia) ----------------
def faixa(v, lo, hi, nome):
    if v is None or not (lo <= v <= hi): raise AssertionError(f"{nome} = {v}, fora da faixa {lo} a {hi}")


def nao_recua(novo, velho, nome):
    if velho and novo and str(novo) < str(velho): raise AssertionError(f"{nome} recuou: {velho} → {novo}")


def chk_safra(n, a):
    m = n["meta"]; nao_recua(m["ref"], (a or {}).get("meta", {}).get("ref"), "referência do SICOR")
    S = m["safra_atual"]; tot = sum(sum(r[:4]) for r in n["serie"]["sfn"]["BR"][str(S - 1)])
    faixa(tot, 300_000, 450_000, f"safra {S - 1} do SFN (R$ mi)")
    if len(n["inst"]) <= 350: raise AssertionError(f"só {len(n['inst'])} instituições no SICOR")
    for g in ("coop_mg", "top5", "crediminas", "cong_sicoob"):
        if g not in n["comp"][str(S)]: raise AssertionError(f"recorte {g} ausente na safra")


def chk_risco(n, a):
    refs, ar = n["meta"]["refs"], (a or {}).get("meta", {}).get("refs", {})
    for k in refs: nao_recua(refs[k], ar.get(k), f"referência {k}")
    u = n["scr"]["serie"]["BR"]["sfn"]["total"][-1]
    s = sgs_ultimos(21082, 6)
    if u["d"] in s and abs(u["inad"] - s[u["d"]]) > 0.3:
        raise AssertionError(f"inadimplência SCR.data {u['inad']} contra SGS 21082 {s[u['d']]} em {u['d']}")
    faixa(n["ifd"]["serie"]["sfn"][-1]["basil"], 12, 25, "Basileia do SFN (IF.data)")
    if not n["scr"].get("rural_fin"): raise AssertionError("scr.rural_fin ausente")
    for g in ("coop_mg", "top5"):
        if g not in n["cosif"]["serie"]: raise AssertionError(f"recorte {g} ausente nos estágios")


def chk_posicao(n, a):
    t = n["meta"]["ref"]; nao_recua(t, (a or {}).get("meta", {}).get("ref"), "referência do IF.data")
    faixa(n["agg"]["sfn"][t]["basil"], 12, 25, "Basileia do SFN")
    for g, lo, hi in (("crediminas", 55, 80), ("cecremge", 40, 65)):
        k = sum(1 for i in n["inst"] if g in i["escopos"])
        if not lo <= k <= hi: raise AssertionError(f"{k} filiadas na {g}, esperado entre {lo} e {hi}")


def chk_resultados(n, a):
    nao_recua(n["meta"]["ref"], (a or {}).get("meta", {}).get("ref"), "referência dos balancetes")
    for g in ("sfn", "coop"): faixa(n["agg"][g]["r12"][-1]["roe"], 5, 30, f"ROE 12 meses ({g})")
    if "top5" not in n["agg"]: raise AssertionError("agregado top5 ausente")
    bb = next((x for x in n["inst"] if x["id"] == "C0080329"), None)
    if not bb or not bb.get("sem") or not bb["sem"][-1]["lucro"] > 0: raise AssertionError("lucro do BB ausente ou não positivo")


def chk_carteira(n, a):
    refs, ar = n["meta"]["refs"], (a or {}).get("meta", {}).get("refs", {})
    for k in refs: nao_recua(refs[k], ar.get(k), f"referência {k}")
    u = n["sgs"]["20539"]["p"][-1]; s = sgs_ultimos(20539, 3)
    if u["d"] in s and abs(u["v"] - s[u["d"]]) > 1: raise AssertionError(f"saldo SFN {u['v']} difere do SGS 20539 ({s[u['d']]})")
    if "top5" not in n["cosif"]: raise AssertionError("recorte top5 ausente na carteira")


CHK = {"safra": chk_safra, "risco": chk_risco, "posicao": chk_posicao, "resultados": chk_resultados, "carteira": chk_carteira}


def ref_de(nome, d):
    m = (d or {}).get("meta", {})
    return m.get("refs") or m.get("ref")


def main():
    t0 = time.time()
    status_ant = ler(os.path.join(DATA, "status.json")) or {}
    tmp = tempfile.mkdtemp(prefix="dash_")
    for f in os.listdir(DATA):
        if f.endswith(".json") and f != "status.json": shutil.copy2(os.path.join(DATA, f), tmp)
    bases = {}
    for nome, script, raw in BASES:
        os.makedirs(raw, exist_ok=True)
        p_pub, p_tmp = os.path.join(DATA, nome + ".json"), os.path.join(tmp, nome + ".json")
        antes = open(p_tmp, "rb").read() if os.path.exists(p_tmp) else b""
        cmd = [sys.executable, "-I", os.path.join(AQUI, script), raw, tmp] + ([] if FORCAR else ["--se-mudou"])
        ti = time.time(); r = None
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        except subprocess.TimeoutExpired:
            pass
        ok_run = r is not None and r.returncode == 0
        saida = (r.stdout.strip().splitlines() or [""])[-1][:300] if r else "tempo esgotado (60 min)"
        b = {"segundos": round(time.time() - ti), "saida": saida}
        if not ok_run:
            b.update(situacao="falhou", motivo=((r.stderr.strip().splitlines() or ["sem mensagem"])[-1][:300] if r else saida))
            if os.path.exists(p_pub): shutil.copy2(p_pub, p_tmp)
        else:
            depois = open(p_tmp, "rb").read()
            if depois == antes:
                b["situacao"] = "sem mudança"
            else:
                novo, velho = ler(p_tmp), ler(p_pub)
                try:
                    CHK[nome](novo, velho); shutil.copy2(p_tmp, p_pub); b["situacao"] = "atualizado"
                except Exception as e:
                    b.update(situacao="reprovado", motivo=f"{type(e).__name__}: {e}"[:300])
        b["ref"] = ref_de(nome, ler(p_pub))
        bases[nome] = b
        print(f"{nome}: {b['situacao']} · {b['ref']} · {b['segundos']} s" + (f" · {b.get('motivo')}" if b.get("motivo") else ""), flush=True)
    shutil.rmtree(tmp, ignore_errors=True)
    st = {"verificado_em": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
          "forcado": FORCAR, "segundos": round(time.time() - t0), "bases": bases,
          "ultima_atualizacao": HOJE if any(b["situacao"] == "atualizado" for b in bases.values()) else status_ant.get("ultima_atualizacao")}
    with open(os.path.join(DATA, "status.json"), "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    # código de saída 0 mesmo com falha parcial: o painel mantém o último dado válido e mostra o status
    return 0


if __name__ == "__main__":
    sys.exit(main())
