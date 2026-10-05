# M010 externally admitted primitives
import math
def sd(a,b): return a/(b if abs(b)>1e-9 else (1e-9 if b>=0 else -1e-9))
def sg(x): x=max(-30.0,min(30.0,x)); return 1.0/(1.0+math.exp(-x))
def pi_dcf6dcbf4b46(a,b):
    return float(abs(((a)-(b))))

def active_controller(a,b): return pi_dcf6dcbf4b46(a,b)
