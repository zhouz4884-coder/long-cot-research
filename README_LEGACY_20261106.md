# 自然推理步骤的干预价值测量

2026-11-05当前工作已按用户要求切换为**有效长思维链研究**。文献基础见 [研究地图、文献库与模块组合评估](research/long_cot_landscape_20261105/README.md)；结合新增两份PDF、讨论和实测算力，当前选择先做**证伪后状态恢复的短周期机制鉴别**，见 [当前目标](docs/next_phase/CURRENT_RESEARCH_GOAL_20261105_ZH.md)、[方向判断与已执行首轮](research/direction_selection_20261105/README.md)。旧实验/计划保留为历史，本轮不恢复旧GPU队列，不预设早停或旧性能目标，不创建定时任务。

随后结合原始输入与新建议，已完成 [下一轮方法设计、CPU审计与固定实验材料](research/next_design_20261105/README.md)：纠正独立变量/旧数来源假设，准备历史100题P1清单与真正独立r对照，明确梯度方向和一步更新门槛；尚未新增GPU实验。

进一步的 [文献启发、候选算法与数学/模型分析](research/algorithm_mechanism_20261105/README.md) 提出版本一致的局部重推，审查阶段指针和转移梯度假说，并明确逐数据集accuracy/pass@1是主指标；当前成果是理论与CPU证据，不是新算法benchmark成绩。

最新 [四补充核查与P0.5短试](research/p05_design_review_20261105/README.md) 已完成80个自由输出，实际4.4591单卡分钟；辅助诊断完成8题后按预算停止。联合臂12/16对同期FullOneLine11/16的净+1主要受输出预算/交付影响，保留全部原文和负例，尚未形成正式benchmark增益。

以下2026-10-14内容为历史：研究目标曾修订为**候选质量准入与长短尺度推理分配**，见 [历史18周研究目标V2](docs/next_phase/RESEARCH_GOAL_V2_20261014_ZH.md)。当时的先完成冻结M1顺序不再是当前执行入口；原结果和下面的旧实验说明继续保留为历史证据。每小时定时任务已按用户要求删除。

本项目执行[分享聊天中的研究计划](https://chatgpt.com/share/6ac7ac26-c6a8-83ec-be63-d018140ce23e)。目标是测量继续一个自然推理步骤的净收益，随后检验其可预测性和真实在线价值。

**最终综合报告写入 `docs/REPORT_ZH.md`；执行过程记录见 `docs/WORKLOG_20261011.md` 和 `docs/WORKLOG_20261012.md`。代码存在、编译通过或 CPU 检查通过均不表示 GPU 实验完成。**

2026-10-13 已完成并核验全部 1648 条实际在线记录。本轮结果为 **NO-GO**：主 300 题 FULL=269/300（89.67%），净收益控制器=248/300（82.67%）；token 节省 45.45%、实际耗时节省 44.89%，伴随 7 pp 准确率损失。详细置信区间、基线、失败定位、表示敏感性与下一轮改进见 [完整实验总结](docs/REPORT_ZH.md)。本轮完成的是研究执行与证据归档，不是论文录用。

## 风险约束新路线的连续执行

用户18周路线在独立目录 `experiments/radar20261013` 继续。旧结果复核完成；新100题pilot与116个固定预算请求完整，39状态交叉随机性正在实际采集。共同29题在1024/2048/4096/8192/16384预算下分别答对10/11/13/17/22；16384救回5题、无反向改错，但11题仍触顶。这是参考预算诊断，不是新算法盲测收益。

恢复及后续阶段：[连续执行入口](docs/next_phase/CONTINUATION_RUNBOOK_ZH.md)；当前方法、结果与错误修正：[本轮工作记录](docs/next_phase/WORKLOG_20261014_CONTINUATION_ZH.md)；完整状态：[18周台账](docs/next_phase/EXECUTION_LEDGER_ZH.md)。每小时定时任务已于2026-10-14按用户要求删除，新目标独立保留；既有远端采集未因删除定时任务而被停止。正式训练、独立校准、1062题新盲测、跨模型/非数学模型成绩及有条件Serving仍须实际完成。

## 冻结输入

- 上游 llm-think-stop：`21efe411bcaf34de884c1120ab7fb0573c193a62`，不修改源码。
- EAT 参考实现：`93a46f7a8b3d401511389e8a10dc117aa7f9c287`。
- Qwen3-4B revision：`1cfa9a7208912126459214e8b04321603b3df60c`。
- MATH-500 revision：`6e4ed1a2a79af7d8630a6b768ec859cb5af4d3be`。
- 题目划分：150 development / 50 engineering / 300 test；见 `data/split_manifest.json`。

主实验计划使用 FP16、T=0.6、top_p=0.95、top_k=20。原版 BF16 greedy 复现独立记录。所有主方法共享短答案协议：强制结束思考后输出一个完整 boxed 答案。

## 执行入口

远程目录为 `/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/projects/reason-transition-20261008`，隔离环境为该目录的 `.venv`。SSH 认证工具在本机被 gitignore 的 `.tools` 中，凭据不进入仓库。

```bash
python scripts/build_splits.py
python -m unittest discover -s tests -v
python scripts/validate_protocol.py --model /path/to/Qwen3-4B --n 24
python scripts/validate_cache_clone.py
# 正确性和原版 P0 完成后，按依赖执行；pilot review 由执行者实际检查 50 个答案。
python scripts/run_pipeline.py
# 以下是另外两个独立进程，按等待依赖运行；主管线不会自动启动它们。
python scripts/run_holdout_remainder.py
python scripts/finalize_execution.py
# 对已完整保存的原始结果重新统计：
python scripts/final_stats.py
```

`run_pipeline.py` 规划的顺序是 24 题分支 pilot、150 题开发、补齐 50 题工程集、Grouped CV、工程集校准、重复采样控制、50 题独立在线测试及第二模型 24 题检查。它必须实际部署和运行才会推进；不能把这个入口文件当成已执行的研究。

主模型四种方法的最终 300 题由 `run_holdout_remainder.py` 补齐；其余控制和消融各 50 题，第二模型两种方法各 24 题，共 1648 条在线记录。输入冻结、实际命令、人工核验和分析复现的详细依赖见 [复现说明](docs/REPRODUCIBILITY_ZH.md)。

主采集器是 `scripts/collect_bank.py`：同一真实父 KV 深拷贝到 STOP/STEP，FULL 为未干预的父轨迹；离线分支开销单独记录。早期 `generate_traces.py` 和 `branch_at_checkpoint.py` 是独立重放辅助代码，不是主采集路径，不应和主数据混跑。

`evaluate_online.py` 在生成期间执行策略，评分仅在结束后进行。统计以题目配对，既报告 bootstrap，也报告精确有害反转风险上界。50 题经验改善不能直接变成 1pp 非劣性声明。

详细协议、基线审计、数值诊断、答案协议和候选创新均在 `docs/`。当前没有已经证实的论文级性能或新颖性结论。
