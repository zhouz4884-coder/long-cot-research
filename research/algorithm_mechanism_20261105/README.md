# 文献启发、候选算法与数学/模型分析

2026-11-05。入口：[算法构想与理论分析](ALGORITHM_IDEAS_AND_THEORY_ZH.md)。目标是借鉴前人模块形成有独立增量的新算法，以不同数据集的最终回答正确率为主指标，争取可复核的论文证据。本轮仅完成分析和CPU控制；没有新GPU、LLM续写、训练或百题语义发生率。

- [13篇定向参考文献JSON](references_targeted.json)、[BibTeX](references_targeted.bib)：模块启发与原始来源，不是穷尽新颖性检索。
- [六篇机制近邻精读/方法审查](model_mechanism_literature.md)：binding、混合机制、迭代head、组合失败、patch和belief revision。
- [VTFR形式审查](vtfr_formal_audit.md)：核验、版本依赖、完整frontier、拒绝后恢复，以及限定soundness命题。
- [转移锚点数学审查](transition_anchor_math_audit.md)：不同梯度不正交，KL/步幅控制的边界，以及归一化目标的变化。
- [正式评测口径](EVALUATION_CONTRACT_V1.json)：逐数据集accuracy/pass@1、同预算比较、pass@k分列、成本和诊断指标。
- [P1标注定义V2](P1_LABEL_SCHEMA_V2.json)：修订有效性与传播失败分轴；旧值复用、错绑、兼容签名与unknown分开。
- [对上一轮设计的理论补充V2](THEORY_REVISIONS_V2.json)：不覆写旧协议/结果，不自动执行附件末尾安排。
- [问题、尝试与独立判断](WORKLOG_ZH.md)。

## 已执行CPU证据

`vtfr_formal_controls.py/.json`：三个精确程序675组有界更新匹配冷计算；似然比、单一首子节点、环、间接不变量和拒绝后未恢复的反例。

`transition_anchor_algebra_controls.py/.json`：同KL不同ESS、零更新方向、同参数norm不同有效LoRA变化、固定norm改变优化排序、prop改善而W变坏；七项预设代数断言通过。

`observational_signature_control.py/.json`：不同高层程序可给相同g(new_x)签名；16输入上19条历史输出仅与该签名兼容，不被标成已定位内部机制。

所有CPU结果都是形式/代数控制，不是Qwen新任务成绩。附件原件已按字节归档至inputs并绑定SHA；用户让分析第三方意见，文内“今天标注/紧接着跑GPU”等句子没有被当作直接执行命令。

标准库控制可直接以Python运行；默认输出文件已存在时应保留旧记录或查看脚本的输出约定。新算法还需真实输入渲染/资源验收和一次预定短模型实验；目前不能声称已经提高正式benchmark正确率。
