import math

# MICCGI M009 generated evolvable language

def sd(a,b): return a/(b if abs(b)>1e-9 else (1e-9 if b>=0 else -1e-9))

def sg(x): x=max(-30,min(30,x)); return 1/(1+math.exp(-x))

def blend(a,b):
    return ((a+b)/2)

def m1012(a,b):
    return min(b,max(1e-6,max(0,min(1,b))))

def m1061(a,b):
    return (-(max(1e-6,a)))

def represent(x):
    return m1012(m1012(x,1.0245360508072758),x)

def generate(v,noise):
    return max(1e-6,max(1e-6,((math.exp(max(-6,min(6,max(noise,0.24747325093236316)))))*(math.exp(max(-6,min(6,((noise)*(0.18)))))))))

def evaluate(metrics):
    xs=[max(1e-9,float(x)) for x in metrics]; floor=min(xs); gm=math.exp(sum(math.log(x) for x in xs)/len(xs)); mean=sum(xs)/len(xs); spread=max(xs)-min(xs); novelty=abs(xs[-1]-xs[0])
    return float(((abs(1.1210075191323379))+(math.sqrt(max(1e-12,abs(max(1e-6,mean)*abs(max(1e-6,spread))))))))

def search_pressure(stagnation,novelty,uncertainty=0,archive_diversity=0):
    return max(0,min(1,float(max(0,min(1,((((stagnation)*(0.18)))+(abs(max(novelty,0.32)))))))))

LANGUAGE_ID='L1061'

LANGUAGE_SHA='a70e00b5419ccc9bd3d3176e16f43084eeada04e1787de98cab46f655e4a64df'

OPS=('abs', 'add', 'clip01', 'clippos', 'exp', 'gmean', 'log', 'max', 'mean', 'min', 'mul', 'neg', 'sigmoid', 'sqrt', 'sub')

MACROS=('blend', 'm1012', 'm1061')
