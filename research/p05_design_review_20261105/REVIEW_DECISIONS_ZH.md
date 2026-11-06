# 四项补充的核查与本轮实验决定

2026-11-05。用户要求先结合自己的判断把设计做好，再开展实验。本轮采用“核对具体实现与数学前提 → CPU验收 → 冻结短试 → 一次有限GPU实验”的顺序；不恢复旧18周队列，不训练模型或展开全部候选组合。最终实际状态以RUN_STATUS_ZH.md为准。

## 1. 四项建议如何处理

| 建议 | 采纳部分 | 必须修正的部分 |
|---|---|---|
| OneLine/工作帧与退役旧状态互补 | 保留2×2主效应/交互及Late/Early路径比较，观察旧值/错绑兼容签名 | 不预设互补必然存在；普通OneLine不等于强制y=的工作帧；交互不证明两个错误源正交或特定induction head被触发 |
| 扩展机制候选 | 在新实验前固定完整的Z/Y角色与去重规则 | 一个readout logits只给首token分布；完整整数+换行需额外teacher forcing，Y前缀另建分支。W中的g(f(x_new))也可能是错值，不能叫true |
| crop尾部回滚 | 在HF4.55.2全注意力DynamicCache上，裁掉全部候选尾部可复用原前缀，避免整个prefix deepcopy/re-prefill | crop逐层更新metadata；不恢复logits、RNG、输入、停止/processor状态；不保证整个拒绝流程O(1)、显存被释放或W最终正确率绝对零伤害 |
| 自然值溯源 | 采用数值/表达式候选索引，减少人工找片段的成本 | 数字相等不等于实体相同，更不等于有向依赖；所有候选待语义复核。不能以该图自动决定删除/失效闭包 |

## 2. 交互项的正确解释

令F/E分别为Full/Whole-Early，D/L为Direct/OneLine，本轮描述性准确率交互为：

\[
I=(Acc_{E,L}-Acc_{E,D})-(Acc_{F,L}-Acc_{F,D}).
\]

在固定16个受控状态上，它描述两个策略因子的组合效果，不是自然总体的效应估计，更不是induction head因果定位。二元结果的天花板/地板、格式服从、输出长度和同一题的相关性都可能影响该数。

推理中“写y=导致复制旧y”是可测假说。原始 [In-context Learning and Induction Heads](https://arxiv.org/abs/2209.11895)对小attention-only模型有强因果证据，对含MLP的大模型更多是关联证据；不能直接推出Qwen3遇到任何y=都瞬间调用同一电路。若要进一步命名机制，还需要变量名/数值/顺序/无关项控制，以及选择性干预。

本轮OneLine只是普通的一行必要计算要求，并未强制y=。离线Y probe是在另一个分支显式追加y=，它不等于真实OneLine生成中已经出现的那个时刻。

## 3. 候选评分改成可计费的两个条件族

原P0的30\n和33\n首token相同，但完整概率不同；旧run140次去重候选评分实际增加140次forward、300个teacher-forced输入token。新实验不再称零额外成本。

对同一case，Z角色为：原题可信终值、旧终值、按修订值完整重算的终值、把新根直接代入外层公式的skip签名。Y角色为：原题可信y、旧y、按修订值推出的y、把新根误作y的签名。它们不是八个必然不同的数字；相同数值/编码去重，角色别名保留，别名之间margin记NA。

完整候选定义为canonical整数加固定换行：

\[
\log p(c_1\ldots c_m\mid s)=\sum_{j=1}^m\log p(c_j\mid s,c_{<j}).
\]

Z分支强制最终答案读出前缀，Y分支强制y读出前缀，各自建cache/readout并计费。这些都是**自由生成前的条件诊断**，不是模型完成OneLine后的真实状态；候选终止符偏好和长度也记录。既不把小候选集当全部答案空间，也不承诺16题有很高统计效力。

先完成自由生成，再把只供评价的候选值放进隔离评分分支。主正确率来自冻结文本解析器；不能用候选评分挑自由答案或泄露Gold。

## 4. crop能省什么，不能保证什么

HF4.55.2的DynamicLayer.crop对K/V取前缀view，Cache层逐层调用。[固定版本源码](https://github.com/huggingface/transformers/blob/v4.55.2/src/transformers/cache_utils.py)

本轮5个seed的tiny Qwen3 CPU控制中，crop后保留前缀K/V与未走拒绝分支的同路径control完全相同，随后同输入readout logits也完全相同。这是一个有用的工程正结果。裁尾与删除中间行不同：只要所有受R影响的后继都裁掉，前缀没有因果读取未来R。

但裁剪的张量仍共享post-R storage，容量未缩；固定层数时crop元数据工作可不随序列长增长，整体仍逐层操作。解码状态还需保存或恢复：pre-R logits、RNG、input_ids、mask/position/cache_position、grammar/repetition/stop状态等。没有保存pre-R logits时，可能需要重新喂最后一个可信token以得到下一分布。

若恢复后采取与参考完全相同的解码操作，可讨论状态非干扰；若为避免重复错误R而改提示/禁止采样/跳到答案，策略已经改变，不能从cache等价直接推出W零伤害。核验器误判、旧前缀本来不可信、多token触发边界、滑窗/量化/其他cache实现也要单独处理。本五臂不集成G/crop策略，其CPU结果不冒充W算法效果。

## 5. 数值来源图的正确定位

本轮在固定100题上运行了确定性候选提取，并验证source/row/question/trace hash，保留15条cap。候选统计由 `P1_heuristic_numeric_candidate_summary.json` 给出，**全部仍为UNKNOWN_UNREVIEWED**。

数值溯源可作为索引，但以下情况阻止它直接成为sound依赖图：同值不同实体/单位、分支或时间变化、否定/引用/备选数值、隐含代词、等价表达、题干同值的新派生量、规则本身被修订。题干中的选项、条件值和假设也不能全部当作当前永久真值。

较可靠的自然桥梁应保留实体/单位/作用域/极性/来源跨度，以明确代入或可核验等式作局部证据；其余保持unknown。先测覆盖与误边，不根据启发式闭包自动破坏原状态。本轮没有完成P1百题语义标注，也没有报告自然复发率。

## 6. 本轮五臂短试的边界

采用已冻结16例和固定顺序，运行FullDirect、FullOneLine、WholeEarlyDirect、WholeEarlyOneLine、WholeLateOneLine。新user后续消息统一要求按原题核算、不预设修订正确；Direct预填最终答案标记，OneLine不预填计算结果。新协议的Full必须本轮重测，不能与旧P0的7/16直接作算法提升比较。

共同控制是同checkpoint/FP16/eager、相同prefix和原位置、相同case/读出内的B屏蔽地址；Gold/组别只用于离线评价。E01/C01/W01做完整接口控制，其余不冒称全部控制通过。模型与源哈希、时间、peak、额外前缀和候选成本全部记录。

草案累计单卡预算≤300秒；启动冻结时为清理预留余量，实际worker270秒、外层timeout285秒及5秒强杀余量；含加载/哈希/失败。按固定顺序保留完整五臂primary配对，诊断不完整单列，不挑短题补齐、不按好坏结果续跑。P-only/P+R基础能力与自然P1语义标注不是这80输出中的附带已完成项，后续仍需分开。

结果可为正、负或无增量：若Full+OneLine足够，就先采用便宜文本策略；若Late/Early在同条件下有任务差别，才保留历史重编码的条件性作用。无论哪种，都不直接推出两个正交错误源、KV不可替代或已经形成新算法的正式benchmark收益。
