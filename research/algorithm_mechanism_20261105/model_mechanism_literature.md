# 局部修订后的变量绑定、组合计算与“stage-pointer”假说

2026-11-05。已完整阅读新附件《已粘贴的文本.txt》。**当前可定义的是“修订后依赖传播失败”的行为任务；`stage-pointer desynchronization`仍是待鉴别机制，现有输出不能唯一识别它。** `28*2=56`支持“把更新后的x放进要求y的下游关系”的候选行为解释；不证明模型内部存在一个已经定位的进度指针，更不证明它停在Stage 3。

本次按 `nature-academic-search` 的multi-source-search与citation-verification流程，沿原始论文、正式会议录/ACL Anthology核验。专用学术MCP未挂载，改用官方web。只读原文与现有附件，没有GPU、远程连接、执行附件中的实验指令或修改旧62篇库。六条可核书目信息另存 `model_mechanism_references.json`。

## 1. 六篇最近邻：技术方法、成立条件及我们应如何区分

| 工作与原始出处 | 原文方法/条件性发现 | 可借鉴的鉴别方法与边界 |
|---|---|---|
| **How do Language Models Bind Entities in Context?** Jiahai Feng、Jacob Steinhardt，ICLR 2024；[正式页](https://proceedings.iclr.cc/paper_files/paper/2024/hash/9d1b7fc578c0d2d6431fc26d736ecaf3-Abstract-Conference.html)，[PDF](https://proceedings.iclr.cc/paper_files/paper/2024/file/9d1b7fc578c0d2d6431fc26d736ecaf3-Paper-Conference.pdf)，arXiv `2310.17191`。 | §2–4以成对entity–attribute上下文作activation interchange/mean intervention，检验factorizability、binding ID与绑定子空间；§5测试跨任务迁移，也明确存在别的binding机制。对象是上下文中“谁对应哪个属性”，不是算术执行进度。 | **第一优先方法近邻。** 固定数值、对调变量名/角色和表达顺序，检验错误是否跟随身份绑定。移植相关activation应导致预期的re-binding，并保留独立实体。能操控entity–value绑定仍不等于找到了next-operation/stage变量。原文主要Pythia/LLaMA，不能直接宣称Qwen3上已成立。 |
| **Mixing Mechanisms: How Language Models Retrieve Bound Entities In-Context.** Yoav Gur-Arieh、Mor Geva、Atticus Geiger，ICLR 2026；[正式页](https://proceedings.iclr.cc/paper_files/paper/2026/hash/2eeff35664016c7f0f8aa704f0d9a83e-Abstract-Conference.html)，[PDF](https://proceedings.iclr.cc/paper_files/paper/2026/file/2eeff35664016c7f0f8aa704f0d9a83e-Paper-Conference.pdf)，arXiv `2510.06182v2`。 | §3.1–3.4设计original/counterfactual对，使positional、lexical、reflexive三机制在同一次interchange后预测不同token；9个Llama/Gemma/Qwen2.5模型、10类binding任务。短列表上的位置机制在中间实体/更长列表不再充分。作者以组合因果模型拟合所测next-token分布，摘要报告95% agreement。 | **比“只找一个pointer”更强的实验范式。** 先让位置、词汇身份、最新数值、阶段四种解释给出不同预测，再干预；不能把模型混合机制强塞成单一stage。§3.4/Appendix D.2特别区分pointer与patching直接复制答案，适用于防止“把正确y/z带进来”的假修复。其任务仍主要是实体检索，不是修订后的多跳算术。 |
| **Iteration Head: A Mechanistic Study of Chain-of-Thought.** Vivien Cabannes等，NeurIPS 2024；[正式页](https://proceedings.neurips.cc/paper_files/paper/2024/hash/c50f8180ef34060ec59b75d6e1220f7a-Abstract-Conference.html)，[作者全文](https://arxiv.org/html/2406.02128v2)，arXiv `2406.02128`，DOI `10.52202/079017-3463`。 | §2–3在copy/parity/有限域多项式迭代任务中，研究两层、每层单头的小Transformer。CoT显式状态、位置差与两层attention可组合出迭代head；任务迁移/消融支持该受控实现。§4也展示同题可学到别的计算电路。 | 提供**阶段/迭代应怎样成为可识别算法状态**的toy参照，而非Qwen3自然CoT已有该电路的证明。可借鉴把“当前状态值”和“下一输入/算子位置”分别控制；attention图像或按层可解码的阶段标签本身不够。其learned absolute positions也不能无条件移植到Qwen的RoPE。 |
| **Measuring and Narrowing the Compositionality Gap in Language Models.** Ofir Press等，Findings EMNLP 2023；[正式页](https://aclanthology.org/2023.findings-emnlp.378/)，[PDF](https://aclanthology.org/2023.findings-emnlp.378.pdf)，DOI `10.18653/v1/2023.findings-emnlp.378`。 | 引入“子问题都答对、复合问题仍答错”的compositionality gap，使用多跳QA；显式CoT/self-ask拆解能改善所测问题。§1–3的对象与读出协议不同于latent机制定位。 | **最重要的低复杂度竞争解释。** 分别问x、y、最终z，若单跳可做、多跳失败，可能是组合/读出失败；One-Line改好只支持显式分解有用，不能独自证明stage pointer被重置。未写出y并不等于内部跳过y；合法的闭式复合运算应算成功。 |
| **Towards Best Practices of Activation Patching in Language Models: Metrics and Methods.** Fred Zhang、Neel Nanda，ICLR 2024；[正式页](https://proceedings.iclr.cc/paper_files/paper/2024/hash/06a52a54c8ee03cd86771136bc91eb1f-Abstract-Conference.html)，[PDF](https://proceedings.iclr.cc/paper_files/paper/2024/file/06a52a54c8ee03cd86771136bc91eb1f-Paper-Conference.pdf)，arXiv `2309.16042`。 | §3–5比较Gaussian noise与等长symmetric token replacement、概率/logit difference、跨层window等选择；同一定位任务可给出不同结论，大噪声可能破坏原机制。讨论覆盖factual recall、IOI及算术等任务。 | 用语义有效、等长、成对反事实和多种预先冻结指标，附identity/random/无关变量patch对照。probe准确率、单层消融损伤或patch后最终答案恢复，都不能独立命名那个activation为“stage”。需要跨模板和双向counterfactual验证，不能只选成功patch。 |
| **Belief Revision: The Adaptability of Large Language Models Reasoning.** Bryan Wilie等，EMNLP 2024；[正式页](https://aclanthology.org/2024.emnlp-main.586/)，[PDF](https://aclanthology.org/2024.emnlp-main.586.pdf)，DOI `10.18653/v1/2024.emnlp-main.586`。 | §3的ΔR比较加入新信息前后两个时刻的回答，Belief-R既测应改也测应保持；约30个模型的结果显示更新能力与不应更新时的稳定性有权衡。数据包含可撤销/常识条件，不能自动解释为纯经典逻辑蕴含。 | 直接支持**更新vs保持**配对评估、保留W/no-change负控的必要性。它评估行为适应性，不证明内部存有显式belief store，也不定位计算阶段。我们算术AST核验属于额外可验证子域，不能把其标签或结果直接当自然推理金标。 |

以上均已核验到正式发表，未依赖聚合站的会议标签。Iteration Head正式PDF因工具文件大小限制改读作者arXiv全文；发表身份由正式proceedings确认。没有把95%等特定任务agreement外推成我们修订任务的效果。

## 2. 先定义什么是错误，再谈机制

设合成题含可核验关系\(y=f(x), z=g(y)\)，修订后根值\(x_n\)。可预先计算以下互不相同的候选：

\[
z_{valid}=g(f(x_n)),\quad z_{old}=g(f(x_o)),\quad
z_{misbind}=g(x_n).
\]

如果这些值碰撞，样例不能区分解释，应在生成状态前按规则标为不辨识，而非看模型输出后挑选。若输出含明确算式 `g(x_n)`，可标“新值跨角色/跨跳错代证据”；若只有一个匹配数字，最多标“与该shortcut兼容”。还应允许其他算术错误、错误revision承接和unresolved。

**行为标签与潜变量标签要分开：**

- `E-Reuse`：后文实际将旧x或失效的旧后代用于推导；仅重述/引用/否定旧值不算。
- `E-Misbind`：有证据把新x用到了要求y的位置，或明确漏用了某条约束。只缺一行可见CoT不算；直接计算\(g\circ f\)是合法策略。
- `E-Unknown`：结果错，但不足以判旧值复用或错代；不能强塞进stage解释。
- 修订有效性单列为valid/invalid/no-op/uncertain；错误修订导致的新答案并非正确修订后的传播失败。W样例必须保留，不能由gold决定是否给某臂干预。

“发生率”需要预先定义有传播机会的有效修订数作分母，报告标签并集及重叠，不把E-Reuse与E-Misbind简单相加。100条历史轨迹若没有足够可核验修订，应如实报告低覆盖，而不是用所有Wait作分母或宣称“漏掉一半病灶”。

## 3. stage-pointer可提出怎样的可证伪定义

在一个**外部已定义的解释器/任务模型**中，可将高层状态写为

\[
S=(V,\mathcal I,F),
\]

其中\(V\)是变量值与绑定，\(\mathcal I\)是失效节点集合，\(F\)是尚待执行的依赖前沿。对线性链及固定执行策略，F可简化为next-operation索引j；对合流DAG，F通常是集合而不是单一pointer。

“desynchronization”假说可以具体为：**修订已改变V，但模型中负责后续运算选择的表征未按同一高层状态更新，使它继续执行j对应的旧运算选择。** 这是研究者提出的高层因果模型；不等于已经从Qwen3中观测出该变量。

要支持这个假说，至少需要：

1. **可分解预测。** 将数值、变量身份、关系/运算、语义进度、绝对token位置和最近数值分开操控，使stage与binding/recency假说有不同输出预测。
2. **泛化的可读出。** 若训练probe，训练/测试按变量名、数值、算子、模板/长度隔离；加入仅靠token位置或最后标记词的baseline。否则“阶段可解码”可能只是位置、格式或答案的编码。
3. **选择性干预。** 找到不同时注入正确中间结果/最终答案的interchange，双向交换后按预定stage反事实改变下一运算，同时保留被声明不变的值和独立分支。random/无关位置patch不能同样解释收益。
4. **替代模型比较。** 在未参与选层/方向的配对样例上，比较stage模型、binding模型、最近值启发式及其混合模型的反事实预测，保留失败case。一个patch可能携带多种信息；无需强求唯一单向量实现。

即使四项成立，也应表述为“该受控任务中一个有因果支持的计算抽象”，而非Transformer通用的唯一进度寄存器。对现有短人工16例，只有行为签名和cache重编码差异，尚不满足这组识别条件。

## 4. 竞争解释与能区分的最小控制

| 假说 | 可观测预测 | 优先区分控制 |
|---|---|---|
| 最近数值+最后算子启发式 | 错误跟随离读出最近的数值/末端算式，即使未发生修订。 | 保持任务与值不变，移位/重排无关数字和revision位置；加入无修订、正确旧链也出现同型错误的控制。 |
| entity/variable binding失败 | 错误跟随变量名、角色、词汇/实体组位置；未必需要“先完成旧链”。 | 交换x/y角色、随机重命名、同时改变数值顺序；使用令positional/lexical/reflexive预测分开的paired counterfactual。 |
| 普通组合性/读出失败 | 单跳x/y能答对，直接z不行；显式拆解/指定先求y就改善。 | 同一信息下Direct、等长中性过程提示、指定y的One-Line分列。对额外输出token/任务指令差别单独记账。 |
| stale descendant信息承接 | 后继缓存或显式旧y/z仍影响后续；早屏蔽重编码与late读取屏蔽不同。 | 在固定One-Line/可见信息/原position下比较late/early，再区分文本可见旧后代、独立支持是否保留；不同只说明历史状态有作用。 |
| stage/frontier更新失败 | 正确新值/绑定已可读出，但next-operation仍像旧阶段；特定stage interchange改变运算选择而不复制值。 | 独立操控“相同数值/绑定、不同完成阶段”；与“相同阶段、不同数值/绑定”交叉，做选择性双向干预。 |
| revision判断/服从错误 | W中遵从错误新值；不是因为错误旧值残留。 | valid/invalid/no-op revision配对；单独测Gate是否识别本地约束满足，不把保持旧值自动视坏事。 |

这些假说可以共存。`Full+One-Line`变好不唯一支持“指针回拨”；`Early+One-Line`再提高也不构成KV闭包清理不可替代的铁证，仍需排除信息保留、位置/时点、读出和数值噪声等差别。

## 5. 对附件VTFR / transition anchor的具体审查

- **局部核验G：** 精确AST算术代回是可定义的外部验证器；\(\log p(P_x\mid x_n)-\log p(P_x\mid x_o)\)是文本似然，受数字频率、序列长度和措辞影响，不等价于满足约束。二者须分列，保留错误revision接受率/正确revision拒绝率。
- **依赖D：** AST给出的合成依赖闭包可以有精确oracle。自然语言中的实体共现不等于有向依赖；共享前提也可能让“独立r”并不独立。应有uncertain标签，不能直接从共现启动删除。
- **前沿T：** 自动拼接“先算y=”已向模型提供外部计划/子目标，属于显式分解/控制器接口。可能有效，且与self-ask等已有范式相近；它的效果不证明内部stage状态被识别或修复。
- **缓存C：** 如果必须撤销根值，删除集合须明确包含旧根断言及其失效后代；图论descendants通常不包含根自身。否则“删闭包”仍保留旧x可导致定义含混。保留独立支持与重编码成本要单独验证。
- **新锚点：** 把监督位置改成“首次传播步”是明确目标选择，但附件的\(g_U,g_A,g_{prop}\)不会因名称不同而自动正交。先验证传播跨度标注、数值/格式泄露和行为失效，不能以matched KL/step norm直接推出新机制存在。

## 6. 建议当前停在什么证据级别

本轮最稳妥的命名是**“修订后的变量绑定/依赖传播鉴别”**，将stage/frontier模型作为候选解释。先做既有文本与规则的无GPU标注审计，明确E-Reuse、显式E-Misbind、可兼容shortcut及Unknown；可预先写出每个候选模型对少量配对状态的不同预测。

如果之后主任务授权短模型实验，先验证One-Line能否改变跨跳错代行为并记录C/W伤害；不要同步叠加Gate、闭包mask、stage steering和训练锚点。只有行为可重复、替代解释可区分后，才进入binding/stage的probe与interchange定位。附件中的“2分钟”“3–5天”“病根立住”均不是文献或现有数据已经保证的结果。

当前判断：研究对象可操作化；stage-pointer未被识别；单一pointer并非默认正确架构。最值得直接借用的是**让替代机制做出不同反事实预测**的实验设计，而不是提前给一个activation取名。
