# Phase5-C：生成结束后的统一离线评分

2026-11-06。`score_readouts.py`只做CPU评分/统计，不修改grader、runner、模型输入或旧分数。

## 何时能运行

脚本首先读取`root/launcher.json`，只有`status=FINISHED`才继续。如存在`STUDY_STATUS.json`，还必须确认该全研究状态与`resume_launcher.json`均为FINISHED；resume缺失/RUNNING/ERROR时拒绝。存在resume却没有STUDY_STATUS也拒绝，不能因原worker已经软停就提前评分。所有门通过之前未读取Gold、bank或模型输出。没有绕过参数。即使结束状态下某worker非零/partial，仍保留缺失计划项，不将其删除；实际224完成数由summary显式重数。

```text
python -B score_readouts.py --root /path/to/phase5c
```

默认新建`root/scoring/`，已有同名目录则拒绝覆盖；可通过`--output`指定另一新目录。必须在已装冻结Math-Verify0.9.0的CPU环境执行。脚本设置CUDA不可见，4个线程调用grader；grader各自使用独立CPU子进程及20秒硬限，不启动推理。

## 输入与输出

- 依据冻结protocol的7方法、manifest的32个bank_id/rank建立224项计划。
- 收集`results/*worker*/`中的job JSON，实际允许原`worker_0/1`和续跑`resume_worker_0/1`；每个job文件必须匹配原224个expected ID。核job名称、bank/rank/method、worker分区、token数和停止标记。未知job/未知worker/重复ID均拒绝，重复即使字节相同也不自动去重，更不按质量择优。metadata文件不作job解析。
- 生成结束后才按bank_id连接`bank_evaluation_only.jsonl`的Gold；核其冻结SHA。历史correct/forced answer不参与新grade或方法选择。
- 统一调用未修改的`grade_final(text,gold)`。各完成结果实时追加`grades.jsonl`，保存源记录/答案SHA、停止/长度与grade诊断；完成后写`summary.json`。

每方法报告planned32、delivered/missing、gradeunknown、unparsed、cap/EOS、正确与EOS且正确。主分母始终是32；confirmed正确率是已确认交付正确数/32。缺失或grader None是未解决，不宣称数学答错；同时给其未知范围。cap/解析失败不会从配对分母中按结果删除。

## 配对与继续线

保存7方法均有输出的共同case列表，另存7方法均grade已解决的列表。Projected对每个baseline分别统计win/loss/tie、两方正确/错误tie和精确两侧McNemar；每个配对显式列missing/unknown与实际分母。还在共同完整已解决子集上另列同样统计。未做多重比较校正，全部是探索性诊断。

继续线按**各baseline在32计划题上的aggregate最高正确数**计算，不用逐题挑最佳输出的oracle。Projected净多至少2题且32题七臂均完成、评分均解决，才标“进入独立确认”；缺失或None则为inconclusive。通过门槛不是显著性、正式benchmark、端到端自然推理或论文已验证。

## 成本与验证

报告评分wall、父进程CPU、Linux子进程累计CPU（平台不支持则None）、各grade重叠wall之和，记录scorer/grader/protocol/manifest/eval/原launcher/resume_launcher/STUDY_STATUS/raw SHA。原与续launcher的GPU成本分别保留；仅两者均有同口径aggregate秒时才相加，不漏掉原轮成本。评分是离线评估，不算作在线G。物理batch墙钟/forward开销不会平分给方法冒充单请求延迟。

当前scorer SHA为`9538b3f187a82152e2f5bb2c5a5d4d20d97cdc854b690d17ae62b0c63ac2f1c0`。`test_score_readouts.py`用纯假32题/224条记录及临时launcher检查38项通过，含三重状态门、原/续目录合并、相同/不同重复拒绝及unknown ID，见`SCORER_CPU_CONTRACT_TEST.json`。这不是实际输出评分；编写/测试时未读取新bank正文、Gold或本轮模型输出。实际结果只能在主任务确认生成结束后执行得到。

用户随后明确取消原30GPU-min上限、要求补齐32×7后比较。因此仅修订I/O完成门与原/续输出收集，数学grader及统计规则未改。原25项版源码按字节保存在`score_readouts_prepare_v1.py`（SHA`4b772d75…`），其旧证据为`SCORER_CPU_CONTRACT_TEST_prepare_v1.json`，只作准备历史，不能用于有续跑的最终评分。
