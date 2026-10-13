"""Coherent joint outcome models: standard baselines, not novelty claims."""
import numpy as np
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

PREFIX_FEATURES=['length','log_length','entropy','margin','logprob','reflection_count','repeat4','steps','reflective']
ANSWER_FEATURES=['candidate_tokens','candidate_complete','candidate_logprob_mean','candidate_logprob_min',
                 'candidate_entropy_mean','candidate_first_entropy','candidate_confidence']


class JointModel:
    """Classes 00, 01, 10, 11 for current candidate vs action answer.

    STOP risk relative to FULL is class 01. All marginals and transitions derive
    from the same normalized four-way distribution. Calibrating this predictor
    alone does NOT certify a complete sequential stopping policy.
    """
    def __init__(self,features=None):
        self.features=features or PREFIX_FEATURES+ANSWER_FEATURES

    def fit(self,x,current,after,weights=None):
        x=np.asarray(x,dtype=float)
        assert np.isfinite(x).all()
        assert len(x)==len(current)==len(after)
        assert set(np.asarray(current).tolist())<={0,1} and set(np.asarray(after).tolist())<={0,1}, 'Marginal means are not binary event labels'
        labels=2*np.asarray(current,dtype=int)+np.asarray(after,dtype=int)
        self.classes=np.unique(labels)
        if len(self.classes)==1:
            self.model=None
            self.constant_class=int(self.classes[0])
        else:
            self.model=make_pipeline(StandardScaler(),LogisticRegression(C=1.0,max_iter=2000,random_state=20261013))
            self.model.fit(x,labels,logisticregression__sample_weight=weights)
        self.min_length=float(x[:,self.features.index('length')].min())
        self.max_length=float(x[:,self.features.index('length')].max())
        return self

    def probabilities(self,x):
        x=np.atleast_2d(np.asarray(x,dtype=float));assert np.isfinite(x).all()
        p=np.zeros((len(x),4))
        if self.model is None:
            p[:,self.constant_class]=1.
        else:
            values=self.model.predict_proba(x)
            p[:,self.model.named_steps['logisticregression'].classes_.astype(int)]=values
        return p

    def predict_one(self,features):
        x=[features[k] for k in self.features]
        p=self.probabilities(x)[0]
        pred={'p00':float(p[0]),'stop_harm_vs_action':float(p[1]),'stop_benefit_vs_action':float(p[2]),
              'p11':float(p[3]),'candidate_correct':float(p[2]+p[3]),'after_correct':float(p[1]+p[3]),
              'continuation_gain':float(p[1]-p[2]),
              'outside_length_support':not self.min_length<=features['length']<=self.max_length}
        assert abs(pred['after_correct']-pred['candidate_correct']-pred['continuation_gain'])<1e-12
        return pred
