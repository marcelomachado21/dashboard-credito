"""Sonda (só no ramo de teste): o que o IF.data traz para o histórico anual da Ficha e se há fonte pública de cooperados."""
import json, re, sys, time, urllib.request, urllib.parse, collections, os

UA = {"User-Agent": "Mozilla/5.0 dashboard-credito"}
OL = "https://olinda.bcb.gov.br/olinda/servico"
OUT = sys.argv[1] if len(sys.argv) > 1 else "out"
os.makedirs(OUT, exist_ok=True)
R = {}


def get(url, tries=4, raw=False):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=300) as r:
                b = r.read()
                return b.decode("utf-8", "replace") if raw else json.loads(b)
        except Exception as e:
            err = e; time.sleep(10 * (i + 1))
    return f"ERRO {err}"


def ifv(am, rel, tipo=1):
    d = get(f"{OL}/IFDATA/versao/v1/odata/IfDataValores(AnoMes=@AnoMes,TipoInstituicao=@TipoInstituicao,Relatorio=@Relatorio)?@AnoMes={am}&@TipoInstituicao={tipo}&@Relatorio='{rel}'&$format=json")
    return d if isinstance(d, str) else d["value"]


ALVO = {"38588174": "Credicope", "03320525": "Aracoop", "C0080329": "BB", "02038232": "Banco Sicoob"}
for am in ("202012", "202112", "202212", "202312", "202406", "202412", "202506", "202606"):
    for rel in ("1", "5"):
        v = ifv(am, rel)
        if isinstance(v, str): R[f"{am}_r{rel}"] = v; print(am, rel, v); continue
        cols = collections.Counter((x.get("NomeColuna") or "").split("\n")[0].strip() for x in v)
        amostra = {ALVO[x["CodInst"]] + " · " + (x.get("NomeColuna") or "").split("\n")[0].strip(): x.get("Saldo") for x in v if x["CodInst"] in ALVO}
        R[f"{am}_r{rel}"] = {"linhas": len(v), "instituicoes": len({x['CodInst'] for x in v}), "colunas": list(cols), "amostra": amostra}
        print(am, "rel", rel, len(v), "linhas;", len({x['CodInst'] for x in v}), "inst; colunas:", list(cols)[:40])
        print("   amostra:", json.dumps(amostra, ensure_ascii=False)[:1500])
    time.sleep(2)

# relatórios disponíveis numa data antiga e numa recente
for am in ("202112", "202606"):
    for path in (f"IFDATA/versao/v1/odata/ListaDeRelatorio()?$format=json", f"IFDATA/versao/v1/odata/IfDataRelatorios(AnoMes=@AnoMes)?@AnoMes={am}&$format=json"):
        d = get(f"{OL}/{path}", tries=2)
        R[f"lista_{am}_{path[:40]}"] = d if isinstance(d, str) else d.get("value", d)
        print("LISTA", am, path[:60], str(d)[:1500])

# catálogo do Olinda e do portal de dados abertos: algo sobre cooperados ou associados por cooperativa?
cat = get(f"{OL}/", raw=True)
achados = sorted(set(re.findall(r"servico/([A-Za-z_]+)", cat if isinstance(cat, str) else "")))
R["olinda_servicos"] = achados; print("OLINDA serviços:", achados)
for q in ("cooperados", "associados cooperativa", "quantidade de cooperados", "agências cooperativas", "postos de atendimento"):
    d = get(f"https://dadosabertos.bcb.gov.br/api/3/action/package_search?q={urllib.parse.quote(q)}&rows=20", tries=2)
    if isinstance(d, dict):
        lst = [(p.get("name"), p.get("title"), [r.get("url") for r in p.get("resources", [])][:3]) for p in d.get("result", {}).get("results", [])]
        R[f"ckan_{q}"] = lst; print("CKAN", q, json.dumps(lst, ensure_ascii=False)[:2500])
    else: print("CKAN", q, d)

json.dump(R, open(f"{OUT}/sonda_historico.json", "w"), ensure_ascii=False, indent=1)
