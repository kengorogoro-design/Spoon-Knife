import math

# MICCGI M009 generated evolvable language

def sd(a,b): return a/(b if abs(b)>1e-9 else (1e-9 if b>=0 else -1e-9))

def sg(x): x=max(-30,min(30,x)); return 1/(1+math.exp(-x))

def blend(a,b):
    return ((a+b)/2)

def m1012(a,b):
    return min(b,max(1e-6,max(0,min(1,b))))

def represent(x):
    return math.tanh(((((sg(x))+(blend(0.1706158293108413,x))))*(1.0)))

def generate(v,noise):
    return max(1e-6,max(1e-6,((math.exp(max(-6,min(6,max(noise,0.24747325093236316)))))*(math.exp(max(-6,min(6,((noise)*(0.18)))))))))

def evaluate(metrics):
    xs=[max(1e-9,float(x)) for x in metrics]; floor=min(xs); gm=math.exp(sum(math.log(x) for x in xs)/len(xs)); mean=sum(xs)/len(xs); spread=max(xs)-min(xs); novelty=abs(xs[-1]-xs[0])
    return float(((((floor)*(1.2)))+(math.sqrt(max(1e-12,abs(gm*abs(max(1e-6,spread))))))))

def search_pressure(stagnation,novelty,uncertainty=0,archive_diversity=0):
    return max(0,min(1,float(max(0,min(1,((((stagnation)*(0.18)))+(abs(((novelty)*(0.32))))))))))

LANGUAGE_ID='L1012'

LANGUAGE_SHA='a80d9c72ab4d692718c7c0813eafd600fae43ebf0e9117a620c32386d9317735'

OPS=('abs', 'add', 'clip01', 'clippos', 'div', 'exp', 'gmean', 'log', 'max', 'mean', 'min', 'mul', 'neg', 'sigmoid', 'sqrt', 'sub')

MACROS=('blend', 'm1012')
