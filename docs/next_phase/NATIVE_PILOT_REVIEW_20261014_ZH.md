# 完整native审查与正式参照决策

范围为共同29个诊断题、两预算58个真实请求；不涉及新盲测或学到的策略性能。

| 名义预算 | native正确 | boxed正确 | native未闭合thinking | native已闭合但final截断 | native触顶 |
|---|---:|---:|---:|---:|---:|
| 8192 | 13/29 | 17/29 | 14 | 2 | 16 |
| 16384 | 18/29 | 22/29 | 11 | 0 | 11 |

每个预算native相对boxed均损失4题、收益0，差−13.79pp；问题Bootstrap区间[−27.59,−3.45]pp，精确双侧McNemar p=.125。小样本离散检验未给出强总体优势/劣势证据。native自然EOS完成的子集均被冻结grader判正确，但这是按完成事件选择的子集，不能据此推断整体可靠性。

独立再审：全部58请求重评分一致；29题两native预算的完整生成prefix相同。两例8k已闭合thinking分别用了8084/7669 tokens，随后300/715 tokens最终回答仍未完成，被总cap8384截断。16k沿同一完整prefix继续至9962/8847 tokens后得到正确完整final。Gold的1和800另用符号投影/交点证明、13824个有序除数组合枚举及stars-bars独立核对。原始失败保持0，不把部分thought回填成成功。

native与boxed增加预算都改善5题，集合仅重合clock问题一题；native另4个改善在boxed8k已正确。boxed16k另外救回的coin/beads/hexagon/polynomial四题，native16k仍未闭合。这说明“+5题”的数值相同并不代表相同机制。native/boxed还同时改变cue、预算分配和闭合后的随机数域，故不是cue-only因果估计。

决策：固定**boxed有界FULL16384**作为后续共同操作性参考。它比8k多5题且无反向损失，有独立精确答案控制；但配对p=.0625、29题且11题触顶，不称总体显著改善或自然无限FULL。12288未实测，不采用。当前信号支持做COMMIT/FULL风险准入的正式开发，复杂多动作要等M1实际质量—成本门槛。

科学review绑定预算、噪声、native、完整pilot审计、修复审计与机制审计六份实际证据及fresh GPU报告。五组接口验收通过：主candidate实际128/8192/16384，16k peak allocated14.63GiB；DTSR三个实际prefix中2个rating解析、1个解释性输出拒绝，全部parent KV/续写控制通过；REFRAIN三个prefix/reader身份通过；ASAG长prefix重复/parent KV通过，16k peak17.03GiB。ASAG512-token真实集成没有ATP/probe，只验证普通路径；真实模型四动作覆盖与完整任务成绩仍未得到。

正式main协议SHA `423f8b632d628443d9a4517bb8bb280714940776e1a4ddf2fbe166593ce323f2`；只放行开发/选择。当前两个实际worker开始530题development bank，然后按依赖推进265题selection、训练及12方法×265题M1。795独立校准、1062盲测、跨模型、非数学及条件Serving等完整路线仍未完成。
