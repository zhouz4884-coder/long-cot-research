# 新材料原始文献独立审查

审查日期：2026-11-05。范围：三页背景材料、七页综述及讨论建议中的 R-KV、LongFlow、CREST、GLoRE，以及这些引文对三个候选方向的支持边界。没有运行 GPU、连接研究服务器或修改原材料；没有把旧 62 篇库的条目当作已核验事实。

使用方法：按 `nature-academic-search` 的 `citation-verification` 流程，逐项做名称消歧、正式发表核验、原始全文/作者代码核验、材料表述对照和条件审查。专用 academic-search MCP 未挂载，使用公开 arXiv、正式会议录、ACL Anthology 与论文链接的作者 GitHub；GitHub 通过已连接工具只读访问。分类保留 `verified`、`mismatch`、`manual_needed`。这里的“verified”只代表书目或指定原文内容经核验，不代表独立复现实验。

## 1. 书目身份与核验级别

| 材料名称 | 原始论文身份 | 正式发表证据/标识 | 本次判定 |
|---|---|---|---|
| R-KV | Zefan Cai 等，*R-KV: Redundancy-aware KV Cache Compression for Reasoning Models* | [NeurIPS 2025 proceedings](https://proceedings.neurips.cc/paper_files/paper/2025/hash/57e0358aed314784cad14a26e1eba642-Abstract-Conference.html)，DOI `10.52202/085713-2038`；[正式 PDF](https://proceedings.neurips.cc/paper_files/paper/2025/file/57e0358aed314784cad14a26e1eba642-Paper-Conference.pdf) | `verified`：正式会议 + 全文；但 HTML/PDF 数字冲突，见下。 |
| LongFlow | Yi Su 等，*LongFlow: Efficient KV Cache Compression for Reasoning Models* | [EMNLP 2026 main](https://aclanthology.org/2026.emnlp-main.112/)，pp.2629–2645，2026年10月；[正式 PDF](https://aclanthology.org/2026.emnlp-main.112.pdf)；arXiv `2603.11504` | 论文真实；附件写“ACL 2026”是 `mismatch`。ACL Anthology 是收录平台，不等于会议 ACL。正式版作者含 Zheming Yang，与 arXiv v2 六名作者版本不同。 |
| CREST | Zhenyu Zhang 等，*Understanding and Steering the Cognitive Behaviors of Reasoning Models at Test-Time* | [arXiv 2512.24574v2](https://arxiv.org/abs/2512.24574)，v1 2025-12-31，v2 2026-01-19；[Together AI 官方代码](https://github.com/togethercomputer/CREST) | 原始预印本 + 作者代码 `verified`；本次未取得正式会议接收的权威证据，会议级别 `manual_needed`。OpenReview 论坛触发浏览器验证，不以第三方聚合站的 ICLR/NeurIPS 标签作录用证明。 |
| GLoRE | Xinyu Tang 等，*Unlocking General Long Chain-of-Thought Reasoning Capabilities of Large Language Models via Representation Engineering* | [ACL 2025 long.339](https://aclanthology.org/2025.acl-long.339/)，pp.6832–6849，DOI `10.18653/v1/2025.acl-long.339`；[原文 HTML](https://arxiv.org/html/2503.11314v2)；[作者代码](https://github.com/txy77/GLoRE) | `verified`：正式发表 + 原文 + 代码。这里不是同名逻辑评测 benchmark 或其他 GLoRE 框架。 |

四个方法均能定位到真实原始工作；正式发表明确核验 3 项，CREST 的正式发表状态未确认；LongFlow 会议信息有一处明确错误。不能由“论文真实”推导附件的数字、分类与创新判断都正确。

## 2. 方法范围与数字条件

### R-KV：不是仅按高注意力保留 token

原文 §3 的策略同时使用近期 query 的注意力重要性 `I`、key 向量余弦相似度冗余 `R` 和联合保留分数 `λI−(1−λ)R`，并有 recent observation/buffer 保留。讨论建议把它归成“错误公式高注意力，所以 R-KV 会死保留”的单分数方法，忽略了其核心冗余项。错误分支是否更易被 R-KV 保留，是待测假说，不能用作已知缺陷。[正式 PDF §3](https://proceedings.neurips.cc/paper_files/paper/2025/file/57e0358aed314784cad14a26e1eba642-Paper-Conference.pdf)

同一正式站点存在版本差异：HTML 摘要为 38% cache、50% memory、2×；链接 PDF 摘要为 16% cache、90% memory、6.6×。不要混用。PDF Table 1/Appendix C 说明吞吐主要来自扩大 batch；A100 80GB、16K、10%预算的 batch 1 是69.41→80.95 tok/s，而各自最大 batch 为30→271、347.03→2300.28 tok/s。缓存预算下降不能直接等同总显存下降，更不能等同少生成了90%的思维 token。[正式 PDF Table 1、Appendix B/C](https://proceedings.neurips.cc/paper_files/paper/2025/file/57e0358aed314784cad14a26e1eba642-Paper-Conference.pdf)

### LongFlow：近12倍吞吐有特定系统条件

原文的 importance 由当前 query 的 attention 中间量和 value norm 近似输出损失，并非只看数学符号的 attention。其静态缓存与融合 Triton 算子也是收益组成。11.8×的条件是 Qwen3-1.7B、A100 40GB、输入512/输出16000、预算3200，各方法扩 batch 直到 OOM。它不支持“在3090上改个 mask 就有12倍单请求速度”的推断。[正式 PDF §3、§4.4](https://aclanthology.org/2026.emnlp-main.112.pdf)

附件“准确率几乎不降”不能逐任务泛化：正式版 Table 1 的 Qwen3-8B/AIME25 在3200预算是46.67%→26.67%（−20个百分点，30题），AIME24是60.00%→50.00%。原文也承认 query 稳定性假设；突变、工具交错等情况可能削弱估计。证伪后改路是否属于此类突变，值得测，但原文没有给出“错误 KV 造成复发”的证明。[正式 PDF Table 1、Limitations](https://aclanthology.org/2026.emnlp-main.112.pdf)

### CREST：关联行为的可控方向，不是正确验证器

原文以双换行划分 step、关键词标记 linear/non-linear，用离线线性 probe 排序 head，再推导向量；正式方法在 step 边界移除向量分量并保范数。标签涵盖 verification、backtracking 等非线性行为，不能等同“无效认知”。Table 1 的 R1-1.5B/AMC23 为72.5%→90.0%，是 **+17.5个百分点**，不是“达到原模型117.5%”；8951→5584 tokens 是−37.6%。[原文 §3–5](https://arxiv.org/html/2512.24574v2)

probe 可预测及干预有效，是相关性和特定干预效应的证据；它们不足以建立“验证方向是独立因果模块”或“向量正向注入必然生成有效反例”。“training-free”也仍需离线 probe 拟合/向量校准。作者代码当前说明 steering 需 `--enforce_eager`，不支持 CUDA graph/torch compile；性能账本要实际测。[作者 README](https://github.com/togethercomputer/CREST/blob/main/README.md)

### GLoRE：控制内部激活，但仍生成显式长 CoT

方法抽取 long/vanilla CoT 对比表征，再从 vanilla-CoT 构建的领域表征 memory 检索与题目有关的向量并注入。实验目标包含激发更长、更充分的显式中间推理。因此附件将它作为“不直接生成显式步骤”的隐式潜在 CoT 代表，分类失当。它没有提供“critical verification”的专属方向、单步验证成功保证或早停风险保证。适用需要模型内部激活与校准/表征库，仍有注入强度、检索数和层位置选择。[原文 §4–5/Limitations](https://arxiv.org/html/2503.11314v2)，[作者代码](https://github.com/txy77/GLoRE)

## 3. 对三个方向的影响（以下为本次分析，不是引用论文已证明的结果）

| 候选方向 | 引用能支撑什么 | 建议中尚未成立的关键跃迁 | 可以保留的研究问题 |
|---|---|---|---|
| 1. 阶段解耦/答案锚定重加权 | 本次四篇均不能直接证明 VCORE 的全链梯度受尾部污染，也不能证明 STOP 掉点原因。 | 梯度与答案损失内积是局部一阶代理，命名 `s_causal` 不会使其成为因果效用；“首次匹配正确答案”不一定是有效推导节点；单验证节点有益与2小时成本均未证实。 | 先测尾部/模板对参考梯度贡献、参考梯度消融与真实一步更新的关系；区分 oracle 锚点与可部署输入。 |
| 2. 证伪分支 KV 隔离 | R-KV/LongFlow 证明推理期 cache 选择可实现，有质量/吞吐权衡；不具备逻辑证伪依赖标签。 | cache 中有旧错≠旧错导致复发；R-KV必保留旧错未证实；移除旧错 token 的 KV 不等于清除残余状态，因为之后保留 token 的 KV 已在错误上下文中计算。 | **最适合先做小规模可证伪诊断**：已验证错分支是否有超出等长删减的复发因果效应；原位 mask 与干净重放是否有差别。 |
| 3. 表征压力测试早停 | CREST/GLoRE 支持激活能改变行为模式。 | “注入→有效反例检查→答案不变→真收敛→安全早停”的每一箭头均缺独立证据。相同模型可能把错误信念变得更稳；激活漂移也可能只是干预扰动。 | 以提示验证、等长普通续写、随机/错误方向干预作对照，检验单步检查对未来翻案风险是否提供增量预测。不能预先称“可信/安全”。 |

三方向都不能依据这四篇宣布“未撞车、原创、能发顶会、100%适配算力”。本次未完成全领域 novelty 排查；没有真实模型/硬件测量。

## 4. 建议方向二的最小机制鉴别约束

先建立一组可程序验证的数学/变量依赖样例；将“否定性语言出现”“变量值改变”“逻辑上证伪且后续依赖失效”分开标注。只把第三类当主诊断集合，并另测真实轨迹覆盖率。对语义标注可离线用答案 oracle，但推理触发与最终评估不得泄露标准答案。

对同一个冻结前缀，至少比较：原 cache；只删已证伪分支；等长随机/独立正确分支删除；同删除集合但保留位置的 attention mask；删除后重新 prefill 保留文本；带否定摘要的重放。匹配生成预算、摘要长度、位置索引/absolute position、随机种子。这样才能区分语义选择、普通压缩、位置变化和上下文重算的影响。重新 prefill 只能作为机制 oracle/较贵基线，成本需计入。

主要终点应为独立判定的错值复用/派生复发和最终正确率，附证伪触发 precision/coverage、token/延迟/峰值KV与总显存账本。若随机删减同样有效、只重放有效而原位 mask 无效、或触发错误抵消收益，则应收缩/否定原命题。不能用注意力权重下降替代复发与正确率改善，也不能以人工构造病例替代自然纠错发生率。

## 5. 明确未证实点与工具限制

- CREST 的正式会议接收状态未证实；搜索结果中的另一个 *CREST: A causal framework for mitigating shortcut learning...* 与本次 steering CREST 不是同一论文，不可借其“causal”措辞移植机制证明。
- 未核验附件的 Yeo、ReBalance 等其余泛称；需要使用时应先补标题/DOI/原文。本报告不为七页综述的所有条目背书。
- LongFlow 官方仓库确实存在且论文直接链接。`README.md` 返回404，目录可读，含 generation/accuracy/kernel 相关文件；因此“无README”不等于“无代码”，也不等于已验证一键复现。未运行作者代码。
- GLoRE 正式 PDF 经 web 读取触发文件过大限制，书目从正式 Anthology页核验、技术从作者 arXiv v2与代码交叉核验。CREST OpenReview论坛验证受限，没有绕过。
- 当前审查区分了：正式书目证据、原文报告实验、作者代码可读、本次推论、尚待实验的因果命题。所有成本及硬件适配尚未实测。

## 6. 定向最近邻补查：不把缓存/文本恢复诊断包装成新方法

本节只补查指定的四项原始工作，没有运行论文代码。三个2026年条目核验到作者 arXiv 原文；本次不额外认定其会议接收状态。LESS 另有 ICML 2024 正式页面。

| 工作与原始来源 | 对象、干预接口与信息前提 | 与当前方向的关系和边界 |
|---|---|---|
| **Random Attention: Rethinking KV Cache Eviction for Efficient Reasoning**，Heng Wang 等，arXiv `2609.03430v2`（2026-09-28）；[原文 §2–3、Appendix H](https://arxiv.org/html/2609.03430v2) | decode 期缓存淘汰；保护 prompt 和近期 buffer，其余位置按 layer/KV head 独立随机保留。无需语义错误标签、答案、梯度或重要性分数；反复抽样形成隐含年龄衰减。原文区分物理 eviction 与保留全缓存的 sparse attention。 | **方向二必须加入的强零假设**：正确的prompt保护和普通删减可能已解释收益。原文没有按证伪依赖删段或写负约束摘要；其跨head副本与重复文本观察，也不能证明错误证据的复发机制。不能把其描述性相近当严格等价检验。 |
| **Budgeted Cache Repair for Cross-Context KV-Cache Reuse**，Haeyong Kang、Chang D. Yoo，arXiv `2610.02233v2`（2026-10-08）；[原文 §3、Appendix B](https://arxiv.org/html/2610.02233v2) | 对象为相同 segment 在新 prefix 下近似复用产生的缓存误差；先生成两token draft再回退，以其 attention 选行/64token chunk/扩展span，在固定预算内逐层重算并覆盖KV。依赖已有近似cache、完整prefix/cache上下文、absolute causal位置和前向计算；不依赖gold答案或逻辑证伪标签。 | **选择性缓存修复/行或段重算已有近邻**。其“错误”指表示近似误差，不是推理命题错误；接口主要在generation前的cross-context reuse，方向二在同链纠错边界。局部重算仍读其他现存cache，不等同完整干净重放；原文全行重算控制也保留了数值差异。 |
| **GRAIL: Gradient-Reweighted Advantages for Reinforcement Learning with Verifiable Rewards**，Tej Deep Pala 等，arXiv `2606.04889v1`；[原文 §3](https://arxiv.org/html/2606.04889v1) | RLVR训练期，把生成rollout的final-answer token NLL对输入embedding求梯度，用gradient×activation的L2 norm构造saliency，再log/标准化/clip、stop-gradient后乘sequence advantage。需要完整rollout、answer span与可验证outcome reward；无需独立PRM。 | **方向一“答案锚定局部效用+token重权”的近邻很直接**。GRAIL是embedding局部敏感度与RL advantage；建议方案是参数梯度内积与SFT权重，接口不同，但“只以最终答案监督给中间token赋权”不能泛称新。高saliency不等于反事实正确性或因果贡献。 |
| **LESS: Selecting Influential Data for Targeted Instruction Tuning**，Mengzhou Xia 等，[ICML 2024正式页](https://proceedings.mlr.press/v235/xia24c.html)，PMLR235:54104–54132；[作者原文 §2–4](https://arxiv.org/html/2402.04333v2) | 训练样本级选择；用目标few-shot示例与候选训练样本的梯度相似性估计目标loss影响，适配Adam、用LoRA warmup/低维投影及多checkpoint特征降低成本。需要目标数据与训练梯度，最终输出为样本子集。 | **目标锚点梯度相似性/一阶loss下降代理已有基础**。它不做ECN分期、token级删尾、KV隔离或负约束摘要。方向一可能的区别须落实在阶段标注、权重对象和可重复失效消除，不能只是把reference loss改名anchor loss。 |

### 6.1 “语义证伪 + KV删段 + 负约束摘要”的拆分判断

| 组成部分 | 当前能确认的已有内容 | 本轮仍需验证/尚不能认定新颖的内容 |
|---|---|---|
| KV删减、按预算保留prompt/近期状态 | R-KV、LongFlow、Random Attention已有具体实现与系统评测。 | 整段删减是否优于token/随机删减；收益是否只是保护prompt、减少干扰或位置变化。 |
| 恢复/重算部分缓存状态 | BCR已有row/chunk/span预算重算，与dense前向对照。 | 单链语义否定之后保留KV是否被旧错上下文影响；选择性重算能否达到干净重放的效果和成本。 |
| 以逻辑证伪信号确定被撤销分支及后代 | 上述四个近邻的方法中，没有把“命题已被证伪+依赖后代”作为缓存编辑依据。 | **这只是这四项的范围差异，不是全领域未有证明**。`Wait`、共享变量、答案出现均不足以充当可靠证伪/依赖识别。oracle标注只适合机制上界，部署时仍需可观测信号。 |
| 负约束摘要/保留失败尝试记忆 | 指定四项未把tombstone文本摘要作为核心接口。 | 同样未完成相关memory/reflection/rollback全域排查；摘要是否防复发、是否强化错误值、是否只靠新增正确信息，均待对照。 |
| 把三部分合在一起改善“纠错后复发” | 当前没有来自这些引文的直接证明。 | 语义隔离超过等长random的增益、重放与原位mask的差距、摘要的独立增益、自然触发precision/coverage与总成本，都是待实验命题。组合本身不构成已确立创新。 |

对首轮机制实验的具体影响：加入**相同prompt保护、删减量和删除年龄分布**的随机对照；段级语义删除须另配等长/等位置段级随机对照，因为按head独立random与跨head共同删整段不是同一操作。把“原位KV屏蔽”“编辑文本后完整重放”“保留文本但选择性重算”作为不同干预分别记账。摘要须配等长中性摘要、仅新正确状态、仅否定旧假设等对照，以确定它传递了什么信息。首轮只判断缓存/文本状态恢复的可重复机制差异，不宣布新的语义修复算法。
