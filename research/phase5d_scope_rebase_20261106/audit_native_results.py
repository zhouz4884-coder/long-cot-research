"""Read-only post-retrieval D1 audit; no model, remote, Gold grading or repair.

Template may exist while GPU work runs. main refuses until launcher FINISHED.
Only then does it write audit artifacts. Source datasets are hashed as bytes;
their JSON decoder retains question/ID fields only and discards answer fields.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent
PROJECT=ROOT.parents[1]


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def digest_ids(ids):return hashlib.sha256(json.dumps(ids,separators=(',',':')).encode()).hexdigest()
def load(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def questions_only(raw):
    return json.loads(raw,object_pairs_hook=lambda pairs:{k:v for k,v in pairs if k in ('question','problem_id')})


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,default=ROOT)
    ap.add_argument('--tokenizer',type=Path);args=ap.parse_args();root=args.root.resolve()
    launcher=load(root/'native_launcher.json')
    if launcher['status']!='FINISHED':raise RuntimeError('D1 generation not finished; no audit result written')
    if set(launcher['workers'])!={'0','1'}:raise ValueError('Unexpected worker set')
    import numpy as np
    checks=[];observations=[];cases_out=[]
    def check(name,condition,detail=None):
        if not bool(condition):raise AssertionError(name+': '+str(detail))
        checks.append(name)
    def approximately(a,b,tol):return math.isfinite(a) and math.isfinite(b) and abs(a-b)<=tol
    # These immutable execution files are not this audit's outputs.
    retrieval=load(root/'D1_RETRIEVAL_MANIFEST.json')
    for row in retrieval['files']:
        path=root/row['path']
        # Offline scoring/evaluation is deliberately not part of this audit.
        if 'eval_only' in path.name or 'scoring' in path.parts:continue
        check('retrieved_'+row['path'],sha(path)==row['sha256'] and path.stat().st_size==row['bytes'])
    for row in load(root/'native_prelaunch_freeze.json')['files']:
        path=root/row['path']
        if row['path']=='p0_base_frozen.py':path=PROJECT/'research/direction_selection_20261105/real_model_p0.py'
        check('frozen_'+row['path'],sha(path)==row['sha256'] and path.stat().st_size==row['bytes'])
    protocol=load(root/'D1_PROTOCOL.json');data=load(root/'D1_DATA_MANIFEST.json')
    visible=[json.loads(v) for v in (root/'native_visible.jsonl').read_text(encoding='utf-8').splitlines() if v.strip()]
    rendered=load(root/'native_rendered_prelaunch.json');by_render={r['case_id']:r for r in rendered}
    check('eight_unique_visible_and_rendered',len(visible)==len(rendered)==len(by_render)==8 and len({c['case_id'] for c in visible})==8)
    check('visible_hash_matches_bank',sha(root/'native_visible.jsonl')==data['visible_sha256'])
    check('protocol_engine_current',sha(root/'native_engine.py')==protocol['source_engine_sha256'])
    check('protocol_worker_current',sha(root/'native_worker.py')==protocol['source_worker_sha256'])
    source=root/'gsm8k_source_test.jsonl';check('official_source_bytes',sha(source)==data['source_sha256'])
    qs=[questions_only(line)['question'] for line in source.read_bytes().splitlines() if line.strip()]
    check('official_source_row_count',len(qs)==data['source_rows']==1319)
    old=[questions_only(line)['question'] for line in (PROJECT/'data/test.jsonl').read_bytes().splitlines() if line.strip()]
    check('old_question_reference_count',len(old)==300)
    oldhash={hashlib.sha256(q.strip().encode()).hexdigest() for q in old}
    ranked=[]
    for i,q in enumerate(qs,1):
        if hashlib.sha256(q.strip().encode()).hexdigest() in oldhash:continue
        key=hashlib.sha256((data['salt']+'\0'+str(i)+'\0'+q).encode()).hexdigest();ranked.append((key,i,q))
    selected=sorted(ranked)[:8]
    for index,((key,line,q),entry,v) in enumerate(zip(selected,data['cases'],visible)):
        check('question_selection_'+str(index),entry['rank']==index+1 and entry['selection_hash']==key and entry['source_line']==line
              and entry['question_sha256']==hashlib.sha256(q.encode()).hexdigest() and v['question']==q and entry['case_id']==v['case_id'])
        check('new_question_not_old300_'+str(index),hashlib.sha256(q.strip().encode()).hexdigest() not in oldhash)
    check('eight_distinct_question_hashes',len({hashlib.sha256(c['question'].encode()).hexdigest() for c in visible})==8)
    # Optional exact tokenizer decoding uses only frozen tokenizer assets, no model.
    decoder=None;tokenizer_info=None
    tp=args.tokenizer or root/'observed_tokenizer'
    if tp.exists() and (tp/'tokenizer.json').exists():
        runtime=PROJECT/'research/p05_design_review_20261105/runtime4552';sys.path.insert(0,str(runtime));os.environ['CUDA_VISIBLE_DEVICES']=''
        from transformers import AutoTokenizer
        decoder=AutoTokenizer.from_pretrained(tp,local_files_only=True,trust_remote_code=False)
        tokenizer_info={'directory':str(tp),'class':type(decoder).__name__,'tokenizer_json_sha256':sha(tp/'tokenizer.json')}
    else:observations.append('Frozen tokenizer assets not available locally: lexical checkpoint predicate not independently decoded; token prefix/NPZ/ledger still audited.')
    all_assets=[];case_ids=[];total_inputs=0;total_calls=0;diagnostic_inputs=0
    for worker in (0,1):
        directory=root/f'native_results/worker_{worker}';manifest=load(directory/'manifest.json');worker_summary=load(directory/'summary.json')
        check('worker_exit_'+str(worker),launcher['workers'][str(worker)].get('exit_code')==0)
        check('worker_finished_'+str(worker),worker_summary['status']=='COMPLETE' and worker_summary['completed_cases']==4)
        check('worker_source_'+str(worker),manifest['source_sha256']==sha(root/'native_worker.py') and manifest['engine_sha256']==sha(root/'native_engine.py'))
        check('worker_runtime_'+str(worker),manifest['torch']=='2.8.0+cu128' and manifest['transformers']=='4.55.2' and manifest['dtype']=='FP16' and manifest['backend']=='sdpa' and manifest['batch']==1)
        check('native_no_tight_budget_'+str(worker),manifest['thinking_template'] and manifest['scientific_new_token_cap'] is None)
        assets=manifest['model_files'];aggregate=hashlib.sha256(json.dumps(assets['files'],sort_keys=True).encode()).hexdigest()
        check('model_manifest_'+str(worker),aggregate==assets['manifest_sha256']==protocol['model_manifest'])
        all_assets.append(assets['files'])
        if decoder is not None:
            assets_by={r['name']:r for r in assets['files']}
            for f in tp.iterdir():
                if f.is_file() and f.name in assets_by:check('tokenizer_asset_'+str(worker)+'_'+f.name,sha(f)==assets_by[f.name]['sha256'])
        config=manifest['model_config'];generation=manifest['generation_config'];eos=generation['eos_token_id'];eos=set(eos if isinstance(eos,list) else [eos])
        capacity=int(config['max_position_embeddings']);check('actual_context_capacity_'+str(worker),capacity==manifest['technical_context_capacity'])
        for index,v in enumerate(visible):
            if index%2!=worker:continue
            cid=v['case_id'];case_ids.append(cid);folder=directory/cid;result=load(folder/'result.json');r=by_render[cid]
            prompt=result['prompt_ids'];tokens=result['generated_ids'];cp_path=folder/'checkpoint.json'
            check('prompt_ids_'+cid,prompt==r['prompt_ids'] and result['prompt_sha256']==digest_ids(prompt))
            check('output_ids_'+cid,len(tokens)==result['new_tokens'] and result['generated_sha256']==digest_ids(tokens) and result['case_id']==cid)
            check('seed_'+cid,result['seed']==20261106+index)
            check('vocabulary_'+cid,all(type(t) is int and 0<=t<config['vocab_size'] for t in prompt+tokens))
            check('context_total_'+cid,len(prompt)+len(tokens)<=capacity==result['context_capacity'])
            check('stop_'+cid,(result['stop_reason']=='EOS' and result['EOS'] and not result['hit_context_cap'] and tokens[-1] in eos)
                  or (result['stop_reason']=='CONTEXT_CAP' and result['hit_context_cap'] and not result['EOS'] and len(prompt)+len(tokens)==capacity))
            check('EOS_only_at_end_'+cid,all(t not in eos for t in tokens[:-1]))
            check('sampling_'+cid,result['sampling']=={'temperature':.6,'top_p':.95,'top_k':20,'min_p':0,'batch':1})
            if decoder is not None:
                true=decoder.apply_chat_template([{'role':'user','content':v['question']+'\nPlease reason step by step, and put your final answer within \\boxed{}.'}],tokenize=True,add_generation_prompt=True,enable_thinking=True)
                false=decoder.apply_chat_template([{'role':'user','content':v['question']+'\nPlease reason step by step, and put your final answer within \\boxed{}.'}],tokenize=True,add_generation_prompt=True,enable_thinking=False)
                check('native_template_'+cid,true==prompt and true!=false)
                open_ids=decoder.encode('<think>',add_special_tokens=False);close_ids=decoder.encode('</think>',add_special_tokens=False)
                check('single_think_tags_'+cid,len(open_ids)==len(close_ids)==1)
                op,cl=open_ids[0],close_ids[0]
                text=decoder.decode(tokens,skip_special_tokens=False);check('decoded_text_'+cid,text==result['text'])
            else:op,cl=151667,151668
            closes=[i for i,t in enumerate(tokens) if t==cl];check('thinkclose_flag_'+cid,bool(closes)==result['think_closed'])
            if decoder is not None:
                final=decoder.decode(tokens[closes[-1]+1:] if closes else [],skip_special_tokens=True)
                check('final_response_only_after_close_'+cid,final==result['final_response'])
            thinking=False
            for t in prompt:
                if t==op:thinking=True
                elif t==cl:thinking=False
            first=None
            for n,t in enumerate(tokens,1):
                if t==op:thinking=True
                elif t==cl:thinking=False
                if t in eos or len(prompt)+n==capacity:break
                if decoder is not None and n>=64 and thinking and decoder.decode(tokens[max(0,n-8):n],skip_special_tokens=False).endswith('\n\n'):
                    first=n;break
            cp=load(cp_path) if cp_path.exists() else None
            check('checkpoint_presence_'+cid,(cp is not None)==result['checkpoint_observed'])
            item={'case_id':cid,'new_tokens':len(tokens),'EOS':result['EOS'],'context_cap':result['hit_context_cap'],'checkpoint':cp is not None}
            if cp is None:
                if decoder is not None:check('no_eligible_checkpoint_'+cid,first is None)
                observations.append(cid+': no eligible checkpoint; not counted as hot/cold replay evidence')
                item.update(numeric_pass=False,strict_pass=False)
            else:
                k=cp['generated_checkpoint_tokens'];prefix=prompt+tokens[:k];horizon=min(32,capacity-len(prefix))
                check('checkpoint_exact_prefix_'+cid,k>=64 and cp['prefix_ids']==prefix and cp['prefix_sha256']==digest_ids(prefix) and cp['cache_length']==len(prefix))
                if decoder is not None:check('first_online_checkpoint_'+cid,k==first)
                state=False
                for t in prefix:
                    if t==op:state=True
                    elif t==cl:state=False
                check('checkpoint_inside_observed_think_'+cid,state and cp['checkpoint_is_inside_thinking'])
                check('diagnostic_not_quality_cap_'+cid,cp['diagnostic_requested_tokens']==32 and cp['diagnostic_horizon_tokens']==horizon and cp['diagnostic_not_quality_cap'])
                check('RNG_state_bytes_'+cid,isinstance(cp['RNG_state'],list) and len(cp['RNG_state'])>0 and all(type(v) is int and 0<=v<=255 for v in cp['RNG_state']))
                arrays=np.load(folder/'checkpoint_logits.npz');hot,cold,repeat=(np.asarray(arrays[name],dtype=np.float64) for name in ('hot','cold','repeat'))
                check('logits_finite_'+cid,hot.shape==cold.shape==repeat.shape==(config['vocab_size'],) and np.isfinite(hot).all() and np.isfinite(cold).all() and np.isfinite(repeat).all())
                def lp(x):m=x.max();return x-m-np.log(np.exp(x-m).sum())
                hp,cp_log=lp(hot),lp(cold);maxabs=float(np.max(np.abs(hot-cold)));repeatdiff=float(np.max(np.abs(repeat-cold)))
                kl=float(np.sum(np.exp(hp)*(hp-cp_log)));top=np.sort(hot)[-2:];margin=float(top[-1]-top[-2]);same_top=int(np.argmax(hot))==int(np.argmax(cold))
                check('saved_numeric_recomputed_'+cid,approximately(maxabs,cp['logit_max_abs'],1e-10) and approximately(kl,cp['logit_KL_hot_to_cold'],1e-9)
                      and approximately(repeatdiff,cp['repeated_cold_max_abs'],1e-10) and approximately(margin,cp['hot_top2_margin'],1e-6) and same_top==cp['same_top1'])
                for branch in ('hot_next_tokens','cold_next_tokens'):
                    bs=cp[branch];check(branch+'_horizon_'+cid,1<=len(bs)<=horizon and (len(bs)==horizon or bs[-1] in eos) and all(t not in eos for t in bs[:-1]))
                hot_tokens=cp['hot_next_tokens'];same_tokens=hot_tokens==cp['cold_next_tokens'];actual=tokens[k:k+len(hot_tokens)]
                check('saved_replay_flags_'+cid,same_tokens==cp['same_sampled_32_tokens'] and cp['observed_future_ids']==actual and cp['hot_branch_matches_actual_unintervened_future']==(hot_tokens==actual))
                fp=cp['original_KV_fingerprints'];check('recorded_original_KV_shape_'+cid,len(fp)==config['num_hidden_layers'] and all(len(row['kv'])==2 and all(t['shape'][0]==1 and t['shape'][-2]==len(prefix) and len(t['sha256'])==64 for t in row['kv']) for row in fp))
                numeric=bool(cp['original_cache_unmodified'] and hot_tokens==actual and maxabs<=.05 and kl<=1e-4 and repeatdiff<=1e-5)
                strict=bool(numeric and same_top and same_tokens)
                check('gate_recomputed_'+cid,numeric==result['checkpoint_structure_numeric_pass'] and strict==result['checkpoint_criteria_pass'])
                item.update(checkpoint_generated_tokens=k,diagnostic_horizon=horizon,logit_max_abs=maxabs,KL=kl,repeated_cold_max_abs=repeatdiff,
                            top2_margin=margin,same_top1=same_top,same_sampled_tokens=same_tokens,original_cache_unmodified_recorded=cp['original_cache_unmodified'],
                            hot_matches_actual=hot_tokens==actual,numeric_pass=numeric,strict_pass=strict)
                reasons=[]
                if not cp['original_cache_unmodified']:reasons.append('recorded original cache changed')
                if hot_tokens!=actual:reasons.append('hot branch differs from actual unintervened future')
                if maxabs>.05:reasons.append('maxabs>'+str(.05))
                if kl>1e-4:reasons.append('KL>'+str(1e-4))
                if repeatdiff>1e-5:reasons.append('repeatcoldmax>'+str(1e-5))
                if not same_top:reasons.append('next argmax differs')
                if not same_tokens:reasons.append('sampled diagnostic tokens differ')
                item['joint_gate_failure_reasons']=reasons
                if not strict:observations.append(cid+': joint criteria not passed: '+', '.join(reasons)+'; seed/thresholds unchanged')
            # Independent expected ledger includes every diagnostic model call.
            expected=[]
            def prefill_rows(length,stage):
                for start in range(0,length,256):expected.append({'stage':stage,'input_tokens':min(256,length-start),'past_tokens':start,'position_start':start})
            prefill_rows(len(prompt),'native_prefill')
            for n in range(1,len(tokens)):
                past=len(prompt)+n-1;expected.append({'stage':'native_decode','input_tokens':1,'past_tokens':past,'position_start':past})
                if cp is not None and n==cp['generated_checkpoint_tokens']:
                    length=len(cp['prefix_ids'])
                    for j in range(len(cp['hot_next_tokens'])-1):expected.append({'stage':'checkpoint_reference','input_tokens':1,'past_tokens':length+j,'position_start':length+j})
                    prefill_rows(length,'checkpoint_reference')
                    for j in range(len(cp['cold_next_tokens'])-1):expected.append({'stage':'checkpoint_reference','input_tokens':1,'past_tokens':length+j,'position_start':length+j})
                    prefill_rows(length,'checkpoint_reference')
            check('complete_forward_ledger_'+cid,result['ledger']==expected)
            total_inputs+=sum(r['input_tokens'] for r in expected);total_calls+=len(expected)
            diagnostic_inputs+=sum(r['input_tokens'] for r in expected if r['stage']=='checkpoint_reference')
            item['forward_calls']=len(expected);item['forward_input_tokens']=sum(r['input_tokens'] for r in expected);cases_out.append(item)
    check('same_assets_both_workers',all_assets[0]==all_assets[1])
    check('eight_distinct_authoritative_outputs',len(case_ids)==len(set(case_ids))==8 and set(case_ids)=={c['case_id'] for c in visible})
    # Recheck raw bytes after this read-only analysis.
    for row in retrieval['files']:
        path=root/row['path']
        if 'eval_only' in path.name or 'scoring' in path.parts:continue
        check('unchanged_'+row['path'],sha(path)==row['sha256'])
    ncp=sum(c['checkpoint'] for c in cases_out);numeric=sum(c['numeric_pass'] for c in cases_out);strict=sum(c['strict_pass'] for c in cases_out)
    summary={'status':'PASS','meaning':'Artifact/source/numeric/ledger integrity audit; strict replay is a separate result below.',
        'checks_passed':len(checks),'planned_questions':8,'actual_questions':8,'checkpoints_observed':ncp,'numeric_pass_count':numeric,'strict_replay_pass_count':strict,
        'next_argmax_identical_count':sum(c.get('same_top1',False) for c in cases_out),
        'sampled_diagnostic_tokens_identical_count':sum(c.get('same_sampled_tokens',False) for c in cases_out),
        'hot_matches_actual_future_count':sum(c.get('hot_matches_actual',False) for c in cases_out),
        'native_interface_result':'PASS' if ncp==numeric==strict==8 and decoder is not None else 'NOT_FULL_STRICT_COVERAGE',
        'EOS_count':sum(c['EOS'] for c in cases_out),'context_cap_count':sum(c['context_cap'] for c in cases_out),
        'native_generated_tokens':sum(c['new_tokens'] for c in cases_out),'forward_calls_including_diagnostics':total_calls,
        'forward_input_tokens_including_diagnostics':total_inputs,'diagnostic_forward_input_tokens':diagnostic_inputs,
        'conservative_GPU_seconds':launcher['conservative_GPU_seconds'],'conservative_GPU_minutes':launcher['conservative_GPU_minutes'],
        'tokenizer':tokenizer_info,'source_engine_sha256':sha(root/'native_engine.py'),'audit_source_sha256':sha(__file__),
        'cases':sorted(cases_out,key=lambda v:v['case_id']),'observations':observations,'checks':checks,
        'limits':['No mathematical correctness or Gold evaluated. Eight questions, not8plusbranches independent tasks.',
                  'Saved NPZ/logit metrics independently recomputed. Cache before fingerprints and recorded unchanged flag checked; after-cache tensors/fingerprints were not retained for independent bitwise rehash.',
                  'Model manifest aggregates checked from recorded file hashes, not8GB weights independently reread.',
                  'No SCOPE-Rebase/bridge/crop or algorithm-quality comparison was executed in this D1 baseline.']}
    (root/'D1_NATIVE_AUDIT.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    table='\n'.join(f"| {c['case_id']} | {c['new_tokens']} | {'EOS' if c['EOS'] else 'CONTEXT_CAP'} | {c.get('checkpoint_generated_tokens','—')} | {c.get('logit_max_abs','—')} | {c['numeric_pass']} | {c['strict_pass']} |" for c in summary['cases'])
    md=f'''# D1原生8题结果的只读完整性审计

完整性状态PASS，{len(checks)}项通过；原生strict接口结果 **{summary['native_interface_result']}**。本审计没有运行模型/GPU、读取evaluation-only或计算数学正确率。

8题均有独立结果，checkpoint覆盖{ncp}/8，数值判据{numeric}/8，含数值阈值的联合strict gate {strict}/8；**下一token argmax相同{summary['next_argmax_identical_count']}/8、采样诊断token序列相同{summary['sampled_diagnostic_tokens_identical_count']}/8、hot分支与实际无干预未来相同{summary['hot_matches_actual_future_count']}/8**。不能把仅数值阈值未过说成实际token分叉。EOS {summary['EOS_count']}/8，context cap {summary['context_cap_count']}/8。多分支不增加独立题数。

| 题 | 原生生成tokens | 停止 | cp已生成tokens | hot/cold maxabs | numeric | strict |
|---|---:|---|---:|---:|---|---|
{table}

已核对官方GSM8K源哈希/只用question的8题选择、旧300字面排除、预渲染/源冻结、两worker模型资产/runtime、原native前缀IDs、NPZ统计与逐项forward台账。诊断调用全部计入{total_calls}次forward、{total_inputs}输入tokens，其中诊断{diagnostic_inputs}；主原生输出{summary['native_generated_tokens']} tokens。外层{summary['conservative_GPU_minutes']:.5f}单卡分钟，不能与内层时间重复相加。

候选checkpoint只按当时已观察open/未close的首个64token后空段重放；本地tokenizer可用={decoder is not None}。不存在时只保留源码/记录层验证，不能称独立decoder验证。cold/hot采样或top1若失败均保留，没有改seed或阈值。

完整性PASS不等于修复有效。这里没有G、bridge、crop或SCOPE-Rebase；数学评分由主任务另行CPU处理。缓存after张量未保存，所以原cache不变来自绑定源码所执行的指纹比较记录，不伪称重新下载并重算全部KV。模型资产也仅核其记录hash聚合。

观察：{json.dumps(observations,ensure_ascii=False)}

机器证据：[D1_NATIVE_AUDIT.json](D1_NATIVE_AUDIT.json)。审核源SHA `{summary['audit_source_sha256']}`。
'''
    (root/'D1_NATIVE_AUDIT_ZH.md').write_text(md,encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('cases','checks','limits')},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
