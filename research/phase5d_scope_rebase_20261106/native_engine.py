"""Native, single-assistant Qwen3 thinking with observable checkpoints.

One model call stream; exact original IDs, separate per-branch RNG, no Gold.
Cold replay is a reference, not physical migration of suffix hidden states.
"""
import copy
import hashlib
import json
from pathlib import Path
import time


def digest_ids(ids):return hashlib.sha256(json.dumps(ids,separators=(',',':')).encode()).hexdigest()


class NativeEngine:
    def __init__(self,model,tokenizer,device):
        import torch
        from transformers import LogitsProcessorList,TemperatureLogitsWarper,TopKLogitsWarper,TopPLogitsWarper
        self.torch=torch;self.model=model;self.tokenizer=tokenizer;self.device=device;self.ledger=[]
        self.warp=LogitsProcessorList([TemperatureLogitsWarper(.6),TopKLogitsWarper(20),TopPLogitsWarper(.95)])
        eos=model.generation_config.eos_token_id or tokenizer.eos_token_id;self.eos=set(eos if isinstance(eos,(tuple,list)) else [eos])
        self.capacity=int(model.config.max_position_embeddings)
        self.open_ids=tokenizer.encode('<think>',add_special_tokens=False);self.close_ids=tokenizer.encode('</think>',add_special_tokens=False)
        if len(self.open_ids)!=1 or len(self.close_ids)!=1:raise ValueError('Pinned Qwen3 thought tag IDs must be single tokens')
        self.stage='setup'

    def sync(self):
        if self.device.type=='cuda':self.torch.cuda.synchronize(self.device)

    def forward(self,ids,cache=None):
        t=self.torch;start=cache.get_seq_length() if cache is not None else 0
        if start+len(ids)>self.capacity:raise ValueError('Context bound')
        before=time.monotonic()
        output=self.model(input_ids=t.tensor([ids],device=self.device,dtype=t.long),
            attention_mask=t.ones((1,start+len(ids)),device=self.device,dtype=t.long),
            position_ids=t.arange(start,start+len(ids),device=self.device).unsqueeze(0),
            cache_position=t.arange(start,start+len(ids),device=self.device),past_key_values=cache,
            use_cache=True,return_dict=True,logits_to_keep=1)
        self.ledger.append({'stage':self.stage,'input_tokens':len(ids),'past_tokens':int(start),'position_start':int(start)})
        logits=output.logits[0,-1].float()
        if not bool(t.isfinite(logits).all()):raise ValueError('Nonfinite logits')
        return output.past_key_values,logits

    def prefill(self,ids):
        cache=None;logits=None
        for start in range(0,len(ids),256):cache,logits=self.forward(ids[start:start+256],cache)
        return cache,logits

    def rng(self,seed=None,state=None):
        g=self.torch.Generator(device=self.device)
        if state is not None:g.set_state(state)
        else:g.manual_seed(seed)
        return g

    def sample(self,logits,rng):
        scores=self.warp(None,logits.unsqueeze(0))
        return int(self.torch.multinomial(scores.softmax(-1),num_samples=1,generator=rng)[0,0])

    def branch(self,cache,logits,rng_state,n=32):
        rng=self.rng(state=rng_state);tokens=[]
        for k in range(n):
            token=self.sample(logits,rng);tokens.append(token)
            if token in self.eos:break
            if k+1<n:cache,logits=self.forward([token],cache)
        return tokens

    def kv_fingerprints(self,cache):
        rows=[]
        for i,layer in enumerate(cache.layers):
            pair=[]
            for tensor in (layer.keys,layer.values):
                raw=tensor.detach().cpu().contiguous().numpy().tobytes()
                pair.append({'shape':list(tensor.shape),'dtype':str(tensor.dtype),'sha256':hashlib.sha256(raw).hexdigest()})
            rows.append({'layer':i,'kv':pair})
        return rows

    def diagnose(self,prefix,cache,logits,rng_state,output):
        t=self.torch;start=time.monotonic();self.stage='checkpoint_reference'
        before=self.kv_fingerprints(cache)
        original_rng=rng_state.clone();hot_cache=copy.deepcopy(cache)
        horizon=min(32,self.capacity-len(prefix))
        if horizon<1:raise ValueError('No next-token capacity at checkpoint')
        hot=self.branch(hot_cache,logits.clone(),original_rng,horizon);del hot_cache
        cold_cache,cold_logits=self.prefill(prefix)
        maxdiff=float((cold_logits-logits).abs().max())
        lp=logits.double().log_softmax(-1);lq=cold_logits.double().log_softmax(-1)
        kl=float((lp.exp()*(lp-lq)).sum())
        top=logits.topk(2);margin=float(top.values[0]-top.values[1])
        cold=self.branch(cold_cache,cold_logits,original_rng,horizon);del cold_cache
        repeat_cache,repeat_logits=self.prefill(prefix)
        repeatdiff=float((repeat_logits-cold_logits).abs().max());del repeat_cache
        after=self.kv_fingerprints(cache)
        import numpy as np
        np.savez_compressed(output/'checkpoint_logits.npz',hot=logits.detach().cpu().numpy(),cold=cold_logits.detach().cpu().numpy(),repeat=repeat_logits.detach().cpu().numpy())
        return {'prefix_ids':list(prefix),'prefix_sha256':digest_ids(prefix),'cache_length':int(cache.get_seq_length()),
            'RNG_state':original_rng.cpu().tolist(),'hot_next_tokens':hot,'cold_next_tokens':cold,
            'same_sampled_32_tokens':hot==cold,'logit_max_abs':maxdiff,'logit_KL_hot_to_cold':kl,
            'same_top1':int(logits.argmax())==int(cold_logits.argmax()),'hot_top2_margin':margin,
            'repeated_cold_max_abs':repeatdiff,'original_cache_unmodified':before==after,
            'original_KV_fingerprints':before,'checkpoint_is_inside_thinking':True,
            'selection':'firstobservedblankparagraphafter64tokens, beforethinkclose; nofuture/Gold',
            'diagnostic_requested_tokens':32,'diagnostic_horizon_tokens':horizon,'diagnostic_not_quality_cap':True,'seconds':time.monotonic()-start}

    def run(self,question,seed,output,write):
        t=self.torch;began=time.monotonic()
        prompt=self.tokenizer.apply_chat_template([{'role':'user','content':question+'\nPlease reason step by step, and put your final answer within \\boxed{}.'}],
            tokenize=True,add_generation_prompt=True,enable_thinking=True)
        if not isinstance(prompt,list) or any(type(x) is not int for x in prompt):raise ValueError('Native template IDs')
        nonthinking=self.tokenizer.apply_chat_template([{'role':'user','content':question+'\nPlease reason step by step, and put your final answer within \\boxed{}.'}],
            tokenize=True,add_generation_prompt=True,enable_thinking=False)
        if prompt==nonthinking:raise ValueError('Template ignored thinking-mode switch')
        rendered=self.tokenizer.decode(prompt,skip_special_tokens=False)
        assistant=rendered.rsplit('<|im_start|>',1)[-1]
        if not assistant.startswith('assistant\n') or '</think>' in assistant or '<|im_end|>' in assistant:
            raise ValueError('Native assistant prefix already closed or malformed')
        rng=self.rng(seed=seed);self.stage='native_prefill';cache,logits=self.prefill(prompt)
        tokens=[];thinking=False;check=None;stop=None;self.stage='native_decode'
        for token in prompt:
            if token==self.open_ids[0]:thinking=True
            if token==self.close_ids[0]:thinking=False
        while len(prompt)+len(tokens)<self.capacity:
            token=self.sample(logits,rng);tokens.append(token)
            if token==self.open_ids[0]:thinking=True
            if token==self.close_ids[0]:thinking=False
            if token in self.eos:stop='EOS';break
            if len(prompt)+len(tokens)==self.capacity:stop='CONTEXT_CAP';break
            cache,logits=self.forward([token],cache)
            tail=self.tokenizer.decode(tokens[-8:],skip_special_tokens=False)
            if check is None and len(tokens)>=64 and thinking and tail.endswith('\n\n'):
                check=self.diagnose(prompt+tokens,cache,logits,rng.get_state(),output)
                check['generated_checkpoint_tokens']=len(tokens)
                write(output/'checkpoint.json',check);self.stage='native_decode'
            if len(tokens)%64==0:
                write(output/'progress.json',{'status':'GENERATING','new_tokens':len(tokens),'capacity':self.capacity,'thinking_active':thinking,
                    'elapsed_seconds':time.monotonic()-began,'token_ids':tokens,'checkpoint_observed':check is not None})
        self.sync()
        if stop is None:stop='CONTEXT_CAP'
        if check is not None:
            k=check['generated_checkpoint_tokens'];hot=check['hot_next_tokens'];observed=tokens[k:k+len(hot)]
            check['hot_branch_matches_actual_unintervened_future']=observed==hot
            check['observed_future_ids']=observed;write(output/'checkpoint.json',check)
        text=self.tokenizer.decode(tokens,skip_special_tokens=False)
        end_positions=[i for i,v in enumerate(tokens) if v==self.close_ids[0]]
        final_ids=tokens[end_positions[-1]+1:] if end_positions else []
        final_text=self.tokenizer.decode(final_ids,skip_special_tokens=True)
        numeric_pass=bool(check is not None and check['original_cache_unmodified'] and check.get('hot_branch_matches_actual_unintervened_future')
                and check['logit_max_abs']<=.05 and check['logit_KL_hot_to_cold']<=1e-4 and check['repeated_cold_max_abs']<=1e-5)
        result={'status':'COMPLETE','seed':seed,'prompt_ids':prompt,'prompt_sha256':digest_ids(prompt),'generated_ids':tokens,
            'generated_sha256':digest_ids(tokens),'text':text,'final_response':final_text,'think_closed':bool(end_positions),
            'stop_reason':stop,'EOS':stop=='EOS','hit_context_cap':stop=='CONTEXT_CAP','new_tokens':len(tokens),
            'context_capacity':self.capacity,'elapsed_seconds':time.monotonic()-began,'checkpoint_observed':check is not None,
            'checkpoint_structure_numeric_pass':numeric_pass,
            'checkpoint_criteria_pass':bool(numeric_pass and check['same_top1'] and check['same_sampled_32_tokens']),
            'ledger':self.ledger,'sampling':{'temperature':.6,'top_p':.95,'top_k':20,'min_p':0,'batch':1},
            'scope':'Nativeunmodified baseline and checkpointreference diagnostics only; no repair/bridgeG/Gold or algorithmgain.'}
        write(output/'result.json',result);return result
