# D0：旧文本的确定性读出审计，不是新算法成绩

2026-11-06。已完整读取本次附件、zip中5个文件及Phase5-C收尾报告。附件里的执行方案作为建议审查，不把其命名、预测或示例PASS当成用户已经确认的效果。

**当前实际进度**：本地39项结构与主任务远程CPU18项数学smoke全部通过，源码绑定一致；随后已冻结D0_parser_contract.json并Gold-blind读取32 thinking＋224生成文本，形成1024个固定选择，旧225个输入文件（1库＋224raw）SHA校验通过。没有读取Gold完成选段，没有新模型/GPU调用。实际数学评分尚由主任务在独立CPU阶段执行，不能提前填成绩。

## 实际目的

在零新增GPU下，拆开三件事：已有thinking正文是否存在可读出的完整答案、最终生成是否未交付、旧严格终端格式是否误拒合法数学对象。所有新结果独立存放，不修改旧224输出、旧27/32或13/32主分。

LastBox只是一个固定读出策略，不是所有可能读出的数学上界；本任务不计算“用Gold从全部候选挑最优”的oracle。它更不能证明推理过程中早期已知正确答案，或为更早checkpoint提供未来boxed信息。

## 四个Gold-blind选择策略

| 策略 | 决定规则 | 如何解释 |
|---|---|---|
| LastBox | 选择最后一个完整boxed对象；后面还有未闭合boxed时弃权 | 纯位置基线，不保证这个候选为真 |
| LastFinalAnswer | 选择最后一个显式Final Answer/最终答案标签的完整对象 | 纯显式交付标签，不抓任意尾数字 |
| FirstCompleteAnswer | 按原文位置选择首个完整boxed/显式最终对象 | 不是“首个正确答案”或ECN oracle |
| ConservativeFinal | 仅在显式候选表面指纹一致时选择，表面不同则弃权 | 表面不同不是已证明的逻辑冲突；可能错把等价代数式标ambiguous |

精确有理数表面如1/2与0.5可消除简单歧义，但不声称解决一般代数等价性或语义作用域。多段反思中的旧候选、子目标、最终答案身份仍需独立解释；不能因LastBox得分高就认定每一段proof可信。

## 新解析契约

- 完整boxed之后的普通单位/名词不导致拒绝，不为已知C006或某个Gold硬编码。
- 保留整个分数、元组/向量、区间端点/开闭性；相邻多个裸boxed分量不当作完整元组的最后一个坐标。
- 对显式or/either/也许/不确定、未闭合结构、缺候选、无法解析的自然语言明确返回ambiguous/incomplete/unknown。
- 不执行任意Python；数学评价在独立CPU子进程用Math-Verify0.9.0，20秒硬限。Gold只进入数学评价，不进入选择器。
- 区间/元组/行向量存在记号歧义，解析不自动赋予题目语义。已支持的区间闭合端点与向量顺序有通用测试，其他形式仍可能返回数学解析unknown。

## 先测试冻结，再读取实际文本

本地通用39项结构/选段测试通过，未读取新D0的旧文本选择结果；首次测试发现or7/或perhaps7缺空格边界，已在通用测试中修正。18项独立数学smoke须在已有Math-Verify0.9.0的远程CPU执行，不能用本地无后端冒称通过。

三步命令（由主任务使用现有合法CPU环境，不能给此模块接GPU）：

```text
python -B test_d0_answer_extract.py --require-backend --output D0_REMOTE_CPU_TEST.json
python -B prepare_d0_audit.py --freeze-contract D0_REMOTE_CPU_TEST.json
python -B prepare_d0_audit.py
```

freeze记录源码和非bank测试hash，在任何新实际选择/评分前形成。prepare只读旧bank_visible和224个原answer_text，校验原DELIVERY_MANIFEST的SHA；不读bank_evaluation_only。

输出32 thinking＋224生成文本，共256个文本；每个4策略共1024相关选择。不能当1024个独立问题，更不能把七方法/多个checkpoint当不同题。

仅在选择已冻结后离线评分：

```text
python -B score_d0_audit.py --root NEW_D0_ROOT --evaluation-file OLD_BANK_EVALUATION_ONLY.jsonl
```

CPU数学比较可按完全相同的surface/Gold字节去重，结果复用只节省CPU，不改变任何候选选择。报告selected、abstained、selected_correct、selected_wrong、backend_unknown与每32题成功率；弃权是策略没有交付，不是模型数学为假的证明。

## 原生执行器交接边界

D0读的是完整已结束/触顶的历史文本。不得把其未来LastBox、最终正确性或Gold用于D1在线触发，也不把该离线读出当原生继续推理或SCOPE-Rebase收益。

本D0子任务没有调用凭据/远程/GPU，没有重跑任何模型。数学backend的实际远程验收、选择冻结、实际准备与最终评分状态由新产物和主任务回执分别确认；未运行就保持待执行。
