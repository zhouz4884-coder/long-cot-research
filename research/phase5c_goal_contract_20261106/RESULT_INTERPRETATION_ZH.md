# Phase5-C独立解释：当前组合NO-GO，读出阶段与未交付是重要线索

2026-11-06。只读重数统一评分与原始记录；未重评分、修改算法/数据或新增GPU。**当前候选未过扩大门槛，应暂停扩模型/数据集。失分主要表现为触顶和未满足交付契约，不能把13/32直接解释成数学能力下降，也不能把它说成父边界充分性理论已经被证伪。**

## 1. 独立重数

224/224结果、32个七方法完整且grade已解决的case，missing/unknown均0。逐条原始文件SHA与grades保存值224项相符；以下计数、全部6组Projected配对和精确两侧p值与summary一致。总EOS115、cap109。

| 方法 | 正确/32 | EOS | cap | 未解析 |
|---|---:|---:|---:|---:|
| ForcedBoxCue | 27 | 29 | 3 | 4 |
| FullContinue | 15 | 17 | 15 | 16 |
| FullContract | 14 | 14 | 18 | 18 |
| FullContractEvidence | 18 | 20 | 12 | 13 |
| TailContract | 11 | 11 | 21 | 21 |
| ProjectedContractEvidence | 13 | 14 | 18 | 19 |
| RestartP | 8 | 10 | 22 | 23 |

Projected相对Forced为0胜14负18平，exact McNemar p=0.00012207；相对同packet的FullContractEvidence为2胜7负23平，p=0.1796875。其余相对FullContinue为1胜3负、FullContract为3胜4负、Tail为4胜2负、Restart为5胜0负。统计仅是固定开发历史题池上的探索性配对，无多重校正，不作自然总体推断。

最强aggregate baseline为Forced的27/32，Projected13/32，净−14，未达到预声明净≥2继续线。不能只展示它胜过Restart/Tail的子比较。

## 2. 失分形式说明什么

Projected的19条失分**全部是output_unparsed**：18条384-token cap，1条EOS但终端格式不符合契约；没有“已经提取出完整答案、再被数学后台判错”的行。13/14 EOS条件成绩不是总体正确率，更不能据此排除未交付病例给候选补分。

实现上，T作为转义后的引用放入新的`enable_thinking=False`聊天模板；FullContinue是给定历史的自由新回复，不是继续原始热cache的native think阶段。因此这里的“阶段/交付”指输入前缀与新回复策略，不是原生长链内部阶段的因果识别。

独立核对32个Forced/FullContinue的messages完全相同，仅Forced追加了assistant open-box prefill与对应评分前缀。Forced对FullContinue为12胜0负20平，exact p=0.00048828125，输出总token从10647降为1480。此事实与“直接进入终局答案填充，比自由续写容易避免重新解题/截断”的解释相符；它没有识别内部stage pointer、注意力垃圾淹没或特定神经电路。

但阶段解释不能抹掉同阶段的负结果：FullContractEvidence与Projected共享相同未核验packet，均无open-box，Projected仍2修复7伤害、净−5。可能是删掉完整历史后候选摘录不充分/噪声，或引发更长重算；当前设计不能把信息丢失、输出策略与截断的贡献定量拆开。输入token虽减少82.57%，输出token却比FullContractEvidence增加7.42%；不能只报输入压缩当作完整效率收益，也不能平分物理batch wall冒充方法延迟。

## 3. 固定规则选取的原文检查

先按bank rank选择：①Forced正确而Projected错误的首例；②Projected正确而FullContractEvidence错误的首例；重复病例不重复挑选。另检查Projected全部“EOS且失分”病例（只有1条）。没有按解释方便程度替换病例。

- **C002，首个伤害例**：题目求只用0/2表示的最小30倍数。Forced6 tokens输出完整boxed2220；FullContractEvidence32 tokens也完整交付2220。Projected从整除规则和小数枚举重新展开，384 tokens截在“2220: Sum”；FullContinue正文已写出2220，却又开始证明最小性，384 tokens截断，未正式交付。这是本固定长度下的完整答案交付差异，不应把原文描述为模型都不会求2220。
- **C005，首个修复例**：题目问抛物线x=y²−4y−1有几个y截距。FullContractEvidence已算出两根2±√5、说有两个截距，却在384 tokens截为`\boxed{2`；Projected301 tokens正常EOS并完整boxed2；Forced3 tokens完成boxed2。这个修复也不单独证明数学求解能力提高，两条自由生成的关键计算均正确。
- **C006，唯一Projected EOS失分**：正文算650/1170=5/9，再乘18得到10，末句为`...$\boxed{10}$ representatives.`。冻结grader以nonterminal_boxed_answer拒绝boxed后的名词。这是严格终端接口的一项限制，不是原文里的算术错误；当前分数保留，不事后给它救分。今后的通用提取契约若调整，应独立冻结、全臂同用并单列新结果。

这些只解释所选病例，未把全部18个cap逐条归因为相同原因。cap既可能来自冗长正确重算，也可能来自思路/证据不足，不能仅凭“cap”认定所有中间推导都正确。

## 4. 对当前方法的结论

本轮实现的是题干模式目标提示、候选文本摘录与投影；protocol明确true_G=false、certified_boundary=false，不能把摘录叫已认证父边界，也不能称已经实现“排除假冲突的GC-PBP”。目标提示仅少量类型可判，其余unknown；不能从当前结果声称可靠目标契约已失败或已成功。

结论是：**当前候选证据投影＋自由终局续写组合NO-GO扩模型；将“open-box相位/交付长度”和“投影保留的证据是否足够”作为尚待区分的两个问题。** 保留负结果，不把最强baseline改成较弱的Restart或Tail，不从未解析中挑正确数字重算成绩。

## 5. 下一最小区分检查——仅待跑设计

可考虑同阶段2×2：固定同一个P、T、K、未核验packet、系统要求、模型/评分和预声明保护顶；仅改变两因素：

| 输入 | 自由终局续写 | 同一open-box终局预填 |
|---|---|---|
| 完整历史＋K＋同packet | 待跑匹配条件 | 待跑 |
| 投影摘录＋K＋同packet | 待跑匹配条件 | 待跑 |

四格应在同一个新冻结协议下比较；当前已观察的32题若复用，只是机制开发复查，不能当独立确认集。若两个open-box格都改善且差距消失，阶段/交付解释更受支持；若投影在同一open-box条件下仍受损，摘录充分性需要重审。任何结果都不能自动给未实现G记功。

本文件没有启动该2×2，没有新增模型成绩，也没有改当前384-token输出后缀或当前分数。依据：scoring/summary.json、scoring/grades.jsonl、原224raw及jobs.json消息/packet一致性核对。
