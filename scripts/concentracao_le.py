"""Leitura da tabela de concentração dos maiores devedores nas notas explicativas.

Entrada: texto de cada página do PDF (pdftotext -layout). Saída: as faixas publicadas, acumuladas, com valor e percentual.

Formatos (amostra de nov/2026, bancos e cooperativas de todos os sistemas):
- acumulado: "Maior devedor / 10 / 20 / 50 / 100 maiores devedores" (BB, Itaú, Bradesco, Santander, Caixa, Inter; singulares Sicoob:
  maior, 10 e 50). Pode ter duas datas e duas visões (múltiplo e consolidado): fica a data-base e, se houver, o consolidado.
- faixas por intervalo: "0 - 10 / 11 - 50 / 51 - 100 maiores devedores / acima de 100" (Cresol): exatas, acumuladas por soma.
- faixas seguintes: "10 maiores / 50 seguintes / 100 seguintes / demais" (combinado Sicoob, Viacredi, Unicred, Banrisul, BTG).
  Acumulando: 10, 60 e 160 maiores (ou 1 + 10 seguintes = 11...). Não existe o número de 50 nem de 100.
- faixas sem a palavra "seguintes" que somam o total com "demais" (Sicredi): só a primeira faixa (10 maiores) é exata.
- frase no relatório ou na nota: "os vinte maiores devedores representavam ... 16,65% da carteira" (algumas singulares Sicoob).

Regras: o percentual é o publicado. Tabela só com valores: o percentual sai do total da carteira da mesma nota (a linha
"Total" da própria tabela ou do quadro vizinho com a mesma data, na mesma página, como o quadro por setor ou por vencimento),
e o ponto fica marcado como calculado. Nada é interpolado. Tabela que não passa nas conferências fica como "conferir" e não
é usada.
"""
import re
import unicodedata

NPAL = {"um": 1, "dez": 10, "vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50, "sessenta": 60, "cem": 100, "cento": 100,
        "duzentos": 200, "quinhentos": 500}
_N = r"(\d{1,3}|dez|vinte|trinta|quarenta|cinquenta|sessenta|cem|cento|duzentos|quinhentos)"
_QUEM = r"(?:devedores|clientes|tomadores|grupos(?:\s+economicos)?|contrapartes)"
R_MAIOR = re.compile(r"^(?:o\s+)?(?:maior(?:es)?\s+(?:devedor|cliente|tomador|grupo|contraparte)|principal\s+(?:devedor|cliente|tomador))\b")
R_RNG = re.compile(rf"^(\d{{1,3}})\s*(?:-|a|ate|ao)\s*(\d{{1,3}})\s*(?:o?s?\s+)?(?:(?:maiores|principais|primeiros)\s*)?{_QUEM}?")
R_SEG = re.compile(rf"^(?:os\s+)?(?:proximos\s+)?{_N}\s+(?:(?:maiores|principais)\s+)?(?:{_QUEM}\s+)?seguintes\b|^(?:os\s+)?{_N}\s+seguintes\b|^(?:os\s+)?proximos\s+{_N}\b")
R_TOP = re.compile(rf"^(?:os\s+)?{_N}\s+(?:maiores|principais|primeiros)\b|^(?:os\s+)?(?:maiores|principais)\s+{_N}\s+{_QUEM}")
R_DEMAIS = re.compile(r"^(?:demais|outros|restantes|acima\s+d[eo]s?\s+\d+|a\s+partir\s+do\s+\d+)\b")
R_TOTAL = re.compile(r"^(?:total|saldo\s+final|saldo\s+total|total\s+geral|carteira\s+total)\b")
R_NUM = re.compile(r"(?<![\w/,.])\(?-?\d{1,3}(?:\.\d{3})+(?:,\d+)?\)?(?:\s?%)?(?![\w/])|(?<![\w/,.])\(?-?\d+(?:[,.]\d+)?\)?(?:\s?%)?(?![\w/])")
R_EXCL = re.compile(r"deposit|captac|passivo|fornecedor|credores|repasse|interfinanceir|individualmente significativ|perda esperada|impairment|"
                    r"provisao para|baixad|recuperad|renegociad|garantias recebidas|cedid|transacoes de pagamento|valores a receber")
R_UNID_MIL = re.compile(r"em\s+milhares\s+de\s+reais|r\$\s*mil\b|em\s+r\$\s*mil|valores\s+em\s+milhares|\(em\s+milhares|milhares\s+de\s+reais|r\$\s*-\s*mil|"
                        r"expressos\s+em\s+milhares|\bem\s+milhares\b")
R_UNID_MI = re.compile(r"em\s+milh[oõ]es\s+de\s+reais|r\$\s*milh[oõ]es|em\s+r\$\s*milh")
MESES = {"janeiro": "01", "fevereiro": "02", "marco": "03", "abril": "04", "maio": "05", "junho": "06", "julho": "07", "agosto": "08",
         "setembro": "09", "outubro": "10", "novembro": "11", "dezembro": "12"}


def sa(s):
    """Minúsculas, sem acento."""
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def _n(tok):
    tok = tok.strip()
    return NPAL[tok] if tok in NPAL else int(tok)


R_QUEBRA = re.compile(r"\d [.,]\d|\d[.,] \d|\d ?/ ?\d|[.,]\d{1,2} \d{1,2}(?![\d.,])")


def _conserta(ln):
    """PDF com glifos espaçados (Itaú): '5 .984' -> '5.984', '0 ,6%' -> '0,6%', '11 6 .06 1' -> '116.061',
    '31 /12/2021' -> '31/12/2021', '1O Maiores' -> '10 Maiores'. Só junta dentro da coluna (espaço simples), e só na linha
    que tem número quebrado."""
    ln = re.sub(r"(?<![\d.,])1\s?[Oo](?=\s+maiores)", "10", ln, flags=re.I)
    if not R_QUEBRA.search(ln): return ln
    for _ in range(6):
        n = re.sub(r"(?<=\d) (?=[.,/] ?\d)|(?<=\d[.,/]) (?=\d)|(?<=[.,]\d) (?=\d)|(?<=[.,]\d\d) (?=\d)|(?<=\d) (?=\d)", "", ln)
        if n == ln: break
        ln = n
    return ln


def rotulo(linha):
    """('maior'|'top'|'seg'|'rng'|'demais'|'total', N) para uma linha da tabela, ou None. Em 'rng', N = (início, fim)."""
    t = sa(linha).strip().lstrip("-•*·| ").strip()
    t = re.sub(r"^(?:\(?[ivx]{1,4}\)|\(?[a-z]\)|[a-z]\d?\.)\s+", "", t)
    t = re.sub(r"\.{3,}", " ", t)
    t = re.sub(r"\bm ?a ?i ?o ?r ?e ?s\b", "maiores", t); t = re.sub(r"\bd ?e ?v ?e ?d ?o ?r ?e ?s\b", "devedores", t)   # 'M a iores' (Itaú)
    if R_MAIOR.match(t): return ("maior", 1)
    m = R_RNG.match(t)
    if m and re.search(r"devedor|cliente|tomador|maiores|contrapart", t[:60]):
        a, b = int(m.group(1)), int(m.group(2))
        if a < b: return ("rng", (a, b))
    m = R_SEG.match(t)
    if m: return ("seg", _n(next(g for g in m.groups() if g)))
    m = R_TOP.match(t)
    if m: return ("top", _n(next(g for g in m.groups() if g)))
    if R_DEMAIS.match(t): return ("demais", None)
    if R_TOTAL.match(t): return ("total", None)
    return None


def numero(tok):
    """'1.551.209' -> 1551209; '0,6%' -> 0.6 (pct); '6.4%' -> 6.4 (pct, ponto decimal); '(1.234)' -> -1234."""
    t = tok.strip(); pct = t.endswith("%"); t = t.rstrip("%").strip()
    neg = t.startswith("(") and t.endswith(")"); t = t.strip("()")
    if pct and re.fullmatch(r"-?\d{1,3}\.\d{1,2}", t):          # percentual com ponto decimal (ex.: Cresol)
        v, casas = float(t), len(t.split(".")[1])
    else:
        v = float(t.replace(".", "").replace(",", ".")); casas = len(t.split(",")[1]) if "," in t else 0
    return (-v if neg else v), pct, ("," in t or (pct and "." in t)), casas


def _tokens(linha, corte=0):
    out = []
    for m in R_NUM.finditer(linha):
        if m.start() < corte: continue
        try: v, pct, dec, casas = numero(m.group())
        except ValueError: continue
        out.append({"v": v, "pct": pct, "dec": dec, "casas": casas, "x": (m.start() + m.end()) / 2, "x0": m.start(), "x1": m.end()})
    return out


def _corte_rotulo(linha):
    """Posição onde termina o rótulo da faixa (para não ler o 10 de '10 maiores devedores' como valor)."""
    if not re.search(r"[A-Za-zÀ-ú]", linha): return 0                 # linha de total sem rótulo
    m = re.match(r"^\s*(?:\S+\s+){0,8}?(?:devedor(?:es)?|clientes?|tomador(?:es)?|contrapartes?|seguintes|demais|total|outros|restantes|maiores|final|geral)\b\.*", linha, re.I)
    if m: return m.end()
    m = re.match(r"^\s*\S+(?:\s\S+)*?(?=\s{2,}|\s*\|)", linha)
    return m.end() if m else 0


def _datas_linha(ln, j, mes_ctx):
    out = []
    for m in re.finditer(r"(\d{1,2})\s+de\s+(janeiro|fevereiro|mar[cç]o|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\s+de\s+(20\d\d)", ln, re.I):
        out.append(((m.start() + m.end()) / 2, f"{m.group(3)}-{MESES[sa(m.group(2))]}", j, m.start(), m.end()))
    for m in re.finditer(r"(?<!\d)(?<!\d[.,])(\d{1,2})[/.](\d{1,2})[/.](\d{4}|\d{2})(?!\d)(?![.,]\d)", ln):
        y, mm = m.group(3), int(m.group(2)); y = ("20" + y) if len(y) == 2 else y
        if 1 <= mm <= 12 and 1 <= int(m.group(1)) <= 31:
            out.append(((m.start() + m.end()) / 2, f"{y}-{mm:02d}", j, m.start(), m.end()))
    if not out:
        for m in re.finditer(r"(?<![\d/])(0[1-9]|1[0-2])/(20\d\d)(?![\d/])", ln):
            out.append(((m.start() + m.end()) / 2, f"{m.group(2)}-{m.group(1)}", j, m.start(), m.end()))
    if not out and mes_ctx:
        txt = sa(ln)
        so_anos = re.findall(r"\b20\d\d\b", ln) and not re.search(r"[a-z]{4,}", txt.replace("consolidado", "").replace("multiplo", "").replace("individual", ""))
        if so_anos:
            for m in re.finditer(r"\b(20\d\d)\b", ln):
                out.append(((m.start() + m.end()) / 2, f"{m.group(1)}-{mes_ctx}", j, m.start(), m.end()))
    return out


R_MES_SO = re.compile(r"(?:\b\d{1,2}\s+de\s+)?\b(janeiro|fevereiro|mar[cç]o|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\b"
                      r"(?!\s+(?:de\s+)?20\d\d)", re.I)


def _so_anos(ln):
    """Linha de cabeçalho só com anos (e 'de', 'em', 'consolidado'...), sem texto corrido."""
    t = sa(ln)
    for w in ("consolidado", "multiplo", "individual", "controladora", "exercicio", "semestre"): t = t.replace(w, "")
    return bool(re.search(r"\b20\d\d\b", t)) and not re.search(r"[a-z]{4,}", t)


def _cabecalho(linhas, i0, data_base, xmax=10 ** 6):
    """Colunas do cabeçalho acima da tabela: datas (da linha de datas mais próxima, dentro da largura da tabela),
    marcadores de % e posição do 'consolidado'."""
    ctx = sa(" ".join(linhas[max(0, i0 - 14):i0]))
    mes_ctx = "06" if re.search(r"30 de junho|junho|1o semestre|primeiro semestre|30/06", ctx) else "12" if re.search(r"31 de dezembro|dezembro|exercicio|31/12", ctx) else data_base[5:]
    D, Pc, cons, linhas_d = [], [], None, set()
    for j in range(i0 - 1, max(-1, i0 - 10), -1):                       # de baixo para cima: a primeira linha com datas
        dd = [d for d in _datas_linha(linhas[j], j, None) if d[3] <= xmax]
        anos = [] if dd or not _so_anos(linhas[j]) else [m for m in re.finditer(r"(?<![\d/.,])(20\d\d)(?![\d/.,])", linhas[j]) if m.start() <= xmax]
        if not dd and not anos: continue
        D, linhas_d = dd, {j}
        if anos:                                    # cabeçalho em duas linhas: "Em 31 de dezembro de" em cima, "2021" embaixo
            meses, cheias = [], []
            for jj in range(j - 1, max(-1, j - 4), -1):
                meses += [(m.start(), m.end(), MESES[sa(m.group(1))], jj) for m in R_MES_SO.finditer(linhas[jj]) if m.start() <= xmax]
                cheias += [d for d in _datas_linha(linhas[jj], jj, None) if d[3] <= xmax]
            for m in anos:
                xc = (m.start() + m.end()) / 2
                if any(d[3] - 2 <= xc <= d[4] + 2 for d in cheias): continue
                mm = min(meses, key=lambda q: abs((q[0] + q[1]) / 2 - xc), default=None)
                if mm and abs((mm[0] + mm[1]) / 2 - xc) <= 30:
                    x0, x1 = min(m.start(), mm[0]), max(m.end(), mm[1])
                    D.append(((x0 + x1) / 2, f"{m.group(1)}-{mm[2]}", j, x0, x1)); linhas_d.add(mm[3]); meses.remove(mm)
                else:
                    D.append((xc, f"{m.group(1)}-{mes_ctx}", j, m.start(), m.end()))
            for d in cheias:                        # data completa na linha de cima ("Em 30 de junho de 2022")
                if not any(abs(d[0] - x[0]) < 4 for x in D): D.append(d); linhas_d.add(d[2])
        break
    if D:
        jmin = min(linhas_d)
        for j in range(jmin, i0):
            for m in re.finditer(r"%|participa[cç][aã]o|percentual", linhas[j], re.I):
                if m.start() <= xmax: Pc.append(((m.start() + m.end()) / 2, j, m.start(), m.end()))
        bloco = " ".join(linhas[max(0, jmin - 3):i0])
        if re.search(r"consolidad", bloco, re.I) and re.search(r"m[uú]ltiplo|individual|controladora", bloco, re.I):
            for j in range(max(0, jmin - 3), i0):
                m = re.search(r"consolidad", linhas[j], re.I)
                if m: cons = m.start()
    return D, Pc, cons


def _unidade(paginas, p):
    txt = sa(" ".join(paginas[max(0, p - 2):p + 1]))
    if R_UNID_MI.search(txt): return 1000.0                # valores em R$ milhões -> R$ mil
    if R_UNID_MIL.search(txt): return 1.0
    return None


def _nota(linhas, i0):
    """Título mais próximo acima da tabela (ex.: 'd) Concentração das operações de crédito')."""
    for j in range(i0 - 1, max(-1, i0 - 25), -1):
        t = linhas[j].strip()
        if re.match(r"^(?:\d{1,2}(?:\.\d{1,2}){0,3}|[a-z]\d?\)|\([a-z]\)|[ivx]{1,4}\)|[a-z]\d?\.)\s*[-–.)]?\s*\S", t, re.I) and re.search(r"concentra|maiores|devedor", sa(t)):
            return _titulo(t)
    for j in range(i0 - 1, max(-1, i0 - 12), -1):
        t = linhas[j].strip()
        if re.search(r"concentra|maiores devedores|principais devedores", sa(t)): return _titulo(t)
    return ""


def _titulo(t):
    """'(h)      Concentração de risco     30/06/2026' -> '(h) Concentração de risco'."""
    out = []
    for p in re.split(r"\s{3,}", t):
        if re.search(r"\d{1,2}/\d{1,2}/\d{2,4}|\b20\d\d\b|^[\d.,%()\s-]+$|^r\$", p, re.I): break
        out.append(p)
    return " ".join(out)[:110]


R_ROT_MEIO = re.compile(r"\s{3,}((?:o\s+)?maior\s+(?:devedor|cliente|tomador)|\d{1,3}\s+maiores\s+(?:devedores|clientes|tomadores))", re.I)


def _lado_a_lado(linhas):
    """Tabela de concentração ao lado de outra na mesma linha (ex.: Itaú IFRS dez/25, 'Por vencimento' | 'Por concentração').
    Devolve (direita, esquerda) cortadas na coluna dos rótulos, ou None."""
    xs = [m.start(1) for l in linhas if not rotulo(l) for m in [R_ROT_MEIO.search(l)] if m and m.start(1) > 25]
    alinhados = [v for v in xs if sum(abs(v - w) <= 3 for w in xs) >= 2]      # pelo menos dois rótulos na mesma coluna
    if not alinhados: return None
    corte = max(0, min(alinhados) - 2)                 # dentro dos 3 espaços que separam as duas tabelas

    def parte(l):                                       # não parte palavra: 'Por Concentração' começa 1 ou 2 colunas antes
        c = corte
        if 0 < c < len(l) and l[c - 1] != " " and l[c] != " ":
            k = c
            while k > 0 and l[k - 1] != " ": k -= 1
            if l[max(0, k - 2):k] == "  " or k == 0: c = k
        return l[c:], l[:c]
    pares = [parte(l) for l in linhas]
    return [a for a, _ in pares], [b for _, b in pares]


def _blocos_linhas(linhas, p, esq=None):
    out, i = [], 0
    while i < len(linhas):
        r = rotulo(linhas[i])
        if r and r[0] in ("maior", "top", "seg", "rng"):
            rows, j, buraco = [], i, 0
            while j < len(linhas) and buraco <= 2:
                rr = rotulo(linhas[j])
                if rr: rows.append((j, rr)); buraco = 0
                elif linhas[j].strip():
                    # total sem rótulo logo depois de "demais" (ex.: '1.079.137 | 100%')
                    if rows and rows[-1][1][0] == "demais" and re.fullmatch(r"[\s\d.,%|]+", linhas[j]) and "100" in linhas[j]:
                        rows.append((j, ("total", None)))
                    buraco += 1
                j += 1
                if rr and rr[0] == "total": break
            bandas = [x for x in rows if x[1][0] in ("maior", "top", "seg", "rng")]
            if len(bandas) >= 2:
                out.append({"pagina": p + 1, "i0": i, "linhas": linhas, "rows": rows, "esq": esq})
            i = j if len(bandas) >= 2 else i + 1
        else:
            i += 1
    return out


def blocos(paginas):
    """Tabelas candidatas: listas de linhas com rótulo de faixa, por página."""
    out = []
    for p, pg in enumerate(paginas):
        linhas = [_conserta(l) for l in pg.split("\n")]
        out += _blocos_linhas(linhas, p)
        lado = _lado_a_lado(linhas)
        if lado: out += _blocos_linhas(lado[0], p, lado[1])
    return out


def _valores(linhas, j, D, Pc, cons, alvo):
    """(valor, percentual, casas) da linha j na coluna da data-base."""
    tk = _tokens(linhas[j], _corte_rotulo(linhas[j]))
    if not tk: return None, None, 2
    dts = sorted(D, key=lambda d: d[0])
    if len(dts) >= 2 or (dts and len(tk) > 2):
        cols = sorted([(d[3], d[4], "d", d[1]) for d in dts] + [(p[2], p[3], "p", None) for p in Pc], key=lambda c: c[0])
        dono, ult = [], None                               # a coluna de % pertence à data à sua esquerda
        for c in cols:
            if c[2] == "d": ult = c[3]
            dono.append((c, c[3] if c[2] == "d" else ult))
        alvos = [k for k, (c, d) in enumerate(dono) if c[2] == "d" and d == alvo]
        if not alvos: return None, None, 2
        idx = [k for k, d in enumerate(dts) if d[1] == alvo]
        kd = idx[0]
        if cons is not None and len(idx) > 1: kd = min(idx, key=lambda q: abs(dts[q][3] - cons))
        pct_like = lambda t: t["pct"] or (t["dec"] and abs(t["v"]) <= 100)
        if len(tk) == 2 * len(dts) and all(not pct_like(tk[2 * q]) or tk[2 * q]["v"] > 100 for q in range(len(dts))) and all(pct_like(tk[2 * q + 1]) for q in range(len(dts))):
            v, p = tk[2 * kd], tk[2 * kd + 1]                 # pares valor/percentual por data, na ordem das datas
            return v["v"], p["v"], p["casas"]
        ka = alvos[0]
        if cons is not None and len(alvos) > 1:            # múltiplo e consolidado: fica o consolidado
            ka = min(alvos, key=lambda k: abs(dono[k][0][0] - cons))
        if len(tk) == len(cols):                           # uma coluna por número: mapeia na ordem
            v = tk[ka]
            p = tk[ka + 1] if ka + 1 < len(cols) and dono[ka + 1][0][2] == "p" else None
            if v["pct"] and p is None: return None, v["v"], v["casas"]
            return v["v"], (p["v"] if p else None), (p["casas"] if p else 2)
        k = kd
        if len(tk) == 2 * len(dts):                        # pares valor/percentual por data
            v, p = tk[2 * k], tk[2 * k + 1]
            return v["v"], p["v"], p["casas"]
        if len(tk) == len(dts):                            # um número por data
            t = tk[k]
            return (None, t["v"], t["casas"]) if t["pct"] else (t["v"], None, 2)
        xa = dono[ka][0][1]                                # sem correspondência exata: o número mais perto da borda direita da data
        v = min(tk, key=lambda t: abs(t["x1"] - xa))
        nxt = [t for t in tk if t["x0"] > v["x0"]][:1]
        p = next((t for t in nxt if t["pct"] or (t["dec"] and t["v"] <= 100)), None)
        return v["v"], (p["v"] if p else None), (p["casas"] if p else 2)
    tp = next((t for t in tk if t["pct"]), None)           # uma data (ou nenhuma): valor e percentual na ordem
    nums = [t for t in tk if not t["pct"]]
    if tp is None and len(tk) >= 2 and tk[1]["v"] <= 100 and (tk[1]["dec"] or tk[1]["v"] < tk[0]["v"]):
        tp, nums = tk[1], [tk[0]]
    if tp is None and len(tk) == 1 and Pc and tk[0]["v"] <= 100 and tk[0]["dec"]:
        return None, tk[0]["v"], tk[0]["casas"]
    return (nums[0]["v"] if nums else None), (tp["v"] if tp else None), (tp["casas"] if tp else 2)


R_TOT_EXCL = re.compile(r"exposi|garantia|aval|fianc|ativo|passivo|patrim|resultado|receita|despesa|provis|perda|liquid|capta|deposit|titulo|"
                        r"derivativ|limite|compromis|cessao|cedid|baixad|moviment")


def _secao(linhas, j):
    """Título do quadro onde está a linha j: a primeira linha de texto sem números acima dela, pouco recuada."""
    for k in range(j - 1, max(-1, j - 16), -1):
        bruto = linhas[k]
        sem_datas = re.sub(r"\d{1,2}/\d{1,2}/\d{2,4}|\b\d{1,2} de [a-zç]+ de 20\d\d|\b20\d\d\b", " ", bruto, flags=re.I)
        t = re.split(r"\s{3,}", bruto.strip())[0]                       # o texto antes das colunas de data
        if not t or len(bruto) - len(bruto.lstrip()) > 24 or re.search(r"\d", sem_datas) or re.search(r"r\$|\bmil\b", sa(t)): continue
        if len(re.findall(r"[A-Za-zÀ-ú]{3,}", t)) >= 2: return re.sub(r"\.{3,}.*", "", t)[:60]
    return ""


def _total_vizinho(linhas, i0, i1, data_base, lado=False):
    """Total da carteira num quadro vizinho da mesma página e da mesma data (ex.: 'Total' do quadro por setor de atividade
    ou por vencimento). lado=True: quadro à esquerda, nas mesmas linhas da tabela. Devolve (valor, descrição) do mais
    próximo, ou None."""
    melhor = None
    meio = list(range(i0, i1 + 1)) if lado else []
    for j in meio + list(range(i1 + 1, min(len(linhas), i1 + 45))) + list(range(i0 - 1, max(-1, i0 - 45), -1)):
        t = sa(linhas[j]).strip().lstrip("|•*- ").strip()
        if not re.match(r"total\b", t) or R_TOT_EXCL.search(t[:100]): continue
        tk = _tokens(linhas[j], _corte_rotulo(linhas[j]))
        if not tk: continue
        sec = _secao(linhas, j)
        if R_TOT_EXCL.search(sa(sec)): continue
        D, Pc, cons = _cabecalho(linhas, j, data_base, max(x["x1"] for x in tk) + 6)
        if data_base not in {d[1] for d in D}: continue
        v, _, _ = _valores(linhas, j, D, Pc, cons, data_base)
        if not v or v <= 0: continue
        dist = j - i1 if j > i1 else (i0 - j if j < i0 else 0)
        if melhor is None or dist < melhor[2]:
            melhor = (v, f"total do quadro “{sec}”" if sec else "total da carteira na mesma página", dist)
    return melhor[:2] if melhor else None


def _descricao(linhas, i0):
    """O que a tabela mede, pelo texto do cabeçalho (ex.: 'Carteira de Crédito com Avais e Fianças, Títulos e Valores
    Mobiliários e Instrumentos Financeiros Derivativos'). Vazio se o cabeçalho não disser."""
    partes = []
    for j in range(i0 - 1, max(-1, i0 - 6), -1):
        t = re.split(r"\s{3,}", linhas[j].strip())[0].strip(" |")
        st = sa(t)
        if re.search(r"concentra", st): break
        if not t or re.search(r"\d{2}/\d|20\d\d|r\$|^%|^\(?em\s", st) or len(re.findall(r"[a-z]{3,}", st)) < 2:
            if partes: break
            continue
        partes.insert(0, t)
    d = re.sub(r"\s*\(\d\)", "", " ".join(partes)).strip(" ,;:")
    return d[:150] if re.search(r"operac|carteira|credito|emprestimo|aval|garantia|titulo|derivativ|arrendamento|exposic", sa(d)) else ""


def le_bloco(b, data_base, paginas):
    """Interpreta uma tabela. data_base 'AAAA-MM'. Devolve dict com faixas acumuladas e situação."""
    linhas, rows = b["linhas"], b["rows"]
    xs = [t["x1"] for (j, (tipo, n)) in rows if tipo in ("maior", "top", "seg", "rng") for t in _tokens(linhas[j], _corte_rotulo(linhas[j]))]
    D, Pc, cons = _cabecalho(linhas, rows[0][0], data_base, (max(xs) + 6) if xs else 10 ** 6)
    datas = sorted({d[1] for d in D}, reverse=True)
    res = {"pagina": b["pagina"], "nota": _nota(linhas, rows[0][0]), "desc": _descricao(linhas, rows[0][0]), "unid_mil": _unidade(paginas, b["pagina"] - 1), "datas": datas}
    if datas and data_base not in datas:
        return {**res, "st": "conferir", "motivo": f"datas da tabela {datas}, data-base {data_base}"}
    lin = []
    for (j, (tipo, n)) in rows:
        v, p, casas = _valores(linhas, j, D, Pc, cons, data_base)
        cent = bool(v is not None and re.search(r"\d\.\d{3},\d{2}(?!\d)", linhas[j]))
        lin.append({"tipo": tipo, "n": n, "v": v, "p": p, "casas": casas, "cent": cent})
    res["bruto"] = lin
    bandas = [x for x in lin if x["tipo"] in ("maior", "top", "seg", "rng")]
    demais = next((x for x in lin if x["tipo"] == "demais"), None)
    total = next((x for x in lin if x["tipo"] == "total" and x["v"]), None)
    tv = total["v"] if total else None
    pc = lambda x: x["p"] if x["p"] is not None else (round(x["v"] / tv * 100, 4) if (tv and x["v"] is not None) else None)
    if any(pc(x) is None for x in bandas):
        achou = None                                                     # só valores: total da carteira no quadro vizinho
        if all(x["v"] for x in bandas) and not any(x["p"] is not None for x in bandas) and not tv:
            achou = _total_vizinho(linhas, rows[0][0], rows[-1][0], data_base) or (_total_vizinho(b["esq"], rows[0][0], rows[-1][0], data_base, True) if b.get("esq") else None)
        if not achou or achou[0] < max(x["v"] for x in bandas):
            return {**res, "st": "conferir", "motivo": "faixa sem percentual" + (" (o total do quadro vizinho é menor que a faixa)" if achou else "")}
        tv = achou[0]; res["calc"] = True; res["base"] = achou[1]
    F, ambig = {}, []
    vals_ok = all(x["v"] is not None for x in bandas)
    if not vals_ok and any(x["v"] is not None for x in bandas):
        return {**res, "st": "conferir", "motivo": "colunas inconsistentes entre as faixas"}
    if any(x["tipo"] == "rng" for x in bandas):                         # intervalos explícitos: exatos
        fmt, av, ap, fim, er = "intervalos", 0.0, 0.0, 0, 0.0
        for x in bandas:
            if x["tipo"] == "maior": F[1] = [x["v"], pc(x), x["casas"]]; continue
            if x["tipo"] != "rng" or x["n"][0] > fim + 1: return {**res, "st": "conferir", "motivo": "intervalos não contínuos"}
            fim = x["n"][1]; av += x["v"] or 0; ap += pc(x); er += 0.5 * 10 ** -x["casas"]
            F[fim] = [av if vals_ok else None, round(ap, 4), x["casas"], er]
    elif any(x["tipo"] == "seg" for x in bandas):                       # faixas seguintes
        fmt, av, ap, n, er = "seguintes", 0.0, 0.0, 0, 0.0
        for k, x in enumerate(bandas):
            prox = bandas[k + 1]["tipo"] if k + 1 < len(bandas) else None
            e1 = 0.5 * 10 ** -x["casas"]
            if x["tipo"] == "maior":
                F[1] = [x["v"], pc(x), x["casas"]]
                if prox == "seg": n, av, ap, er = 1, (x["v"] or 0), pc(x), e1   # "maior" + "10 seguintes" = 11 maiores
                continue
            if x["tipo"] == "top": n, av, ap, er = x["n"], (x["v"] or 0), pc(x), e1
            else: n += x["n"]; av += x["v"] or 0; ap += pc(x); er += e1
            F[n] = [av if vals_ok else None, round(ap, 4), x["casas"], er]
    else:                                                                # só rótulos acumulados: confere se é mesmo acumulado
        tops = [x for x in bandas if x["tipo"] == "top"]
        cresce_v = all(bandas[k]["v"] <= bandas[k + 1]["v"] for k in range(len(bandas) - 1)) if vals_ok else True
        cresce_p = all(pc(bandas[k]) <= pc(bandas[k + 1]) + 0.051 for k in range(len(bandas) - 1))
        maior = next((x for x in bandas if x["tipo"] == "maior"), None)
        fecha = lambda soma, alvo, tol: abs(soma - alvo) <= tol
        tem_v = bool(tv and demais and demais["v"] is not None and vals_ok)
        tem_p = bool(demais and pc(demais) is not None)
        dv = (demais or {}).get("v") or 0
        soma_todas = (tem_v and fecha(sum(x["v"] for x in bandas) + dv, tv, max(2, 0.003 * tv))) or (tem_p and fecha(sum(pc(x) for x in bandas) + pc(demais), 100, 0.6))
        soma_tops = (tem_v and fecha(sum(x["v"] for x in tops) + dv, tv, max(2, 0.003 * tv))) or (tem_p and fecha(sum(pc(x) for x in tops) + pc(demais), 100, 0.6))
        acum = bool(tops) and ((tem_v and fecha(tops[-1]["v"] + dv, tv, max(2, 0.003 * tv))) or (tem_p and fecha(pc(tops[-1]) + pc(demais), 100, 0.6)))
        if maior and soma_todas and not acum:
            fmt = "faixas_ambiguas"                                       # cada linha é uma faixa, inclusive o maior: só o maior é exato
            F[1] = [maior["v"], pc(maior), maior["casas"]]
            ambig = [x["n"] for x in tops]
        elif (soma_tops and not acum) or not cresce_v or not cresce_p:
            fmt = "faixas_ambiguas"                                       # faixas sem fim conhecido: só a primeira é exata
            if maior: F[1] = [maior["v"], pc(maior), maior["casas"]]
            if tops: F[tops[0]["n"]] = [tops[0]["v"], pc(tops[0]), tops[0]["casas"]]
            ambig = [x["n"] for x in tops[1:]]
        else:
            fmt = "acumulado"
            for x in bandas: F[x["n"]] = [x["v"], pc(x), x["casas"]]
    ks = sorted(F); ps = [F[k][1] for k in ks]                          # conferências
    if any(p is None or p <= 0 or p > 100 for p in ps): return {**res, "st": "conferir", "motivo": f"percentual fora de 0 a 100: {ps}"}
    if any(ps[i] > ps[i + 1] + 0.051 for i in range(len(ps) - 1)): return {**res, "st": "conferir", "motivo": f"acumulado não cresce: {ps}"}
    tol = lambda k: (F[k][3] if len(F[k]) > 3 else 0.5 * 10 ** -F[k][2]) / F[k][1] + 0.015
    bases = [(F[k][0] / F[k][1] * 100, tol(k)) for k in ks if F[k][0] and F[k][1] > 0]
    if len(bases) >= 2:
        ref = min(bases, key=lambda b_: b_[1])
        if any(abs(b_[0] - ref[0]) / ref[0] > b_[1] + ref[1] for b_ in bases):
            return {**res, "st": "conferir", "motivo": "base implícita difere entre as faixas"}
    if tv and bases and any(abs(b_[0] - tv) / tv > b_[1] for b_ in bases):
        return {**res, "st": "conferir", "motivo": "base implícita difere do total da tabela"}
    u = res["unid_mil"]
    if u is None and any(x.get("cent") for x in bandas): u = 0.001        # valores com centavos: reais
    res.update(st="ok", formato=fmt, ambiguas=ambig,
               faixas={str(k): [round(F[k][0] * u, 1) if (F[k][0] is not None and u) else None, round(F[k][1], 2)] for k in ks})
    return res


R_FRASE = re.compile(rf"(?:os\s+)?{_N}\s+maiores\s+devedores\s+(?:representa\w*|correspond\w*|equival\w*|concentra\w*|somava\w*|totaliza\w*)"
                     r"([^%]{0,140}?)(\d{1,3}(?:[.,]\d{1,2})?)\s*%")


def le_frases(paginas, data_base):
    """Frases como 'Os Vinte Maiores Devedores representavam na data-base de 30/06/2026 o percentual de 16,65% da carteira'."""
    F, pag = {}, None
    for p, pg in enumerate(paginas):
        t = sa(re.sub(r"\s+", " ", pg))
        for m in R_FRASE.finditer(t):
            dt = re.search(r"(\d{2})/(\d{2})/(\d{4})", m.group(2))
            if dt and f"{dt.group(3)}-{dt.group(2)}" != data_base: continue
            n = _n(m.group(1)); v = float(m.group(3).replace(",", "."))
            if 0 < v <= 100 and n not in F: F[n] = [None, v]; pag = pag or p + 1
    if not F: return None
    ks = sorted(F); ps = [F[k][1] for k in ks]
    if any(ps[i] > ps[i + 1] for i in range(len(ps) - 1)): return None
    return {"st": "ok", "formato": "texto", "pagina": pag, "nota": "frase do relatório ou da nota", "faixas": {str(k): F[k] for k in ks}, "ambiguas": []}


def le_documento(paginas, data_base):
    """Melhor tabela de concentração de devedores do documento: a da carteira de crédito que passa nas conferências."""
    lidos, blo = [], {}
    for b in blocos(paginas):
        r = le_bloco(b, data_base, paginas)
        tit = sa(r.get("nota", "") + " " + " ".join(b["linhas"][max(0, b["rows"][0][0] - 4):b["rows"][0][0]]))
        r["excluida"] = bool(R_EXCL.search(tit))
        r["credito"] = bool(re.search(r"operac\w* de credito|carteira de credito|emprestimos|devedores|concessao de credito", tit))
        r["ifrs"] = "ifrs" in sa(" ".join(b["linhas"][:6]))              # página do IFRS dentro do PDF do Cosif (Bradesco 2022)
        r["amplo"] = bool(re.search(r"titulos e valores|derivativ|avais|fianc", tit + " " + sa(r.get("desc", ""))))
        lidos.append(r); blo[id(r)] = b
    ok = [r for r in lidos if r.get("st") == "ok" and not r["excluida"]]
    if ok:
        r = sorted(ok, key=lambda r: (not r["credito"], r["ifrs"], r["amplo"], bool(r.get("calc")), -len(r["faixas"])))[0]
        comp = {}                                   # coluna comparativa da mesma tabela (ex.: 31/12 do ano anterior)
        for d in r.get("datas") or []:
            if d == data_base: continue
            rc = le_bloco(blo[id(r)], d, paginas)
            if rc.get("st") == "ok": comp[d] = {k: rc[k] for k in ("faixas", "formato", "ambiguas", "calc", "base") if rc.get(k) not in (None, "", [])}
        if comp: r = {**r, "comp": comp}
    else:
        f = le_frases(paginas, data_base)
        if f: return f
        validos = [r for r in lidos if not r["excluida"]]
        if not validos: return {"st": "sem_tabela"}
        r = validos[0]
    r = {k: v for k, v in r.items() if k not in ("excluida", "credito", "bruto", "ifrs", "amplo", "datas") and v not in ("", None)}
    r["outras_tabelas"] = len(lidos) - 1
    return r
