import math
# MICCGI M008 generated meta-machinery
REPRESENTATION_POWER=0.45
GENERATOR_SCALE=0.06648649032251544
EVALUATOR_FLOOR=1.2547555484705195
EVALUATOR_BALANCE=0.7425457490566276
SEARCH_RADICAL=0.1227697506490386
SEARCH_MEMORY=0.7052097230565283

def represent(x):
    return math.copysign(abs(x)**REPRESENTATION_POWER,x)

def generate(v,noise):
    return max(0.001,v*math.exp(noise*GENERATOR_SCALE))

def evaluate(metrics):
    xs=[max(1e-9,float(x)) for x in metrics]
    floor=min(xs)
    gm=math.exp(sum(math.log(x) for x in xs)/len(xs))
    mean=sum(xs)/len(xs)
    return EVALUATOR_FLOOR*floor+EVALUATOR_BALANCE*gm+(1-EVALUATOR_BALANCE)*mean

def search_pressure(stagnation,novelty):
    return min(1.0,max(0.0,SEARCH_RADICAL*(1+stagnation*.25)+novelty*(1-SEARCH_MEMORY)))
