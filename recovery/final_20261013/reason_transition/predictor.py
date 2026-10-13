import numpy as np
from sklearn.linear_model import LogisticRegression,Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

FEATURES=['length','log_length','entropy','margin','logprob','reflection_count','repeat4','steps','reflective']
READOUT_FEATURES=FEATURES+['readout_entropy']


def with_readout(rows):
    return [{**r,'features':{**r['features'],'readout_entropy':r['stop']['eat_entropy']}} for r in rows]


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
        self._compile_linear_heads()
        return self

    def _compile_linear_heads(self):
        """Algebraically fuse fitted scaler/linear heads for online decisions."""
        self.fast_names=list(self.heads)
        weights=[];biases=[];constants=[]
        for model in self.heads.values():
            if isinstance(model,Constant):
                weights.append(np.zeros(len(self.features)));biases.append(0.0);constants.append(model.p)
            else:
                scaler=model.named_steps['standardscaler'];linear=model.named_steps['logisticregression']
                weight=linear.coef_.reshape(-1)/scaler.scale_
                weights.append(weight);biases.append(float(linear.intercept_[0]-weight@scaler.mean_));constants.append(np.nan)
        self.fast_weights=np.asarray(weights);self.fast_bias=np.asarray(biases);self.fast_constants=np.asarray(constants)
        cost_weights=[];cost_bias=[]
        for action in ['STEP','FULL']:
            model=self.cost_heads[action];scaler=model.named_steps['standardscaler'];linear=model.named_steps['ridge']
            weight=linear.coef_.reshape(-1)/scaler.scale_
            cost_weights.append(weight);cost_bias.append(float(linear.intercept_-weight@scaler.mean_))
        self.fast_cost_weights=np.asarray(cost_weights);self.fast_cost_bias=np.asarray(cost_bias)

    def fast_one(self,features):
        if not hasattr(self,'fast_weights'):self._compile_linear_heads()
        x=np.asarray([features[k] for k in self.features],dtype=float)
        if not np.isfinite(x).all():raise ValueError('Nonfinite online features')
        z=self.fast_weights@x+self.fast_bias
        probabilities=1/(1+np.exp(-np.clip(z,-700,700)))
        known=np.isfinite(self.fast_constants);probabilities[known]=self.fast_constants[known]
        pred=dict(zip(self.fast_names,probabilities.tolist()))
        cost_values=np.expm1(np.clip(self.fast_cost_weights@x+self.fast_cost_bias,0,12))
        return pred,dict(zip(['STEP','FULL'],cost_values.tolist()))
    def predict(self,rows):
        x=matrix(rows,self.features)
        return {k:model.predict_proba(x)[:,1] for k,model in self.heads.items()}
    def choose(self,features,cost_lambda=0.0001,margin=0.0,mode='transition',prepared=None):
        pred,costs=self.fast_one(features) if prepared is None else prepared
        # Conservative fallback outside the observed training support.
        if features['length']>self.length_range[1]:return 'FULL',pred
        delta_step=pred['step_correct']-pred['stop_correct'] if mode=='outcome' else pred['step_fix']-pred['step_harm']
        delta_full=pred['full_correct']-pred['stop_correct'] if mode=='outcome' else pred['full_fix']-pred['full_harm']
        values={'STOP':margin,'STEP':delta_step-cost_lambda*costs['STEP'],'FULL':delta_full-cost_lambda*costs['FULL']}
        return max(values,key=values.get),{**pred,'values':values,'predicted_extra_tokens':costs,'mode':mode}


class TreePredictor(Predictor):
    def fit(self,rows):
        from sklearn.ensemble import GradientBoostingClassifier
        super().fit(rows)
        x=matrix(rows,self.features)
        self.heads={}
        for key,y in targets(rows).items():
            if len(np.unique(y))<2:self.heads[key]=Constant(np.mean(y))
            else:
                model=GradientBoostingClassifier(n_estimators=100,max_depth=2,min_samples_leaf=15,
                    learning_rate=0.05,subsample=0.8,random_state=20261008)
                self.heads[key]=model.fit(x,y)
        return self

    def fast_one(self,features):
        x=matrix([{'features':features}],self.features)
        pred={k:(m.p if isinstance(m,Constant) else float(m.predict_proba(x)[0,1])) for k,m in self.heads.items()}
        costs=np.expm1(np.clip(self.fast_cost_weights@x[0]+self.fast_cost_bias,0,12))
        return pred,dict(zip(['STEP','FULL'],costs.tolist()))
