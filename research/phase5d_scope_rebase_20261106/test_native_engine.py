"""CPU-only native-engine contracts on random tiny Qwen3 and scripted mocks.

No bank/Gold, remote connection or GPU use. The supplied kit is not modified.
The guarded bridge below is a TEST POLICY WRAPPER, not an integrated repair.
"""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parent
RUNTIME=ROOT.parent/'p05_design_review_20261105/runtime4552'
sys.path.insert(0,str(RUNTIME));os.environ['CUDA_VISIBLE_DEVICES']=''
import torch
import transformers
from transformers import Qwen3Config,Qwen3ForCausalLM
import native_engine


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class FixtureTokenizer:
    """A structural ChatML fixture; explicitly NOT the real Qwen tokenizer."""
    eos_token_id=2;pad_token_id=0
    tags={'<think>':3,'</think>':4,'<|im_start|>':10,'<|im_end|>':11,'<|endoftext|>':2}
    def __init__(self):self.flags=[]
    def encode(self,text,add_special_tokens=False):
        if text in self.tags:return [self.tags[text]]
        out=[];i=0
        while i<len(text):
            tag=next((v for v in self.tags if text.startswith(v,i)),None)
            if tag:out.append(self.tags[tag]);i+=len(tag)
            else:out.append(6 if text[i]=='\n' else 20+(ord(text[i])%60));i+=1
        return out
    def decode(self,tokens,skip_special_tokens=False):
        rev={v:k for k,v in self.tags.items()}
        header=''
        if list(tokens[:3])==[1,8,9]:
            header='' if skip_special_tokens else '<|im_start|>assistant\n';tokens=tokens[3:]
        return header+''.join(('' if skip_special_tokens else rev[v]) if v in rev else ('\n' if v==6 else 'a') for v in tokens)
    def apply_chat_template(self,messages,tokenize=True,add_generation_prompt=True,enable_thinking=True):
        assert tokenize and add_generation_prompt and len(messages)==1 and messages[0]['role']=='user'
        self.flags.append(enable_thinking)
        # True begins at assistant header; the model must actually emit <think>.
        return [1,8,9] if enable_thinking else [1,8,9,3,6,6,4,6,6]


class MockCache:
    def __init__(self):
        self.layers=[SimpleNamespace(keys=torch.empty((1,1,0,1)),values=torch.empty((1,1,0,1)))]
    def get_seq_length(self):return self.layers[0].keys.shape[-2]
    def append(self,ids):
        tensor=torch.tensor(ids,dtype=torch.float32).reshape(1,1,-1,1)
        layer=self.layers[0];layer.keys=torch.cat([layer.keys,tensor],dim=-2);layer.values=torch.cat([layer.values,tensor+1],dim=-2)


class ScriptedModel:
    def __init__(self,sequence,capacity=160):
        self.sequence=list(sequence);self.config=SimpleNamespace(max_position_embeddings=capacity)
        self.generation_config=SimpleNamespace(eos_token_id=2)
    def __call__(self,input_ids,past_key_values=None,**kwargs):
        cache=MockCache() if past_key_values is None else past_key_values
        assert kwargs['cache_position'].tolist()==list(range(cache.get_seq_length(),cache.get_seq_length()+input_ids.shape[1]))
        assert kwargs['attention_mask'].shape[1]==cache.get_seq_length()+input_ids.shape[1]
        cache.append(input_ids[0].tolist());index=max(0,cache.get_seq_length()-3)
        token=self.sequence[min(index,len(self.sequence)-1)]
        scores=torch.full((1,1,96),-1000.0);scores[0,0,token]=0
        return SimpleNamespace(past_key_values=cache,logits=scores)


def safe_bridge_wrapper(tokenizer,prefix,bridge,*,at_complete_step):
    """Structural test wrapper only; does not verify semantic certificates."""
    if not at_complete_step:raise ValueError('No complete step boundary')
    opens=[i for i,v in enumerate(prefix) if v==3];closes=[i for i,v in enumerate(prefix) if v==4]
    if not opens or (closes and max(closes)>max(opens)):raise ValueError('No active thinking block')
    forbidden=tuple(tokenizer.tags)
    if any(tag in bridge for tag in forbidden):raise ValueError('Control tag')
    added=tokenizer.encode(bridge,add_special_tokens=False)
    if set(added)&set(tokenizer.tags.values()):raise ValueError('Control token ID')
    return list(prefix)+added


def main():
    began=time.monotonic();start_sha=sha(ROOT/'native_engine.py');checks=[];details={}
    def check(name,value,detail=None):
        if not bool(value):raise AssertionError(name+': '+str(detail))
        checks.append(name)
        if detail is not None:details[name]=detail
    check('target_transformers_4552',transformers.__version__=='4.55.2',transformers.__version__)
    check('CPU_only',not torch.cuda.is_available() or os.environ['CUDA_VISIBLE_DEVICES']=='')
    torch.set_num_threads(4);torch.manual_seed(20261106)
    tok=FixtureTokenizer();true=tok.apply_chat_template([{'role':'user','content':'generic toy'}],enable_thinking=True)
    false=tok.apply_chat_template([{'role':'user','content':'generic toy'}],enable_thinking=False)
    check('true_false_templates_different',true!=false)
    check('true_does_not_preclose_thinking',4 not in true)
    check('true_may_wait_for_model_to_emit_open',3 not in true)
    check('false_contains_closed_thinking',3 in false and 4 in false and false.index(3)<false.index(4))
    cfg=Qwen3Config(vocab_size=96,hidden_size=32,intermediate_size=64,num_hidden_layers=3,num_attention_heads=4,
        num_key_value_heads=2,head_dim=8,max_position_embeddings=1024,attention_dropout=0.0,
        eos_token_id=2,pad_token_id=0,bos_token_id=1,layer_types=['full_attention']*3)
    cfg._attn_implementation='sdpa';model=Qwen3ForCausalLM(cfg).eval();device=torch.device('cpu')
    check('random_tiny_Qwen3_SDPA',model.config.model_type=='qwen3' and model.config._attn_implementation=='sdpa')
    with torch.inference_mode():
        engine=native_engine.NativeEngine(model,tok,device)
        prefix=true+[3]+[20+(i%60) for i in range(306)]
        whole,whole_logits=engine.forward(prefix)
        stream=None;stream_logits=None
        for token in prefix:stream,stream_logits=engine.forward([token],stream)
        chunk,chunk_logits=engine.prefill(prefix)
        diff=float((whole_logits-stream_logits).abs().max());chunkdiff=float((whole_logits-chunk_logits).abs().max())
        check('stream_full_prefill_logits_within_CPU_tolerance',diff<1e-5,{'max_abs':diff})
        check('chunk256_full_prefill_logits_within_CPU_tolerance',chunkdiff<1e-5,{'max_abs':chunkdiff})
        check('same_next_argmax_three_paths',int(whole_logits.argmax())==int(stream_logits.argmax())==int(chunk_logits.argmax()))
        check('native_token_ids_not_reencoded',whole.get_seq_length()==stream.get_seq_length()==chunk.get_seq_length()==len(prefix))
        original_fp=engine.kv_fingerprints(stream);r=engine.rng(seed=99);rng_state=r.get_state().clone()
        global_state=torch.random.get_rng_state().clone()
        first=engine.branch(copy.deepcopy(stream),stream_logits.clone(),rng_state,12)
        # A different isolated branch must not change this checkpoint's RNG or cache.
        engine.branch(copy.deepcopy(stream),stream_logits.clone(),engine.rng(seed=444).get_state(),7)
        second=engine.branch(copy.deepcopy(stream),stream_logits.clone(),rng_state,12)
        check('restored_local_RNG_replays_same_branch',first==second)
        check('provided_RNG_state_unchanged',torch.equal(rng_state,r.get_state()))
        check('isolated_branch_does_not_change_global_RNG',torch.equal(global_state,torch.random.get_rng_state()))
        check('branched_KV_original_unmodified',engine.kv_fingerprints(stream)==original_fp)
        check('distinct_seed_generators_have_distinct_states',not torch.equal(engine.rng(seed=1).get_state(),engine.rng(seed=2).get_state()))
        # Compare exact HF sampling policy with the engine's separate local RNG.
        small=true+[3,21,22,23];cache,logits=engine.prefill(small)
        manual=engine.branch(copy.deepcopy(cache),logits.clone(),engine.rng(seed=345).get_state(),16)
        saved_global=torch.random.get_rng_state();torch.manual_seed(345)
        hf=model.generate(input_ids=torch.tensor([small]),attention_mask=torch.ones((1,len(small)),dtype=torch.long),
            max_new_tokens=16,do_sample=True,temperature=.6,top_k=20,top_p=.95,min_p=0,
            eos_token_id=2,pad_token_id=0,use_cache=True)[0,len(small):].tolist()
        torch.random.set_rng_state(saved_global)
        check('manual_sampling_matches_HF_same_seed',manual==hf,{'manual':manual,'HF':hf})
        with tempfile.TemporaryDirectory(prefix='p5d_native_cpu_') as temp:
            temp=Path(temp)
            real_output=temp/'real_random_tiny';real_output.mkdir()
            real_check=engine.diagnose(prefix,stream,stream_logits,rng_state,real_output)
            check('real_tiny_diagnose_original_cache_unmodified',real_check['original_cache_unmodified'])
            check('real_tiny_diagnose_hot_cold_sampled_equal',real_check['same_sampled_32_tokens'])
            check('real_tiny_diagnose_numeric_and_repeat',real_check['logit_max_abs']<1e-5 and real_check['repeated_cold_max_abs']==0,
                  {k:real_check[k] for k in ('logit_max_abs','logit_KL_hot_to_cold','same_top1','repeated_cold_max_abs')})
            def run_mock(name,seq,capacity=160,engine_class=None,tokenizer=None):
                output=temp/name;output.mkdir()
                e=(engine_class or native_engine.NativeEngine)(ScriptedModel(seq,capacity),tokenizer or FixtureTokenizer(),device)
                return e,e.run('generic toy, no evaluation',123,output,lambda path,obj:Path(path).write_text(json.dumps(obj),encoding='utf-8'))
            seq=[3]+[7]*61+[6,6]+[7]*7+[4,8,2]
            e,result=run_mock('checkpoint',seq)
            cp=json.loads((temp/'checkpoint/checkpoint.json').read_text())
            check('online_checkpoint_exactly_first_visible_boundary',cp['generated_checkpoint_tokens']==64)
            check('checkpoint_contains_only_observed_prefix',cp['prefix_ids']==true+seq[:64])
            check('checkpoint_open_has_been_observed',3 in seq[:64] and 4 not in seq[:64])
            check('checkpoint_prefix_hash_matches_original_IDs',cp['prefix_sha256']==native_engine.digest_ids(true+seq[:64]))
            check('mock_hot_cold_same_sampled_continuation',cp['same_sampled_32_tokens'])
            check('mock_original_cache_fingerprints_unchanged',cp['original_cache_unmodified'])
            check('mock_hot_branch_matches_actual_unintervened_future',cp['hot_branch_matches_actual_unintervened_future'])
            check('mock_repeated_cold_prefill_exact',cp['repeated_cold_max_abs']==0)
            check('mock_normal_EOS_recorded',result['stop_reason']=='EOS' and result['EOS'] and not result['hit_context_cap'])
            check('diagnostic32_is_not_quality_generation_cap',result['new_tokens']>32 and cp['diagnostic_horizon_tokens']==32 and cp['diagnostic_not_quality_cap'])
            check('mock_final_response_after_closing_think',result['think_closed'] and bool(result['final_response']))
            class IgnoredSwitch(FixtureTokenizer):
                def apply_chat_template(self,*args,**kwargs):return [1,8,9]
            try:run_mock('ignored_switch',seq,tokenizer=IgnoredSwitch())
            except ValueError:check('reject_template_ignoring_thinking_switch',True)
            else:check('reject_template_ignoring_thinking_switch',False)
            class ClosedTemplate(FixtureTokenizer):
                def decode(self,tokens,skip_special_tokens=False):
                    text=super().decode(tokens,skip_special_tokens)
                    return text+'</think>' if list(tokens)==[1,8,9] else text
            try:run_mock('closed_template',seq,tokenizer=ClosedTemplate())
            except ValueError:check('reject_preclosed_assistant_template',True)
            else:check('reject_preclosed_assistant_template',False)
            class MismatchTop1(native_engine.NativeEngine):
                def diagnose(self,*args,**kwargs):
                    value=super().diagnose(*args,**kwargs);value['same_top1']=False;return value
            _,mismatch=run_mock('strict_top1_gate',seq,engine_class=MismatchTop1)
            check('strict_top1_mismatch_not_hidden_by_numeric_tolerance',mismatch['checkpoint_structure_numeric_pass'] and not mismatch['checkpoint_criteria_pass'])
            class MismatchSample(native_engine.NativeEngine):
                def diagnose(self,*args,**kwargs):
                    value=super().diagnose(*args,**kwargs);value['same_sampled_32_tokens']=False;return value
            _,mismatch=run_mock('strict_sample_gate',seq,engine_class=MismatchSample)
            check('strict_sample_mismatch_not_hidden_by_numeric_tolerance',mismatch['checkpoint_structure_numeric_pass'] and not mismatch['checkpoint_criteria_pass'])
            # Alter future while keeping every checkpoint-selection observation fixed.
            seq2=list(seq);seq2[68]=17
            _,result2=run_mock('different_future',seq2)
            cp2=json.loads((temp/'different_future/checkpoint.json').read_text())
            check('future_change_cannot_change_checkpoint_time',cp2['generated_checkpoint_tokens']==cp['generated_checkpoint_tokens'])
            check('future_change_cannot_change_checkpoint_prefix',cp2['prefix_ids']==cp['prefix_ids'])
            check('future_intervention_did_change_only_future_fixture',result2['generated_ids']!=result['generated_ids'])
            _,early=run_mock('early_closed',[3,7,4,8,2])
            check('early_think_close_no_fabricated_checkpoint',not early['checkpoint_observed'] and early['think_closed'] and early['EOS'])
            _,unclosed=run_mock('unclosed_context',[3]+[7]*100,capacity=80)
            check('unclosed_think_hits_context_not_normal_EOS',unclosed['hit_context_cap'] and not unclosed['EOS'] and not unclosed['think_closed'])
            check('unclosed_thinking_not_returned_as_final_answer',unclosed['final_response']=='')
            _,badend=run_mock('EOS_in_thinking',[3,7,2])
            check('EOS_before_thinkclose_is_explicit',badend['EOS'] and not badend['think_closed'] and badend['final_response']=='')
            _,near_end=run_mock('checkpoint_near_context',seq,capacity=69)
            near_cp=json.loads((temp/'checkpoint_near_context/checkpoint.json').read_text())
            check('diagnostic_horizon_clamped_to_remaining_context',near_cp['diagnostic_requested_tokens']==32 and near_cp['diagnostic_horizon_tokens']==2)
            check('near_context_checkpoint_does_not_crash_quality_run',near_end['hit_context_cap'] and not near_end['EOS'])
            check('near_context_hot_branch_matches_observed_prefix',near_cp['hot_branch_matches_actual_unintervened_future'] and len(near_cp['hot_next_tokens'])==2)
        # Kit gaps are demonstrated, never repaired in upstream source.
        kitpath=ROOT/'provided_kit/phase5d_codex_kit/native_prefix_reference.py'
        spec=importlib.util.spec_from_file_location('kit_native_reference_cpu',kitpath);kit=importlib.util.module_from_spec(spec);spec.loader.exec_module(kit)
        active=true+[3,7,6,6];kit_before=sha(kitpath)
        unsafe=kit.append_in_thought_bridge(tok,active,'</think>')
        check('provided_reference_gap_accepts_thinkclose_demonstrated',unsafe[-1]==4)
        for idx,bridge in enumerate(['</think>','<think>','<|im_start|>','<|im_end|>','<|endoftext|>']):
            try:safe_bridge_wrapper(tok,active,bridge,at_complete_step=True)
            except ValueError:check(f'test_wrapper_rejects_control_tag_{idx}',True)
            else:check(f'test_wrapper_rejects_control_tag_{idx}',False)
        class HiddenControl(FixtureTokenizer):
            def encode(self,text,add_special_tokens=False):return [4] if text=='opaque-control' else super().encode(text,add_special_tokens)
        try:safe_bridge_wrapper(HiddenControl(),active,'opaque-control',at_complete_step=True)
        except ValueError:check('test_wrapper_rejects_control_ID_without_literal_tag',True)
        else:check('test_wrapper_rejects_control_ID_without_literal_tag',False)
        safe=safe_bridge_wrapper(tok,active,'\nI will continue from the current evidence.\n',at_complete_step=True)
        check('test_wrapper_keeps_exact_original_ID_prefix',safe[:len(active)]==active and active==true+[3,7,6,6])
        for idx,(p,complete) in enumerate([(active,False),(true+[3,4],True)]):
            try:safe_bridge_wrapper(tok,p,'neutral',at_complete_step=complete)
            except ValueError:check(f'test_wrapper_rejects_bad_boundary_{idx}',True)
            else:check(f'test_wrapper_rejects_bad_boundary_{idx}',False)
        class CaptureModel(torch.nn.Module):
            def __init__(self):super().__init__();self.p=torch.nn.Parameter(torch.zeros(1));self.generation_config=SimpleNamespace(eos_token_id=2)
            def generate(self,input_ids,generation_config,**kwargs):self.seen=generation_config;return torch.cat([input_ids,torch.tensor([[8,2]])],dim=1)
        capture=CaptureModel();global_saved=torch.random.get_rng_state()
        kit.model_continue_reference(capture,tok,active,8,123);torch.random.set_rng_state(global_saved)
        check('provided_reference_pad0_gap_demonstrated',tok.pad_token_id==0 and capture.seen.pad_token_id==2)
        check('provided_reference_source_unmodified',sha(kitpath)==kit_before)
    check('source_hash_stable_during_CPU_test',sha(ROOT/'native_engine.py')==start_sha)
    result={'status':'PASS','passed':len(checks),'checks':checks,'details':details,'seconds':time.monotonic()-began,
        'source_sha256':start_sha,'test_sha256':sha(__file__),'versions':{'torch':torch.__version__,'transformers':transformers.__version__},
        'scope':'CPU random tinyFP32 Qwen3SDPA plus scripted structure/RNG/EOS mocks; no real tokenizer/4B/FP16/CUDA or task quality validation.',
        'reading_or_online_data_used':False,'bridge_wrapper_scope':'Local test policy only, not production neutral/certified repair bridge.',
        'provided_reference_gaps':['append permits closing thinking tag','pad ID0 replaced byEOS via or'],
        'no_generator_Gold_or_sample_bank_read':True}
    (ROOT/'D1_CPU_INTERFACE.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('checks','details')},indent=2))


if __name__=='__main__':main()
