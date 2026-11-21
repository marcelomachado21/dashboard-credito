#!/usr/bin/env python3
"""Concentração dos maiores devedores por instituição, semestre a semestre (junho e dezembro).

Fonte: notas explicativas das demonstrações financeiras, na Central de Demonstrações Financeiras do SFN (CDSFN, Banco Central):
documento 9010 (Cosif) e, se a tabela não estiver nele, 9030 (IFRS) ou 9060 (conglomerado prudencial). Tabela só com valores:
percentual sobre o total da carteira da mesma nota (ponto marcado como calculado).
Sicoob e Sicredi como sistema: demonstrações combinadas, nas páginas públicas dos sistemas.

Universo: as instituições da base de posição (cooperativas singulares e conglomerados/instituições bancárias do IF.data).
Banco: PDF da instituição líder do conglomerado (cadastro do IF.data). Itaú: a tabela está nas demonstrações da holding.

Rodada leve: só consulta o que falta (instituição × semestre sem resultado definitivo). Carga em lotes: para ao atingir o
limite de tempo (CONC_MINUTOS, padrão 120) e continua na rodada seguinte, de onde parou.
Saídas: concentracao.json (publicado) e concentracao_controle.json (situação de cada documento, para continuar a carga).
Uso: python3 -I scripts/atualiza_concentracao.py <pasta_brutos> <pasta_saida>
"""
import concurrent.futures as cf
import datetime
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from concentracao_le import le_documento          # noqa: E402
import concentracao_combinados as comb             # noqa: E402

RAW, OUT = sys.argv[1], sys.argv[2]
OUTFILE, CTRL = os.path.join(OUT, "concentracao.json"), os.path.join(OUT, "concentracao_controle.json")
LEITURA = 1                       # versão da leitura: subir quando a leitura melhorar, para reler "conferir" e "sem_tabela"
MINUTOS = float(os.environ.get("CONC_MINUTOS", "120"))
FIM = time.time() + MINUTOS * 60
INICIO = (2021, 6)
HOJE = datetime.date.today()
BASE = "https://www3.bcb.gov.br/informes/rest/balanco"
CDSFN = "https://www.bcb.gov.br/estabilidadefinanceira/cdsfn"
OLINDA = "https://olinda.bcb.gov.br/olinda/servico"
UA = {"User-Agent": "dashboard-credito (github actions)"}
TOP5 = {"C0080329": "bb", "C0080075": "bradesco", "C0080099": "itau", "C0080738": "caixa", "C0080185": "santander"}
LIDER_EXTRA = {"C0080099": ["60872504"]}         # Itaú Unibanco Holding: onde está a nota de concentração
# líderes dos conglomerados principais, para quando o cadastro do IF.data (Olinda) não responde
LIDER_FIXO = {"C0080329": "00000000", "C0080075": "60746948", "C0080099": "60701190", "C0080738": "00360305", "C0080185": "90400888",
              "C0080336": "30306294", "C0080996": "00416968", "C0084693": "18236120", "C0084844": "31872495", "C0084813": "08561701",
              "C0084820": "10573521", "C0080154": "92702067", "C0080879": "02038232", "C0080745": "01181521"}
TEXTOS = os.environ.get("CONC_TEXTOS")           # teste: grava o texto das páginas candidatas dos casos que não fecham
PARALELO = 4


def get(url, tries=4, timeout=300):
    err = None
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except Exception as e:
            err = e
            time.sleep(6 * (k + 1))
    raise RuntimeError(f"{url[:90]}: {err}")


def ler(p, padrao=None):
    try:
        with open(p, encoding="utf-8") as f: return json.load(f)
    except Exception: return padrao


def semestres():
    out, (y, m) = [], INICIO
    while True:
        fim = datetime.date(y, m, 30 if m == 6 else 31)
        if fim + datetime.timedelta(days=45) > HOJE: break
        out.append(f"{y}-{m:02d}")
        y, m = (y, 12) if m == 6 else (y + 1, 6)
    return out


def link_pdf(cnpj, am, doc):
    return f"{BASE}/download/{am}-{doc}-{cnpj}.pdf?cnpj={cnpj}&anoMes={am}&periodo=3"


def texto(pdf_bytes):
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(pdf_bytes); f.flush()
        p = subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, timeout=600)
    return p.stdout.decode("utf-8", "replace").split("\f")


def le_pdf(b, sem, chave=""):
    pg = texto(b)
    if sum(len(p.strip()) for p in pg) < 2000: return {"st": "sem_texto"}
    r = le_documento(pg, sem)
    if TEXTOS and (r["st"] in ("conferir", "sem_tabela") or os.environ.get("CONC_TEXTOS_OK")):
        import re as _re
        kw = _re.compile(r"maiores\s+devedores|maior\s+devedor|maiores\s+clientes|devedores\s+seguintes|concentra[çc][ãa]o", _re.I)
        cand = [i for i, t in enumerate(pg) if kw.search(t)]
        os.makedirs(TEXTOS, exist_ok=True)
        with open(os.path.join(TEXTOS, f"{chave}_{r['st']}.txt"), "w", encoding="utf-8") as fh:
            for j in sorted({j for i in cand for j in (i - 1, i, i + 1) if 0 <= j < len(pg)}): fh.write(f"\n=== página {j + 1} ===\n{pg[j]}")
    return r


def processa_cdsfn(cnpjs, sem):
    """Lista os documentos do semestre, baixa o PDF e lê a tabela. Devolve o resultado do melhor documento."""
    am, conferir, ultimo = sem.replace("-", ""), None, None
    for cnpj in cnpjs:
        docs = {}
        for per in (6, 3):                       # em junho, o IFRS (9030) só aparece na consulta trimestral
            for d in json.loads(get(f"{BASE}/?cnpj={cnpj}&anoMes={am}&periodo={per}", timeout=120)): docs.setdefault(d["nomeArquivo"], d)
        pdfs = sorted((d for d in docs.values() if d["nomeArquivo"].lower().endswith(".pdf") and d["tipo"]["codigo"] in (9010, 9030, 9060)
                       and d.get("anoMes") == am), key=lambda d: (9010, 9030, 9060).index(d["tipo"]["codigo"]))
        for d in pdfs:
            cod = d["tipo"]["codigo"]
            b = get(f"{BASE}/download/{urllib.parse.quote(d['nomeArquivo'])}?cnpj={cnpj}&anoMes={am}&periodo=3", timeout=600)
            r = le_pdf(b, sem, f"{cnpj}_{am}_{cod}")
            r.update(doc=cod, cnpj=cnpj)
            if r["st"] == "ok": return r                    # primeiro documento cuja tabela fecha
            if r["st"] == "conferir": conferir = conferir or r
            ultimo = ultimo if (ultimo and ultimo["st"] == "sem_tabela") else r
    return conferir or ultimo or {"st": "sem_doc"}


def confere_carteira(r, cart_bi, tipo):
    """Cooperativa: base implícita da tabela (valor ÷ %) entre 0,8 e 1,25 vez a carteira de crédito do IF.data na mesma data.
    Fora disso, a tabela vai para conferência: o % não está sobre a carteira de crédito. Banco não passa por esta conferência:
    as tabelas de banco têm bases próprias (avais, fianças, títulos, repasses às cooperativas) e a carteira do IF.data não
    serve de régua; nelas valem as conferências internas da tabela e as quebras de série."""
    if r.get("st") != "ok" or not cart_bi or tipo != "coop": return r
    for k in ("10", "50", "100", "20", "1", "60", "160"):
        f = (r.get("faixas") or {}).get(k)
        if f and f[0] and f[1]:
            razao = f[0] / f[1] * 100 / 1e6 / cart_bi
            lo, hi = (0.8, 1.25) if tipo == "coop" else (0.5, 2.0)
            if not lo <= razao <= hi:
                return {**r, "st": "conferir", "motivo": f"base implícita da tabela é {razao:.2f} vez a carteira de crédito do IF.data"}
            r["razao_carteira"] = round(razao, 2)
            break
    return r


def resumo(r):
    """Só o que vai para o controle (sem o texto bruto da tabela)."""
    k = ("st", "faixas", "formato", "pagina", "nota", "desc", "calc", "base", "doc", "cnpj", "motivo", "ambiguas", "url", "razao_carteira", "comp")
    return {x: r[x] for x in k if r.get(x) not in (None, "", [])}


def difere(fa, fb):
    """O mesmo semestre publicado com percentual diferente em dois documentos (base revista)?"""
    for k in ("10", "1", "20", "50", "100", "60", "160"):
        if k in fa and k in fb and fa[k][1] and fb[k][1]:
            a, b = fa[k][1], fb[k][1]
            return abs(a - b) > max(0.15, 0.04 * max(a, b))
    return False


def serie(C, chave, sems, confere=None):
    """Pontos publicados de uma instituição (ou sistema): o documento do próprio semestre e, na falta dele, a coluna
    comparativa do documento seguinte (marcada com 'de'). Quando o documento seguinte republica um semestre com outro
    percentual, o ponto seguinte leva 'rev' (a base mudou e a linha do gráfico é interrompida ali)."""
    def ponto(e, c=None):
        c = c or e
        p = {"f": c["faixas"], "doc": e.get("doc"), "pag": e.get("pagina"), "nota": (e.get("nota") or "")[:70], "fmt": c.get("formato")}
        if e.get("desc"): p["desc"] = e["desc"][:150]
        if c.get("calc"): p["calc"] = 1; p["base"] = (c.get("base") or "")[:90]
        if e.get("url"): p["url"] = e["url"]
        if e.get("cnpj"): p["c"] = e["cnpj"]
        return p
    out = {}
    for s in sems:
        e = C.get(f"{chave}|{s}")
        if e and e["st"] == "ok": out[s] = ponto(e)
    visto = set()
    for s in sems:                                   # do documento mais antigo para o mais novo: vale o primeiro comparativo
        e = C.get(f"{chave}|{s}")
        if not e or e["st"] != "ok": continue
        for d, c in sorted((e.get("comp") or {}).items()):
            if d not in sems or d >= s or d in visto: continue
            visto.add(d)
            if d in out and not out[d].get("de"):
                if difere(out[d]["f"], c["faixas"]): out[s]["rev"] = d
            elif d not in out and (confere is None or confere(c["faixas"], d)):
                out[d] = {**ponto(e, c), "de": s}
    return out


def pendente(e, sem):
    if not e: return True
    if e["st"] == "ok": return False
    if e["st"] == "erro": return True
    if e["st"] in ("conferir", "sem_tabela", "sem_texto"): return e.get("v", 0) < LEITURA
    if e["st"] == "sem_doc":                     # documento ainda não enviado ou não publicado: tenta de novo por até 15 meses
        y, m = map(int, sem.split("-"))
        idade = (HOJE.year - y) * 12 + HOJE.month - m
        return idade <= 15 and (HOJE - datetime.date.fromisoformat(e.get("ult", "2000-01-01"))).days >= 25
    return True


def lideres(ref_ifd, antes):
    """CodInst do conglomerado -> CNPJ (8 dígitos) da instituição líder, pelo cadastro do IF.data.
    Se o Olinda não responder, usa os da rodada anterior e, para os conglomerados principais, a lista fixa."""
    am = ref_ifd.replace("-", "")
    out = dict(antes or {})
    for k in range(6):
        try:
            cad = json.loads(get(f"{OLINDA}/IFDATA/versao/v1/odata/IfDataCadastro(AnoMes=@AnoMes)?@AnoMes={am}&$format=json", tries=1, timeout=300))["value"]
            novo = {x["CodInst"]: str(x.get("CnpjInstituicaoLider") or "").zfill(8)[:8] for x in cad if str(x.get("CodInst", "")).startswith("C")}
            out.update({c: v for c, v in novo.items() if v.strip("0") or c == "C0080329"})
            break
        except Exception as e:
            if k == 5: print("aviso: cadastro do IF.data indisponível; uso os líderes anteriores e a lista fixa:", e, file=sys.stderr)
            time.sleep(15 * (k + 1))
    for c, v in LIDER_FIXO.items(): out.setdefault(c, v)
    return out


def main():
    t0 = time.time()
    pos = ler(os.path.join(OUT, "posicao.json"))
    if not pos: raise SystemExit("posicao.json ausente: a base de posição precisa rodar antes")
    cad = (ler(os.path.join(OUT, "cadastro_coop.json"), {}) or {}).get("coop", {})
    ctrl = ler(CTRL, {}) or {}
    C, meta_c = ctrl.get("itens", {}), ctrl.get("meta", {})
    ant = ler(OUTFILE, {}) or {}
    sems = semestres()

    # universo: cooperativas singulares e bancos (sem centrais e confederações)
    nao_sing = {k for k, x in cad.items() if x.get("CLASSE") in ("Central", "Confederação")}
    univ = [i for i in pos["inst"] if not (i["id"] in nao_sing or (i["tipo"] == "banco" and "COOPERATIVA CENTRAL" in i["nome"].upper())
                                          or (i["tipo"] == "banco" and i["nome"].upper().startswith("CENTRAL ")))]
    if os.environ.get("CONC_SO"):                        # teste: só estas instituições
        so = set(os.environ["CONC_SO"].split(",")); univ = [i for i in univ if i["id"] in so]
    lid = lideres(pos["meta"]["ref"], meta_c.get("lideres", {}))
    cnpjs = lambda i: [i["id"]] if not i["id"].startswith("C") else (LIDER_EXTRA.get(i["id"], []) + ([lid[i["id"]]] if lid.get(i["id"]) else []))
    cart = lambda i: (i.get("s", {}).get(pos["meta"]["ref"]) or {}).get("cart") or 0
    cart_em = lambda i, s: (i.get("s", {}).get(s) or {}).get("cart")      # carteira (R$ bi) no IF.data, no mesmo mês
    ordem = sorted(univ, key=lambda i: (i["id"] not in TOP5, -cart(i)))

    # fila: semestres mais recentes primeiro; dentro do semestre, os 5 maiores e depois por tamanho da carteira
    fila = [(i, s) for s in reversed(sems) for i in ordem if cnpjs(i) and pendente(C.get(f"{i['id']}|{s}"), s)]
    print(f"universo {len(univ)} · semestres {sems[0]} a {sems[-1]} · pendentes {len(fila)}", flush=True)

    # sistemas: demonstrações combinadas do Sicoob e do Sicredi
    alertas = []
    for sis, fn in (("sicoob", comb.sicoob), ("sicredi", comb.sicredi)):
        falta = [s for s in sems if pendente(C.get(f"sis:{sis}|{s}"), s)]
        if not falta: continue
        try: links = fn(log=lambda *a: print(*a, flush=True))
        except Exception as e:
            alertas.append(f"página das combinadas do {sis.capitalize()} indisponível ({str(e)[:80]})"); links = {}
        for s in falta:
            k = f"sis:{sis}|{s}"
            if s not in links:
                C[k] = {**(C.get(k) or {}), "st": "sem_doc", "ult": HOJE.isoformat(), "v": LEITURA}; continue
            try:
                r = le_pdf(get(links[s], timeout=600), s, f"{sis}_{s}"); r["url"] = links[s]
                C[k] = {**resumo(r), "ult": HOJE.isoformat(), "v": LEITURA}
            except Exception as e:
                C[k] = {"st": "erro", "motivo": str(e)[:160], "ult": HOJE.isoformat(), "v": LEITURA}
            print(f"{sis} {s}: {C[k]['st']} {C[k].get('faixas', '')} {C[k].get('motivo', '')}", flush=True)

    # instituições: carga em paralelo, até o limite de tempo
    feitos, erros = 0, 0
    with cf.ThreadPoolExecutor(PARALELO) as ex:
        voando, it = {}, iter(fila)
        while True:
            while len(voando) < PARALELO * 2 and time.time() < FIM - 300:
                nxt = next(it, None)
                if nxt is None: break
                i, s = nxt
                if not pendente(C.get(f"{i['id']}|{s}"), s): continue
                voando[ex.submit(processa_cdsfn, cnpjs(i), s)] = (i, s)
            if not voando: break
            pronto, _ = cf.wait(voando, return_when=cf.FIRST_COMPLETED)
            for fu in pronto:
                i, s = voando.pop(fu); k = f"{i['id']}|{s}"
                try:
                    r = confere_carteira(fu.result(), cart_em(i, s), i["tipo"]); C[k] = {**resumo(r), "ult": HOJE.isoformat(), "v": LEITURA}
                except Exception as e:
                    erros += 1; C[k] = {"st": "erro", "motivo": str(e)[:160], "ult": HOJE.isoformat(), "v": LEITURA}
                feitos += 1
                if feitos % 100 == 0 or i["id"] in TOP5:
                    print(f"{feitos}/{len(fila)} · {i.get('curto') or i['nome'][:30]} {s}: {C[k]['st']} {C[k].get('faixas', '')}", flush=True)
    restantes = sum(1 for i, s in fila if pendente(C.get(f"{i['id']}|{s}"), s))

    # saída publicada: só o que passou nas conferências
    COD = {"ok": "o", "conferir": "c", "sem_tabela": "t", "sem_texto": "x", "sem_doc": "d", "erro": "e"}
    inst, cob = [], {s: {} for s in sems}
    for i in univ:
        sit = {}
        ok_carteira = lambda f, d, i=i: confere_carteira({"st": "ok", "faixas": f}, cart_em(i, d), i["tipo"])["st"] == "ok"
        s_ok = serie(C, i["id"], sems, ok_carteira)
        for p in s_ok.values():
            if p.get("c") == i["id"]: p.pop("c")
        for s in sems:
            e = C.get(f"{i['id']}|{s}")
            st = e["st"] if e else "pendente"
            cob[s][st] = cob[s].get(st, 0) + 1
            if st != "ok" and s not in s_ok:
                sit[s] = COD.get(st, "p")
                if st == "conferir": sit[s] += f":{e.get('doc', 9010)}:{e.get('cnpj', '')}:{e.get('pagina', '')}"
        x = {k: i.get(k) for k in ("id", "tipo", "nome", "curto", "numero", "uf", "sistema", "central") if i.get(k)}
        x["escopos"] = i.get("escopos", []); x["s"] = s_ok
        if sit: x["sit"] = sit
        if i["id"].startswith("C") and cnpjs(i): x["c"] = cnpjs(i)[0]
        inst.append(x)
    sistemas = {}
    for sis, nome in (("sicoob", "Sicoob (demonstrações combinadas)"), ("sicredi", "Sicredi (demonstrações combinadas)")):
        ss = serie(C, f"sis:{sis}", sems)
        for p in ss.values(): p.pop("doc", None)
        sistemas[sis] = {"nome": nome, "s": ss, "fonte": comb.SICOOB_RAIZ if sis == "sicoob" else comb.SICREDI_PAG}
    oks = {s: cob[s].get("ok", 0) for s in sems}
    ref = max((s for s in sems if oks[s] >= 50), default=(ant.get("meta") or {}).get("ref"))
    novo = sorted(k for k, e in C.items() if e.get("st") == "ok" and e.get("ult") == HOJE.isoformat())
    if restantes > 0: alertas.append(f"carga em andamento: {restantes} documentos ainda não consultados")
    pub = {"meta": {"ref": ref, "semestres": sems, "atualizado": HOJE.isoformat(),
                    "novo_desde": HOJE.isoformat() if novo else (ant.get("meta") or {}).get("novo_desde"),
                    "fonte": "Notas explicativas das demonstrações financeiras, Central de Demonstrações Financeiras do SFN (Banco Central)",
                    "url": CDSFN, "url_pdf": BASE + "/download/{am}-{doc}-{cnpj}.pdf?cnpj={cnpj}&anoMes={am}&periodo=3",
                    "leitura": LEITURA, "cobertura": cob, "pendentes": restantes, "alerta": "; ".join(alertas)},
           "sistemas": sistemas, "inst": inst}
    with open(OUTFILE, "w", encoding="utf-8") as f: json.dump(pub, f, ensure_ascii=False, separators=(",", ":"))
    with open(CTRL, "w", encoding="utf-8") as f:
        json.dump({"meta": {"lideres": lid, "atualizado": HOJE.isoformat(), "leitura": LEITURA}, "itens": C}, f, ensure_ascii=False, separators=(",", ":"))
    tot = {s: cob[s] for s in sems[-2:]}
    print(f"concentração: {feitos} documentos nesta rodada ({erros} com erro), {restantes} pendentes, ref {ref}, {round((time.time() - t0) / 60)} min · {tot}", flush=True)


if __name__ == "__main__":
    main()
