# VCORE / 答案锚定一步诊断：原文、代码与最近邻审查

日期：2026-11-05。**结论：可以先做参数梯度与一阶代理的极小诊断，不能把“答案锚定”“阶段解耦”重命名为新算法或因果重要性。** VCORE 的 one-backward 指一个参考方向的一阶探测，不是一遍普通反传免费得到两个独立anchor；STOP 的ECN也不是首次出现正确数字的正则位置。

本次仅阅读本地62篇库定位条目，再在线核验原始会议页、论文全文和作者代码；未连接GPU/服务器、未训练或运行论文代码。按 `nature-academic-search` router→manifest/core→citation-verification 工作流执行。专用学术MCP未挂载，改用公开原始论文和作者GitHub只读工具。先前文档仅作线索，不继承其核验结论。

## 1. 身份与正式来源

| 工作 | 准确身份与原始来源 | 核验状态 |
|---|---|---|
| VCORE | Xuan Gong、Senmiao Wang、Hanbo Huang、Ruoyu Sun、Shiyu Liang；*VCORE: Variance-Controlled Optimization-based Reweighting for Chain-of-Thought Supervision*；[ACL 2026 long.1298](https://aclanthology.org/2026.acl-long.1298/)，pp.28161–28180，DOI `10.18653/v1/2026.acl-long.1298`；[正式PDF](https://aclanthology.org/2026.acl-long.1298.pdf)；[arXiv 2510.27462v2](https://arxiv.org/abs/2510.27462) | 正式元数据/全文verified；作者代码只读核对，未复现。不是别的同名VCORE。一个聚合检索误配的arXiv `2510.27243`实际是向量数据库论文，已排除。 |
| STOP | Chenjun Xu等；*STOP: Structured On-Policy Pruning of Long-Form Reasoning in Low-Data Regimes*；[Findings EMNLP 2026.672](https://aclanthology.org/2026.findings-emnlp.672/)，pp.14109–14125；[正式PDF](https://aclanthology.org/2026.findings-emnlp.672.pdf) | 正式元数据/全文verified；是Findings，不能无差别简称主会发表。 |
| GRAIL | Tej Deep Pala、Vernon Toh、Soujanya Poria；*Gradient-Reweighted Advantages for Reinforcement Learning with Verifiable Rewards*；[arXiv 2606.04889v1](https://arxiv.org/html/2606.04889v1) | 原始预印本verified；不额外认定会议接收。 |
| LESS | Mengzhou Xia等；*LESS: Selecting Influential Data for Targeted Instruction Tuning*；[ICML 2024正式页](https://proceedings.mlr.press/v235/xia24c.html)，PMLR235:54104–54132；[作者原文](https://arxiv.org/html/2402.04333v2) | 正式发表/全文verified。 |
| GRAD-MATCH | Krishnateja Killamsetty等；[ICML 2021正式页](https://proceedings.mlr.press/v139/killamsetty21a.html)，PMLR139:5464–5474；[正式PDF](https://proceedings.mlr.press/v139/killamsetty21a/killamsetty21a.pdf) | 正式发表/公式verified。 |
| TracIn | Garima Pruthi、Frederick Liu、Satyen Kale、Mukund Sundararajan；[NeurIPS 2020正式页](https://proceedings.neurips.cc/paper/2020/hash/e6385d39ec9394f2f3a354d9d2b88eec-Abstract.html)；[正式PDF](https://proceedings.neurips.cc/paper_files/paper/2020/file/e6385d39ec9394f2f3a354d9d2b88eec-Paper.pdf) | 正式发表/公式verified。 |

## 2. VCORE精确对象与one-backward的信息条件

以下数学定义来自正式PDF §3–4，核心为PDF第3–5页/印刷页28163–28165；Eq.(1)/(2)、§4.1 Step 1–3、Algorithm 1。与原文区分：后续关于两anchor、信息泄露和诊断的结论是本次推导。

令token loss为

\[
\ell_t(\theta;x,y)=-\log p_\theta(y_t\mid x,y_{<t}),\qquad
L(\theta)=\mathbb E_{(x,y)\sim P}\Big[\frac1{|y|}\sum_t\ell_t\Big].
\]

原文Eq.(1)是对重权单步后的**population全轨迹SFT loss**求优化：

\[
\min_q L(\theta^+(q)),\quad \mathrm{KL}(q\Vert u)\le\delta,
\qquad u_t=1/|y|.
\]

§4.1在SGD、小步长一阶近似下定义Eq.(2)：

\[
s_t=\langle\nabla_\theta L(\theta),\nabla_\theta\ell_t(\theta;x,y)\rangle,
\qquad q_t^*=\frac{e^{\tau s_t}}{\sum_j e^{\tau s_j}}.
\]

它是**参数空间的方向对齐**，不是输入embedding梯度、attention权重或某层activation方向。正文无“只对最终答案正确率优化”的等价结论。[正式PDF §3–4.1](https://aclanthology.org/2026.acl-long.1298.pdf)

Step 3从独立参考batch \(B'\) 得到

\[
g_u=\nabla_\theta L_{B'}(\theta;u),\qquad
\widehat s_t(\epsilon)=\frac{\ell_t(\theta;x,y)-\ell_t(\theta-\epsilon g_u;x,y)}{\epsilon}.
\]

在平滑、小\(\epsilon\)、\(B'\)独立且其梯度无偏的条件下，\(\lim_{\epsilon\to0}\mathbb E_{B'}\widehat s_t=s_t\)。一次参考反传先产生一个\(g_u\)，再在主batch对所有token做同方向的前向差分。baseline token loss也必须存在；若后续执行学习更新，主batch weighted loss的反传仍需另计。“one-backward”没有消除参考forward、基线forward、扰动forward或最终update backward。[正式PDF §4.1 Step 3、Algorithm 1、Appendix G](https://aclanthology.org/2026.acl-long.1298.pdf)

**本次技术推论：**

- 若改为答案anchor \(L_a\)，需先取得\(g_a=\nabla_\theta L_a\)。这把所估目标改成答案NLL的局部下降，不能仍宣称是原VCORE population全轨迹目标的无偏估计。
- 同一参考forward可共用计算图，但要分别保留\(g_u\)与\(g_a\)，通常需两个VJP；对\(L_u+L_a\)做一次scalar backward只得到\(g_u+g_a\)，不能从和恢复两者。batched VJP/Jacobian接口可以一次API调用承载两条cotangent，工作量和内存仍需按两方向记账。
- 对两个参考方向估计所有\(s_t\)，共用一份baseline后仍需两个perturbed forward，或两方向JVP。不能把“每个方向one-backward”写成“两anchor总共one-backward”。
- 以\(B'=B\)或复用自身答案做参考，可作自对齐诊断，但独立参考batch的原无偏条件不再成立，含self-influence；必须单独标注。
- 如果只对LoRA或某参数块求梯度，\(\theta\)应明确改写为该子空间\(\psi\)。所得分数不是全参数分数。新LoRA常有一因子零初始化，另一个因子的初始梯度可能全零；初始化、trainable列表和参数dtype均需记录。

### 2.1 alpha与优化器不能靠同名替代

正文§4.2（PDF第4–5页）定义的是标量utility聚合的方差：

\[
V_q=\mathrm{Var}[\sum_tq_ts_t],\quad
V_u=\mathrm{Var}[\sum_ts_t/|y|],\qquad
\alpha=\sqrt{V_u/V_q}.
\]

这不是未经条件即可等同的整条参数梯度协方差匹配。极少参考样本也不足以稳定估计其方差。本轮最小诊断应先固定\(\alpha=1\)看方向/权重差别，避免把scalar幅度和anchor混在一起；若后续测试alpha，另立清晰实现分支。

正式PDF Appendix H（PDF第18–19页/印刷页28178–28179）还引入固定optimizer state下的update-map Jacobian \(J_k\)，optimizer-aligned utility为

\[
\widetilde s_t=\langle J_k^T\nabla L,\nabla\ell_t\rangle.
\]

因此简单SGD内积并不能自动预测AdamW实际一步的loss下降。初始Adam矩估计、clipping、weight decay、LoRA参数化都影响更新；先用无momentum SGD做一阶鉴别，再谈AdamW，或显式实现并核对其映射。[正式PDF Appendix H](https://aclanthology.org/2026.acl-long.1298.pdf)

## 3. 作者公开代码与正文之间必须保留的差异

固定作者仓库commit：`2dc91e161b1b06bb3876892c1930bbb194c5088b`（本次只读，不运行）。[作者README](https://github.com/coder-gx/VCORE/blob/2dc91e161b1b06bb3876892c1930bbb194c5088b/README.md)链接的arXiv为正确的`2510.27462`；其评测全套脚本尚非全部发布。

| 核对点 | 可核查代码位置与实际行为 | 对最小实验的影响 |
|---|---|---|
| probe的对象 | [trainer.py L973–1019 / L1114–1173](https://github.com/coder-gx/VCORE/blob/2dc91e161b1b06bb3876892c1930bbb194c5088b/llama_factory/src/llamafactory/train/sft/trainer.py#L973)：参考batch反传、可clip，随后只给LoRA trainable参数加\(-\epsilon g\)；单进程分支计算probe loss后恢复权重。 | 是参数扰动，不是activation steering。clip后的方向也不能直接套未clip无偏推导。不要原位修改后漏恢复。 |
| `pre_loss`名字 | 同文件L1163–1173实际保存的是**扰动后**token loss，再恢复baseline参数。 | `cur_loss-pre_loss`的符号是baseline减probe，并非bug；只看变量名会把符号反转。 |
| temperature映射 | [loss_utils.py L118–129](https://github.com/coder-gx/VCORE/blob/2dc91e161b1b06bb3876892c1930bbb194c5088b/transformers-4.52.4/src/transformers/loss/loss_utils.py#L118)：\(q=\mathrm{softmax}[(L_{base,t}-L_{probe,t})/(\epsilon T_{code})]\)。 | 与正文\(\mathrm{softmax}(\tau s)\)对应时，需\(T_{code}=1/\tau\)，不能把同名超参直接代入。应先逐token对比q；尚未运行，不能认定论文结果无效或代码复现已通过。 |
| alpha实际实现 | [同文件L149–165](https://github.com/coder-gx/VCORE/blob/2dc91e161b1b06bb3876892c1930bbb194c5088b/transformers-4.52.4/src/transformers/loss/loss_utils.py#L149)：variance公式被注释，实际\(c=\min(1,L_{uniform}/L_{weighted})\)，两loss取detach比值。正式论文Algorithm 1第6行也写uniform/reweighted loss ratio。 | 作者算法伪代码已有ratio口径，不应描述成代码擅自改法；但它与§4.2的\(\sqrt{V_u/V_q}\)数学等价条件未证实。将“loss-ratio实现”与“数学式alpha”分列。 |
| dropout/normalization | 作者训练脚本含LoRA dropout；loss按有效token数、每序列权重缩放后聚合。 | 差分probe要固定随机性，否则loss差混入dropout；均值/sum/长度缩放及方向norm会影响Gibbs温度。 |

**判定：书目/公式verified，当前公开代码与正文的逐项等价性尚未验证。** 不能直接启动两个新anchor然后称“已忠实复现VCORE”。本轮应先实现清晰数学版诊断；若要复现作者结果，必须另解上述映射和实现选择。

## 4. STOP：ECN、首次出现答案与安全截断是三个对象

正式PDF §2.3（PDF第4页/印刷页14112）的ECN要求结点既是**回答本题的conclusion**，又与金标相符；中间结论与answering conclusion分开。显式答案可做归一化匹配；隐式/歧义结点用\((q,a^\star,N_i)\)交给annotation model判断。Appendix A.4（PDF第12页）提示还要求结点构成完整、逻辑充分的解答。Limitations（PDF第9页）明确它是oracle训练数据构建规则，不是可部署早停保证。[STOP原文](https://aclanthology.org/2026.findings-emnlp.672.pdf)

用本报告记号转写（不是原文编号公式）：

\[
k_{ECN}=\min\{i:\mathrm{AnsweringConclusion}(N_i)\land
\mathrm{Correct}(N_i;q,a^\star)\},\qquad y_{\le k_{ECN}}.
\]

而**Appendix D.3，PDF第17页/14125**的\(k^\star=\min\{i:A^\star\text{ appears in }N_i\}\)只是结构统计：\(A^\star\)从最后一个含boxed/“Final Answer”的source node抽取，没有proxy则该轨迹不进入相关指标。这不是§2.3的ECN，更不是“看到正确数字就可以安全截断”。该指标的定义来自本地用户指向的正式全文，已对照在线正式PDF。

本次分析得到的边界：

- 正确数字可能是猜测、被否定的假设、引用、子问题答案，或重复出现；最早字面匹配不足以确认complete conclusion。
- 即使某个人工核验前缀已正确，是否能让未修改模型立即稳定输出、以及用截断数据训练后的迁移表现，是另两个经验问题。
- ECN用gold可合法用于离线训练/诊断，但须隔离于推理触发信号。后ECN不等于每一token均无训练价值；后来验算也不能从原表格差异直接认定为精度改变的原因。
- STOP主表和Gemini附表的annotation版本不同；讨论中的53.3→46.7等数值不能混入别的表或归因成“少一次验算导致”。

## 5. 最近邻：哪些思想已有，哪些仍需独立证据

| 工作/公式位置 | 已有对象和公式 | 对“答案锚定”新意与机制的限制 |
|---|---|---|
| GRAIL §3.1–3.3，[原文](https://arxiv.org/html/2606.04889v1) | \(L_{ans}=-\sum_{t\in\mathcal F}\log\pi_\theta(o_t\mid o_{<t})\)；\(s_t=\|\partial L_{ans}/\partial e_t\odot e_t\|_2\)。log标准化/clip、stop-gradient后重权RL advantage。answer内部、delimiter与post-answer/EOS另作权重纠正。 | “由最终答案loss指导中间token重权”已有直接近邻。它是输入embedding局部敏感度、RLVR目标，不是VCORE参数内积或SFT Gibbs分布。换成参数内积是差异，不自动构成创新。 |
| LESS §2 Eq.(1)、§3.1/3.2 Def.3.1，[原文](https://arxiv.org/html/2402.04333v2) | 目标few-shot示例loss梯度与候选训练例的Adam方向作cosine similarity，并跨checkpoint、按学习率加权；warmup、LoRA和投影做成本控制。 | 目标anchor、梯度对齐、一阶目标loss下降代理已有。LESS是sequence selection；token层与ECN阶段可作对象差别，但不能声称首次目标锚定。 |
| GRAD-MATCH §2及§3 Eq.(1)–(3)，[正式PDF](https://proceedings.mlr.press/v139/killamsetty21a/killamsetty21a.pdf) | 选择子集与权重去匹配training或validation梯度，核心误差\(\|\sum_{i\in X}w_i\nabla L_i-\nabla L_{target}\|_2\)，再正则化/OMP选择。 | “让加权梯度接近一个目标梯度”不是新命题；与单个内积排序也不完全相同，包含梯度之间的冗余/合成效应。 |
| TracIn §3.2、§3.3 Eq.(1)，[正式PDF](https://proceedings.neurips.cc/paper_files/paper/2020/file/e6385d39ec9394f2f3a354d9d2b88eec-Paper.pdf) | \(\mathrm{TracInCP}(z,z')=\sum_i\eta_i\langle\nabla\ell(z;\theta_i),\nabla\ell(z';\theta_i)\rangle\)。原文也要求核对预测的一阶变化与实际loss变化。 | loss-gradient内积及checkpoint attribution已有。单次局部proxy不是长训练的精确删除因果效应。 |

### 5.1 特别容易混淆的两类“尾部无贡献”

下式是因果attention图的结构结论，\(t\)在\(L_{ans}\)所含最后答案位置之后时：

\[
\frac{\partial L_{ans}}{\partial e_t}=0.
\]

但共享参数\(\theta\)下，通常**不能**推出

\[
\langle\nabla_\theta L_{ans},\nabla_\theta\ell_{tail,t}\rangle=0.
\]

尾部监督改变共享参数，可能帮助也可能伤害其他位置/题目的答案预测。因此，若embedding-gradient方法发现post-answer零分，有一部分是图结构预设；不能拿它当“VCORE尾部污染”的新实证。把anchor放在首次ECN位置而后续token梯度自动消失，也不能再用这件事验证“尾部语义无用”。

## 6. 答案anchor本身的风险：不能只换loss mask就说学到了推理

以下是本次审查的可证伪分析，不是上述论文已经证明的事实。

1. **上下文拷贝。** 用完整teacher-forced CoT后的最终答案NLL作anchor，可能只衡量复制已写出的数字/格式。它不等价于不看已知答案的独立解题能力。固定参考上下文、只改监督mask，与删尾/移动答案位置必须分开。
2. **目标泄漏与循环验证。** 用\(B'\)选q再只报告同一\(B'\)答案NLL下降，有明显目标复用；至少保留不参与anchor构造的\(H\)测量一步loss变化。测试题金标不得用来选q、调温度或选择anchor。
3. **长度不是梯度污染比例。** 40%尾token不意味着40%参考梯度，也不意味负效用。按同一均值约定分解\(g_{all}=g_{pre}^{contrib}+g_{tail}^{contrib}+g_{ans}^{contrib}\)，报告各norm、相互cosine和带符号投影；投影可为负或超过1，不能当概率。
4. **温度与步幅混淆。** 更换anchor会改变gradient norm，从而改变softmax尖锐度和实际步长。原始量、单位方向量、q熵/ESS与更新norm应并列；不要把纯scale变化叫语义改进。
5. **优化目标不等于行为。** teacher-forced答案NLL下降只是代理变化。要有任务效果结论，另需不含gold提示的固定生成与预冻解析；不能从一个参数虚拟步外推完整SFT或长期泛化。

## 7. 极小且按先后执行的诊断方案（本次未执行）

**第0步：先冻结对象，半页协议足够。** 指明是“VCORE数学式的SGD局部诊断”，还是“作者当前代码复现”；首轮建议前者。固定\(\theta_0\)/模型、trainable子空间、tokenizer、loss mask/均值、两anchor、参考batch \(B'\)、主batch \(B\)和留出\(H\)。只研究full-CoT anchor对answer-only anchor；暂不同时加STOP截断、单验证buffer、alpha、AdamW或训练100步。

**第1步：CPU tiny的精确导数接口控制。** 在固定随机小模型/短序列上，用少量token的逐token参数autograd做合法oracle，核对其与方向差分/可用JVP的符号和数值；同时核对两个anchor各自的VJP、sum-backward仅得和、同输入重复、\(\epsilon=0\)无变化、参数逐字节恢复。固定两三个用于精度鉴别的epsilon，不按任务收益搜参。若方向/归一化/恢复失败，在此停止修接口。

**第2步：真正的模型仅做一次短梯度画像。** 将来由主任务明确调度授权后，冻结最多4条短、人工核对过结论边界的轨迹，至少包括“正确数字早出现但不是conclusion”和“ECN后含真正验证”的反例；固定两条参考、两条主/留出用途，不根据当前模型结果筛选。首轮在可承受的明确LoRA子空间中、最多512 token、eval/dropout关闭，取两个参数梯度方向及分段贡献；不持久化参数更新、不训练。先测一次加载+单F/B成本，再决定余量；不按论文的4×5880结果承诺3090两小时。

每个anchor至少记录：参考FWD/VJP数、主batch baseline/probe FWD数、参与求导参数和dtype、gradient norm/cosine、每token有符号utility、按阶段的q质量相对uniform的比值、q熵/ESS、finite-difference是否越过权重量化下限、全阶段耗时/峰值。LoRA权重应在足够精度下扰动；FP16/BF16中很小epsilon可能根本不改变存储值。activation梯度可作为GRAIL式**另一指标**，不能偷换参数空间oracle。

**第3步：画像有稳定差异后，才做单步预测验证。** 从同一\(\theta_0\)分别建立uniform、full-anchor q、answer-anchor q三个**独立单SGD虚拟步**；q/方向均detach，重置参数后再试下一臂。先保留原始步幅，再加一次匹配update norm的明确控制，避免靠大步长取胜。用未参与选q的\(H\)测答案NLL真实变化，比较\(-\eta\langle\nabla L_H,g_{update}\rangle\)预测与实测；列全部正负例、前缀/尾部差异，不做100步或全数据微调。

第3步本身已经是参数更新实验，**不在本次“只核验文献、不训练”的任务中执行**。单步小量loss变化若没有超出same-input重复/恢复误差，或只在参考batch改善、留出无改善，结论应为局部假说未获支持；不扩队列。

### 首轮能回答与不能回答

| 观察 | 可得到的窄结论 | 不能推出 |
|---|---|---|
| 两anchor给出不同参数方向/q | 目标定义改变了局部学习信号 | 尾部废话污染已被证明、答案anchor创新成立 |
| 同形状FP32/可核对精度下差分符合精确内积 | 一阶probe实现可用 | 长期训练有效、AdamW也服从同一预测 |
| 特定尾部方向损害留出答案NLL，去除后一步改善 | 这些固定样例/参数子空间存在可重复局部失效 | 所有post-ECN都无用、训练因果机制普遍成立 |
| 原始步有益，匹配norm后消失 | 步幅/温度解释更可能 | 语义阶段特异性收益 |
| 独立H一步改善且反例无新增伤害 | 有理由设计下一次独立短复核 | 可发布新方法、两小时完整训练承诺 |

最终判断：先检验“全链reference在何种固定反例中产生错误的局部优化方向”，再讨论如何消除此失效。若没有失效证据、或答案锚定只改变scale/拷贝目标，则保留负结果，不通过命名或加模块制造创新。
