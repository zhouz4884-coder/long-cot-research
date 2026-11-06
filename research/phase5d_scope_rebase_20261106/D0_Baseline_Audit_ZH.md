# D0完成：固定文本读出审计与Phase5-C边界复核

2026-11-06。**D0零新增GPU，独立重数5146/5146项通过；Phase5-C旧330个冻结成员逐项SHA均未变。** 本文是另列的事后确定性读出诊断，不改旧主分，不是SCOPE-Rebase或新模型成绩。

## 目的、实际步骤和冻结顺序

先完整读新附件、zip中5文件和Phase5-C收尾，再用通用假例设计选择器：本地39项结构/歧义测试与远程CPU18项数学smoke通过后，冻结`D0_parser_contract.json`。随后只读取旧可见库与原224个`answer_text`，不读取Gold做选择，得到32条thinking＋224项生成＝256个文本、4个固定策略＝1024条相关选择。

Gold只在选择冻结后的CPU数学评价加入。对完全相同的surface/Gold字节复用评价，共43个唯一语义比较、墙钟7.761秒；这不是43个独立题。语义后端未知0。本次独立审计没有重新调用数学grader，也没有新模型/GPU调用，只重放固定选择、校验来源/缓存对应并重新计数。

## 全部8种文本条件×4种策略

每格为“正确数/原32题（可选出数）”；弃权和缺格式均留在32分母，**不是数学判错**。四策略分别为LastBox、LastFinalAnswer、FirstCompleteAnswer和保守表面一致策略；都不按Gold择优。

| 文本条件 | LastBox | LastFinalAnswer | FirstCompleteAnswer | ConservativeFinal |
|---|---:|---:|---:|---:|
| 原历史thinking正文 | 28/32（28） | 16/32（16） | 27/32（27） | 27/32（27） |
| ForcedBoxCue生成 | 28/32（32） | 0/32（0） | 28/32（32） | 28/32（32） |
| FullContinue生成 | 16/32（17） | 13/32（14） | 16/32（17） | 3/32（3） |
| FullContract生成 | 15/32（15） | 9/32（9） | 15/32（15） | 6/32（6） |
| FullContractEvidence生成 | 19/32（20） | 12/32（13） | 19/32（20） | 7/32（7） |
| TailContract生成 | 12/32（12） | 7/32（7） | 12/32（12） | 5/32（5） |
| ProjectedContractEvidence生成 | 14/32（14） | 9/32（9） | 14/32（14） | 5/32（5） |
| RestartP生成 | 9/32（10） | 8/32（8） | 9/32（10） | 1/32（2） |

历史thinking的28个可选LastBox全部匹配Gold；另外4题没有按该策略可交付的完整对象。这是**给定这32条完整历史文本的一种确定政策观测**，不是Gold-best oracle，更不是所有读出/修复算法的数学上界或新独立benchmark。

ForcedBoxCue的评分字符串只保留预填`\boxed{`和模型续写，不包含输入侧的`Final answer:`文字。因此其LastFinalAnswer覆盖0是策略/格式不适用，不能说32题数学都错。thinking的LastFinalAnswer只覆盖16，也不能由此推断其余16题没有答案。

## 与旧主分的区别：七条件各恢复1项，没有新生成

固定新LastBox相对旧严格终端契约，七个生成条件各多1项且无损失；这是新后处理的诊断，不给旧主表补分：

| 条件 | 旧主分 | D0 LastBox | 被恢复ID | 可核对原因 |
|---|---:|---:|---|---|
| ForcedBoxCue | 27/32 | 28/32 | C013 | 完整boxed后跟square meters |
| FullContinue | 15/32 | 16/32 | C009 | 完整boxed后跟square centimeters |
| FullContract | 14/32 | 15/32 | C006 | 完整boxed后跟representatives |
| FullContractEvidence | 18/32 | 19/32 | C006 | 完整boxed后跟中文名代表 |
| ProjectedContractEvidence | 13/32 | 14/32 | C006 | 完整boxed后跟representatives |
| RestartP | 8/32 | 9/32 | C009 | 完整boxed后跟中文平方厘米 |
| TailContract | 11/32 | 12/32 | C004 | cap前已给出boxed−2，后面又展开未完推导 |

Tail的这条特别说明：触顶并不必然表示之前从未写出完整答案，但事后读出早先boxed也不是新的局部修复行为。D0没有追加一token，更没有依Gold去选择该题的候选。

## 主要教训与已知解析限制

1. **存在强零新增模型调用的文本读出参考。** 历史thinking的LastBox28/32高于若干追加自由回复条件，说明不能忽略“已有答案再读出/再推理反而未交付”的可能。这个对照应与原生模型真正到EOS的基线一起解释，不能直接用来宣称自然原生正确率87.5%。
2. **合法后缀单位造成的测量损失是实证事实。** 新统一解析恢复了各条件一项，但没有缩小Projected与同证据Full的5题差距，也没有创造算法质量收益。旧27/32、13/32等分数保持原样。
3. **固定LastBox不是认证。** Forced的LastBox选出32，其中4项仍不匹配Gold；“看见框”不能给proof边PASS，不能据此提前停机或覆盖旧证据。
4. **表面不一致不是语义冲突。** Conservative的低覆盖既可能来自多个候选，也可能来自标签/对象解析噪声；不能用该标记直接当反例仲裁G。
5. **当前label策略仍有限。** C013 thinking的FirstCompleteAnswer选择了过长的早期标签捕获，因`empty_or_oversize`弃权；Conservative也将其与最后boxed的表面差异计入歧义。这不是“早期数学答案被证伪”。复杂标签后prose可能返回unknown；本轮未为提升覆盖而后验改规则。

## D1交接与不能跨越的结论

这些完整thinking可能包含相对于早期checkpoint的未来信息。D0的LastBox/最终正确性不得用于选择D1“首次正确点”、触发回退、桥接或在线动作。字符span也不是可直接crop的token位置。

下一步应以冻结原生token前缀、真实可观察事件和自然EOS建立D1执行器。D0只能给出读出参考及解析问题清单；它没有验证证书范围、独立多重支持保留、KV重建、错误反思防护或端到端修复收益。

证据：[D0固定契约](D0_parser_contract.json)、[Gold-blind准备](D0_PREPARATION.json)、[1024逐项评分](d0_scoring/D0_scores.jsonl)、[统一结果](d0_scoring/D0_RESULTS.json)、[独立机器审计](D0_AUDIT.json)、[复算脚本](audit_d0_results.py)、[原生提交边界](D0_commit_boundaries.md)。
