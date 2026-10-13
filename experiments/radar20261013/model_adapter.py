"""Explicit multi-token thinking terminators for cross-family math protocols."""
from collections import deque
import time

from reason_transition.core import Engine, boundary, cheap_features, digest_ids, REFLECTION
from radar_engine import candidate


class MathModelAdapter(Engine):
    def __init__(self,model_path,**kwargs):
        super().__init__(model_path,**kwargs)
        self.closer_ids=self.tok.encode('</think>',add_special_tokens=False)
        self.is_single_token_closer=len(self.closer_ids)==1 and self.closer_ids[0]==self.endthink

    def prompt(self,question):
        ids=super().prompt(question)
        # Distilled Llama templates may not add the explicit reasoning opener.
        if not self.tok.decode(ids,skip_special_tokens=False).rstrip().endswith('<think>'):
            ids+=self.tok.encode('<think>\n',add_special_tokens=False)
        return ids

    def answer(self,prefix,seed,natural_closed=False,initial=None):
        if self.is_single_token_closer:
            return super().answer(prefix,seed,natural_closed=natural_closed,initial=initial)
        if initial is None:
            initial=self.forward(prefix)
        return candidate(self,prefix,initial[0],initial[1],seed,natural_closed=natural_closed)

    def decode(self,prefix,max_tokens,seed,phase='think',offset=0,until='think',
               checkpoint_hook=None,capture=False,initial=None):
        if self.is_single_token_closer:
            return super().decode(prefix,max_tokens,seed,phase,offset,until,checkpoint_hook,capture,initial)
        assert until in ['think','step','eos'],'Cross-family arbitrary decoder mode must be implemented explicitly'
        self.torch.cuda.synchronize();start=time.perf_counter()
        model_before=self.model_ms;feature_before=self.feature_gpu_ms
        cache,logits=self.forward(prefix) if initial is None else initial
        prefill_ms=self.model_ms-model_before
        ids=[];text='';points=[];history=deque(maxlen=10);last_checkpoint=-128;reason='limit'
        paused_ms=paused_model_ms=paused_feature_ms=0.
        for i in range(max_tokens):
            token,stats=self.sample(logits,seed,phase,offset+i,stats=capture)
            ids.append(token);text+=self.tok.decode([token],skip_special_tokens=False)
            if stats is not None:history.append(stats)
            cache,logits=self.forward([token],cache)
            if token in self.eos:reason='eos';break
            if until in ['think','step'] and ids[-len(self.closer_ids):]==self.closer_ids:
                reason='natural_end';break
            natural=boundary(text)
            if (capture or checkpoint_hook is not None) and natural and i+1>=128 and i+1-last_checkpoint>=128:
                paragraph=text.split('\n\n')[-2]
                kind='reflective' if REFLECTION.search(paragraph) else 'natural'
                features,feature_ms=cheap_features(ids,text,history,kind) if capture else ({'length':len(ids)},0.)
                point={'offset':i+1,'kind':kind,'features':features,'feature_ms':feature_ms,
                       'prefix_hash':digest_ids(prefix+ids),'elapsed_ms':1000*(time.perf_counter()-start)-paused_ms,
                       'model_ms_sofar':self.model_ms-model_before-paused_model_ms}
                points.append(point);last_checkpoint=i+1
                if checkpoint_hook is not None:
                    pause_start=time.perf_counter();m=self.model_ms;f=self.feature_gpu_ms
                    outcome=checkpoint_hook(point,prefix+ids,cache,logits)
                    if isinstance(outcome,dict) and outcome.get('offline_branching'):
                        paused_ms+=1000*(time.perf_counter()-pause_start)
                        paused_model_ms+=self.model_ms-m;paused_feature_ms+=self.feature_gpu_ms-f;outcome=False
                    elif isinstance(outcome,dict):
                        if outcome.get('disable_capture'):capture=False
                        outcome=outcome.get('stop',False)
                    if outcome:reason='policy_stop';break
            if until=='step' and natural and i+1>=16:reason='step_end';break
        self.torch.cuda.synchronize()
        return {'ids':ids,'text':text,'tokens':len(ids),'ms':1000*(time.perf_counter()-start)-paused_ms,
                'offline_branching_ms':paused_ms,'model_ms':self.model_ms-model_before-paused_model_ms,
                'prefill_model_ms':prefill_ms,'feature_gpu_ms':self.feature_gpu_ms-feature_before-paused_feature_ms,
                'stop_reason':reason,'length_censored':reason=='limit','checkpoints':points,'cache':cache,'logits':logits}
