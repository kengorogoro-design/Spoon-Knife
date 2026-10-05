import miccgi_m009_runtime as m

def emit_fixed(g):
    nl=chr(10)
    z=[
        "import math",
        "# MICCGI M009 generated evolvable language",
        "def sd(a,b): return a/(b if abs(b)>1e-9 else (1e-9 if b>=0 else -1e-9))",
        "def sg(x): x=max(-30,min(30,x)); return 1/(1+math.exp(-x))",
    ]
    for macro in g["macros"]:
        z.append(
            "def "+macro["n"]+"("+",".join(macro["p"])+"):"+nl+
            "    return "+m.es(macro["e"])
        )
    z.extend([
        "def represent(x):"+nl+"    return "+m.es(g["rep"]),
        "def generate(v,noise):"+nl+"    return max(1e-6,"+m.es(g["gen"])+")",
        "def evaluate(metrics):"+nl+
        "    xs=[max(1e-9,float(x)) for x in metrics]; floor=min(xs); gm=math.exp(sum(math.log(x) for x in xs)/len(xs)); mean=sum(xs)/len(xs); spread=max(xs)-min(xs); novelty=abs(xs[-1]-xs[0])"+nl+
        "    return float("+m.es(g["eval"])+")",
        "def search_pressure(stagnation,novelty,uncertainty=0,archive_diversity=0):"+nl+
        "    return max(0,min(1,float("+m.es(g["search"])+")))",
        "LANGUAGE_ID="+repr(g["id"]),
        "LANGUAGE_SHA="+repr(m.H(g)),
        "OPS="+repr(tuple(g["ops"])),
        "MACROS="+repr(tuple(x["n"] for x in g["macros"])),
    ])
    return (nl+nl).join(z)+nl

m.emit=emit_fixed

if __name__=="__main__":
    m.main()
