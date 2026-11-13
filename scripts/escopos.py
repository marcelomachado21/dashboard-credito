"""Recortes (escopos) comuns a todas as bases do painel.

Centrais: cada central de filiação do cadastro do BC vira um recorte (cen_<CNPJ da central>); Crediminas e Cecremge mantêm
os ids "crediminas" e "cecremge". Chamar prepara(coop) logo depois de carregar o cadastro.

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


import hashlib, re

CENTRAIS = {}    # FILIACAO (maiúsculas) -> {id, nome, uf (sede), sis, ufs (UFs das filiadas)}
NOME_CENTRAL = {"25683434": "Central Crediminas", "00309024": "Central Cecremge", "87437687": "Central Sicredi Sul/Sudeste",
                "62931522": "Sicoob Central Cecresp", "80160260": "Sicoob Central SC/RS", "33416108": "Sicoob Nova Central",
                "80230774": "Central Sicredi PR/SP/RJ", "00315557": "Unicred do Brasil", "01401771": "Central Cresol Baser",
                "07202627": "Cresol Central Brasil", "05036532": "Sicoob Central Unicoob", "05463212": "Central Ailos",
                "21198087": "Central Cresol Sicoper", "70119680": "Central Sicredi Nordeste", "63917579": "Sicoob São Paulo",
                "70116611": "Sicoob Central NE", "14568725": "Sicoob Unimais Rio", "34148882": "Sicoob Central BA",
                "03046391": "Uniprime Central Nacional", "33667205": "Central Sicredi Centro Norte", "04243780": "Sicoob Uni",
                "00106180": "Sicoob Central MT/MS", "32428294": "Sicoob Central ES", "03502131": "Sicoob Norte",
                "33737818": "Central Sicredi Brasil Central", "10398952": "Confesol"}


def _nome_auto(f):
    t = f.split(" - ")[-1] if " - " in f else f
    t = re.sub(r"\bLTDA\b\.?", "", t, flags=re.I).strip(" .-")
    if "CONFEDERA" in f.upper(): t = ("Confederação " + sistema_de(f).capitalize() + " (filiação direta)") if sistema_de(f) != "outras" else t
    elif "CREDISIS" in f.upper(): t = "Credisis Central"
    return " ".join(w if w.isupper() and len(w) <= 3 else w.capitalize() for w in t.split()) if t.isupper() else t


def prepara(coop):
    """coop: {cnpj: registro do cadastro}. Monta o mapa de centrais (filiação -> recorte)."""
    CENTRAIS.clear()
    sede = {(x.get("NOME_INSTITUICAO") or "").strip().upper(): x for x in coop.values() if x.get("CLASSE") in ("Central", "Confederação")}
    for x in coop.values():
        f = (x.get("FILIACAO") or "").strip()
        if not f or x.get("CLASSE", "Singular") != "Singular": continue      # centrais filiadas à confederação não formam recorte
        k = f.upper()
        if k not in CENTRAIS:
            m = sede.get(k) or {}
            cn = m.get("CNPJ")
            cid = "crediminas" if "CREDIMINAS" in k else "cecremge" if "CECREMGE" in k else "cen_" + (cn or hashlib.md5(k.encode()).hexdigest()[:8])
            CENTRAIS[k] = {"id": cid, "nome": NOME_CENTRAL.get(cn) or _nome_auto(f), "uf": m.get("UF", ""), "sis": sistema_de(f), "ufs": set()}
        if x.get("UF") in UFS: CENTRAIS[k]["ufs"].add(x["UF"])


def central_id(filiacao):
    c = CENTRAIS.get((filiacao or "").strip().upper())
    return c["id"] if c else central_de(filiacao)


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
    c = central_id(filiacao) if singular and (filiacao or "").strip() not in ("", "x") else ""
    if c: out.append(c)
    solteira = singular and not (filiacao or "").strip()
    if solteira: out.append("solteiras")
    if uf in UFS:
        u = uf.lower(); out.append("coop_" + u)
        if sistema != "outras": out.append(f"{sistema}_{u}")
        if solteira: out.append("solteiras_" + u)
    return out


BASES_UF = ("coop", "solteiras") + tuple(s for _, s, *_ in SISTEMAS)


def uf_do_escopo(e):
    """'MG' para recortes da UF (e Crediminas/Cecremge, que ficam no arquivo principal); None para recortes nacionais e demais centrais."""
    if e in ("crediminas", "cecremge"): return "MG"
    p = e.rsplit("_", 1)
    return p[1].upper() if len(p) == 2 and p[0] in BASES_UF and p[1].upper() in UFS else None


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
        L.append(("coop_" + u, f"Cooperativas {uf}", "#4F7F7A", "uf", uf))
        L += [(f"{s}_{u}", f"{n} {uf}", c, "uf", uf) for _, s, n, c in SISTEMAS]
        L.append(("solteiras_" + u, f"Solteiras {uf}", "#8C5A30", "uf", uf))
    cor_c = {"crediminas": "#007A6E", "cecremge": "#5BC2B8"}
    for c in sorted(CENTRAIS.values(), key=lambda c: (c["id"] not in cor_c, c["nome"])):
        L.append((c["id"], c["nome"], cor_c.get(c["id"]) or next((x[3] for x in SISTEMAS if x[1] == c["sis"]), "#A3ACA8"), "central", c["uf"]))
    L += [("bb", "Banco do Brasil", "#465EFF", "banco", ""), ("bradesco", "Bradesco", "#CC092F", "banco", ""), ("itau", "Itaú", "#EC7000", "banco", ""),
          ("caixa", "Caixa", "#005CA9", "banco", ""), ("santander", "Santander", "#EC0000", "banco", ""), ("digitais", "Bancos digitais", "#820AD1", "banco", "")]
    return L


def saida(L, presentes):
    """Lista para o JSON, só com recortes que têm instituição na base (recortes nacionais ficam sempre).
    Centrais levam o sistema (sis) e as UFs das filiadas (ufs), usados no filtro Estado → Recorte → Central."""
    cen = {c["id"]: c for c in CENTRAIS.values()}
    out = []
    for a, b, c, d, u in L:
        if d == "central":
            if a not in presentes: continue
            x = cen[a]; out.append(dict(id=a, nome=b, cor=c, grupo=d, uf=u, sis=x["sis"], ufs=sorted(x["ufs"])))
        elif not u or a in presentes:
            out.append(dict(id=a, nome=b, cor=c, grupo=d, **({"uf": u} if u else {})))
    return out
