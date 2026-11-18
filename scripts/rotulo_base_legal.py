"""Rótulo padrão de base legal de renegociação (usado quando o código ainda não está em bases_legais_reneg.csv)."""
import re, unicodedata
def _n(x):
    x = x.replace(".", ""); return f"{x[:-3]}.{x[-3:]}" if len(x) > 3 else x
def rotulo(desc):
    """Rótulo padrão a partir da descrição oficial: MCR primeiro, com a resolução entre parênteses; senão MP / Res.; senão Res., Lei ou Decreto. Sem artigo."""
    t = " ".join((desc or "").split())
    tu = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().upper()
    tu = re.sub(r"\b(REVOGAD[OA]S?|ENCERRADO)\b.*?(?=$|\bE\b|[,;/)(-])", " ", tu)
    tu = re.sub(r"\bARTS?\.?\s*\d+\s*[OºA°]?", " ", tu)
    mcr = re.findall(r"MCR\s+(\d+-\d+-\d+)(?:-\"?\w\"?)?(?:\s+E\s+(\d+-\d+-\d+))?", tu)
    mp = re.findall(r"\bMP\s*(?:N[OA]?\s*)?(\d\.?\d{3}/\d{4})", tu)
    lei = re.findall(r"\bLEI\s*(?:N[OA]?\s*)?(\d{1,2}\.?\d{3}/\d{4})", tu)
    dec = re.findall(r"\bDECRETO\s*(?:N[OA]?\s*)?(\d{1,2}\.?\d{3}/\d{4})", tu)
    resto = re.sub(r"MCR\s+[\d-]+(\s+E\s+[\d-]+)?|\bMP\s*(N[OA]?\s*)?[\d./]+|\bLEI\s*(N[OA]?\s*)?[\d./]+|\bDECRETO\s*(N[OA]?\s*)?[\d./]+", " ", tu)
    resto = re.sub(r",?\s*\bDE\s+\d{1,2}/\d{2}/(\d{4})", r"@\1", resto); resto = re.sub(r",?\s*\bDE\s+\d{1,2}\s+DE\s+[A-Z]+\s+DE\s+(\d{4})", r"@\1", resto)
    res = []
    if re.search(r"\bRES", resto):
        for m in re.finditer(r"(?<![@/\d])(\d\.?\d{3})\b(?:\s*,?\s*@(\d{4})|/(\d{4}))?", resto):
            res.append((_n(m.group(1)), m.group(2) or m.group(3)))
    # junta números com o mesmo ano: "5.330 e 5.340/2026"
    seen, out = set(), []
    for n, y in res:
        if n not in seen: seen.add(n); out.append([n, y])
    grp = []
    for n, y in out:
        if grp and grp[-1][1] is None and y: grp[-1][0].append(n); grp[-1][1] = y
        elif grp and grp[-1][1] is None and not y: grp[-1][0].append(n)
        else: grp.append([[n], y])
    lst = lambda xs: xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " e " + xs[-1]
    rtxt = lst([lst(ns) + (f"/{y}" if y else "") for ns, y in grp]) if grp else ""
    R = f"Res. CMN {rtxt}" if rtxt else ""
    if mcr:
        m = mcr[0]; base = "MCR " + m[0] + (f" e {m[1]}" if m[1] else "")
        return base + (f" ({R})" if R else "")
    partes = [f"MP {_n(x.split('/')[0])}/{x.split('/')[1]}" for x in mp] + [f"Lei {_n(x.split('/')[0])}/{x.split('/')[1]}" for x in lei] + [f"Decreto {_n(x.split('/')[0])}/{x.split('/')[1]}" for x in dec]
    return " / ".join(partes + ([R] if R else [])) or t
