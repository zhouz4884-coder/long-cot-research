# Phase5-A：公式、质量优先与同信息原型短试

2026-11-06。当前状态 **QUALITY_PARTIAL_TIME_BUDGET**；不是完整控制器或正式benchmark。

- [先回答用户问题：上传、下步、公式与token上限](USER_QUESTIONS_AND_ANSWERS_ZH.md)
- [完整候选思想与公式](PLAN_AND_FORMULAS_ZH.md)
- [真实结果、失败原因、判断与下一门槛](RUN_STATUS_ZH.md)
- [问题与尝试日志](WORKLOG_ZH.md)
- [冻结协议](QUALITY_PROTOCOL_V1.json)、[预启动字节绑定](prelaunch_freeze_01.json)
- [观测数值汇总](OBSERVED_RESULTS.json)、[原始结果](results/quality_round_01/summary.json)、[进程退出与完整成本](provenance/launcher_01.json)
- [输入CPU审查](CPU_ADAPTER_CHECKS_ZH.md)、[runner CPU验收](CPU_QUALITY_RUNNER_ACCEPTANCE.json)、[独立源码审查](RUNNER_SOURCE_REVIEW_ZH.md)
- [独立结果重数](INDEPENDENT_RESULT_AUDIT_ZH.md)、[结果判断](RESULTS_CRITIQUE_ZH.md)、[实际输入/输出完整性](POSTRUN_INPUT_INTEGRITY_ZH.md)

实际单张3090/Qwen3-4B/FP16/eager，4.38345单卡分钟；19/30输出完整，3/6主状态四方法完整配对，2独立程序。Direct/Compact/Stepwise各3/3，VersionFrame冻结主分1/3，另两条是正确JSON未解析。自然EOS19/19、512cap0。当前帧没有质量或成本增量，W主比较未运行，不新增训练/大队列。

## 证据版本说明

真实运行只使用runner **0eab**、adapter **3556**、prepared dataset **5260**、topology-v2 **93f3**和冻结parser **c2bc**，完整哈希在freeze/manifest中。

`tiny_quality_cpu_4552_final/`是这一最终源码的随机CPU接口证据。`tiny_quality_cpu_4552_01/`、`tiny_quality_cpu_4552_release/`及若干draft input是准备过程材料，原样保留，不用于当前绑定验收或数学效果。CPU报告中的“未跑GPU”指该CPU阶段的范围，当前真实状态看RUN_STATUS。prelaunch输入快照中的draft/not_executed标签是冻结时元数据，不能替代实际run状态。

未修改旧P0/P0.5数据/分数；没有补写截断后缀或事后放宽主评分器。未来若兼容JSON，需要另立接口契约；本轮两条未解析只能作为明确标注的错误分类证据。
