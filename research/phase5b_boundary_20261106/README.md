# Phase5-B：自然失败诊断与后台边界投影

2026-11-06。已完成：先核查顾问意见和真实轨迹，再做一次已知图/合法核验器条件下的组件小试。实际10/10输出、E/C/W全覆盖，2.90678单卡分钟；没有最强基线正确率增益或自然任务收益。

- [意见取舍、理论边界与对照协议](ADVISOR_REVIEW_AND_PROTOCOL_ZH.md)
- [自然轨迹：实际阅读范围、失败原因与证据](NATURAL_DIAGNOSIS_ZH.md)
- [19条审阅记录](NATURAL_REVIEW_NOTES.json)、[100条筛查与选择分母](NATURAL_TRIAGE_INDEX.json)
- [先前研究与理论出处](PRIOR_ART_AND_THEORY_ZH.md)
- [问题、尝试与决定日志](WORKLOG_ZH.md)
- [本轮冻结协议](PROTOCOL.json)、[启动前source/data/tokenizer绑定](prelaunch_freeze.json)
- [CPU准入](CPU_ADMISSION.json)、[受控输入](CONTROL_DATASET.json)、[模型消息](PREPARED_JOBS.json)
- [真实结果与决定](RUN_STATUS_ZH.md)、[原始数据重数](RESULT_AUDIT.json)，执行状态以它们为准。
- [面向用户的建议取舍与当前进度](../../docs/phases/Phase5B_自然诊断与父边界投影_ZH.md)

后台控制器只从可见原题核验x与独立支路r的支持算式，不计算新目标分支；新目标仍由模型提出一次。它支持三种可判定E/C/W状态并保留未知/拒绝检查，不是自然图自动提取或完整逐节点验收。

\[
P_t=\operatorname{BackwardSlice}(z;\operatorname{stop}=C_t),\qquad
\partial P_t=\Bigl(\bigcup_{v\in P_t}Pa(v)\Bigr)\setminus P_t.
\]

其中C是当前已认证支持；未知规则/父支持不能静默剪掉。只向模型传边界值、P内完整规则和目标，后台版本/旧错值不进入投影prompt。完整确定性DAG及有效证书下，精确投影计算=冷重算；不保证LLM解码正确或天然格式合规。

本轮仅1个20定义程序，含12个独立支路算式和7个目标算式，E/C/W是相关变体；投影后三个prompt相同，重复生成不能充当3个独立任务。普通DAG切片器也产生相同prompt，这是CPU等价控制，不是第二个新算法。

CPU逻辑最终684项通过。最终随机接口目录为`cpu_interface_final_02/`；`cpu_interface_01/`和`cpu_interface_final/`只是准备历史，未用于最终绑定。随机CPU输出全部8token cap只验证接口，不能当模型能力。

旧Phase5-A及所有历史分数不改。本轮比较含RawFull、SharedGFull、BoundaryProjection、唯一RestartP；共享核验基线仍保留。全部fresh-prefill，不宣称热KV续接部署加速；旧历史生成是共同给定前置成本。
