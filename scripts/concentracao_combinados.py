"""Demonstrações combinadas do Sicoob e do Sicredi: localiza o PDF de cada semestre nas páginas públicas dos sistemas.

Sicoob: biblioteca "Combinadas do Sicoob" (uma pasta por ano), em sicoob.com.br/web/relacaocooperados/publicacoes.
Sicredi: página "Demonstrações financeiras" (banco, combinado e empresas), em sicredi.com.br/site/sobre-nos/relatorios.
Devolve {'AAAA-MM': url} só para junho e dezembro. Se a página mudar, devolve o que achou e a rodada registra um alerta.
"""
import html as _html
import re
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (dashboard-credito; github actions)"}
SICOOB_RAIZ = "https://www.sicoob.com.br/web/relacaocooperados/publicacoes/-/document_library/LCLbg6wyOAft/view/154754836"
SICREDI_PAG = "https://www.sicredi.com.br/site/sobre-nos/relatorios/demonstracoes-financeiras-banco-combinado-empresas/"
MES = {"jan": "01", "fev": "02", "mar": "03", "abr": "04", "mai": "05", "jun": "06", "jul": "07", "ago": "08", "set": "09", "out": "10", "nov": "11", "dez": "12"}


def get(url, tries=3, timeout=120):
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except Exception:
            if k == tries - 1: raise
            time.sleep(5 * (k + 1))


def _txt(s):
    return _html.unescape(re.sub(r"<[^>]+>", " ", s)).strip()


def _mes_titulo(t):
    """Mês da data-base pelo título do documento (só junho e dezembro)."""
    t = t.lower()
    if re.search(r"\b(1[ºo°]?|primeiro)\s*semestre|30[./]06|\b06[./]20\d\d|\bjun\w*", t): return "06"
    if re.search(r"\b(2[ºo°]?|segundo)\s*semestre|31[./]12|\b12[./]20\d\d|\bdez\w*|anual|exerc[ií]cio", t): return "12"
    return None


def sicoob(log=print):
    """{'AAAA-MM': url_pdf} das Demonstrações Contábeis Combinadas do Sicoob."""
    raiz = get(SICOOB_RAIZ).decode("utf-8", "replace")
    anos = {}
    for m in re.finditer(r'href="([^"]*?/view/(\d+)\?[^"]*?folderId=\2[^"]*)"[^>]*>(.*?)</a>', raiz, re.S):
        a = re.search(r"\b(20\d\d)\b", _txt(m.group(3)))
        if a: anos[a.group(1)] = _html.unescape(m.group(1))
    if not anos:                                           # alguns temas do Liferay põem o ano num span fora do <a>
        for m in re.finditer(r'/view/(\d+)\?[^"]*?folderId=\1', raiz):
            trecho = _txt(raiz[m.end():m.end() + 600])
            a = re.search(r"\b(20\d\d)\b", trecho)
            if a and a.group(1) not in anos: anos[a.group(1)] = SICOOB_RAIZ.rsplit("/", 1)[0] + "/" + m.group(1)
    out = {}
    for ano, url in sorted(anos.items()):
        if int(ano) < 2021: continue
        pasta = get(url).decode("utf-8", "replace")
        vistos = set()
        for m in re.finditer(r'href="([^"]*?/view_file/(\d+)[^"]*)"[^>]*>(.*?)</a>', pasta, re.S):
            tit = _txt(m.group(3)).lower()
            if not tit or m.group(2) in vistos: continue
            vistos.add(m.group(2))
            log(f"  Sicoob {ano}: '{tit[:90]}'")
            if re.search(r"ingl|english|resumo|apresenta", tit): continue
            mes = _mes_titulo(tit)
            if not mes: continue
            db = f"{ano}-{mes}"
            if db in out: continue
            pg = get(_html.unescape(m.group(1))).decode("utf-8", "replace")
            d = re.search(r'href="(https://www\.sicoob\.com\.br/documents/d/[^"]+?\?download=true)"', pg)
            if d: out[db] = _html.unescape(d.group(1))
        log(f"Sicoob combinado {ano}: {sorted(k for k in out if k.startswith(ano))}")
    return out


def _db_sicredi(rotulo, href):
    r = rotulo.upper().replace(" ", "")
    m = re.search(r"([1-4])T(20\d\d)", r)
    if m: return f"{m.group(2)}-{('03', '06', '09', '12')[int(m.group(1)) - 1]}"
    m = re.search(r"([12])S(20\d\d)", r)
    if m: return f"{m.group(2)}-{'06' if m.group(1) == '1' else '12'}"
    h = href.lower()
    m = re.search(r"(30|31)[_-]?(06|12)[_-]?(20\d\d)", h) or re.search(r"(?<!\d)()(06|12)[_-](20\d\d)", h)
    if m: return f"{m.group(3)}-{m.group(2)}"
    m = re.search(r"(20\d\d)(06|12)(?!\d)", h)
    if m: return f"{m.group(1)}-{m.group(2)}"
    m = re.search(r"\b(20\d\d)\b", r)
    if m and ("ANUAL" in r or re.fullmatch(r".*\b20\d\d\b.*", r)): return f"{m.group(1)}-12"
    return None


def sicredi(log=print):
    """{'AAAA-MM': url_pdf} das Demonstrações Financeiras Combinadas do Sicredi (em português)."""
    pg = get(SICREDI_PAG).decode("utf-8", "replace")
    out = {}
    for m in re.finditer(r'<a[^>]+href="([^"]+\.pdf)"[^>]*>(.*?)</a>', pg, re.S | re.I):
        href, txt = _html.unescape(m.group(1)), _txt(m.group(2))
        antes = _txt(pg[max(0, m.start() - 700):m.start()])[-250:]
        rot = f"{antes} {txt}"
        if "ingles" in href.lower() or "english" in href.lower() or re.search(r"combined", rot[-120:], re.I): continue
        if not re.search(r"combinad", href + " " + rot[-160:], re.I): continue
        db = _db_sicredi(rot[-60:], href)
        if db and db[-2:] in ("06", "12") and db not in out:
            out[db] = href if href.startswith("http") else "https://www.sicredi.com.br" + href
    log(f"Sicredi combinado: {sorted(out)}")
    return out
