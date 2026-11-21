#!/usr/bin/env python3
"""Teste: baixa uma amostra de demonstrações da Central de Demonstrações Financeiras do SFN (BC),
extrai o texto e guarda as páginas com a tabela de maiores devedores, para desenvolver a leitura."""
import json, os, re, subprocess, sys, time, urllib.parse, urllib.request

BASE = "https://www3.bcb.gov.br/informes/rest/balanco"
UA = {"User-Agent": "dashboard-credito (github actions)"}
KW = re.compile(r"maiores\s+devedores|maior\s+devedor|maiores\s+clientes|devedores\s+seguintes|concentra[çc][ãa]o\s+d[aeo]s?\s+(?:opera|carteira|risco|cr[ée]dito)", re.I)
BANCOS = {"00000000": "BB", "60746948": "Bradesco", "60872504": "Itaú Holding", "60701190": "Itaú Unibanco", "00360305": "Caixa",
          "90400888": "Santander", "30306294": "BTG", "00416968": "Inter", "31872495": "C6", "30680829": "Nu Financeira",
          "18236120": "Nu Pagamentos", "08561701": "PagSeguro", "10264663": "Banco Seguro", "10573521": "Mercado Pago",
          "01181521": "Banco Sicredi", "02038232": "Banco Sicoob", "92702067": "Banrisul"}
COOPS = {"71297899": "Sicoob Credicopa", "02480577": "Sicoob Credijur", "81011686": "Sicoob Credinorte", "35571249": "Sicredi Evolução",
         "91586982": "Sicredi Pioneira", "02663426": "Cresol Noroeste", "08624548": "Cresol MG", "82639451": "Viacredi (Ailos)",
         "01039011": "Unicred Desbravadora", "02833202": "Unicred Sudoeste", "03985375": "Credisis Sudoeste", "01286361": "Uniprime Pioneira",
         "44746352": "Coop. Barra Bonita (solteira)", "75174953": "Coop. Votorantim (solteira)"}
COMBINADOS = {"sicoob_202512": "https://www.sicoob.com.br/documents/d/relacaocooperados/demonstracoes-contabeis-combinadas-do-sicoob-dez-2025?download=true",
              "sicredi_202509": "https://www.sicredi.com.br/media/produtos/filer_public/2025/12/09/df_combinado_202509.pdf"}


def get(url, tries=4, timeout=180):
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except Exception as e:
            if k == tries - 1: raise
            time.sleep(6 * (k + 1))


def paginas(pdf):
    p = subprocess.run(["pdftotext", "-layout", pdf, "-"], capture_output=True, timeout=600)
    return p.stdout.decode("utf-8", "replace").split("\f")


def guarda(out, chave, pdf_bytes, resumo):
    f = os.path.join(out, chave + ".pdf")
    open(f, "wb").write(pdf_bytes)
    pg = paginas(f); os.remove(f)
    cand = [i for i, t in enumerate(pg) if KW.search(t)]
    txt = sum(len(t.strip()) for t in pg)
    keep = sorted({j for i in cand for j in (i - 1, i, i + 1) if 0 <= j < len(pg)})
    with open(os.path.join(out, chave + ".txt"), "w", encoding="utf-8") as fh:
        for j in keep: fh.write(f"\n=== página {j + 1} ===\n{pg[j]}")
    resumo[chave] = {"bytes": len(pdf_bytes), "paginas": len(pg), "caracteres": txt, "candidatas": [i + 1 for i in cand]}
    print(chave, len(pdf_bytes) // 1024, "KB", len(pg), "pág.", "texto" if txt > 2000 else "SEM TEXTO", "candidatas:", [i + 1 for i in cand][:12], flush=True)


def main():
    out = sys.argv[1]; os.makedirs(out, exist_ok=True)
    resumo, listas = {}, {}
    for grupo, alvo, ams in (("banco", BANCOS, ("202606", "202112")), ("coop", COOPS, ("202606", "202112"))):
        for cnpj, nome in alvo.items():
            for am in ams:
                try:
                    docs = json.loads(get(f"{BASE}/?cnpj={cnpj}&anoMes={am}&periodo=6"))
                except Exception as e:
                    print(cnpj, nome, am, "ERRO lista", e, flush=True); continue
                listas[f"{cnpj}_{am}"] = [(d["tipo"]["codigo"], d["nomeArquivo"], d.get("tamanhoArquivo")) for d in docs]
                pdfs = [d for d in docs if d["nomeArquivo"].lower().endswith(".pdf") and d["tipo"]["codigo"] in (9010, 9030)]
                if not pdfs: print(cnpj, nome, am, "sem PDF", [d["nomeArquivo"] for d in docs], flush=True)
                for d in pdfs:
                    try:
                        b = get(f"{BASE}/download/{urllib.parse.quote(d['nomeArquivo'])}?cnpj={cnpj}&anoMes={am}&periodo=3", timeout=400)
                        guarda(out, f"{grupo}_{cnpj}_{am}_{d['tipo']['codigo']}", b, resumo)
                    except Exception as e:
                        print(cnpj, nome, am, d["nomeArquivo"], "ERRO download", e, flush=True)
    for k, u in COMBINADOS.items():
        try: guarda(out, "combinado_" + k, get(u, timeout=400), resumo)
        except Exception as e: print(k, "ERRO", e, flush=True)
    json.dump({"resumo": resumo, "listas": listas, "nomes": {**BANCOS, **COOPS}}, open(os.path.join(out, "resumo.json"), "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
