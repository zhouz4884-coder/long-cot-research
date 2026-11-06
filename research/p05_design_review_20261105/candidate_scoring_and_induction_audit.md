# P0.5：induction推断与固定候选评分审查

2026-11-05。只读旧P0源/结果、核验原始文献并运行一次随机tiny Qwen3的CPU接口控制；未运行真实模型、GPU或远程任务。**结论：`y=`不保证抄旧值；工作帧与mask可作互补假说，不能预称正交双保险。单个readout logits只提供下一个token的分布，无法零额外forward恢复一般多token候选的完整logP。**

## 1. induction/binding文献实际支持的范围

[Olsson等，In-context Learning and Induction Heads，2022，作者原文](https://transformer-circuits.pub/2022/in-context-learning-and-induction-heads/index.html)研究`[A][B]…[A]`提高再次输出B的概率，区分prefix matching与copying；小attention-only模型的机制证据强，对大模型的一般化论证更间接。它没有证明Qwen3在看到`y=`时必然复制旧`y`，也没有排除算术、关系绑定或多个head的竞争。

[Feng/Steinhardt，ICLR2024 Binding ID](https://proceedings.iclr.cc/paper_files/paper/2024/hash/9d1b7fc578c0d2d6431fc26d736ecaf3-Abstract-Conference.html)给出entity–attribute绑定的干预证据；[Gur-Arieh等，ICLR2026 Mixing Mechanisms](https://proceedings.iclr.cc/paper_files/paper/2026/hash/2eeff35664016c7f0f8aa704f0d9a83e-Abstract-Conference.html)则表明位置、词汇与reflexive检索可混合，且依任务/位置改变。可将“重复`y=`后的旧值复制倾向”列为候选行为，但要定位induction机制仍需反事实、activation/路径干预以及非复制对照。

当前拟跑的五臂使用**普通OneLine指令**，不强制自由生成以`y=`开头。离线Y probe如果追加`y =`，也是另一个条件查询，不是对自由OneLine轨迹已经触发induction的证明。交互项或二者组合优于单项只说明当前设置下的联合效果；有限样本不能单独建立两个错误源“正交”、安全性或创新。

## 2. 旧P0的实际评分语义与成本

源：`direction_selection_20261105/real_model_p0.py`，SHA256 `246219aee9774fae0966c7663c765daf3dba2f1df68bc054b539a4dd5d64331b`，`score_candidates`第393–418行。旧readout是`\n按题目原始定义核算，最终 z=`。候选来自离线评价字段，去重后编码`str(value)+'\n'`：首token用readout末位logits；其余项用**独立深拷贝cache**喂入候选`ids[:-1]`取得。不是从一个logits向量切片得到所有数字的概率。

原run配套tokenizer为`Qwen2TokenizerFast`（Qwen3-4B使用此类），模型manifest SHA `37ff9857bb53edf35d5c80bfa0c078b1cdb8d5e5aa864115d153e237cb854511`。逐条重数16例×5臂的冻结候选，得到：

- 140条去重完整候选：120条长3 token、20条长4 token，均包括终止换行。
- 相应额外candidate forward **140次**、teacher-forced输入 **300 token**；不含shared prefill、readout、自由生成或控制。
- 有40对不同候选共享首token。E01 Full中`30\n=[18,15,198]`、`33\n=[18,18,198]`：首token logP均为−0.06256946，完整logP却为−12.43949731和−9.17715684。因此首token margin=0不代表完整答案偏好相同。

证据与全部碰撞对：`candidate_scoring_cpu_evidence.json`。这是旧实际token ID/评分的重数，不是对线上tokenizer主分支漂移后的推测。

## 3. 完整序列、首token与条件前缀必须分开

给定固定上下文C及候选token串\(a_{1:m}\)：

\[
\log p(a_{1:m}\mid C)=\sum_{i=1}^m\log p(a_i\mid C,a_{<i}).
\]

一个readout向量仅包含第一项。除非候选本身单token，或所有必要的候选分支条件分布已由其他工作完整保存，否则后续项不能由首分布推回。即使数值只有一token，若要求“这个整数结束”，终止符仍可能需要额外条件分布。

旧scorer接口的可执行成本是：K条唯一候选中，长度大于1的每条另做一次forward，输入长\(m_k-1\)，总候选输入token为\(\sum_k(m_k-1)\)。可以batch候选或用trie共享公共前缀，但只是减少调用/重复计算，并不是零forward或零FLOPs；须同时记录batch、有效/补齐token和实际时间。

`p(y_value | C, 'y =')`与`p(z_value | C, '最终答案：')`不是同一条件分布。Y/Z query都需要各自readout forward及分支cache；只可共享此前的只读C。拿z前缀的logits给y数值评分，测的是“把该数字作为z输出”，不能解释为模型内部y的信念。

CPU随机tiny控制（Torch2.11+cpu/Transformers5.4，不是目标GPU版本复现）显示：

- 同一上下文下30/33首token项完全相同，完整logP不同；cached评分与整串dense参考最大差`2.93e-8`。
- 只改变模拟Y/Z前缀的一个fixture token，末位logits最大差0.107805。
- fixture前缀ID为任意受控ID，**不是实际Qwen tokenizer的`y=`/`z=`编码**；实际旧候选数字ID取自冻结结果。

复现命令见 `candidate_scoring_cpu_audit.py --help`；只做CPU接口验证，不证明真实模型的机制或效果。

## 4. 固定四角色，允许同值别名；W组不把revision叫true

建议用两组各四个**角色**，而非强凑四个不同数字：

| 分支 | 冻结角色 | 值的定义（只供离线评分） |
|---|---|---|
| Z query | trusted_final | 原题规则下的正确最终值 |
| Z query | old_final | 原旧分支B声称的最终值 |
| Z query | revision_consistent_final | 按R的根值完整传播得到的终值；W中未必正确 |
| Z query | skip_signature | 将R根值直接代进下游g的结果，仅是预定义错代签名 |
| Y query | trusted_y | 原题规则下正确的中间y |
| Y query | old_y | 旧B根值推出/旧B声称的y，二者不一致时需预声明采用哪一个 |
| Y query | revision_consistent_y | 按R根值经f得到的y；不自动称true |
| Y query | root_misbind | R根值本身，作为把x放进y槽位的候选签名 |

本次旧16例中B内部计算一致，已用精确AST生成 `fixed_candidate_roles.json`，包括每例角色值、规范字符串及别名。Z/Y各合计44条唯一规范字符串（按16例加总，不跨case混去重）：

- E02：Z角色值38/30/38/56，Y为19/15/19/28。
- W02：Z为21/21/19/67，Y为9/9/8/32，明确保留旧值正确而修订错误的情况。
- C02：Z为16/16/16/70，Y为6/6/6/24。前三角色同值，不能据此分辨三种机制。

规范格式固定`str(int(value))+'\n'`，不带多余正号/前导零；记录实际token ID并按规范token串再次去重。相同字符串只评分一次，保留全部角色alias；同值角色间margin记NA。不得把别名重复放入softmax导致概率质量重复计算，也不得把候选归一化分布叫全词表校准概率。

同首ID不同完整串则保留两条完整候选；其首token margin标`first_token_collision/unidentifiable`，不能拿该0当负结果。完整margin使用稳定log-softmax逐token求和，保留原始sum、不默认长度归一化；固定终止符使`3\n`与`30\n`成为不同完整事件。首token指标单列，不能改名“完整答案logP”。

## 5. 这轮≤5 GPU-min的可执行修订

1. **保留五臂自由生成为主行为测量。** Direct与普通OneLine格式各预冻结，固定解析并保留原文；不把Y强制scaffold悄悄混入OneLine定义。
2. **Z/Y辅助probe分别建分支。** 从指定的同一臂上下文快照各自接预声明scaffold，readout实际token及起点留档；不能从Z向量无代价得到Y。probe即使相同最后token，也要核前缀整体是否相同。若预算不足，预先保留Z、删去整个Y辅助面板，不按case效果选择性计算。
3. **完整候选计入预算。** 这套角色表每个臂44条Z候选；若全部实际编码均需续传，五臂将有220次候选分支forward。Y同规模额外220次；另外还需Y/Z readout。最终以实际编码长度/批处理计账，不能用单次140次旧成本直接宣称新设计同价。
4. **分离生成和评价cache。** 所有自由输出先完成；Z/Y/每候选都深拷贝，或从同一只读快照恢复。gold、角色值只进入离线评分，不能构造工作帧、触发mask或选择输出。
5. **工程门槛先验收。** tokenizer分段/终止符、cache不变性、cached-vs-dense完整评分、首token碰撞、Y/Z各自前缀、same-input no-op、五臂的mask禁读与causal限制必须通过。硬deadline包含hash/load、probe、评分与控制；超时保留部分、退出，不追加模型重试。

结果解释限于预声明样例/接口：可以报告工作帧与mask的主效应/交互和候选偏好变化，但不承诺统计灵敏度，不由交互直接宣布“两个独立错误源”或induction机制已定位。完整数值logP是**给定强制query的条件测量**，不是自由生成过程中逐步信念的无扰动读取。
