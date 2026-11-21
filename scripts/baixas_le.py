"""Leitura das baixas para prejuízo nas notas explicativas (quadro de movimentação da provisão ou da carteira).

Entrada: texto de cada página do PDF (pdftotext -layout). Saída: o valor baixado no período da coluna da data-base, com o saldo
inicial e o final da mesma coluna (para a conferência entre documentos) e o tipo de período da coluna, quando o cabeçalho diz.

Formatos (amostra de nov/2026):
- provisão, uma coluna por período: "Saldo inicial | Constituição/(reversão) | Baixas para prejuízo | Saldo final" (BB, Banco Sicoob,
  Sicredi, Unicred, combinadas do Sicoob). Sinal da provisão negativo ou positivo, conforme a instituição.
- carteira bruta por estágio: "Saldo inicial | Aquisição | Liquidação | Baixa para prejuízo | Saldo final" (singulares Sicoob).
- períodos: "1º Semestre/2026", "2º Semestre/2025 | Exercício/2025", "30/06/2026 | 30/06/2025" ou "30/06/2026 | 31/12/2025".

Regras: o valor é o publicado. A tabela só é aceita quando o saldo inicial mais as movimentações dá o saldo final, dentro do
arredondamento. Em dezembro, quando a coluna não diz se é semestre ou exercício, a rotina decide comparando com o documento de junho.
"""
import re
from concentracao_le import sa, _tokens, _conserta, _unidade, _titulo

R_INI = re.compile(r"^(?:\(?[a-z0-9]\)\s*)?saldos?\s+(?:inicia(?:l|is)|no\s+inicio|do\s+inicio|de\s+abertura|anterior|em\s+(?:1[ºo°]?|01|31|30)\b)|^saldos?\s+em\s+\d")
R_FIM = re.compile(r"^(?:\(?[a-z0-9]\)\s*)?saldos?\s+(?:fina(?:l|is)|no\s+fim|no\s+final|do\s+fim|de\s+fechamento|em\s+(?:30|31)\b)")
R_BX = re.compile(r"baixad|baixas?\b|transfer\w*\s+(?:para|a|ao)\s+(?:o\s+)?preju|utiliza[cç][aã]o|write")
R_TIT = re.compile(r"moviment|evolu[cç][aã]o|consolida[cç][aã]o dos est[aá]gios|concilia[cç][aã]o")
R_TIT_OK = re.compile(r"provis|perdas?\s+(?:esperada|incorrida|de credito)|devedores duvidosos|liquidacao duvidosa|risco de credito|carteira|estagio|operac")
R_TIT_EXCL = re.compile(r"garantias?\s+(?:financeiras\s+)?prestad|compromiss|contingen|trabalhist|civeis|fisca|tributar|passivos|imobilizado|intangiv|"
                        r"bens nao de uso|ativos nao financeiros|transacoes de pagamento|valores a receber|outros creditos|repasses?\s+interfin|"
                        r"titulos e valores|aplicacoes interfinanceiras|depositos|captac|beneficio|participac")
R_OUTRAS = re.compile(r"outras operacoes|caracteristicas de (?:concessao de )?credito|demais")
P_S1 = re.compile(r"1\s?[ºo°]\s*sem|primeiro\s+sem|\b1s\b|1o\.?\s*sem")
P_S2 = re.compile(r"2\s?[ºo°]\s*sem|segundo\s+sem|\b2s\b|2o\.?\s*sem")
P_ANO = re.compile(r"exerc[ií]cio|\banual\b|12 meses|acumulado no ano")


def _rotulo(l):
    return re.sub(r"^\(?[+-]\)?\s*", "", sa(l).strip().lstrip("|•*· ").strip())


def _cols_cabecalho(linhas, i_ini, i_tit):
    """Rótulos acima do saldo inicial: [(x_centro, ano, tipo)], tipo 'dMM' (data), 'a' (ano) ou '1S', '2S', 'ANO' (período)."""
    labs = []
    for j in range(max(i_tit, i_ini - 8), i_ini):
        l = linhas[j]; t = sa(l)
        for m in re.finditer(r"(\d{1,2})/(\d{1,2})/(20\d\d)", l):
            labs.append(((m.start() + m.end()) / 2, int(m.group(3)), "d" + m.group(2).zfill(2)))
        for m in re.finditer(r"(?<!\d)(?<!\d/)(20\d\d)(?![\d/])", l):
            labs.append(((m.start() + m.end()) / 2, int(m.group(1)), "a"))
        for pat, nome in ((P_S1, "1S"), (P_S2, "2S"), (P_ANO, "ANO")):
            for m in pat.finditer(t):
                labs.append(((m.start() + m.end()) / 2, None, nome))
    return labs


def _periodo_tabela(texto):
    t = sa(texto)
    if P_S1.search(t): return "1S"
    if P_S2.search(t): return "2S"
    if P_ANO.search(t): return "ANO"
    return None


def _colunas(linhas, i_ini, i_tit, xs):
    """Para cada coluna de valor (centro x no saldo inicial): [ano, per, tipo_do_rotulo]. per None quando nada diz o período
    (ex.: '31/12/2025' sozinho, que pode ser o semestre ou o exercício)."""
    labs = _cols_cabecalho(linhas, i_ini, i_tit)
    geral = _periodo_tabela(" ".join(linhas[max(i_tit, 0):i_ini]))
    cols = []
    for x in xs:
        anos = [l for l in labs if l[1] is not None and abs(l[0] - x) <= 26]
        pers = [l for l in labs if l[1] is None and abs(l[0] - x) <= 26]
        a = min(anos, key=lambda l: abs(l[0] - x)) if anos else None
        per = min(pers, key=lambda l: abs(l[0] - x))[2] if pers else (geral if len({l[2] for l in labs if l[1] is None}) <= 1 else None)
        if per is None and a and a[2] == "d06": per = "1S"                # 30/06: fluxo de janeiro a junho
        cols.append([a[1] if a else None, per, a[2] if a else None])
    return cols


def _tabelas(linhas):
    """Blocos saldo inicial ... saldo final com ao menos uma linha de baixa."""
    out, i = [], 0
    while i < len(linhas):
        if R_INI.search(_rotulo(linhas[i])):
            j, bx = i + 1, []
            while j < len(linhas) and j - i <= 22:
                r = _rotulo(linhas[j])
                if R_FIM.search(r): break
                if R_INI.search(r): j = len(linhas); break
                if R_BX.search(r) and _tokens(linhas[j], _corte(linhas[j])): bx.append(j)
                j += 1
            if j < len(linhas) and bx:
                out.append((i, j, bx)); i = j + 1; continue
        i += 1
    return out


def _corte(l):
    """Fim do rótulo: depois do último caractere alfabético da parte esquerda (para não ler números do texto)."""
    m = re.match(r"^\s*(?:\(?[+-]\)?\s*)?[^\d(]*[A-Za-zÀ-ú)\]]", l)
    if not m: return 0
    k = m.end()
    m2 = re.match(r"^.*?[A-Za-zÀ-ú](?=\s{2,}[\d(-])", l)
    return max(k, m2.end() if m2 else 0)


def _titulo_tabela(linhas, i0):
    for j in range(i0 - 1, max(-1, i0 - 14), -1):
        t = sa(linhas[j])
        if R_TIT.search(t): return j, _titulo(linhas[j].strip())
    return max(0, i0 - 4), ""


def le_baixas(paginas, data_base):
    """Melhor quadro com baixas para prejuízo: devolve st, baixas (valor absoluto, na unidade da nota, convertido para R$ mil se a
    unidade for conhecida), ini e fim da mesma coluna, per (1S, 2S, ANO ou None), tipo (provisao ou carteira), nota, pagina, comp."""
    ano_db, mes_db = int(data_base[:4]), data_base[5:]
    lidos = []
    for p, pg in enumerate(paginas):
        linhas = [_conserta(l) for l in pg.split("\n")]
        for (i, f, bx) in _tabelas(linhas):
            jt, tit = _titulo_tabela(linhas, i)
            ctx = sa(" ".join(linhas[max(0, jt - 1):i]))
            if R_TIT_EXCL.search(sa(tit)) or (not R_TIT_OK.search(sa(tit) + " " + ctx)): continue
            tipo = "carteira" if re.search(r"carteira|estagios das operac|aquisi", sa(tit) + " " + sa(" ".join(linhas[i:f]))) and not re.search(r"provis|perdas", sa(tit)) else "provisao"
            tk_ini, tk_fim = _tokens(linhas[i], _corte(linhas[i])), _tokens(linhas[f], _corte(linhas[f]))
            if not tk_ini or not tk_fim: continue
            xs = [t["x1"] for t in tk_ini]
            cols = _colunas(linhas, i, jt, [t["x"] for t in tk_ini])
            # quadro por estágio (Estágio 1, 2, 3 e Total): só a coluna Total serve
            cab = linhas[max(jt, i - 8):i]
            est = [m for l in cab for m in re.finditer(r"est[aá]gio", l, re.I)]
            if est:
                tots = [(m.start() + m.end()) / 2 for l in cab for m in re.finditer(r"\btotal\b", l, re.I)]
                if tots:
                    so = sorted({min(range(len(tk_ini)), key=lambda k: abs(tk_ini[k]["x"] - x)) for x in tots})
                elif len(tk_ini) % 4 == 0:
                    so = list(range(3, len(tk_ini), 4))           # E1, E2, E3, Total em cada grupo
                else:
                    continue
            else:
                so = list(range(len(cols)))
            # coluna da data-base: em junho, a primeira coluna do ano da data-base com 1S (ou 30/06); em dezembro, 2S, senão ANO, senão
            # a primeira coluna do ano (período a decidir com o documento de junho)
            cand = [k for k in so if cols[k][0] == ano_db]
            if not cand and cols[so[0]][0] is None: cand = [so[0]]
            if not cand: continue
            if mes_db == "06":
                pref = [k for k in cand if cols[k][1] in ("1S", None)]
            else:
                pref = [k for k in cand if cols[k][1] == "2S"] or [k for k in cand if cols[k][1] == "ANO"] or [k for k in cand if cols[k][1] is None]
            if not pref: continue
            res = []
            for k in pref[:1] + [c for c in so if c not in pref[:1]]:
                xk = xs[k]
                def val(j):
                    tk = _tokens(linhas[j], _corte(linhas[j]))
                    if not tk: return None
                    t = min(tk, key=lambda t: abs(t["x1"] - xk))
                    return t["v"] if abs(t["x1"] - xk) <= 6 else None
                ini, fim = val(i), val(f)
                if ini is None or fim is None: res.append(None); continue
                movs = [val(j) for j in range(i + 1, f) if _tokens(linhas[j], _corte(linhas[j])) and not re.search(r"^sub\s*total|^total|^saldo", _rotulo(linhas[j]))]
                b = [val(j) for j in bx]
                b = [x for x in b if x is not None]
                soma = ini + sum(x for x in movs if x is not None)
                fecha = abs(soma - fim) <= max(2.0, abs(fim) * 0.002)
                # ajuste de transição da Res. CMN 4.966 (1º/1/2025) só aparece em coluna que começa em janeiro: é o exercício
                trans = any(re.search(r"transi[cç][aã]o|ado[cç][aã]o inicial|4\.?966", _rotulo(linhas[j])) and val(j) not in (None, 0) for j in range(i + 1, f))
                res.append({"k": k, "ini": ini, "fim": fim, "baixas": abs(sum(b)) if b else None, "fecha": fecha, "col": cols[k], "trans": trans})
            alvo = res[0]
            if not alvo or alvo["baixas"] is None: continue
            u = _unidade(paginas, p)
            if u is None and re.search(r"\d\.\d{3},\d{2}(?!\d)", linhas[i]): u = 0.001
            r = {"pagina": p + 1, "nota": tit[:90], "tipo": tipo, "outras": bool(R_OUTRAS.search(sa(tit))), "unid_mil": u,
                 "ini": alvo["ini"], "fim": alvo["fim"], "baixas": alvo["baixas"], "per": alvo["col"][1], "data_col": alvo["col"][2], "trans": alvo["trans"],
                 "st": "ok" if alvo["fecha"] else "conferir"}
            if not alvo["fecha"]: r["motivo"] = "saldo inicial mais movimentações não dá o saldo final"
            comp = {}
            for o in res[1:]:
                if o and o["fecha"] and o["baixas"] is not None and o["col"][0] and o["col"][1] in ("1S", "2S", "ANO"):
                    comp[f"{o['col'][0]}|{o['col'][1]}"] = {"baixas": o["baixas"], "ini": o["ini"], "fim": o["fim"]}
            if comp: r["comp"] = comp
            lidos.append(r)
    ok = [r for r in lidos if r["st"] == "ok"]
    if not ok:
        return ({k: v for k, v in lidos[0].items()} if lidos else {"st": "sem_tabela"})
    # preferência: provisão das operações de crédito; depois carteira; tabelas de "outras operações" por último
    r = sorted(ok, key=lambda r: (r["outras"], r["tipo"] != "provisao", r["pagina"]))[0]
    u = r.get("unid_mil")
    if u:
        for k in ("baixas", "ini", "fim"): r[k] = round(r[k] * u, 1)
        for c in (r.get("comp") or {}).values():
            for k in ("baixas", "ini", "fim"): c[k] = round(c[k] * u, 1)
    r["outras_tabelas"] = len(lidos) - 1
    return r
