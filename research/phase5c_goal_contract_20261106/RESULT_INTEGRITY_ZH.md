# Phase5-C 两wave结果完整性独立核对

2026-11-06。**PASS：3086/3086项；224个权威输出完整，32个题目各七条件齐全。** 只读本地取回文件，不读Gold/evaluation、不评分正确率、不运行远程、模型或GPU。没有修改原始输出。

## 范围与字节保持

- 原wave：worker0=65、worker1=60，共125输出；两summary均如实为PARTIAL_TIME_BUDGET。
- 用户撤销原30单卡分钟限制后，续wave按存在性计划只补worker0=47、worker1=52，共99输出。原125输出及其metadata共139文件，与ORIGINAL_WAVE_RETRIEVAL的bytes/SHA全部相符，没有覆盖或回填。
- 最终RETRIEVAL_MANIFEST的257文件全部校验相符；原freeze15项、resume freeze8项及CPU batch49/helper46/resume planner33的源码绑定通过。
- 32个问题ID、32个精确题干SHA、32个空白归一化题干SHA、32个trace SHA，无重复组。这排除了字面/空白重复，不证明不同措辞题的语义或统计独立。
- 224个预渲染输入对应完整32×7；worker奇偶分片、bankID/方法/rank/指纹/提示长度、同packet对照、评分前缀与source对应一致。实际raw未保存全部输入张量，依冻结源码的输入重建检查及保存的指纹/长度核对，没有另跟踪GPU每个实参。

## 续接与计费

实际128批，原71＋续57；没有重复权威job、没有缺失，STUDY_STATUS=FINISHED。每份resume_plan由原有权威行与同一planner独立重建一致；无成绩驱动的选择。原pair/方法参数维持。实际没有部分pair的已有行弃用重算（discard0）；该分支由CPU合成检查覆盖，不能说真实GPU已经动态覆盖它。

全部逻辑生成65512 tokens，discard0，全部physical forward输入695892。逐批独立重数batch×sequence、首prefill/后续单token形状、prompt左padding与已EOS行后续填充计数、较早EOS行后续physical工作和各summary一致。physical输入不是无padding的prompt+output，也不是可直接等同的FLOP。

原＋续四worker外层GPU时间合计3089.214850秒=51.486914单卡分钟，不能只报并行墙钟或续wave。原30分钟上限是历史协议，已按用户授权修订；不继续用它作为本轮完成门槛。

## EOS与保护顶

| 条件 | 输出数 | 正常EOS | 384保护顶 | 逻辑生成tokens |
|---|---:|---:|---:|---:|
| ForcedBoxCue | 32 | 29 | 3 | 1480 |
| FullContinue | 32 | 17 | 15 | 10647 |
| FullContract | 32 | 14 | 18 | 10897 |
| FullContractEvidence | 32 | 20 | 12 | 9764 |
| TailContract | 32 | 11 | 21 | 11153 |
| ProjectedContractEvidence | 32 | 14 | 18 | 10489 |
| RestartP | 32 | 10 | 22 | 11082 |

总EOS115、cap109。当前同37ff模型资产取回的observed_model_generation_config.json与四worker模型manifest中的generation_config字节hash相符，配置EOS为151643/151645；各行都按首EOS结束，或无EOS且恰384触顶，前缀与输出拼接一致。没有另加载tokenizer独立重解码每条输出文本。

**384终局保护明显绑定，尤其Projected18/32触顶。** 质量分析必须单列cap和EOS且正确，不能把本轮当不受长度限制的自然交付质量。是否答对由另一个冻结CPU评分流程判断，本审计没有查看任何正确率或Gold。

详细机器证据见RESULT_INTEGRITY.json；issues=[]、observations=[]。这份报告只确认来源、输入、完成分母、续接不覆盖及计费一致性，不替代数学评分、神经机制、因果或自然泛化结论。
