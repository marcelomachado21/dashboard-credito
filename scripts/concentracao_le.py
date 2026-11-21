"""Leitura da tabela de concentração dos maiores devedores nas notas explicativas.

Entrada: texto de cada página do PDF (pdftotext -layout). Saída: as faixas publicadas, acumuladas, com valor e percentual.

Formatos conhecidos (nov/2026):
- acumulado: "Maior devedor / 10 / 20 / 50 / 100 maiores devedores" (ex.: Banco do Brasil, nota 12 j); singulares Sicoob: maior, 10 e 50.
- faixas seguintes: "10 maiores / 50 seguintes / 100 seguintes / demais", somando o total (ex.: Sicoob combinado, nota 9.1.2).
  Acumulando: 10, 60 e 160 maiores. Não existe o número de 50 nem de 100.
- faixas sem a palavra "seguintes" mas que somam o total com "demais" (ex.: Sicredi combinado, nota 9 d): só o 10 maiores é exato;
  as outras faixas ficam marcadas como ambíguas (não se sabe se vão até o 50º ou o 60º devedor) e não são usadas.

Regras: o percentual é o publicado pela instituição. Só se calcula percentual quando a própria tabela traz o total
(valor da faixa ÷ total da tabela). Nada é interpolado. Tabela que não passa nas conferências fica como "conferir".
"""
import re
import unicodedata

NPAL = {"um": 1, "dez": 10, "vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50, "cem": 100, "cento": 100, "duzentos": 200}
_N = r"(\d{1,3}|dez|vinte|trinta|quarenta|cinquenta|cem|cento|duzentos)"
_QUEM = r"(?:devedores|clientes|tomadores|grupos(?:\s+economicos)?)"
R_MAIOR = re.compile(r"^(?:o\s+)?maior(?:es)?\s+(?:devedor|cliente|tomador|grupo)\b")
R_SEG = re.compile(rf"^(?:os\s+)?(?:proximos\s+)?{_N}\s+(?:(?:maiores|principais)\s+)?(?:{_QUEM}\s+)?seguintes\b|^(?:os\s+)?{_N}\s+seguintes\b|^(?:os\s+)?proximos\s+{_N}\b")
R_TOP = re.compile(rf"^(?:os\s+)?{_N}\s+(?:maiores|principais|primeiros)\b|^(?:os\s+)?(?:maiores|principais)\s+{_N}\s+{_QUEM}")
R_DEMAIS = re.compile(r"^(?:demais|outros|restantes)\b")
R_TOTAL = re.compile(r"^total\b")
R_DATA = re.compile(r"(\d{2})[/.](\d{2})[/.](\d{2,4})")
R_NUM = re.compile(r"(?<![\w/,.])\(?-?\d{1,3}(?:\.\d{3})+(?:,\d+)?\)?%?(?![\w/])|(?<![\w/,.])\(?-?\d+(?:,\d+)?\)?%?(?![\w/])")
R_PASSIVO = re.compile(r"deposit|captac|passivo|fornecedor|credores|funding|recursos de clientes")
R_CRED = re.compile(r"operac\w* de credito|carteira de credito|carteira|concessao de credito|maiores devedores|devedor")
R_UNID_MIL = re.compile(r"em\s+milhares\s+de\s+reais|r\$\s*mil\b|em\s+r\$\s*mil|valores\s+em\s+milhares|\(em\s+milhares|milhares\s+de\s+reais")
R_UNID_MI = re.compile(r"em\s+milh[oõ]es\s+de\s+reais|r\$\s*milh[oõ]es|em\s+r\$\s*milh")


def sa(s):
    """Minúsculas, sem acento."""
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def _n(tok):
    tok = tok.strip()
    return NPAL[tok] if tok in NPAL else int(tok)


def rotulo(linha):
    """('maior'|'top'|'seg'|'demais'|'total', N) para uma linha da tabela, ou None."""
    t = sa(linha).strip().lstrip("-•*· ").strip()
    t = re.sub(r"^\(?[a-z0-9]{1,3}\)\s*", "", t) if re.match(r"^\(?[ivx]{1,4}\)\s", t) else t
    if R_MAIOR.match(t): return ("maior", 1)
    m = R_SEG.match(t)
    if m: return ("seg", _n(next(g for g in m.groups() if g)))
    m = R_TOP.match(t)
    if m: return ("top", _n(next(g for g in m.groups() if g)))
    if R_DEMAIS.match(t): return ("demais", None)
    if R_TOTAL.match(t): return ("total", None)
    return None


def numero(tok):
    """'1.551.209' -> 1551209.0; '0,6%' -> 0.6 (pct=True); '(1.234)' -> -1234."""
    t = tok.strip(); pct = t.endswith("%"); t = t.rstrip("%")
    neg = t.startswith("(") and t.endswith(")"); t = t.strip("()")
    v = float(t.replace(".", "").replace(",", "."))
    return (-v if neg else v), pct, ("," in t), (len(t.split(",")[1]) if "," in t else 0)


def _tokens(linha):
    out = []
    for m in R_NUM.finditer(linha):
        try: v, pct, dec, casas = numero(m.group())
        except ValueError: continue
        out.append({"v": v, "pct": pct, "dec": dec, "casas": casas, "x": (m.start() + m.end()) / 2, "txt": m.group()})
    return out


def _cabecalho(linhas, i0):
    """Datas e marcadores de % nas linhas acima da tabela: [(x, 'data', 'AAAA-MM'), (x, 'pct', None)]."""
    H = []
    for j in range(max(0, i0 - 8), i0):
        ln = linhas[j]
        for m in R_DATA.finditer(ln):
            d, mth, y = m.groups(); y = ("20" + y) if len(y) == 2 else y
            H.append(((m.start() + m.end()) / 2, "data", f"{y}-{mth}", j))
        for m in re.finditer(r"%|participa[cç][aã]o|percentual", ln, re.I):
            H.append(((m.start() + m.end()) / 2, "pct", None, j))
    return H


def _unidade(paginas, p):
    txt = sa(" ".join(paginas[max(0, p - 2):p + 1]))
    if R_UNID_MI.search(txt): return 1000.0                # valores em R$ milhões -> R$ mil
    if R_UNID_MIL.search(txt): return 1.0
    return None


def _nota(linhas, i0):
    """Título mais próximo acima da tabela (ex.: 'd) Concentração das operações de crédito')."""
    for j in range(i0 - 1, max(-1, i0 - 25), -1):
        t = linhas[j].strip()
        if re.match(r"^(?:\d{1,2}(?:\.\d{1,2}){0,3}|[a-z]\)|\([a-z]\)|[ivx]{1,4}\))\s*[-–.)]?\s*\S", t, re.I) and re.search(r"concentra|maiores|devedor", sa(t)):
            return re.split(r"\s{3,}", t)[0][:110]
    for j in range(i0 - 1, max(-1, i0 - 12), -1):
        t = linhas[j].strip()
        if re.search(r"concentra|maiores devedores", sa(t)): return re.split(r"\s{3,}", t)[0][:110]
    return ""


def blocos(paginas):
    """Tabelas candidatas: listas de linhas com rótulo de faixa, por página."""
    out = []
    for p, pg in enumerate(paginas):
        linhas = pg.split("\n"); i = 0
        while i < len(linhas):
            r = rotulo(linhas[i])
            if r and r[0] in ("maior", "top", "seg"):
                rows, j, buraco = [], i, 0
                while j < len(linhas) and buraco <= 2:
                    rr = rotulo(linhas[j])
                    if rr: rows.append((j, rr)); buraco = 0
                    elif linhas[j].strip(): buraco += 1
                    j += 1
                    if rr and rr[0] == "total": break
                bandas = [x for x in rows if x[1][0] in ("maior", "top", "seg")]
                if len(bandas) >= 2:
                    ctx = sa(" ".join(linhas[max(0, i - 12):i]))
                    out.append({"pagina": p + 1, "i0": i, "linhas": linhas, "rows": rows, "ctx": ctx})
                i = j if len(bandas) >= 2 else i + 1
            else:
                i += 1
    return out


def le_bloco(b, data_base, paginas):
    """Interpreta uma tabela. data_base 'AAAA-MM'. Devolve dict com faixas acumuladas e situação."""
    linhas, rows = b["linhas"], b["rows"]
    H = _cabecalho(linhas, rows[0][0])
    datas = sorted({h[2] for h in H if h[1] == "data"}, reverse=True)
    alvo = data_base if data_base in datas else (datas[0] if datas else None)
    if datas and data_base not in datas:
        return {"st": "conferir", "motivo": f"datas da tabela {datas}, data-base {data_base}", "pagina": b["pagina"]}
    hx = [h for h in H if h[1] == "data"]
    lin = []
    for (j, (tipo, n)) in rows:
        tk = _tokens(linhas[j])
        # tira o número que é parte do rótulo (ex.: o 10 de "10 maiores devedores")
        rot = re.match(r"^\s*\S+(?:\s+\S+){0,5}?\s+(?:devedor(?:es)?|clientes?|tomador(?:es)?|seguintes|demais|total|outros|restantes)\b", linhas[j], re.I)
        corte = rot.end() if rot else 0
        tk = [t for t in tk if t["x"] > corte]
        if len(hx) >= 2:                                    # duas datas: cada número vai para a coluna mais próxima do cabeçalho
            cols = sorted(((h[0], h[1], h[2]) for h in H if h[3] == max(hh[3] for hh in H if hh[1] == "data") or h[1] == "data"), key=lambda c: c[0])
            dono, ult = [], None
            for x, k, d in cols:                            # a coluna de % pertence à data à sua esquerda
                if k == "data": ult = d
                dono.append((x, d if k == "data" else (ult or next((c[2] for c in cols if c[1] == "data"), None))))
            meus = [t for t in tk if min(dono, key=lambda c: abs(c[0] - t["x"]))[1] == alvo]
            tk = meus or tk
        val = next((t["v"] for t in tk if not t["pct"] and not (t["dec"] and t["v"] <= 100 and len(tk) > 1 and t is tk[-1])), None)
        tp = next((t for t in tk if t["pct"]), None)
        if tp is None and len(tk) >= 2 and tk[-1]["v"] <= 100 and (tk[-1]["dec"] or tk[-1]["v"] < tk[0]["v"]):
            tp = tk[-1]
            if val == tp["v"]: val = tk[0]["v"]
        if tp is None and len(tk) == 1 and any(h[1] == "pct" for h in H) and tk[0]["v"] <= 100 and tk[0]["dec"]:
            tp, val = tk[0], None
        lin.append({"tipo": tipo, "n": n, "v": val, "p": tp["v"] if tp else None, "casas": tp["casas"] if tp else 2})
    bandas = [x for x in lin if x["tipo"] in ("maior", "top", "seg")]
    demais = next((x for x in lin if x["tipo"] == "demais"), None)
    total = next((x for x in lin if x["tipo"] == "total"), None)
    unid = _unidade(paginas, b["pagina"] - 1)
    res = {"pagina": b["pagina"], "nota": _nota(linhas, rows[0][0]), "unid_mil": unid, "data": alvo, "bruto": lin}
    if not bandas: return {**res, "st": "conferir", "motivo": "sem faixas"}
    tem_seg = any(x["tipo"] == "seg" for x in bandas)
    soma_total = None
    if total and total["v"] and demais and demais["v"] is not None and all(x["v"] is not None for x in bandas if x["tipo"] != "maior"):
        s = sum(x["v"] for x in bandas if x["tipo"] != "maior") + demais["v"]
        soma_total = abs(s - total["v"]) <= max(2, 0.003 * total["v"])
    incremental = tem_seg or soma_total is True
    if not incremental and demais and total and total["v"] and all(x["v"] is not None for x in bandas if x["tipo"] != "maior"):
        # sem "seguintes" e sem fechar a soma: tenta pelos valores (acumulado cresce)
        pass
    F, ambiguas = {}, []
    if incremental:
        acum_v, acum_p, n = 0.0, 0.0, 0
        for x in bandas:
            if x["tipo"] == "maior":
                if x["p"] is not None: F[1] = [x["v"], x["p"], x.get("casas", 2)]
                continue
            if x["tipo"] == "seg" or (n and x["tipo"] == "top" and not tem_seg):
                if not tem_seg:                            # "50 maiores" que somam com "demais": faixa sem fim conhecido
                    ambiguas.append(x["n"]); continue
                n += x["n"]
            else:
                n = x["n"]
            pv = x["p"]
            if pv is None and total and total["v"] and x["v"] is not None: pv = round(x["v"] / total["v"] * 100, 4)
            if x["v"] is not None: acum_v += x["v"]
            if pv is None: return {**res, "st": "conferir", "motivo": "faixa sem percentual"}
            acum_p += pv
            F[n] = [acum_v if x["v"] is not None else None, round(acum_p, 4), x.get("casas", 2)]
        res["formato"] = "seguintes" if tem_seg else "faixas_ambiguas"
    else:
        for x in bandas:
            pv = x["p"]
            if pv is None and total and total["v"] and x["v"] is not None: pv = round(x["v"] / total["v"] * 100, 4)
            if pv is None: return {**res, "st": "conferir", "motivo": "faixa sem percentual"}
            F[x["n"]] = [x["v"], pv, x.get("casas", 2)]
        res["formato"] = "acumulado"
    # conferências
    ks = sorted(F)
    ps = [F[k][1] for k in ks]
    if any(p is None or p <= 0 or p > 100 for p in ps): return {**res, "st": "conferir", "motivo": f"percentual fora de 0 a 100: {ps}"}
    if any(ps[i] > ps[i + 1] + 0.051 for i in range(len(ps) - 1)): return {**res, "st": "conferir", "motivo": f"acumulado não cresce: {ps}"}
    # base implícita (valor ÷ %): igual entre as faixas e igual ao total da tabela, dentro do arredondamento do % publicado
    tol = lambda k: 0.5 * 10 ** -F[k][2] / F[k][1] + 0.015
    bases = [(F[k][0] / F[k][1] * 100, tol(k)) for k in ks if F[k][0] and F[k][1] > 0]
    if len(bases) >= 2:
        ref = min(bases, key=lambda b: b[1])
        if any(abs(b[0] - ref[0]) / ref[0] > b[1] + ref[1] for b in bases):
            return {**res, "st": "conferir", "motivo": "base implícita difere entre as faixas"}
    if total and total["v"] and bases and any(abs(b[0] - total["v"]) / total["v"] > b[1] for b in bases):
        return {**res, "st": "conferir", "motivo": "base implícita difere do total da tabela"}
    res["faixas"] = {str(k): [round(F[k][0] * unid, 1) if (F[k][0] is not None and unid) else None, round(F[k][1], 2)] for k in ks}
    res["ambiguas"] = ambiguas
    res["st"] = "ok"
    return res


def le_documento(paginas, data_base):
    """Melhor tabela de concentração de devedores do documento: a primeira da carteira de crédito que passa nas conferências."""
    cands = [b for b in blocos(paginas) if not R_PASSIVO.search(b["ctx"][-400:])]
    if not cands: return {"st": "sem_tabela"}
    lidos = [le_bloco(b, data_base, paginas) for b in cands]
    ok = [r for r in lidos if r.get("st") == "ok"]
    if ok:
        r = ok[0]; r["outras_tabelas"] = len(lidos) - 1
        return r
    r = lidos[0]; r["outras_tabelas"] = len(lidos) - 1
    return r
