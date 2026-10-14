# V2目标修订的文献身份与方法范围核对

核对日期：2026-10-14。流程：nature-academic-search / citation-verification。学术MCP检索接口在本会话不可用，使用官方arXiv、PMLR、ICLR Proceedings及ACL Anthology页面直接核对。去重依据为arXiv ID或正式论文页面ID。

范围：两份输入中影响目标的12项独立文献，核对标题、时间、正式出版/预印本身份及摘要可支持的方法范围。**不是本轮完成12篇全文精读、源码复现或验证其数字真实性。** 旧轮次已经审查的论文/源码证据保留，后续完整强基线仍按各自冻结版本执行。

结果：verified 12；mismatch 0；not_found 0；suspicious 0；manual_needed 0。这里只对下表12项文献的身份分类，不将作者仓库完整可运行性计入verified。

| 文献与主来源 | 当前核对身份 | 与目标有关的可支持范围 | 对本项目的约束或研究判断 |
|---|---|---|---|
| [Stable Answers, Unfinished Reasoning](https://arxiv.org/abs/2609.09989) | arXiv v1，2026-09-09 | 摘要报告固定协议上3520条一致性规则未通过三道预声明门槛，同流水线DEER边界置信控制通过；提出一致性与终止之间的差别 | 不能把一致当正确或终止。结果限定于作者协议；不证明所有主动干预无效，也不证明我们的完成性特征有效 |
| [Stop When Reasoning Converges: Semantic-Preserving Early Exit for Reasoning Models / PUMA](https://arxiv.org/abs/2605.17672) | arXiv v1，2026-05-17；页面写under review | 推理级语义冗余检测与答案级验证结合，摘要报告平均token减少26.2% | “冗余+验证”已有先例；本项目需检验额外信息和完整实测耗时，不能仅命名PVRL作为新颖性证据 |
| [When Does Learning to Stop Help? A Cost-Aware Study of Early Exits in Reasoning Models](https://arxiv.org/abs/2606.30852) | arXiv v2，2026-07-04（初版06-29） | LearnStop与置信度/熵/稳定性控制比较，作者报告相同策略在KV分支与重复prefill下成本结论可反转 | 需对照简单规则、包含全部执行成本；作者风险容忍和任务设置不能直接等同本项目1pp目标 |
| [AERA: Adaptive Evidence Residual Allocation for Efficient Test-Time Reasoning](https://arxiv.org/abs/2608.27964) | arXiv v1，2026-08-28 | 累积多候选响应前缀上学习追加response-block的残余价值；未来正确性只作离线监督 | 不能声称首次预测未来计算价值；单条CoT内读出/长程预算的收益需单独证明 |
| [Conformal Thinking: Risk Control for Reasoning on a Compute Budget](https://proceedings.mlr.press/v306/wang26hd.html) | ICML 2026，PMLR306 | 上/下阈值停止和风险控制预算选择 | Conformal模块或双阈值不是本项目独立创新；源码快照接口问题不等于论文理论失败 |
| [Does Your Reasoning Model Implicitly Know When to Stop Thinking? / SAGE](https://proceedings.mlr.press/v306/huang26bn.html) | ICML 2026，PMLR306 | 采样范式影响停止行为；另有SAGE-RL | 记录Thinking/采样/读出协议敏感性。目标修订不自动授权重训RL或更换主解码协议 |
| [Conformal Policy Control](https://proceedings.mlr.press/v306/prinster26a.html) | ICML 2026，PMLR306 | 以安全参照策略和conformal校准约束新策略，涉及非单调有界损失 | 本项目有界FULL可答错，不能默认满足安全参照前提；有限分层测试池保证另按项目契约推导 |
| [Think Again or Think Longer? Selective Verification for Budget-Aware Reasoning / SEVRA](https://arxiv.org/abs/2606.19808) | arXiv v1，2026-06-18 | 保留初答或选择性验证；作者设置中更长初始预算可比后置验证更经济 | 固定预算是不可省略对照；“增加验证”不能预先认定有效 |
| [Dynamic Early Exit in Reasoning Models / DEER](https://proceedings.iclr.cc/paper_files/paper/2026/hash/8df90a1440ce782d1f5607b7a38f2531-Abstract-Conference.html) | ICLR 2026 Conference | 在推理转换点根据试答置信动态提前结束 | 完整方法、兼容性修复、独立适配和confidence proxy分别标记，真实试答成本计入 |
| [Stop When Further Reasoning Won’t Help: Attention-State Adaptive Generation in Reasoning Models / ASAG](https://proceedings.mlr.press/v306/li26ev.html) | ICML 2026，PMLR306 | 注意力状态驱动的自适应生成 | 动作数量或注意力特征不是独占创新；冻结适配不因有限归一化诊断临时改阈值 |
| [Stop When Enough: Adaptive Early-Stopping for Chain-of-Thought Reasoning / REFRAIN](https://aclanthology.org/2026.acl-long.1256/) | ACL 2026 Long Papers，DOI10.18653/v1/2026.acl-long.1256 | 反思冗余判断与跨题SW-UCB调阈值 | 必须保留全局流顺序与真实额外开销；不继承每题固定潜在结果条件下的M1风险证书 |
| [Learn then Test: Calibrating Predictive Algorithms to Achieve Risk Control](https://arxiv.org/abs/2110.01052) | 此次核对arXiv v5，2022-09-29（初版2021-10-03） | 将有限样本风险校准转为多重假设检验 | 方法借鉴需与冻结候选家族、抽样和损失匹配；不能直接把IID示例代入当前有限分层池 |

本轮综合判断：资料支持把研究问题收敛到候选质量与计算尺度，但没有建立本项目的算法新颖性或性能结论。“完成性”只能先作为可操作观测和待验证信号；真正验收是条件增量风险识别及质量匹配后的实际耗时收益。主文档见 [修订目标](RESEARCH_GOAL_V2_20261014_ZH.md)。
