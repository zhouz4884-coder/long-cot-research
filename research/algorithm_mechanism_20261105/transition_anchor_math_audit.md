# Transition-Anchored VCORE：目标、约束与一步诊断的数学审查

日期：2026-11-05。**结论：propagation-span anchor 是可明确研究的条件监督目标，但附件尚未建立三方向正交、同 KL 即同 ESS/方差、同 LoRA 参数步长即同功能变化，或一步留出 loss 下降即泛化保证。特别是：把更新归一到同一 norm 后，原始 Gibbs 权重不再自动是这个新目标的一阶最优解。** 可以保留它作为待检验的 anchor 设计，不宣称新方法已成立。

已完整阅读新附件 `已粘贴的文本.txt`：14,093 bytes、7,378 字符、113 行，SHA256 `7366c6c946986ec2dbab8075197bac14e73d67e25cf8692a8e3cdd3f47983e1f`；同时读取 [上一轮梯度审查](D:/ACL/research/next_design_20261105/gradient_design_literature_audit.md)。下文区分原论文定义、本次推导、已执行 CPU 控制和未执行模型诊断。未连接远程、使用 GPU 或新增模型训练。

## 1. 先把目标函数写清楚

令 ψ 是固定 LoRA/可训练参数子空间；B 是主训练批次，B′ 是独立参考批次，H 是不参与 anchor/q 构造的留出批次。固定同一 ψ₀、teacher-forced 上下文与有效 token 支持集 I，n=|I|，定义：

\[
\ell_t(\psi)=-\log p_\psi(y_t\mid x,y_{<t}),\qquad
L_j(B';\psi)=\frac{1}{Z_j}\sum_t m_t^{(j)}\ell_t(\psi),
\quad g_j=\nabla_\psi L_j(B';\psi_0),
\quad j\in\{U,A,P\}.
\]

这里 P 表示 prop，不是 population。Z_j 是明确的 token/序列均值归一化常数，必须为正；没有合格 prop span 的参考例应记录为不适用/unknown，不能用 0/0 或零梯度悄悄补成正常 anchor。主批次 token 梯度记为 v_t=∇ℓ_t(ψ₀)，则一个可审查的设计为：

\[
s_t^{(j)}=\langle g_j,v_t\rangle,\qquad
q_j\in\arg\max_{q\in\Delta_n}\sum_tq_ts_t^{(j)}
\quad\text{s.t. }D_{KL}(q\Vert u)\le\delta,
\qquad u_t=1/n,
\]

\[
G_j=\sum_tq_{j,t}v_t,\qquad \Delta\psi_j=-\eta G_j.
\]

q 在实际 weighted-loss 反传时需要 stop-gradient；若继续对 q(ψ) 求导，会多出权重导数项，已不是上述更新。参考方向差分只近似此处的参数内积；三个参考方向通常需要分别取得三个 VJP 和相应主批次 probe，不能把一条总 loss 的 backward 当成三条独立方向。

这是把 VCORE 的参考目标换为条件过程目标后的局部诊断式。原 VCORE 的总体全链 loss、variance coefficient α 和 optimizer-aligned 扩展不能未经条件原样继承；首轮建议固定 α=1、无 momentum SGD。GRAIL 的 embedding saliency/RL 目标也不等于这里的参数内积。见 [VCORE 正式论文 §3–4、Appendix H](https://aclanthology.org/2026.acl-long.1298.pdf) 与上一轮审查。

## 2. 三个方向通常不正交，也不需要先强求正交

附件把 U/A/prop 称为三个“正交”方向，这在欧氏参数空间没有依据。如果 U 覆盖所有 token，A、prop 是其中互不相交的部分，按相同均值约定就有：

\[
g_U=\frac{n_A}{n}g_A+\frac{n_P}{n}g_P+\frac{n_O}{n}g_O.
\]

共享参数导致不同位置梯度可以同向、反向或相关，loss mask 不重叠也不能推出内积为零。极小反例为 g_U=g_A=g_P=(1,0)，三者余弦全为 1；这可以来自在同一参数上预测相同 token 的监督，完全符合梯度定义。

所以应改称“**三个不同定义的参考目标**”，实际报告 Gram matrix、cosine、norm 与相互线性解释程度。若 g_P 几乎落在 span(g_U,g_A) 中，新 anchor 可能只是已有信号的重配比；若不同，也只说明局部信息不同，尚非任务价值。可选的正交残差诊断是 `g_P−Proj_span(g_U,g_A)g_P`，但它改变了目标/噪声性质，残差可能为零，不能把 Gram–Schmidt 后的方向继续当成原 prop loss 的梯度或当作“发现了新机制”。

CPU 固定种子示例中 cos(U,P)=0.8361、cos(A,P)=−0.9579；这里只是代数接口控制，不是 Qwen 梯度测量。

## 3. prop-span 的监督信息、可观测性与循环验证

“首次受影响派生步且正确”比最终数字的位置更接近目标行为，但它不是免费可见标签：

- **合成精确 AST：** 可以知道修订的真伪、引用/作用域、第一受影响子步、独立支持与正确派生值；这是训练/诊断 oracle，不是自然任务已解决的检测器。
- **自然链：** 变量复用、单位、隐式约束、多个合法推导和不完整文本会使首次传播位置/正确性不可判。共现不等于依赖，最终答对也不证明这一步正确；需独立局部见证、unknown 与标注成本。
- **目标泄露：** teacher forcing 中，只监督 prop 位置并不自动消除复制捷径；若此前文本已写出同值/派生结果，模型仍可复制。因果 attention 阻止看未来，不阻止从已有上下文抄答案。应保留/核查前缀，不能把只换 loss mask 与删除已知值的效果混合解释。
- **选择偏差：** 只取成功且“正确修订”的参考例，优化的是条件子群；它不覆盖错误修订 W、无修订 C、没有合格 span 或本来不会传播的状态。U/A/P 还可能有不同有效监督 token 数与参考梯度估计方差。
- **循环验证：** 用同一解析器/teacher 选出“好 prop”，再用它生成的同一类表达评分，会偏向该标注器。至少分离 B/B′/H 的问题身份、固定局部正确性见证，在改名/换数/换规则与不同正确表达的 H 上复核；H 用来调 mask、δ 或挑 anchor 后，便不再是最终未见测试。

需要分别记录“正确修订后正确传播”的正样本、“错误修订应拒绝”的 W 样本和无错保持的 C 样本，不能把所有含新数字的跨度都奖励为推进。单一 token CE 也会惩罚不同但等价的正确表达；先声明是在优化参考表达 NLL 还是语义关系成立，二者不可互换。

## 4. 固定 KL 球面：何时可解，究竟控制什么

对固定非恒定分数 s，KL-ball 线性目标的活动约束解为：

\[
q_t(\beta)=\frac{e^{\beta s_t}}{\sum_ke^{\beta s_k}},\qquad \beta\ge0.
\]

设最大分数有 m 个并列位置。正 β 的 softmax 分布满足：

\[
D(0)=0,\quad D'(\beta)=\beta\operatorname{Var}_{q(\beta)}(s)\ge0,
\quad \lim_{\beta\to\infty}D(\beta)=\log(n/m).
\]

因此：

1. 非恒定 s、`0<δ<log(n/m)` 时有唯一有限正 β；δ=0 取 uniform。终点一般只在 β→∞ 的极限达到。
2. 若所有分数相等，任何 β 都给 uniform，不能调到正 δ；原 KL-ball 问题只是退化为所有可行 q 同样最优，并非应该人为挑出一个“语义尖锐”分布。
3. 整个 simplex 上的 KL 等式可行范围是 `[0,log n]`。有并列最大时，`log(n/m)≤δ≤log n` 可以存在等式可行分布，但不属于正 β softmax 的这一参数路径。对原 KL-ball，集中在最大分数支持上已最优，不要求用满预算；不能为“每臂完全相同球面”强制解一个该族不可达的温度。
4. 当 n/support、padding mask 或均值规则不同，同一 δ 不是同一个控制；应保持主批次的有效支持和先验 u 完全相同。有限精度近似并列、下溢、clip 与温度求根容差也需记录。

同 n 下 `KL(q||u)=log n−H(q)`，所以相同 δ **精确固定 Shannon 熵**。若分数仅作正仿射变换 as+b（a>0），精确校准会用 β/a 抵消尺度，q 不变；它确实能移除这一类纯 gradient-norm/score-scale 混杂。

但它不固定：

\[
\mathrm{ESS}(q)=1/\sum_tq_t^2,\quad \max_tq_t,
\quad\|G(q)\|^2=q^TKq,\quad K_{ts}=\langle v_t,v_s\rangle.
\]

同熵不等于同二阶矩；ESS 只有在额外的同方差/独立等假定下才可作为某类方差代理，token 梯度一般相关。不能由同 KL 推出 VCORE α 方差控制已被替代。

本次 CPU 反例在 n=3、δ=0.3 时：

| 分布 | q | Shannon H | ESS | max q |
|---|---|---:|---:|---:|
| A | (0.712853, 0.143573, 0.143573) | 0.798612 | 1.820213 | 0.712853 |
| B | (0.486495, 0.486495, 0.027009) | 0.798612 | 2.109325 | 0.486495 |

两个 KL 的数值差只有 2.22×10⁻¹⁶。把它们称为“完全相同尖锐度”会掩盖已不同的 ESS 和最大权重；准确说法是“同 KL/同 Shannon 熵的权重预算控制”。

## 5. 同 LoRA 参数步长有用，但不能保证同功能变化

对非零 G_j，可以另做明确的步幅控制：

\[
\Delta\psi_j=-c\,d_j,\qquad d_j=G_j/\|G_j\|_2.
\]

它消除参数空间欧氏步长大小的区别，保留方向区别。但不固定：有效 ΔW、输出函数变化、策略 KL、不同样本的 loss 变化、optimizer 的预条件方向，或梯度估计信噪比。LoRA 以 `W=W₀+(α/r)BA` 参数化，精确变化为：

\[
\Delta W=\frac{\alpha}{r}(B\Delta A+\Delta B A+\Delta B\Delta A).
\]

同一个 ψ₀ 下取 A=diag(1,10)、B=(0,0)、α/r=1：两步 ΔB=(c,0)/(0,c) 的参数 norm 都是 c，有效 ΔW norm 却为 c/10c。策略的局部 KL 约为 `½ΔψᵀFΔψ`，F 一般不是单位矩阵；**token 重权分布的 KL 与策略输出 KL 也不是同一种 KL**。

还存在 G_j=0 或接近零：CPU 构造中，非均匀 q=(0.1,0.3,0.6) 正好来自 anchor 内积的 softmax，但加权梯度为零；浮点残余 norm 为 2.22×10⁻¹⁶。正 c 的归一化方向此时没有定义。需预定阈值、记录零步/skip 和缺失配对，不能加任意方向或删掉失败臂来强凑“相同一步”。近零方向还会放大相对噪声，参数步幅匹配并不能修复它。

### 5.1 关键：norm 匹配后，原 Gibbs 最优性不能继续照搬

原线性 utility 是 `g_j·G(q)`，用于固定 η 的 SGD 一阶下降；norm 匹配后的参考一阶下降则正比：

\[
\frac{\langle g_j,G(q)\rangle}{\|G(q)\|}.
\]

分母依赖 q，已不是原线性目标。因此可以“先按原式构造 q，再把 norm 匹配当对照”，但不能声称该 q 仍解出了“固定一步 c 下的最优传播更新”。

明确反例：g_ref=(1,0)，两个 token 梯度为 (133,400/3)、(−32,−100/3)；q_A=(0.8,0.2)、q_B=(0.2,0.8) 的 KL 都是 0.192745。q_A 是该 KL-ball 上的线性 utility 最大解，得到 G_A=(100,100)，q_B 得到 G_B=(1,0)。原对齐是 100 对 1，norm 匹配后却是 0.7071 对 1，顺序反转。这个反例已执行 CPU 核验。

## 6. 一阶界、余项与留出泛化应怎样表述

若留出损失 L_H 在 ψ₀ 到 ψ₀+Δψ 的线段上二阶可微，Hessian 的算子 norm≤M_H，则：

\[
\Delta L_H=\langle g_H,\Delta\psi\rangle+R_H,
\qquad |R_H|\le\tfrac12M_H\|\Delta\psi\|^2.
\]

对 norm 匹配的下降方向：

\[
\Delta L_H\le-c\langle g_H,d_j\rangle+\tfrac12M_Hc^2.
\]

只有 `〈g_H,d_j〉>M_H c/2` 时，该上界保证下降。比较两臂时，余项差的绝对上界为 M_H c²；方向对齐的差别太小就不能保证实际排序。附件只固定 c，还未给出局部平滑常数或余项测量，不能省略二阶项。

同 norm 不同效果的最小反例是 `L_H(ψ)=½(ψ−1)²`、ψ₀=0、c=0.1：+0.1 的实际 ΔL=−0.095，−0.1 的实际 ΔL=+0.105。两者 norm 相同，且各自一阶余项均为 0.005。真正要核对的是一阶预测是否解释实际变化，而不是只看两个 loss 中谁小一点。

若目标是 population 损失 L_pop，另外设 `||g_pop−g_H||≤ε_H`、局部 population 平滑常数为 M_pop，则有：

\[
\Delta L_{pop}\le-c\langle g_H,d_j\rangle+c\varepsilon_H+\tfrac12M_{pop}c^2.
\]

这是带明确条件的界，**不是本项目已得到的泛化保证**。有限 H、领域/标签选择、可变长 loss 及参数自适应会影响 ε_H；本轮没有估计它。独立 H 的一次经验 NLL 下降也不自动推出生成正确率、W 组不受伤、跨域或多步训练泛化。用 H 选最好的 δ/c/anchor 后再称其独立测试，会产生选择偏差；需要下一份未参与选择的问题级留出复核。

## 7. 正确 prop anchor 不会自动保护 W

“新值向后正确传播”假定这个新值本来应该被采纳；“修订是否应该采纳”是另一个目标。只用正确修订样本训练 prop，不会自动学到 G 核验门，更不能用正确 prop anchor 的定义证明 W 安全。

CPU 反例：p(θ)=sigmoid(θ) 表示采用修订的概率；正确修订的传播 loss 为 `L_P=−log p`，错误修订 W 要求拒绝，loss 为 `L_W=−log(1−p)`。从 θ=0 迈一步 +0.1，正确 prop loss 改善 0.0487505，W loss 却增加 0.0512495。两者都是合法平滑二元 CE；正例 anchor 对齐和同 norm 控制不会消除此冲突。

如果目标需要 W 保护，应把它作为独立条件，例如单独的门控监督和留出 W/C 指标，或明确的约束 `ΔL_W≤ε_W`；这些会改变目标与可行域，需要重新分析。不能先只优化正例传播，再以“监督 span 都正确”代替 W 实测。

## 8. 一手近邻：能区别对象，不能先宣称新

本次按 `nature-academic-search` 的 manifest/core→multi-source-search/citation-verification 路由执行。专用学术 MCP 未挂载；预检 CrossRef/arXiv 可用、PubMed 返回服务器错误；OpenAlex 发现检索返回 HTTP 429，未重复轰击。回退到正式会议页、作者论文原文与已有库中的明确标识核验。以下是必要近邻，不是穷尽新颖性结论。

| 一手来源 | 与本提案直接相关的内容 | 应保持的区别 |
|---|---|---|
| [VCORE，ACL 2026，§3–4、Appendix H](https://aclanthology.org/2026.acl-long.1298.pdf) | 一步优化 utility、KL 约束 Gibbs 重权、参考梯度 probe、方差缩放与 optimizer-aligned 扩展。 | 换成 prop 目标是参考任务/监督改变，不会自动继承原总体目标解释；固定 norm 后目标又变一次。 |
| [DART，ACL 2026，§2 process advantage](https://aclanthology.org/2026.acl-long.649.pdf) | 树中节点成功价值，优势为全局差与父子局部差之和；子轨迹 token 继承相应 advantage。 | 给有益状态/动作分配局部信用已有。它使用 rollout 的结果与树结构，非 prop 参数梯度；成功可达性也不等同于每一步逻辑真值。 |
| [TRAE，ACL 2026，§4](https://aclanthology.org/2026.acl-long.1636.pdf) | 将 immediate correctness 与树估计的未来 return 合成 turn-level 信号，针对反思复制与探索塌缩。 | “只奖最终答案不足，要区别修订贡献”已有直接近邻；本目标若仅一次正确派生 NLL，不包含该长程 return。 |
| [ReST-MCTS*，arXiv:2406.03816v3，§3及限制](https://arxiv.org/html/2406.03816v3) | 通过树搜索/rollout 推断中间 value，联合自训练策略与过程模型，仍需正确答案/奖励反馈支持。 | 中间训练价值/可达成功并非精确传播正确性。标签与树采样不是免费监督，不能省掉其信息来源。 |
| [Let’s Verify Step by Step，arXiv:2305.20050，§2.6、§6.1](https://arxiv.org/html/2305.20050v1) | 显式比较最终结果监督与中间步骤反馈，使用人工步骤标签训练过程模型。 | “监督正确中间过程”本身已有；本提案的待检验差别只能落在修订后首次传播子群、anchor 对象、可核验标注和实际增量。 |

上一轮已核验的 LESS/GRAD-MATCH/TracIn/GRAIL 进一步覆盖目标梯度、梯度匹配、一步影响和答案锚定。当前没有找到足以证明“本提案完全相同”的一手实现，也没有完成足以证明新颖性的穷尽检索；正确结论是**机制对象更具体，创新与收益尚待验证**。

## 9. 已执行的 CPU 极小控制与复现

源码：[transition_anchor_algebra_controls.py](D:/ACL/research/algorithm_mechanism_20261105/transition_anchor_algebra_controls.py)；完整数值与输入：[transition_anchor_algebra_controls.json](D:/ACL/research/algorithm_mechanism_20261105/transition_anchor_algebra_controls.json)。只使用 Python 标准库双精度代数；解析反例先定义，随机梯度示例固定唯一 seed=20261105，没有挑 seed、训练模型或优化任务指标。

| 控制 | 实际结果 | 可得结论 |
|---|---|---|
| 同 mask 目标可给相同方向 | 解析例三方向 cosine=1 | 不存在由目标名字导出的正交性。 |
| 同 KL、不同 ESS | δ=0.3，ESS 1.820213 / 2.109325 | 同 KL 仅固定此处 Shannon 熵。 |
| 分数正仿射缩放后校准 | q 差小于 10⁻¹² | 精确同 KL 确实移除这类纯 scale 混杂。 |
| 常数分数/并列最大 | 正 δ 或超出 log(n/m) 的请求被判 softmax 族无有限解 | 温度校准要先检查可达性。 |
| 非均匀 q、非零 anchor、聚合梯度为零 | norm≈2.22×10⁻¹⁶，按 10⁻¹² 阈值保留 skip | 不可强制正 c 同步长。 |
| 线性 utility 与归一化 utility | 100>1，归一化后 0.7071<1 | 固定 norm 对照不能继承原线性最优性。 |
| 同参数 norm、实际留出 loss | −0.095 / +0.105 | 更新方向与二阶余项必须测。 |
| 同 LoRA 参数 norm、不同 ΔW | c / 10c | 不是功能空间或策略 KL 匹配。 |
| 正确 prop 与 W | prop −0.0487505，W +0.0512495 | 正例传播监督不自动拒绝错误修订。 |

脚本还对同一固定随机二次 loss 的内积/前向差分在 ε=10⁻²、10⁻⁴、10⁻⁶ 上核对解析误差；这是数值接口控制，不是深度模型的 ε 推荐。七个预设断言均通过。

## 10. 最小模型诊断建议：本次未执行

先不命名新算法、不训 100 步。由主任务在后续明确预算内另行决定：

1. 冻结固定 ψ₀ 与 LoRA 参数列表、参考上下文和 U/A/P 三个 mask；按问题隔离 B/B′/H，正例、W、C 都保留。先只取极少短样本，prop 标注 unknown 不强行补齐。δ/c 预定，不在 H 上找最优。
2. 取得三个独立参数梯度，报告 norm/Gram/cosine；主批次用逐 token 精确内积作极小 oracle，再核对差分、符号、精度与参数恢复。记录 VJP/probe 的真实次数，不称三 anchor 免费 one-backward。
3. 同主 token 支持校准 KL：先检查 β 可达范围、零/近零 anchor/aggregate gradient；报告 q 熵、ESS、最大权重、阶段总质量、G norm 和失败臂。等 KL 不替代 ESS/梯度协方差记录。
4. 从完全相同 ψ₀ 做各自独立的原始单 SGD 虚拟步；再单列同 c 方向控制。q detach，dropout/RNG/优化器状态一致，分支之间严格恢复。norm 控制是诊断，不冠以新的线性最优性。
5. 在 H 同时测实际 ΔL、`g_H·Δψ` 和残差；H_prop 的预结论输入排除复制捷径，H_W/C 单独报告伤害。零步、不适用和低于数值噪声的结果均保留；loss 结果不直接转换成生成正确率。

若 g_P 没有稳定独立信息、增益仅是 scale/步幅、只在 B′ 上改善、W/C 损害不可接受或一步残差大于对齐差，就停止扩大；允许改正数学叙事和保留负结果。若这些小控制都通过，也只支持进一步独立复核，不支持附件中“真正有效”“铁证”“两分钟保证”或新颖性已经成立的表述。
