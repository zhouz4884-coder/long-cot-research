import numpy as np
from sklearn.linear_model import LogisticRegression,Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

FEATURES=['length','log_length','entropy','margin','logprob','reflection_count','repeat4','steps','reflective']


class Constant:
    def __init__(self,p):self.p=float(p)
    def predict_proba(self,x):
        p=np.full(len(x),self.p);return np.stack([1-p,p],axis=1)


def fit_head(x,y):
    if len(np.unique(y))<2:return Constant(np.mean(y))
    model=make_pipeline(StandardScaler(),LogisticRegression(C=1.0,max_iter=2000,random_state=20261008))
    model.fit(x,y)
    return model


def matrix(rows,features=FEATURES):
    x=np.array([[r['features'][k] for k in features] for r in rows],dtype=np.float64)
    if not np.isfinite(x).all():raise ValueError('Nonfinite predictor inputs')
    return x


def targets(rows):
    stop=np.array([r['stop_correct'] for r in rows]);step=np.array([r['step_correct'] for r in rows]);full=np.array([r['end_correct'] for r in rows])
    return {'step_fix':((stop==0)&(step==1)).astype(int),'step_harm':((stop==1)&(step==0)).astype(int),
            'full_fix':((stop==0)&(full==1)).astype(int),'full_harm':((stop==1)&(full==0)).astype(int),
            'stop_correct':stop,'step_correct':step,'full_correct':full}


class Predictor:
    def __init__(self,features=FEATURES):self.features=features;self.heads={}
    def fit(self,rows):
        x=matrix(rows,self.features)
        self.heads={k:fit_head(x,y) for k,y in targets(rows).items()}
        self.cost_step=float(np.median([r['step_tokens']-r['stop_tokens'] for r in rows]))
        self.cost_full=float(np.median([r['end_tokens']-r['stop_tokens'] for r in rows]))
        self.cost_heads={}
        for action,key in [('STEP','step_tokens'),('FULL','end_tokens')]:
            costs=np.log1p([max(0,r[key]-r['stop_tokens']) for r in rows])
            self.cost_heads[action]=make_pipeline(StandardScaler(),Ridge(alpha=1.0)).fit(x,costs)
        self.length_range=(float(x[:,self.features.index('length')].min()),float(x[:,self.features.index('length')].max())) if 'length' in self.features else (0,4096)
        return self
    def predict(self,rows):
        x=matrix(rows,self.features)
        return {k:model.predict_proba(x)[:,1] for k,model in self.heads.items()}
    def choose(self,features,cost_lambda=0.0001,margin=0.0,mode='transition'):
        pred={k:float(v[0]) for k,v in self.predict([{'features':features}]).items()}
        # Conservative fallback outside the observed training support.
        if features['length']>self.length_range[1]:return 'FULL',pred
        x=matrix([{'features':features}],self.features)
        costs={a:float(np.expm1(np.clip(m.predict(x)[0],0,12))) for a,m in self.cost_heads.items()}
        delta_step=pred['step_correct']-pred['stop_correct'] if mode=='outcome' else pred['step_fix']-pred['step_harm']
        delta_full=pred['full_correct']-pred['stop_correct'] if mode=='outcome' else pred['full_fix']-pred['full_harm']
        values={'STOP':margin,'STEP':delta_step-cost_lambda*costs['STEP'],'FULL':delta_full-cost_lambda*costs['FULL']}
        return max(values,key=values.get),{**pred,'values':values,'predicted_extra_tokens':costs,'mode':mode}
