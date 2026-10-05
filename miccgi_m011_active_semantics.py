import math

def sd(a,b): return a/(b if abs(b)>1e-9 else (1e-9 if b>=0 else -1e-9))

def sg(x): x=max(-30.0,min(30.0,x)); return 1/(1+math.exp(-x))

import math
def sd(a,b): return a/(b if abs(b)>1e-9 else (1e-9 if b>=0 else -1e-9))
def sg(x): x=max(-30.0,min(30.0,x)); return 1/(1+math.exp(-x))
def spi_9b7b932aead5(a,b):
    return float((((-(min(b,0.24675351315042615))))-((-(abs(-0.5647305614130238))))))


import math
def sd(a,b): return a/(b if abs(b)>1e-9 else (1e-9 if b>=0 else -1e-9))
def sg(x): x=max(-30.0,min(30.0,x)); return 1/(1+math.exp(-x))
def spi_d66a822cf7eb(a,b):
    return float(((((math.sqrt(abs(math.log1p(abs(a)))))*(math.tanh(a))))+(((((min(b,0.5041938480312045))*(((b)-(-0.6533705026017482)))))+(abs(math.tanh(a)))))))


def active_controller(a,b): return spi_d66a822cf7eb(a,b)
