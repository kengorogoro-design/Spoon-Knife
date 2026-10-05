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

def m1164(a,b,c):
    return ((max(math.log1p(abs(((b)-(0.49012582594290555)))),math.log1p(abs(math.log1p(abs(b))))))+(max(math.sqrt(abs(math.log1p(abs(b)))),((math.log1p(abs(b)))-(-0.45386621131797567)))))

def m1003(a):
    return a

def represent(x):
    return math.tanh(((sd(min(x,x),x))*(1.0)))

def generate(v,noise):
    return max(1e-6,max(1e-6,((math.exp(max(-6,min(6,max(noise,0.24747325093236316)))))*(math.exp(max(-6,min(6,((noise)*(0.18)))))))))

def evaluate(metrics):
    xs=[max(1e-9,float(x)) for x in metrics]; floor=min(xs); gm=math.exp(sum(math.log(x) for x in xs)/len(xs)); mean=sum(xs)/len(xs); spread=max(xs)-min(xs); novelty=abs(xs[-1]-xs[0])
    return float(((abs(1.1210075191323379))+(math.sqrt(max(1e-12,abs((-(max(1e-6,mean)))*abs(max(1e-6,spread))))))))

def search_pressure(stagnation,novelty,uncertainty=0,archive_diversity=0):
    return max(0,min(1,float(max(0,min(1,((((stagnation)*(0.18)))+(abs(max(novelty,0.32)))))))))

LANGUAGE_ID='F1184'

LANGUAGE_SHA='816ab5699e4aef32c36eb95845d1424040b53b349cebe514c4063096526e4b1e'

OPS=('abs', 'add', 'clip01', 'clippos', 'div', 'exp', 'gmean', 'log', 'max', 'mean', 'min', 'mul', 'neg', 'sigmoid', 'sqrt', 'sub', 'tanh')

MACROS=('blend', 'm1012', 'm1061', 'm1164', 'm1003')
