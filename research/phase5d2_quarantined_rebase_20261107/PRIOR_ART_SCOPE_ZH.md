# Phase5-D2 直接近邻与贡献边界核查

核查日期为2026-11-07。按 nature-academic-search 的引文核验与多源检索流程核对5篇核心论文。academic-search MCP未提供，本次直接读取ACL官方PDF、arXiv正文和作者仓库。未解析的指定论文为0。此文件记录原文事实与我们的推论，尚未复现这些方法。

四个指定名字均可解析。TAAR为 *Thinking Traps in Long Chain-of-Thought: A Measurable Study and Trap-Aware Adaptive Restart*，ACL Findings 2026，1930。Logic Tree为 *Logic Tree: Topology-Aware Backtracking for DeepResearch Agents*，EMNLP Findings 2026，844。其余为 *Sherlock: Reliable and Efficient Agentic Workflow Execution*，2511.00330v1，以及 *From Faulty Memories to Corrected Actions: Dependency-Guided Rollback Repair for Memory-Augmented Agents*，2608.10502v2。TAAR的ACL网页作者拼写与PDF有差异，导出引文采用PDF的Kang Chen、Shihan Zhao、Heng Wang、Minshen Yu。标识与作者字段见同目录PRIOR_ART_VERIFIED.json/BIB。

| 论文 | 触发、核验和恢复的原文设计 | 报告效果与成本口径 | 直接约束 |
|---|---|---|---|
| TAAR | 训练诊断模型预测trap位置及escape概率，在预测位置前截断，按概率继续、重采样或强重启。离线trap标注及escape标签使用参考答案，推理时预测。保留的是截断前文本。§4.1–4.4，PDF第3–5页。 | 表2的4B宏均分48.9→50.6，120B为80.6→79.2。表6显示相对baseline额外31.2% tokens，42.6%是额外开销相对all-traps消融的减少。§5.2、§6.4，PDF第5–8页。 | 去掉错误前缀再生成已有直接Long-CoT近邻。诊断模型训练和实际额外token均要计入。没有收益必然性。 [官方PDF](https://aclanthology.org/2026.findings-acl.1930.pdf) |
| Logic Tree | Worker请求回退，Judge可阻止错误回退。局部重置目标及后代，失败日志引导重试。全局重规划先把有检索证据/执行日志支持的原子事实整理后携带。§3.3–3.4，第5页，A.1.1第11页。 | Qwen3-4B prompt-only宏均分9.14→5.84，SFT后23.09，表1第7页。匹配495 query-runs的准确率48.5→54.5，平均时延518→629秒，附录表3第12页。 | Judge挡住假反思和保留有效事实均已有先例。提示式复杂DAG管理在小模型上可能退步。 [官方PDF](https://aclanthology.org/2026.findings-emnlp.844.pdf) |
| Sherlock | 离线故障注入定位易错节点，选择验证器。验证与后续执行并行，结果不一致时回退依赖节点。数学/code的廉价相似性接近随机，采用保守全回退。§5–7.2、附录C。 | §8.4表3的48.7%为LiveCodeBench平均最终验证结束时延下降。§6.1、7.1、8.1分别建模验证效用、投机浪费及两种结束时延。 | 隔离、验证后保留和依赖回退本身已有系统先例。原生单次CoT的token/KV/RNG恢复仍须独立实证。 [原文](https://arxiv.org/html/2511.00330v1) |
| DGRR | 输入已诊断fault及runtime provenance，按依赖追踪，保留独立支持，选择答案相关重放。§3.4明确一个未受影响前驱即足够，不验证其覆盖整条内容。§3.1–3.6。 | 150受控病例恢复85.3%对LLM-judge77.3%，复发26.6%对12.1%，LLM calls5.70对9.80。去support-check反而恢复88.0%，表2–3、§5.1–5.2。 | 完整支持覆盖是可测试缺口。支持保留直接改善准确率没有现成保证。此处恢复率条件于已诊断受影响病例。 [原文](https://arxiv.org/html/2608.10502v2) |
| ClaimScope | 预给claim、assumptions和witness schema，只核模型提交的状态，不搜索替代反例。拒绝一个反例不建立原命题真值。scope为指定核验目标。§1–2、附录A.1/A.4。 | Qwen3-8B、thinking关闭。表3中generic→verifier，反例15/39→23/39，safe20/72→25/72，verdict47/72→46/72。事后schema-only同为25/72。§3、附录A.6列调用和时间。 | 域条件与提交witness的核验已有直接先例。结构修复、参考标签一致和最终数学能力需要分别验证。 [原文](https://arxiv.org/html/2610.21581v1) |

DGRR作者代码另作了静态核对。commit为713724491b9bbc6e55f0f9d8723da0eb0766ced7，`support_checker.py`的`has_trusted_support`在没有直接证据时返回True，否则取至少一个有效前驱。模块早期说明仍提到递归walk，实际函数与§3.4的直接前驱规则相符。这里应以函数体作为实现比较依据。没有执行该仓库。[固定源码第277行](https://github.com/xiaoqi-7/memory-rollback/blob/713724491b9bbc6e55f0f9d8723da0eb0766ced7/methods/ours/support_checker.py#L277)

这些原文共同支持一个研究判断。回退、隔离、选择验证、支持保留、带条件反例，均已有可借鉴模块。尚值得检验的组合是，把**作用域与版本绑定的证明失效**连接到**真实原生CoT的因果文本清除**，同时携带仍有完整证明的事实。五篇已读方法节没有提供这一整套原生token/KV/RNG对齐、证明与结论双前沿的实验，但这个检索范围不足以证明首次创新。

我们的可证伪差别可写成下表。以下都是待实验的贡献候选。

| 候选差别 | 必要对照与反例 | 能成立的最小结论 |
|---|---|---|
| 完整作用域与证明角色授权 | 域外反例、近似等号、假设/反证、相同数字但不同对象，比较Unscoped与Scoped。 | 受支持目标范围内，减少错误撤销。参考答案正确性仍需最终评分。 |
| 全前提与备选证明 | 单个前驱仅覆盖复合结论的一部分，旧版本前提，两个独立证明。对比DGRR式单前驱保留、纯后代失效及完整证书规则。 | 获得更准确的撤销与保留集合。不能从CPU图证明直接推出LLM准确率增益。 |
| 两个恢复前沿 | 一条证明失效但另一路仍支持其结论，令语义失效集合为空、错误文本集合非空。比较只看失去支持的结论与双前沿。 | 即使结论仍成立，也正确退役已失效证明的文本。还需验证重放后的实际续推。 |
| 证据承接的行为增量 | 相同核验证据下比较GenericRewind、RebaseNoCarry、RebaseCarry、FullRestart、SameEvidenceCompactBridge及独立重采样。 | 排除单纯新证据信息和提示重写后，观察承接是否仍有净收益。 |
| 隔离分支的实际价值 | 相同提案和核验信息、完整计费，比较InContext与隔离处理。UNKNOWN无cue路径检查逐token与终止一致。 | 若只获得身份一致性，结论限于实现正确。拒绝动作和真实伤害减少需另测。 |

数学上应维护每条证明的全部必需前提，并允许同一结论存在备选证明。若`j`被证伪，只撤销该证明及依赖它而失去支持的成果。结论`c`若仍有另一条现行证明，可继续保留。另一方面，原生因果文本中的`span(j)`仍须退役。语义集合与文本集合分别定义为

\[
F_{\mathrm{sem}}=\operatorname{Cert}(G)\setminus\operatorname{Cert}(G'),\qquad
F_{\mathrm{text}}=\{\operatorname{span}(j):j\text{ 已被授权撤销}\}.
\]

当前保守策略是在两个前沿的最早来源之前选择合法完整段落边界，再用有现行证书的事实重建后续状态。桥中的事实要带scope、版本、所有前提和来源。改变前缀后必须重新执行相应模型计算。支持图中的“仍有效”不能认证原KV在新前缀下等价。这个策略没有最优切点或最低成本证明。

自然事件覆盖必须成为第一道判断。若范围、角色或READY计划覆盖很低，即便条件修复有效，也难以提高整集正确率。对只改变可行动子集的策略，整集净变化为`(修对数−改错数)/全题数`。不同种子和多个段落属于同一问题簇。成本需要包含原轨迹、提案、核验、复制、重放、丢弃分支和恢复后续推。相同采样次数与相同上限不足以证明等算力。

当前实现还存在明确适用范围。封闭字面等式没有非空反例变量，现有提案解析器会给UNKNOWN。它们可以产生字面核验覆盖，却不足以测出Scoped相对Unscoped的拒错价值。自然修复的双审查角色许可也属于额外离线信息和成本，需要单独保留分母。此报告未读取本阶段Gold或生成轨迹正文。

名称检索另发现 *Dual-Frontier: When Can an Agent Trust Its World Model?*，2609.26293v2。仅核其标题、摘要和版本。它讨论世界模型误差界与策略决策准入，与本项目的语义/文本边界含义不同，方法命名应避免暗示与其同一算法。[arXiv元数据](https://arxiv.org/abs/2609.26293)
