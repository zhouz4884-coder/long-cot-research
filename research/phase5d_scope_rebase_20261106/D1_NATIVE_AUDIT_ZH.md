# D1原生8题结果的只读完整性审计

完整性状态PASS，372项通过；原生strict接口结果 **NOT_FULL_STRICT_COVERAGE**。本审计没有运行模型/GPU、读取evaluation-only或计算数学正确率。

8题均有独立结果，checkpoint覆盖8/8，数值判据6/8，含数值阈值的联合strict gate 6/8；**下一token argmax相同8/8、采样诊断token序列相同8/8、hot分支与实际无干预未来相同8/8**。不能把仅数值阈值未过说成实际token分叉。EOS 8/8，context cap 0/8。多分支不增加独立题数。

| 题 | 原生生成tokens | 停止 | cp已生成tokens | hot/cold maxabs | numeric | strict |
|---|---:|---|---:|---:|---|---|
| D1_01 | 2051 | EOS | 85 | 0.0625 | False | False |
| D1_02 | 1588 | EOS | 73 | 0.03125 | True | True |
| D1_03 | 1309 | EOS | 108 | 0.046875 | True | True |
| D1_04 | 3498 | EOS | 78 | 0.0390625 | True | True |
| D1_05 | 1092 | EOS | 205 | 0.046875 | True | True |
| D1_06 | 1077 | EOS | 93 | 0.046875 | False | False |
| D1_07 | 3073 | EOS | 74 | 0.034423828125 | True | True |
| D1_08 | 1347 | EOS | 81 | 0.0390625 | True | True |

已核对官方GSM8K源哈希/只用question的8题选择、旧300字面排除、预渲染/源冻结、两worker模型资产/runtime、原native前缀IDs、NPZ统计与逐项forward台账。诊断调用全部计入15549次forward、18692输入tokens，其中诊断3140；主原生输出15035 tokens。外层16.67275单卡分钟，不能与内层时间重复相加。

候选checkpoint只按当时已观察open/未close的首个64token后空段重放；本地tokenizer可用=True。不存在时只保留源码/记录层验证，不能称独立decoder验证。cold/hot采样或top1若失败均保留，没有改seed或阈值。

完整性PASS不等于修复有效。这里没有G、bridge、crop或SCOPE-Rebase；数学评分由主任务另行CPU处理。缓存after张量未保存，所以原cache不变来自绑定源码所执行的指纹比较记录，不伪称重新下载并重算全部KV。模型资产也仅核其记录hash聚合。

观察：["D1_01: joint criteria not passed: maxabs>0.05; seed/thresholds unchanged", "D1_06: joint criteria not passed: KL>0.0001; seed/thresholds unchanged"]

机器证据：[D1_NATIVE_AUDIT.json](D1_NATIVE_AUDIT.json)。审核源SHA `d4f8f2f5e2cc867e495cc7d9f84b389967b90a83449ddcd6392b73de2f70afde`。
