"""Recortes (escopos) comuns a todas as bases do painel.

Um lugar só para: sistemas cooperativos, recortes por UF da sede, nomes e cores.
- Sistema: procurado no nome da central de filiação (cadastro do BC) e no nome da cooperativa.
- Recortes por UF (sede da cooperativa no cadastro do BC): cooperativas, Sicoob, Sicredi e solteiras da UF.
  Em MG também as centrais Crediminas e Cecremge.
- Conglomerado (coop. + banco): só Sicoob e Sicredi têm banco cooperativo próprio.
"""

SISTEMAS = [("SICOOB", "sicoob", "Sicoob", "#00AE9D"), ("SICREDI", "sicredi", "Sicredi", "#7CC35A"),
            ("CRESOL", "cresol", "Cresol", "#6E5A9E"), ("UNICRED", "unicred", "Unicred", "#9C7A3C"),
            ("AILOS", "ailos", "Ailos", "#3D7CC9"), ("CREDISIS", "credisis", "Credisis", "#C9902A"),
            ("UNIPRIME", "uniprime", "Uniprime", "#B5487A")]

UFS = {"AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas", "BA": "Bahia", "CE": "Ceará", "DF": "Distrito Federal",
       "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão", "MT": "Mato Grosso", "MS": "Mato Grosso do Sul", "MG": "Minas Gerais",
       "PA": "Pará", "PB": "Paraíba", "PR": "Paraná", "PE": "Pernambuco", "PI": "Piauí", "RJ": "Rio de Janeiro",
       "RN": "Rio Grande do Norte", "RS": "Rio Grande do Sul", "RO": "Rondônia", "RR": "Roraima", "SC": "Santa Catarina",
       "SP": "São Paulo", "SE": "Sergipe", "TO": "Tocantins"}


def sistema_de(texto):
    t = (texto or "").upper()
    for k, s, *_ in SISTEMAS:
        if k in t: return s
    return "outras"


def central_de(filiacao):
    f = (filiacao or "").upper()
    return "crediminas" if "CREDIMINAS" in f else "cecremge" if "CECREMGE" in f else ""


def escopos_cooperativa(sistema, uf, filiacao, singular=True):
    """Recortes de uma cooperativa (sem o 'sfn', que cada base acrescenta se usar)."""
    out = ["coop", sistema]
    if sistema in ("sicoob", "sicredi"): out.append("cong_" + sistema)
    c = central_de(filiacao)
    if c: out.append(c)
    solteira = singular and not (filiacao or "").strip()
    if solteira: out.append("solteiras")
    if uf in UFS:
        u = uf.lower(); out.append("coop_" + u)
        if sistema in ("sicoob", "sicredi"): out.append(f"{sistema}_{u}")
        if solteira: out.append("solteiras_" + u)
    return out


def uf_do_escopo(e):
    """'MG' para recortes da UF (inclui centrais de MG); None para recortes nacionais."""
    if e in ("crediminas", "cecremge"): return "MG"
    p = e.rsplit("_", 1)
    return p[1].upper() if len(p) == 2 and p[0] in ("coop", "sicoob", "sicredi", "solteiras") and p[1].upper() in UFS else None


def lista(agregado_bancos="Bancos", sfn=True):
    """Lista de recortes (id, nome, cor, grupo, uf). O front-end mostra só os que tiverem dado na base."""
    L = []
    if sfn: L.append(("sfn", "SFN", "#2B2F33", "agregado", ""))
    L += [("bancos", agregado_bancos, "#8A9097", "agregado", ""), ("coop", "Cooperativas", "#56606A", "agregado", ""),
          ("cong_sicoob", "Conglomerado Sicoob", "#003641", "conglomerado", ""), ("cong_sicredi", "Conglomerado Sicredi", "#3FA110", "conglomerado", "")]
    L += [(s, n, c, "sistema", "") for _, s, n, c in SISTEMAS]
    L.append(("solteiras", "Cooperativas solteiras", "#B07A4A", "sistema", ""))
    for uf in sorted(UFS, key=lambda u: (u != "MG", UFS[u])):
        u = uf.lower()
        L += [("coop_" + u, f"Cooperativas {uf}", "#4F7F7A", "uf", uf), ("sicoob_" + u, f"Sicoob {uf}", "#2E8F86", "uf", uf),
              ("sicredi_" + u, f"Sicredi {uf}", "#5E9E3F", "uf", uf)]
        if uf == "MG":
            L += [("crediminas", "Central Crediminas", "#007A6E", "uf", uf), ("cecremge", "Central Cecremge", "#5BC2B8", "uf", uf)]
        L.append(("solteiras_" + u, f"Solteiras {uf}", "#8C5A30", "uf", uf))
    L += [("bb", "Banco do Brasil", "#465EFF", "banco", ""), ("bradesco", "Bradesco", "#CC092F", "banco", ""), ("itau", "Itaú", "#EC7000", "banco", ""),
          ("caixa", "Caixa", "#005CA9", "banco", ""), ("santander", "Santander", "#EC0000", "banco", ""), ("digitais", "Bancos digitais", "#820AD1", "banco", "")]
    return L


def saida(L, presentes):
    """Lista para o JSON, só com recortes que têm instituição na base (recortes nacionais ficam sempre)."""
    return [dict(id=a, nome=b, cor=c, grupo=d, **({"uf": u} if u else {})) for a, b, c, d, u in L if not u or a in presentes]
