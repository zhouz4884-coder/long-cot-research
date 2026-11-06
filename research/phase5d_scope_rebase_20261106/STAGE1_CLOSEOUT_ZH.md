# Phase5-D第一批收尾：方法重构、D0审计与D1原生准入

2026-11-06。**本批D0、必要CPU内核、D1与调度定位控制均已完成。允许使用原生Continue与调度匹配的冷重放参考；尚未验证SCOPE-Rebase自然修复收益。D2–D5没有被冒充已完成。**

## 1. 本批想解决什么

总目标仍是长思维链最终正确率和可重复的强baseline增量。上一阶段的384终局读出大量触顶、引用历史不是native继续，也缺真实G；继续扩大这个矩阵不会直接回答“有效纠错”问题。

本批首先修正测量基础，再完善方法：

1. 旧思考是否已有可直接读出的答案，额外生成是否必要？
2. 真实assistant thinking的token、RNG、KV和续写能否被正确记录/重建？
3. 撤回哪条证明、保住哪个结论、退役哪些文本，能否由实际可核验的支持语义决定？

用户输入的zip五文件和粘贴意见均完整读取、原样归档。其执行清单作为参考，不当作已实现功能/效果或高于用户的命令。

## 2. 方法取舍与创新候选

主线保留**作用域限定的完整支持核验＋多重依据保护＋必要的原生状态重建**，工作名SCOPE-Rebase。隔离反思是可接入该内核的结构备选，VOI/训练后置。

近邻已包含依赖回退、Judge、保留有效事实和投机验证，不能仅组合换名。更值得检验的差异是：某个未受影响前驱是否真的覆盖整个结论，反驳证据是否针对当前scope/版本/论证，是否因此减少错误保留、误撤与过度回退。

本轮有两项重要修正：

- 经典逆否析取公式本身可以成立；它不提供唯一错误来源。支持失效不等于结论为假。
- `lost_support`可为空而坏proof文本非空。结论有替代证明时应保住结论，但失效推导的文本仍可能影响native续写；逻辑更新和神经文本重建要分开。

若完整目标已被工具认证，必须比较同工具直接交付；真正需要修复价值的是目标尚未解决、局部合法进展仍值得保留的状态。

详见[方法规格与创新假设](METHOD_SPEC_AND_INNOVATION_ZH.md)、[取舍/设计](DESIGN_DECISION_ZH.md)、[原始文献审查](ADVISOR_AND_PRIOR_ART_REVIEW_ZH.md)。创新与收益仍待D2/D3实证。

## 3. 实现到了哪里

| 模块 | 已实现/实测 | 不能据此声称 |
|---|---|---|
| Claim/Justification/Challenge/ProofCertificate/EvidenceLedger | scope、实体/版本、许可规则、证书重放、AND/OR最小不动点、矛盾隔离 | 自然语言完整证明自动解析已解决 |
| 受限精确检查 | 有理算术、目标绑定、真算术错误否定、可信约束下claim否定、UNKNOWN | 任意数学/几何/语义G可用 |
| 支持与文本退役 | 多重支持保留、坏proof span即使无lost claim仍触发安全cut候选、规范bridge | 最小成本cut已证明、桥已带来模型质量收益 |
| 原生执行 | True模板、真实token IDs、local RNG、在线cp、EOS/实际context技术界 | 旧历史作为User引用等于native执行 |
| reference replay | 原prompt调度＋逐token观察前缀重放，在8cp通过控制 | 所有设备/长度/cache策略通用零差 |
| 自然修复策略 | 方法规格/待测协议 | 已执行ScopedRebase、隔离反思或取得准确率提升 |

## 4. D0：零GPU的固定读出审计

先用题外通用例冻结新契约：39结构＋18数学CPU检查。再对旧32条thinking及224生成文本应用LastBox、LastFinalAnswer、FirstCompleteAnswer、ConservativeFinal；共256文本/1024相关选择，不是1024独立问题。

Gold只在选择后评分，完全相同surface/Gold的语义查询复用，共43次。没有按Gold选最好候选；旧Phase5-C原分数与330冻结文件完全未改。5146项独立核对通过。

| 固定政策 | 原32 thinking选出 | 匹配Gold | 弃权 |
|---|---:|---:|---:|
| LastBox | 28 | 28 | 4 |
| LastFinalAnswer | 16 | 16 | 16 |
| FirstCompleteAnswer | 27 | 27 | 5 |
| ConservativeFinal | 27 | 27 | 5 |

这说明旧材料中有大量现成答案，必须有简单直接读出baseline；28/32是该固定政策的观测成绩，不是数学真实上界，也不是模型修复收益。标签策略低覆盖还包含表示/解析限制，不能说其余题没有数学答案。

新LastBox下，旧七条件的匹配数分别为Forced28、FullContinue16、FullContract15、FullContractEvidence19、Tail12、Projected14、Restart9（各32）。每项比旧严格主分多1，来自合法单位后缀等交付差异；Tail另有cap前已存在完整boxed值、后续仍未完成的情况。**旧27/13等主分保留，不改成28/14。**

Conservative的表面差异并不证明逻辑矛盾，部分低覆盖来自长标签解析噪声；不能将其冒充真值G。完整旧T包含相对于早期cp的未来，不能用于在线选cp或决定回退。

数据：[D0汇总](d0_scoring/D0_RESULTS.json)、[1024逐项](d0_scoring/D0_scores.jsonl)、[独立审计](D0_Baseline_Audit_ZH.md)。

## 5. CPU支持内核：从示例契约补到实际核验

原提供包的5个示例测试复跑5/5通过，但其证书前置条件未实现。另复现任意非空字符串形成根支持、无关PASS挑战撤证明、lost空时无crop三个集成缺口。原资料也已说明“由外部先验明”，因此它是参考起点，不是已完成自然G。

加固版必须重放证书，绑定结论/规则许可/前提版本/scope/checker；算对一个表达式不代表证明指定subject。初稿发现此缺口后补许可机制，最终版本才验收。真实算术错误可撤其论证/文本，不由此否定仍有别证支持的结论或其正确父事实。

30/30通用测试、200图×3状态＝600次独立agenda闭包/撤回对照通过；无根循环不自证、多根版本原子更新、矛盾隔离、跨域证书拒绝等均覆盖。

可信原题规则/条件能否正确从自然问题取得，仍是外部未解假设。内部issued registry不是密码学签名或Python沙箱；CPU通过不等于自然任务有效。

证据：[实现/边界](support_engine/IMPLEMENTATION_AUDIT_ZH.md)、[30＋600检查](support_engine/CPU_SUPPORT_CHECKS.json)、[上游缺口复现](support_engine/UPSTREAM_GAPS_REPRODUCED.json)。

## 6. D1：8题真正的原生thinking

数据为官方GSM8K test固定commit的8道新接口题，按ID/题干哈希选，旧300题字面重叠0；答案/解答离线分离。GSM8K较基础，本批用于执行器，不用于证明困难Long-CoT修复或多数据集泛化。

既有固定Qwen3-4B资产、TF4.55.2、Torch2.8.0、FP16/SDPA、batch1。按官方thinking建议temperature0.6、top-p0.95、top-k20、min-p0采样，使用独立local RNG，不将greedy确定性调试作为质量协议。

真实True模板以assistant header结束，模型实际产生think open。checkpoint为首次在线观察到的64个生成token后空段边界、且think尚未闭合；不看未来、Gold或“首次答对”。原生prompt/生成IDs不解码后改写重编码，不插新User回合。

主生成到正常EOS，只以实际config的40960上下文容量作技术界，无384/512紧预算。32-token窗口只用于无干预重放诊断，主流仍继续到EOS。

### 实际完成

| 指标 | 结果 |
|---|---:|
| 不同接口题 / 在线检查点 | 8 / 8 |
| 正常EOS / context cap | 8 / 0 |
| 主生成tokens | 15035 |
| 单题长度范围 | 1077–3498 |
| 下一top1匹配 | 8/8 |
| hot/cold下一32采样tokens匹配 | 8/8 |
| hot分支与未干预主流实际未来匹配 | 8/8 |
| 重复cold logits差 | 全部0 |
| 原联合数值准入 | **6/8，原样保留** |

两项未过门：D1_01 maxabs=0.0625超过0.05；D1_06 KL=0.000106234超过1e-4。它们没有实际32-token分叉，不能写成模型生成错误；也不能改阈值/换seed刷PASS。

## 7. 新控制定位了数值差异

先冻结新的调度控制，再对全部8个原cp重放：**按原prompt相同批块，再逐token重放已观察生成前缀**。没有改采样、模型、题目或答案，没有重新采整题。

8/8报告logits差0、KV指纹比较相同、实际32-token列表与原hot/主流未来相同。它支持这些检查点的差异来自bulk-prefill与原逐token执行调度的FP16数值路径，而非前缀、RNG或分支串样。

原6/8仍保留；当前只准入NativeContinue和调度匹配的正确性参考。bulk-prefill“完全等价”捷径、fast crop、旧后缀KV嫁接均未准入。

原D1保存了hot/cold/repeat logits供独立数值复算。新调度控制未保存完整replay logits/KV张量，其0差和KV相同属于绑定源码的执行记录；不能伪称已独立二次下载所有张量复算。实际32-token列表、前缀和ledger已独立核对；它也不证明所有设备/长度或完整未来均无差异。

证据：[原生审计](D1_NATIVE_AUDIT_ZH.md)、[调度控制审计](D1_SCHEDULE_CONTROL_AUDIT_ZH.md)、[限定准入记录](D1_NATIVE_INTERFACE_PASS.json)。

## 8. 数学成绩与成本应怎样读

8题原生最终响应以预冻结LastBox离线评分为8/8、unknown0。**这是未干预Continue基线，零修复动作，不能记作SCOPE-Rebase增益。** 同题的诊断分支不是额外独立题。

原生执行及诊断16.672747单卡分钟，调度控制2.224414，合计18.897161，含模型加载和全部诊断。主轨迹15035 tokens与辅助诊断计算分开计；D0评分墙钟约7.76秒，native离线评分约1.67秒，不混入在线算法开销。

CPU58项仅准入真实模型；原GPU372项、调度178项是完整性核对，不是更多解题样本。模型权重和本地tokenizer副本不重复上传，hash与源可复查。

## 9. 强基线公平吗，最后要即时还是大规模

两者都需要：**正式主结果应新题即时原生生成，并在较大独立题集、多种子/模型/数据源上验证。** 当场保存/冻结原生checkpoint做同状态分支，可以同时保证公平与可复算，不等于重用旧错题冒充新评测。

要分三层：从P比较完整系统；同可见声明/工具比较scope核验；同prefix、同已核验事实/撤回决定比较重建。不给ours隐藏正确父值，也不故意削弱baseline。若工具已认证完整答案，比较同工具直接交付；多采样的Gold-best只作headroom。

D0的完整旧T读出可作题末廉价基线，但不能带未来信息与早期修复作同状态比较。D1八题只验接口；后续先24–32题检自然事件/核验覆盖，再新100–200题初步确认，最终规模按配对差值方差/置信区间规划，而非认为“3模型3数据集”自动足够。

详见[公平性与即时/大规模方案](FAIRNESS_AND_FRESH_VALIDATION_ZH.md)。

## 10. 当前决定与下一门槛

本批目的已完成：旧读出参考、真实证据内核、原生执行器和数值定位控制都交付。方法设计比简单“删分支/塞摘要”更明确，但**自然scope提取/G、真实证据桥接、反思隔离与ScopedRebase端到端收益仍未测**。

下一先测D2自然事件与核验覆盖，不自动上训练或D4大队列。若coverage低，缩小可靠核验范围或检验隔离反思；若同信息/等成本强基线一样好，保留负结果，不追加复杂策略找表面阳性。新指标优先全题正确率、修复/伤害，辅以false accept/reject、UNKNOWN、支持误保/误删、复发和完整成本。

原来的384结果及全部旧Phase不改。下一阶段仍正常EOS、完整执行优先；硬件/上下文异常透明记录，不能又以研究时间截止反复只交partial。

阅读入口：[方法规格](METHOD_SPEC_AND_INNOVATION_ZH.md)、[下一决策](NEXT_DECISION_ZH.md)、[问题与尝试日志](WORKLOG_ZH.md)、[源材料manifest](PROVIDED_KIT_MANIFEST.json)。
