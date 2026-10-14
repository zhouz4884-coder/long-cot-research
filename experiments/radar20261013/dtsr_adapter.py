"""Token-level DTSR-inspired controlled adaptation, not author reproduction.

Paper: ACL2026 2026.acl-long.1080, algorithm1 and sections3.1/appendixA-B.
Preserves the paper's default threshold100 and interval64, with a paraphrased
third-person rating prompt, common bounded solver/boxed reader, and serial HF
execution. Ratings use only the question and already generated thought.
"""
import math
import re
import time
from reason_transition.core import public,digest_ids,stable_seed
from reason_transition.text_decoder import RollingTextDecoder

REFLECTION_MARKERS=('Wait','Alternative','Alternatively','But wait','But let me',"But let's")
MARKER=re.compile(r"(?<![A-Za-z])(?:But wait|But let me|But let's|Alternatively|Alternative|Wait)(?![A-Za-z])",re.I)


def parse_rating(text):
    match=re.fullmatch(r'\s*(?:Confidence\s*:\s*)?([+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*',text,re.I)
    if not match:return None
    value=float(match.group(1))
    return value if math.isfinite(value) and 0<=value<=100 else None


def rating_prompt(question,thought):
    # This is deliberately a declared paraphrase, not the original figure8 text.
    return ('Judge whether the reasoning below already supports a final solution to the question. '
            'Rate completeness from 0 to 100; 100 requires no further reasoning. '
            'Return only Confidence: number.\n\nQuestion:\n'+question+
            '\n\nReasoning so far:\n'+thought)


def evaluate_sufficiency(e,question,thought,seed,max_tokens=64):
    assert max_tokens>0
    prompt=e.tok.apply_chat_template([{'role':'user','content':rating_prompt(question,thought)}],
            tokenize=True,add_generation_prompt=True,enable_thinking=False)
    e.torch.cuda.synchronize();started=time.perf_counter()
    response=e.decode(prompt,max_tokens,seed,phase='rating',until='eos',capture=False)
    e.torch.cuda.synchronize()
    text=e.tok.decode(response['ids'],skip_special_tokens=True,clean_up_tokenization_spaces=False)
    result={**public(response),'rating_text':text,'rating':parse_rating(text),
            'input_tokens':len(prompt),'input_sha256':digest_ids(prompt),
            'auxiliary_wall_ms':1000*(time.perf_counter()-started),
            'gold_available_to_rating':False,'prompt_variant':'controlled_paraphrase_non_thinking',
            'rating_seed':seed}
    del response
    return result


def decode_dtsr(e,question,prefix,max_think_tokens,seed,threshold=100.,minimum_interval=64,rating_max_tokens=64):
    assert max_think_tokens>0 and 0<=threshold<=100 and minimum_interval>0
    e.torch.cuda.synchronize();started=time.perf_counter();model_before=e.model_ms
    cache,logits=e.forward(prefix);prefill_ms=e.model_ms-model_before
    ids=[];decoder=RollingTextDecoder(e.tok);text='';decisions=[];last_checked_offset=0;last_marker_end=0
    reason='limit';rating_tokens=rating_inputs=0;rating_ms=0.
    for i in range(max_think_tokens):
        token,_=e.sample(logits,seed,'think',i,stats=False)
        ids.append(token);text=decoder.append(token);cache,logits=e.forward([token],cache)
        if token in e.eos:reason='eos';break
        if token==e.endthink:reason='natural_end';break
        matches=[m for m in MARKER.finditer(text) if m.end()>last_marker_end]
        if not matches:continue
        latest=matches[-1];last_marker_end=latest.end()
        offset=i+1
        if offset-last_checked_offset<minimum_interval:continue
        parent_length=cache.get_seq_length()
        rating=evaluate_sufficiency(e,question,text,stable_seed(seed,'dtsr-rating',offset),rating_max_tokens)
        assert cache.get_seq_length()==parent_length,'Rating modified solver cache'
        last_checked_offset=offset
        rating_tokens+=rating['tokens'];rating_inputs+=rating['input_tokens'];rating_ms+=rating['auxiliary_wall_ms']
        commit=rating['rating'] is not None and rating['rating']>=threshold
        decisions.append({'offset':offset,'observed_marker':latest.group(),'prefix_sha256':digest_ids(prefix+ids),
                          'action':'STOP' if commit else 'CONTINUE','rating_response':rating})
        if commit:reason='policy_stop';break
    e.torch.cuda.synchronize()
    return {'ids':ids,'text':text,'tokens':len(ids),'stop_reason':reason,'length_censored':reason=='limit',
            'ms':1000*(time.perf_counter()-started),'model_ms':e.model_ms-model_before,
            'prefill_model_ms':prefill_ms,'decisions':decisions,'rating_generated_tokens':rating_tokens,
            'rating_input_tokens':rating_inputs,'rating_wall_ms':rating_ms,
            'cache':cache,'logits':logits,'quality_labels_available_during_decisions':False,
            'scope':'Controlled token-triggered adaptation; serial auxiliary rating costs are included, not author vLLM performance.'}
