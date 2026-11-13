#!/usr/bin/env python3
"""Gera os mapas do painel (rodar à mão; o resultado fica fixo no repositório, a malha não muda toda semana).

Entradas (pasta passada como argumento):
  <UF>_malhas.csv  malha municipal do IBGE por UF, com micro/mesorregião e regiões imediata/intermediária
                   (github.com/Miguel-mmf/ibge, extraída da API de malhas e localidades do IBGE)
  br_states.json   contorno das UFs (github.com/giuliano-oliveira/geodata-br-states)
Saídas:
  site/mapas/BR.json    UFs, para o mapa do Brasil
  site/mapas/<UF>.json  municípios da UF, no mesmo formato do antigo mg_mapa.json: {vb, fonte, m: {cod_ibge: {n, p}}}
  scripts/ibge_regioes_br.csv  regiões de todos os municípios (usada pela rotina do território)
Projeção: equiretangular com correção do cosseno da latitude média; simplificação Douglas-Peucker por anel.
Uso: python3 scripts/gera_mapas.py <pasta_com_malhas>
"""
import csv, glob, json, math, os, re, sys

csv.field_size_limit(10 ** 9)
ENT = sys.argv[1]
AQUI = os.path.dirname(os.path.abspath(__file__))
SAI = os.path.join(AQUI, "..", "site", "mapas")
os.makedirs(SAI, exist_ok=True)
UF_COD = {"11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO", "21": "MA", "22": "PI", "23": "CE", "24": "RN",
          "25": "PB", "26": "PE", "27": "AL", "28": "SE", "29": "BA", "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR", "42": "SC",
          "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF"}


def wkt(g):
    """POLYGON/MULTIPOLYGON em WKT -> lista de polígonos, cada um lista de anéis [(lon, lat)]."""
    polys = []
    for p in re.findall(r"\(\(([^()]*(?:\)\s*,\s*\([^()]*)*)\)\)", g):
        polys.append([[tuple(map(float, xy.split())) for xy in anel.split(",")] for anel in re.split(r"\)\s*,\s*\(", p)])
    return polys


def dp(pts, tol):
    if len(pts) < 4: return pts
    keep = [False] * len(pts); keep[0] = keep[-1] = True
    pilha = [(0, len(pts) - 1)]
    while pilha:
        a, b = pilha.pop()
        (x1, y1), (x2, y2) = pts[a], pts[b]
        dx, dy = x2 - x1, y2 - y1; L = math.hypot(dx, dy)
        imax, dmax = -1, tol
        for i in range(a + 1, b):
            x, y = pts[i]
            d = abs(dy * x - dx * y + x2 * y1 - y2 * x1) / L if L > 1e-9 else math.hypot(x - x1, y - y1)   # anel fechado: distância ao ponto inicial
            if d > dmax: imax, dmax = i, d
        if imax > 0:
            keep[imax] = True; pilha += [(a, imax), (imax, b)]
    return [p for p, k in zip(pts, keep) if k]


def projeta(feats, largura=1000, tol=1.4, area_min=0.5):
    """feats: {id: (nome, [polígonos em lon/lat])} -> (vb, {id: {n, p}})"""
    lons = [x for _, ps in feats.values() for pol in ps for anel in pol for x, _ in anel]
    lats = [y for _, ps in feats.values() for pol in ps for anel in pol for _, y in anel]
    k = math.cos(math.radians((min(lats) + max(lats)) / 2))
    x0, y1 = min(lons), max(lats)
    esc = largura / ((max(lons) - x0) * k)
    alt = round((y1 - min(lats)) * esc)
    out = {}
    for fid, (nome, ps) in feats.items():
        d = []
        for pol in ps:
            for anel in pol:
                pts = [((x - x0) * k * esc, (y1 - y) * esc) for x, y in anel]
                pts = dp(pts, tol)
                if len(pts) < 4: continue
                a = abs(sum(pts[i][0] * pts[i - 1][1] - pts[i - 1][0] * pts[i][1] for i in range(len(pts)))) / 2
                if a < area_min and len(ps) > 1: continue                   # ilhotas minúsculas
                d.append("M" + "L".join(f"{x:.1f},{y:.1f}".replace(".0,", ",").replace(".0L", "L") for x, y in pts[:-1]) + "Z")
        out[fid] = {"n": nome, "p": "".join(d)}
    return [largura, alt], out


# municípios por UF + tabela de regiões
reg = []
for f in sorted(glob.glob(os.path.join(ENT, "*_malhas.csv"))):
    uf = os.path.basename(f)[:2]
    feats = {}
    for r in csv.DictReader(open(f, encoding="utf-8")):
        feats[r["codarea"]] = (r["nome"], wkt(r["geometry"]))
        fix = lambda s: s.replace("Juíz de Fora", "Juiz de Fora")           # grafia errada na API do IBGE
        reg.append([r["codarea"], r["nome"], uf, fix(r["microrregiao"]), fix(r["mesorregiao"]), fix(r["regiao_imediata"]), fix(r["regiao_intermediaria"])])
    vb, m = projeta(feats)
    json.dump({"vb": vb, "fonte": "Malha municipal do IBGE (via Miguel-mmf/ibge), simplificada", "m": m},
              open(os.path.join(SAI, uf + ".json"), "w"), ensure_ascii=False, separators=(",", ":"))
    print(uf, len(m), os.path.getsize(os.path.join(SAI, uf + ".json")) // 1024, "KB")
with open(os.path.join(AQUI, "ibge_regioes_br.csv"), "w", encoding="utf-8", newline="") as fh:
    w = csv.writer(fh, delimiter=";"); w.writerow(["cod_ibge", "municipio", "uf", "microrregiao", "mesorregiao", "regiao_imediata", "regiao_intermediaria"])
    w.writerows(sorted(reg))

# UFs
g = json.load(open(os.path.join(ENT, "br_states.json")))
feats = {}
for ft in g["features"]:
    s = ft["properties"]["SIGLA"]; geo = ft["geometry"]
    ps = geo["coordinates"] if geo["type"] == "MultiPolygon" else [geo["coordinates"]]
    feats[s] = (ft["properties"]["Estado"], [[[tuple(p) for p in anel] for anel in pol] for pol in ps])
vb, m = projeta(feats, tol=0.9, area_min=2)
json.dump({"vb": vb, "fonte": "Contorno das UFs (via giuliano-oliveira/geodata-br-states), simplificado", "m": m},
          open(os.path.join(SAI, "BR.json"), "w"), ensure_ascii=False, separators=(",", ":"))
print("BR", len(m), os.path.getsize(os.path.join(SAI, "BR.json")) // 1024, "KB")
