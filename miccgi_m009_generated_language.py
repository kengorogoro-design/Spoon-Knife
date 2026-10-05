import math

# MICCGI M009 generated evolvable language

def sd(a,b): return a/(b if abs(b)>1e-9 else (1e-9 if b>=0 else -1e-9))

def sg(x): x=max(-30,min(30,x)); return 1/(1+math.exp(-x))

def blend(a,b):
    return ((a+b)/2)

def m1018(a):
    return abs(((((sd(a,a))+(math.exp(max(-6,min(6,a))))))-(math.log1p(abs(math.exp(max(-6,min(6,a))))))))

def m1264(a):
    return abs(max(math.tanh(m1018(a)),((-0.6286678774376366)*(a))))

def represent(x):
    return math.tanh(((max(1e-6,x))-(math.log1p(abs(1.0)))))

def generate(v,noise):
    return max(1e-6,max(1e-6,max(((math.exp(max(-6,min(6,v)))+math.tanh(0.8997480137360923))/2),math.exp(max(-6,min(6,((noise)*(0.18))))))))

def evaluate(metrics):
    xs=[max(1e-9,float(x)) for x in metrics]; floor=min(xs); gm=math.exp(sum(math.log(x) for x in xs)/len(xs)); mean=sum(xs)/len(xs); spread=max(xs)-min(xs); novelty=abs(xs[-1]-xs[0])
    return float(((((floor)*(1.2)))+(((math.exp(max(-6,min(6,1.5890928941451343))))+(((floor)+(1.540548243462742)))))))

def search_pressure(stagnation,novelty,uncertainty=0,archive_diversity=0):
    return max(0,min(1,float(max(0,min(1,((min(abs(-0.6628700148778257),max(1e-6,stagnation)))+(((novelty)*(0.32)))))))))

LANGUAGE_ID='L1264'

LANGUAGE_SHA='1cb67754ce75c95abf5addafd4043ddd2ebec76fb42d42b5539f1b0076cbeec7'

OPS=('abs', 'add', 'clip01', 'clippos', 'div', 'exp', 'gmean', 'log', 'max', 'mean', 'min', 'mul', 'neg', 'sigmoid', 'sub', 'tanh')

MACROS=('blend', 'm1018', 'm1264')
