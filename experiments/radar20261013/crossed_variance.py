"""Finite-sample method-of-moments decomposition for crossed random seeds."""
import numpy as np


def crossed_components(values):
    y=np.asarray(values,dtype=float)
    if y.ndim!=2 or min(y.shape)<2 or not np.isfinite(y).all():
        raise ValueError('Need at least two independent seed levels on each axis')
    r,m=y.shape
    row=y.mean(axis=1);column=y.mean(axis=0);grand=y.mean()
    residual=y-row[:,None]-column[None,:]+grand
    interaction=float(np.square(residual).sum()/((r-1)*(m-1)))
    return {'within_readout':float(np.var(y,axis=1,ddof=1).mean()),
            'observed_reasoning_means':float(np.var(row,ddof=1)),
            'reasoning_unclipped':float(np.var(row,ddof=1))-interaction/m,
            'answer_seed_unclipped':float(np.var(column,ddof=1))-interaction/r,
            'interaction':interaction}
