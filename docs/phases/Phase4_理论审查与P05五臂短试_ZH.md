# Phase 4：模型理论、候选图与P0.5五臂短试

状态：**理论/CPU控制与本轮16题primary已完成；辅助诊断仅8题，按预算停止。没有正式算法benchmark或新训练结果。** 更新：2026-11-06。

## 研究问题

哪些现象能归因于读出/计算组织，哪些只与数字签名兼容？普通OneLine、旧段WholeEarly屏蔽、同可见信息下Late/Early分别贡献什么？版本/依赖管理与转移锚点训练的数学前提是否充分？

## 输入与协议

文献/理论审查结合固定原16例、新用户意见和一手近邻；CPU分析包括有界程序、梯度代数、观察签名、候选溯源与crop状态恢复。真实P0.5仍为Qwen3-4B、单RTX3090、FP16/eager，但关闭旧人工assistant记录，添加新的核算user-turn；Direct预填最终答案scaffold，OneLine不预填计算结果。

冻结解析器SHA为`c2bc053b66778288f524d46f4353e825b1ee654d829027bd02b1cb3173255eed`。自由生成先完成，候选值仅在后续隔离评分分支出现；每臂上限64新token，按固定顺序保留全部完成配对，不按得分补题。

## 实际动作

1. 完成模型绑定/阶段假说、版本前沿与转移anchor的一手近邻及数学审查；保存有界/代数反例，未进行模型训练。
2. 冻结历史P1 100题清单；只做CPU词法候选提取和标注约束，没有语义发生率。
3. 完成渲染、mask、分支缓存、crop与候选概率计费的CPU验收和独立源码审查。
4. 完成新五臂16×5=80自由输出；独立重应用冻结parser及整数oracle、逐条阅读全部原文、复核实际成本与条件probe。

## 数据与结论

| 本轮臂 | 正确/16 | E/8 | C/4 | W/4 | 未解析 | 64-token cap |
|---|---:|---:|---:|---:|---:|---:|
| FullDirect | 8 | 0 | 4 | 4 | 0 | 0 |
| FullOneLine | 11 | 5 | 3 | 3 | 4 | 5 |
| WholeEarlyDirect | 0 | 0 | 0 | 0 | 0 | 0 |
| WholeEarlyOneLine | 12 | 6 | 3 | 3 | 2 | 4 |
| WholeLateOneLine | 8 | 4 | 2 | 2 | 5 | 7 |

描述性交互`(12−0−11+8)/16=0.5625`很大，但联合臂仅比FullOneLine净多1题。E07/C04是FullOneLine已写对z、却被cap截在最终标记的交付修复；C03从正确30变错误56。Late→Early四修复中E04/E07/C04同样涉及cap/解析，W03是已交付49→121。不能称已证明消除旧值复制或两个正交神经错误源。

E01不能因前面出现正确z而改分；E08未完成RHS不能补出82；W04到80被截后续是否会减1未知，不补成79，也不声称永久算错。全部主分保留原冻结口径。

launcher267.5468秒=**4.4591单卡分钟**；worker264.3589秒；2618自由生成token，OneLine三臂2520、Direct两臂98。2961次forward、累计16336输入token，控制/probe/共享前缀均计费；阶段计时相互包含，不相加当总成本。加载后观察峰值allocated约9.07GiB，保留完整cache槽位，无节省显存主张。

诊断仅固定前8题完成，E4/C2/W2；80个Y/Z条件面板、220个去重完整候选。完整整数＋换行logP与首token边际分开，Y=`y =`是生成前状态上的强制query，不是OneLine生成后的自然中间信念。完整控制bundle仅E01/C01/W01，其余13题不冒称全部控制PASS。

理论/CPU层：三种anchor不保证正交；同KL只固定同支持集Shannon熵，不固定ESS；同LoRA参数norm不固定有效ΔW/策略KL；归一化更新后不继承原Gibbs线性最优性；正确prop监督不自动保护W。七项代数控制通过，仍非真实模型梯度/训练成绩。

自然候选层：固定100题保留15条cap，提取12560条数值重现候选，全部语义状态UNKNOWN_UNREVIEWED；10885条的目标前已有多个同值源单元。没有gold依赖图、自然复发率或自动闭包触发器。

## 失败、限制与可证伪猜想

普通OneLine多数从原题重新展开，当前增量可能来自计算组织、格式与预算交付；WholeEarlyDirect的严重退化足以制造大正交互。阶段指针/induction只是候选解释，没有head定位。原16例无独立r与一般合流DAG，也不代表自然长链。

可检验猜想收紧为：在提供相同核验信息、目标与父值后，版本一致/局部前沿约束能否优于同样简短的普通子目标提示。若优势只由更少文字或cap导致，则不主张新的推理能力/KV机制；缓存操作后置。

## 下一门槛

进入[Phase 5](Phase5_候选算法与公平基线_计划_ZH.md)只表示准备候选算法与强基线，不表示本轮已实现该算法。先比较同信息、同工具、同输出契约和总预算的简短提示/子目标/版本前沿；P1语义审查与P-only/P+R能力仍需独立完成。当前不补齐诊断、不追加旧run token、不训练、不铺正式大矩阵。

## 证据路径

- [本轮状态](../../research/p05_design_review_20261105/RUN_STATUS_ZH.md)、[冻结协议](../../research/p05_design_review_20261105/P05_PROTOCOL_DRAFT_20261105.json)。
- [独立主分析](../../research/p05_design_review_20261105/PRIMARY_P05_ANALYSIS_ZH.md)、[完整JSON](../../research/p05_design_review_20261105/PRIMARY_P05_ANALYSIS.json)、[原始run summary](../../research/p05_design_review_20261105/p05_five_arm_01/summary.json)。
- [算法/模型理论入口](../../research/algorithm_mechanism_20261105/README.md)、[转移anchor数学审查](../../research/algorithm_mechanism_20261105/transition_anchor_math_audit.md)、[VTFR形式审查](../../research/algorithm_mechanism_20261105/vtfr_formal_audit.md)。
- [固定P1清单](../../research/next_design_20261105/P1_sampling_manifest.json)、[数值溯源审查](../../research/p05_design_review_20261105/numeric_provenance_dependency_audit.md)。
