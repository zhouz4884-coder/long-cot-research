"""Read-only same-prefix schedule-control audit, no model or Gold grading."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent


def load(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def digest_ids(ids):return hashlib.sha256(json.dumps(ids,separators=(',',':')).encode()).hexdigest()


def main():
    root=ROOT;launcher=load(root/'schedule_launcher.json')
    if launcher['status']!='FINISHED':raise RuntimeError('Schedule study still running')
    original=load(root/'D1_NATIVE_AUDIT.json')
    original_report_sha={n:sha(root/n) for n in ('D1_NATIVE_AUDIT.json','D1_NATIVE_AUDIT_ZH.md')}
    checks=[];records=[]
    def check(name,condition):
        if not bool(condition):raise AssertionError(name)
        checks.append(name)
    retrieval=load(root/'SCHEDULE_RETRIEVAL_MANIFEST.json')
    for row in retrieval['files']:
        p=root/row['path'];check('retrieved_'+row['path'],sha(p)==row['sha256'] and p.stat().st_size==row['bytes'])
    # Original native outputs must still be their independently retrieved bytes.
    for row in load(root/'D1_RETRIEVAL_MANIFEST.json')['files']:
        p=root/row['path'];check('original_unchanged_'+row['path'],sha(p)==row['sha256'] and p.stat().st_size==row['bytes'])
    for row in load(root/'schedule_control_freeze.json')['files']:
        check('frozen_'+row['path'],sha(root/row['path'])==row['sha256'])
    check('same_original_engine_source',sha(root/'native_engine.py')==original['source_engine_sha256'])
    protocol=load(root/'SCHEDULE_CONTROL_PROTOCOL.json')
    check('protocol_diagnostic_only',protocol['same_sampler_source'] and protocol['zero_error_and_KV_fingerprints_for_strictpass'] and protocol['only_diagnostic_tokens']==32)
    rendered=load(root/'native_rendered_prelaunch.json');expected_ids={r['case_id'] for r in rendered};render_map={r['case_id']:r for r in rendered}
    check('eight_original_case_ids',len(expected_ids)==8)
    total_calls=0;total_inputs=0;new_diagnostic_tokens=0
    for worker in (0,1):
        check('worker_exit_'+str(worker),launcher['workers'][str(worker)]['status']=='FINISHED' and launcher['workers'][str(worker)]['exit_code']==0)
        d=root/f'schedule_control/worker_{worker}';summary=load(d/'summary.json')
        check('worker_complete_'+str(worker),summary['status']=='COMPLETE' and summary['cases']==4 and summary['algorithm_inputs_or_sampling_changed'] is False)
        check('control_source_'+str(worker),summary['source_sha256']==sha(root/'replay_schedule_control.py'))
        rows=[]
        for folder in sorted((root/f'native_results/worker_{worker}').glob('D1_*')):
            cid=folder.name;row=load(d/(cid+'.json'));rows.append(row)
            result=load(folder/'result.json');cp=load(folder/'checkpoint.json');k=cp['generated_checkpoint_tokens'];prefix=result['prompt_ids']+result['generated_ids'][:k]
            check('same_exact_prefix_'+cid,row['case_id']==cid and row['prefix_sha256']==cp['prefix_sha256']==digest_ids(prefix)
                  and prefix==cp['prefix_ids'] and result['prompt_ids']==render_map[cid]['prompt_ids'])
            check('prefix_length_metadata_'+cid,row['prompt_tokens']==len(result['prompt_ids']) and row['generated_prefix_tokens']==k)
            check('diagnostic_matches_original_hot_list_'+cid,row['new_diagnostic_tokens']==cp['hot_next_tokens'])
            check('diagnostic_matches_actual_future_'+cid,row['new_diagnostic_tokens']==result['generated_ids'][k:k+len(row['new_diagnostic_tokens'])])
            check('same32_flag_consistent_'+cid,row['same_sampled_diagnostic_tokens']==(row['new_diagnostic_tokens']==cp['hot_next_tokens']))
            # These scalar/fingerprint flags are source-bound execution records.
            # Complete replay logits/KV tensors were NOT saved by the control.
            check('recorded_zero_difference_'+cid,row['max_abs_from_original_stream']==0)
            check('recorded_same_top1_'+cid,row['same_top1'] is True)
            check('recorded_all_KV_equal_'+cid,row['same_all_KV_fingerprints'] is True)
            expected_pass=row['max_abs_from_original_stream']==0 and row['same_all_KV_fingerprints'] and row['same_sampled_diagnostic_tokens']
            check('recorded_pass_definition_'+cid,row['pass']==expected_pass)
            expected=[]
            for start in range(0,len(result['prompt_ids']),256):expected.append({'stage':'schedule_matched_cold_replay','input_tokens':min(256,len(result['prompt_ids'])-start),'past_tokens':start,'position_start':start})
            for index in range(k):
                pos=len(result['prompt_ids'])+index;expected.append({'stage':'schedule_matched_cold_replay','input_tokens':1,'past_tokens':pos,'position_start':pos})
            for index in range(len(row['new_diagnostic_tokens'])-1):
                pos=len(prefix)+index;expected.append({'stage':'schedule_matched_cold_replay','input_tokens':1,'past_tokens':pos,'position_start':pos})
            check('teacherforced_schedule_complete_'+cid,row['ledger']==expected)
            total_calls+=len(expected);total_inputs+=sum(v['input_tokens'] for v in expected);new_diagnostic_tokens+=len(row['new_diagnostic_tokens'])
            records.append({'case_id':cid,'prefix_sha256':row['prefix_sha256'],'checkpoint_generated_tokens':k,
                'recorded_max_abs':row['max_abs_from_original_stream'],'recorded_KV_fingerprints_equal':row['same_all_KV_fingerprints'],
                'sampled_tokens_equal_independently_compared':row['new_diagnostic_tokens']==cp['hot_next_tokens'],
                'forward_calls':len(expected),'forward_input_tokens':sum(v['input_tokens'] for v in expected),'pass':row['pass']})
        check('worker_summary_rows_'+str(worker),summary['rows']==rows and summary['passed']==sum(r['pass'] for r in rows))
    check('all8_checkpoints_once',len(records)==len({r['case_id'] for r in records})==8 and {r['case_id'] for r in records}==expected_ids)
    check('original_gate_result_not_rewritten',original['numeric_pass_count']==6 and original['strict_replay_pass_count']==6
          and original['next_argmax_identical_count']==original['sampled_diagnostic_tokens_identical_count']==original['hot_matches_actual_future_count']==8)
    # Parent's separate offline baseline score: totals/scope only, no row/Gold access.
    scores=load(root/'D1_NATIVE_SCORES.json')
    score_totals={k:scores[k] for k in ('status','n','correct','unknown','scope')}
    check('separate_baseline_scores_8of8',score_totals['status']=='COMPLETE' and score_totals['n']==score_totals['correct']==8 and score_totals['unknown']==0)
    for name,digest in original_report_sha.items():check('original_report_unchanged_'+name,sha(root/name)==digest)
    for row in retrieval['files']:check('control_unchanged_'+row['path'],sha(root/row['path'])==row['sha256'])
    seconds=launcher['conservative_GPU_seconds'];original_seconds=original['conservative_GPU_seconds']
    check('launcher_cost_sum',abs(seconds-sum(w['elapsed_seconds'] for w in launcher['workers'].values()))<1e-8)
    report={'status':'PASS','checks_passed':len(checks),'checkpoints':8,'source_sha256':sha(root/'replay_schedule_control.py'),
        'audit_source_sha256':sha(__file__),'native_original_joint_gate_pass_count':6,'native_original_token_replay_identical_count':8,
        'schedule_control_recorded_zero_logit_difference_count':sum(r['recorded_max_abs']==0 for r in records),
        'schedule_control_recorded_equal_KV_count':sum(r['recorded_KV_fingerprints_equal'] for r in records),
        'schedule_control_sample_lists_equal_count':sum(r['sampled_tokens_equal_independently_compared'] for r in records),
        'forward_calls':total_calls,'forward_input_tokens':total_inputs,'diagnostic_generated_tokens':new_diagnostic_tokens,
        'control_GPU_seconds':seconds,'control_GPU_minutes':seconds/60,'native_plus_control_GPU_minutes':(seconds+original_seconds)/60,
        'baseline_offline_score_record':score_totals,'cases':sorted(records,key=lambda r:r['case_id']),'checks':checks,
        'scope':'Same original8checkpoints, schedule/reference control only; no new quality trajectory, no repair, no crop/bridge/G.',
        'evidence_limits':['Replay logits arrays and replay KV tensors/after-fingerprints were not retained. Zero maxdiff and all-KV equality are bound-source execution records, not independently re-subtracted/rehashed tensors.',
                          'Actual new diagnostic token lists and ledger were independently compared with original hot/actual future and exact schedule.',
                          'Control prelaunch freeze explicitly binds control source/protocol, not every previous D1 result/cp/NPZ input; original artifacts were rechecked against their existing retrieval hashes and prefix identities.',
                          'Offline8/8 is a descriptive Continue baseline score from separate parent CPU grading; this audit did not read evaluation-only or recompute Gold.',
                          'Supports schedule-related numerical explanation, not proof that FP16 alone is the sole cause or that all future replay paths are identical.']}
    (root/'D1_SCHEDULE_CONTROL_AUDIT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    md=f'''# D1同前缀执行调度控制的只读审计

2026-11-06。**完整性审计PASS，{len(checks)}项通过。** 原D1的联合数值门槛6/8原样保留；原下一top1/采样32/实际未来均8/8一致，也未改写。

新控制覆盖原8个相同checkpoint：记录的hot-vs-调度匹配replay logits最大差均0，完整KV指纹比较flag均true；8份实际32-token列表与原hot及已生成的主流未来逐项相同。重放是原prompt同chunk后逐token teacher-force已观察前缀，再恢复原checkpoint RNG；不是重新采原整道题、不是改seed/阈值、不是新修复动作。

逐条prefixSHA/长度、原生ID拼接、控制源/协议冻结、原D1取回hash及控制取回hash均相符；8个checkpoint只算8道原题。控制worker summary与各个case文件一致，ledger精确对应{total_calls}次forward、{total_inputs}输入tokens；新生成仅诊断{new_diagnostic_tokens} tokens。控制{seconds/60:.6f}单卡分钟，native＋control共{(seconds+original_seconds)/60:.6f}，不把两卡并行的wall和单卡分钟混同。

## 证据必须分层

- **可独立重数/逐项比较：** 所有文件SHA、8个原prefix、32-token实际列表、teacher-forcing调度/位置与forward台账、worker分母及GPU秒相加。
- **绑定源码的执行记录：** 新控制没有保存完整replay logit数组或KV张量/after指纹，因此不能声称本审计再次做tensor相减得到0，或再次rehash全部KV。它核对的是源代码明确实施这些比较、固定源哈希、标量/布尔记录及原NPZ/指纹的引用关系。
- 原D1 bulk cold的两项超预注册数值阈值仍是失败；本新控制支持“bulk与stream调度有关”的解释，不把原门槛改成8/8，也不证明FP16是唯一因素。并未观察实际token分叉。

主任务独立CPU评分记录为**native Continue 8/8**；本审计只核总数与scope，未读Gold/重新判数学答案。8/8不是SCOPE-Rebase收益，因为根本没有执行repair、bridge、crop或G；诊断分支也不增加独立质量样本数。

控制prelaunch只显式绑定控制源/协议，未列尽前一D1的每个result/cp/NPZ；本次依据原取回hash重新核它们未变，并以prefix身份及源码读取关系绑定，不把事后核对夸成事前全部输入独立冻结。

证据：[D1_SCHEDULE_CONTROL_AUDIT.json](D1_SCHEDULE_CONTROL_AUDIT.json)、[原D1审计](D1_NATIVE_AUDIT_ZH.md)、`schedule_control/`、`SCHEDULE_RETRIEVAL_MANIFEST.json`、`schedule_control_freeze.json`。本报告无模型、GPU、远程或新数学评分运行。
'''
    (root/'D1_SCHEDULE_CONTROL_AUDIT_ZH.md').write_text(md,encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('checks','cases','evidence_limits')},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
