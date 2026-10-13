"""Optional past/candidate hidden-state observation with a fixed projection.

Activation probing is prior art. This observer is a feature ablation and has
no correctness guarantee. It never changes solver weights or sampling rules.
"""
import time
import numpy as np
from reason_transition.core import Engine, stable_seed


class ProbeEngine(Engine):
    def __init__(self,model_path,projection_dim=64,**kwargs):
        super().__init__(model_path,**kwargs)
        self.observe_candidates=True
        self.capture_hidden=False
        self.last_projection=None
        self.observation_ms=0.
        size=self.model.config.hidden_size
        rng=np.random.default_rng(stable_seed('fixed-observer',size,projection_dim))
        matrix=(rng.normal(size=(size,projection_dim))/np.sqrt(projection_dim)).astype(np.float32)
        self.projection=self.torch.tensor(matrix,device=self.device)
        self.projection_dim=projection_dim

    def forward(self,ids,cache=None):
        if not self.capture_hidden:
            return super().forward(ids,cache)
        torch=self.torch
        x=torch.tensor([ids],device=self.device,dtype=torch.long)
        torch.cuda.synchronize();start=time.perf_counter()
        with torch.inference_mode():
            result=self.model(input_ids=x,past_key_values=cache,use_cache=True,logits_to_keep=1,
                              output_hidden_states=True,return_dict=True)
        torch.cuda.synchronize();self.model_ms+=1000*(time.perf_counter()-start)
        observation_start=time.perf_counter()
        vector=result.hidden_states[-1][0,-1,:].float()
        normalized=vector/vector.norm().clamp_min(1e-12)
        projected=normalized@self.projection
        self.last_projection=projected.cpu().tolist()
        self.observation_ms+=1000*(time.perf_counter()-observation_start)
        return result.past_key_values,result.logits[0,-1,:]
