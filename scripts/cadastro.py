"""Cadastro de cooperativas (Olinda SedesCooperativas) com proteção contra respostas incompletas do Banco Central.

O cadastro decide quem é filiada a qual central (Crediminas, Cecremge, Sicoob, solteiras...). Se a API devolver a
filiação vazia por falha, todo o painel muda de grupo de uma vez. Por isso:
  - a última versão boa fica salva em site/data/cadastro_coop.json (versionada no repositório);
  - resposta com menos de 90% das cooperativas da versão salva é descartada inteira;
  - filiação que some (preenchida -> vazia) só é aceita se continuar vazia por 6 dias ou mais (a rotina é semanal,
    então a mudança precisa aparecer em duas rodadas); até lá vale a filiação anterior;
  - mais de 15% das filiações sumindo de uma vez é tratado como falha da base: vale a versão salva inteira;
  - troca de uma central para outra e cooperativa nova entram direto.
Uso: from cadastro import sedes_coop; coop = sedes_coop(fetch)  ->  {cnpj: registro}
"""
import json, os, sys, datetime

AQUI = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(AQUI, "..", "site", "data", "cadastro_coop.json")
URL = "Instituicoes_em_funcionamento/versao/v1/odata/SedesCooperativas?$format=json"
DIAS = 6


def _fil(x): return (x.get("FILIACAO") or "").strip()


def sedes_coop(fetch):
    """fetch(path_olinda) -> lista de registros. Devolve {CNPJ: registro} já protegido."""
    hoje = datetime.date.today()
    snap = None
    try:
        with open(SNAP, encoding="utf-8") as f: snap = json.load(f)
    except Exception: pass
    try:
        novo = {x["CNPJ"]: x for x in fetch(URL)}
    except Exception as e:
        if snap: print(f"aviso: cadastro do BC indisponível ({e}); usando a versão salva de {snap['data']}", file=sys.stderr); return snap["coop"]
        raise
    if not snap:
        _salva(novo, {}, hoje); return novo
    velho, pend = snap["coop"], snap.get("pendentes", {})
    if len(novo) < 0.9 * len(velho):
        msg = f"cadastro do BC veio com {len(novo)} cooperativas contra {len(velho)} em {hoje.isoformat()}; mantida a versão de {snap['data']}"
        print("aviso: " + msg, file=sys.stderr); _salva(velho, pend, datetime.date.fromisoformat(snap["data"]), msg)
        return velho
    sumiu = [c for c in novo if c in velho and _fil(velho[c]) and not _fil(novo[c])]
    com_fil = sum(1 for x in velho.values() if _fil(x))
    if com_fil and len(sumiu) > 0.15 * com_fil:
        msg = f"{len(sumiu)} filiações vieram vazias de uma vez no cadastro do BC em {hoje.isoformat()}; mantida a versão de {snap['data']}"
        print("aviso: " + msg, file=sys.stderr); _salva(velho, pend, datetime.date.fromisoformat(snap["data"]), msg)
        return velho
    out, pend2 = {}, {}
    for c, x in novo.items():
        if c in sumiu:
            desde = pend.get(c, hoje.isoformat())
            if (hoje - datetime.date.fromisoformat(desde)).days >= DIAS:
                out[c] = x                                   # vazio confirmado em duas rodadas: aceita
            else:
                out[c] = dict(x, FILIACAO=velho[c]["FILIACAO"]); pend2[c] = desde
        else:
            out[c] = x
    if pend2: print(f"aviso: {len(pend2)} filiações vazias no BC mantidas pela versão anterior até confirmar", file=sys.stderr)
    _salva(out, pend2, hoje, f"{len(pend2)} filiações vazias aguardando confirmação" if pend2 else "")
    return out


def _salva(coop, pend, hoje, alerta=""):
    tmp = SNAP + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"data": hoje.isoformat(), "fonte": "Banco Central, Olinda SedesCooperativas", "alerta": alerta, "pendentes": pend, "coop": coop},
                  f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, SNAP)
