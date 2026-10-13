"""Design-aware audit for a stratified, finite calibration/test partition.

Bounds are for the frozen remaining test pool and fixed per-question potential
outcomes under the admitted seed/runtime, not unseen deployment distributions.
"""
import math
import json,hashlib
from collections import Counter
from pathlib import Path
from fractions import Fraction
import numpy as np
from scipy.special import logsumexp
from scipy.stats import hypergeom


def strata_from_frozen_data(root):
    root=Path(root);freeze=json.loads((root/'provenance/data_freeze.json').read_text())
    counts=[]
    for split in ['calibration','test']:
        file=root/f'data/{split}.jsonl'
        assert hashlib.sha256(file.read_bytes()).hexdigest()==freeze['splits'][split]['sha256']
        rows=[json.loads(s) for s in file.read_text(encoding='utf-8').splitlines()]
        assert {r['problem_id'] for r in rows}==set(freeze['splits'][split]['ids'])
        # Only already frozen design metadata enters this calculation.
        counts.append(Counter((r['subject'],int(r['difficulty'])//2) for r in rows))
    keys=sorted(set(counts[0])|set(counts[1]))
    return [(counts[0][k]+counts[1][k],counts[0][k]) for k in keys]


def validate_strata(strata):
    assert strata and all(isinstance(N,int) and isinstance(n,int) and 0<=n<=N for N,n in strata)


def zero_harm_tail_bound(strata,total_harms):
    """Exact worst probability of no observed harm over integer allocations."""
    validate_strata(strata);M=int(total_harms)
    if M>sum(N for N,n in strata):return 0.
    assert M>=0
    dp=[None]*(M+1);dp[0]=Fraction(1)
    for N,n in strata:
        factors=[Fraction(math.comb(N-k,n),math.comb(N,n)) if N-k>=n else Fraction(0)
                 for k in range(min(N,M)+1)]
        next_dp=[None]*(M+1)
        for previous,value in enumerate(dp):
            if value is None:continue
            for k,factor in enumerate(factors[:M-previous+1]):
                candidate=value*factor;old=next_dp[previous+k]
                if old is None or candidate>old:next_dp[previous+k]=candidate
        dp=next_dp
    return min(1.,float(dp[M])+1e-12)


def lower_tail_bound(strata,total_harms,observed_harms):
    """Chernoff upper bound after maximizing over every harm allocation.

For each negative lambda, dynamic programming maximizes the product of exact
hypergeometric MGFs. Markov bounds P(X<=h). The minimum of fixed valid bounds
is still a valid bound. The zero case uses an exact rational DP instead.
"""
    validate_strata(strata);M=int(total_harms);h=int(observed_harms)
    assert h>=0 and M>=0
    if M>sum(N for N,n in strata):return 0.
    if h==0:return zero_harm_tail_bound(strata,M)
    if h>=M:return 1.
    remaining=M;minimum_mean=0.
    for rate,N in sorted((n/N,N) for N,n in strata if N):
        take=min(remaining,N);minimum_mean+=take*rate;remaining-=take
        if not remaining:break
    # Jensen: for an allocation with E[X]<=h, every negative-lambda
    # Chernoff expression is >=1. Maximizing allocations cannot improve it.
    if minimum_mean<=h:return 1.
    lambdas=-np.array([.02,.05,.1,.2,.4,.8,1.6,3.2,6.4,12.8,25.6])
    dp=np.full((len(lambdas),M+1),-np.inf);dp[:,0]=0.
    for N,n in strata:
        limit=min(N,M);factors=np.zeros((len(lambdas),limit+1))
        for k in range(1,limit+1):
            values=np.arange(max(0,n-(N-k)),min(k,n)+1)
            logp=hypergeom.logpmf(values,N,k,n)
            factors[:,k]=logsumexp(logp[None,:]+lambdas[:,None]*values[None,:],axis=1)
        new=np.full_like(dp,-np.inf)
        for k in range(limit+1):
            new[:,k:]=np.maximum(new[:,k:],dp[:,:M+1-k]+factors[:,k,None])
        dp=new
    log_bound=np.min(dp[:,M]-lambdas*h)
    return min(1.,float(np.exp(min(0.,log_bound)))+1e-12)


def finite_test_risk_audit(strata,observed_harms,risk_target,alpha):
    n_test=sum(N-n for N,n in strata);assert n_test>0
    allowed=math.floor(risk_target*n_test)
    # Reject H_test >= allowed+1. Invert a worst lower-tail bound on total
    # population harms at M=h+allowed+1. Monotonicity gives coverage for the
    # unknown held-out total even though h is observed after sampling.
    null_total=int(observed_harms)+allowed+1
    probability_upper=lower_tail_bound(strata,null_total,observed_harms)
    return {'risk_target':risk_target,'held_out_n':n_test,'maximum_allowed_test_harms':allowed,
            'calibration_harms':int(observed_harms),'null_total_harms':null_total,
            'worst_lower_tail_probability_upper':probability_upper,'alpha':alpha,
            'risk_bound_passed':probability_upper<=alpha,
            'scope':'Fixed remaining finite test pool; stratified uniform sampling without replacement, fixed policy/potential outcomes; not a deployment-population certificate.'}
