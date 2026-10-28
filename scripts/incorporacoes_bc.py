import re,glob,json,sys
D=sys.argv[1]; out=[]
for f in sorted(glob.glob(D+"/q_*.txt")):
    t=open(f,encoding="utf-8",errors="ignore").read()
    m=re.search(r"\n\s*Incorpora[çc][õo]es\s*\n(.*?)(\n\s*(Autoriza|Cancelamento|Mudan|Transfer|Fus[ãa]o|Cis[ãa]o|Elei|Altera|Reorganiza|Conversão|Instala)[^\n]{0,80}\n\s*Resumo)",t,re.S)
    if not m: continue
    s=re.sub(r"\s+"," ",m.group(1))
    for it in re.finditer(r"([A-ZÀ-Ú][^()]{5,220}?)\(CNPJ:?\s*(\d{2}\.\d{3}\.\d{3})\)\.?\s*Assuntos?:\s*incorpora[çc][ãa]o (.*?)(?:sucedendo|mediante|cancelamento|$)",s):
        inc=re.sub(r"\D","",it.group(2)); alvo=it.group(3)
        for n,c in re.findall(r"([^()]{3,200}?)\(CNPJ:?\s*(\d{2}\.\d{3}\.\d{3})\)",alvo):
            c=re.sub(r"\D","",c)
            if c!=inc: out.append({"mes":f[-10:-4],"incorporada":c,"nome_incorporada":re.sub(r"^(d[ao]s?|e)\s+","",n.strip(" ,;e")),"incorporadora":inc,"nome_incorporadora":it.group(1).strip(" .")})
json.dump(out,open(D+"/incorporacoes.json","w"),ensure_ascii=False,indent=0)
print(len(out))
