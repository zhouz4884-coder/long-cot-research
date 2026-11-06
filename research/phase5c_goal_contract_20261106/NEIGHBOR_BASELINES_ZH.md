# 为什么当前必须保留这些baseline：六项近邻核对

2026-11-06。沿用`nature-academic-search`的citation-verification流程，先查既有62项地图，再核对官方arXiv/ACL原始来源；当前没有挂载学术检索MCP，使用primary网页。**仅做下面6项近邻核对，未复现作者方法、未查看本轮32题质量，也未改变任何输入/算法。**

阅读层级：前三项中STOP、intrinsic self-correction、SCoRe来自原62地图；PAL此前Phase5-B也已核对。此轮所有项刷新官方元数据/摘要，STOP另读ECN构造相关段落，SCoRe另读第5节及reward定义；其余不称全文精读。下面是机制与对照需求，非跨论文效果排行榜。

| 原始来源 | 与当前工作的关系 | 核验信息从哪里来 | baseline含义与边界 |
|---|---|---|---|
| [STOP：Structured On-Policy Pruning，Findings EMNLP2026](https://aclanthology.org/2026.findings-emnlp.672/)（原P35） | ECN要求节点既有完整作答功能、又给正确最终答案；不能把任何“出现候选”节点视为完成节点 | 训练数据构造使用真实答案/正确性与结构标注；不是部署时免费的真值G | 借鉴“完整答案对象”而非只抽一个数字。当前候选摘录无Gold，不能声称找到ECN或复现STOP。随机尾窗/简单选段是必要控制，真实STOP训练方法此轮未复现 |
| [Large Language Models Cannot Self-Correct Reasoning Yet，ICLR2024](https://arxiv.org/abs/2310.01798)（原P18） | 区分无外部反馈的内在自纠错与额外反馈；其所测设置中可能改坏原正确回答 | 论文研究的intrinsic设置没有外部正确性反馈；这是一项边界研究，不是通用拒绝门 | FullContinue是必要的额外算力/自行修正对照。仅看到Wait、不同候选或同模型再判断，不等于得到独立证书；也不能由该标题否定训练后的纠错能力 |
| [SCoRe：Training Language Models to Self-Correct via RL](https://arxiv.org/abs/2409.12917)（原P07） | 用多轮on-policy训练和转移奖励，明确奖励错→对、惩罚对→错，处理行为塌缩 | 训练奖励依赖真实正确性；推理时不是额外提供Gold，也不等于对任意候选有形式证明 | 若未来主张防W，需要区分普通续写、专门训练纠错与外部核验。当前冻结4B没有做SCoRe训练，不能将当前启发式冲突标志命名为等价功能 |
| [Rephrase and Respond（RaR）](https://arxiv.org/abs/2311.04205) | 通过重述/扩展问题改善目标理解，可与CoT组合；功能上直接邻近“目标契约提示” | 来自原问题和LLM重述，没有外部真值checker | FullContract控制“只是重新强调题目就能改善”的解释。当前question模式/原文复制不是作者RaR实现；正式论文若主打目标理解，应纳入同成本的真实重述方法，而非只比强制boxed读出 |
| [LLMLingua：Compressing Prompts，EMNLP2023](https://arxiv.org/abs/2310.05736) | 用预算控制与压缩模型选择保留输入；与“去掉长历史、保留有用片段”属近邻 | 压缩模型/信息分数不是数学真值证书，也不认证摘录满足完整依赖 | TailContract是便宜尾窗基线，FullContractEvidence与ProjectedContractEvidence共用候选以隔离删历史；当前启发式quote selector不是LLMLingua复现。若主张优于通用压缩，后续应补同预算/含压缩器成本的正式压缩基线 |
| [PAL：Program-aided Language Models](https://arxiv.org/abs/2211.10435) | 将问题分解/程序生成与运行时算术执行分开 | Python等外部运行时按程序语义执行；这是确实不同于同模型自我声称正确的执行信息，但不保证自然语言到程序的映射正确 | 真正加入符号checker/解释器后，应给普通方法相同工具权限并计工具成本。精确解释器已可解完整已知程序时，不能把其正确率归为LLM投影创新；本自然32题原型没有实现PAL或这类G |

## 当前原型究竟测什么

`goal_evidence.py`从题干生成软类型/目标提示，再按boxed、结论词和目标词相关性选原文摘录。全部摘录是UNVERIFIED，语义冲突判定UNKNOWN；既没有自动建立完整依赖图，也没有独立真值仲裁。当前更接近**目标重述＋抽取式上下文压缩**，不能仅凭GC-PBP新名称称已实现“契约＋可靠G＋认证父边界”。

“模型再判断一次”和“真正外部核验”不能混为一谈；类型正确也不等于数值正确。概率0/1、等价小数与分数、最终答案恰好等于某中间量都可能合法，不能靠无条件数值黑名单证明目标绑定正确。

## 七臂各自排除的替代解释

- **ForcedBoxCue → FullContinue：**是否只是去掉强制答案起始片段、让输出完整结束即可改善。二者是本地提示/读出控制，不冒称复现历史所有采样与缓存细节。
- **FullContinue → FullContract：**是否只需重申原题目标/答案对象，不需要压缩或候选选择。
- **FullContract → FullContractEvidence：**额外候选摘录本身是否有用；有用不代表候选已核验。
- **FullContractEvidence → ProjectedContractEvidence：**双方同样的目标提示、同一个候选packet，差别才是保留/去掉完整历史。否则是新增信息与删历史混淆。
- **TailContract ↔ ProjectedContractEvidence：**是否简单取最后一段就够用，启发式目标/候选选择是否超出廉价窗口。字符预算相同不代表token或计算严格相同，仍须实测。
- **RestartP：**是否从原题重新解就足以胜过复杂历史处理。当前它只获得相同额外readout保护顶，不是新生成8192-token完整RawFull的等价复现。

这些消融比“只比一个历史forced baseline”更能判断模块作用；但七臂**不是七个已发表算法的作者级复现**。跨模型、跨数据集是另一个泛化维度，不能替代同输入条件下的组件归因；本轮单模型32个独立题ID，只是历史前缀上的探索性读出比较，尚非新的端到端长CoT基准成绩。

后续若本轮出现稳定增量，优先补真实重述/通用压缩/同工具核验等相关强方法，再扩骨干与题型。无需在尚未证明模块有用时直接付出全部训练与多模型成本。
