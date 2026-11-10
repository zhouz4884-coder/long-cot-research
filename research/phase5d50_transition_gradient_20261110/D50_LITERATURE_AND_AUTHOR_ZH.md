# D5.0 文献边界与 VCORE 作者实现复核

2026-11-10。仅审阅论文和固定版本源码。未运行作者训练、读取研究数据或查看留出结果。本轮最接近的先例是 RECAP，已联合使用答案信号、依赖传播与带符号赋权。D5.0 的可检验区别在于以独立题的已验证 E/W/C 续写对定义参数方向，并检验该方向赋权后的真实一步更新能否提高留出修订裕量、同时保护原来正确的状态。[RECAP §4](https://arxiv.org/html/2609.27156v1#S4) · [D5.0 协议](D50_PROTOCOL_ZH.md)

## VCORE 的论文推导与可复现边界

VCORE 以均匀全链 token CE 定义参考损失 $L$。令 $v_t=\nabla_\psi\ell_t$，$g=\nabla_\psi L$，其中 $\psi$ 是实际更新的参数。若一步 SGD 使用固定权重 $q$，则

$$
L\!\left(\psi-\eta\sum_tq_tv_t\right)-L(\psi)
=-\eta\sum_t q_t\langle g,v_t\rangle+O\!\left(\eta^2\left\|\sum_tq_tv_t\right\|^2\right).
$$

在光滑性和参考梯度无偏等前提下，独立抽样参考批 $B'$ 后计算 $g'=\nabla_\psi L(B')$，在主批 $B$ 上以 $[\ell_t(\psi)-\ell_t(\psi-\epsilon g')]/\epsilon$ 估计投影。该差分对 $g'$ 的一阶误差受方向曲率和 $\epsilon$ 影响，浮点消减、随机前向及裁剪会另行改变估计。LoRA 实验测得的是其可训练子空间中的局部方向。附录 H 另推导平滑优化器在固定状态和小 KL 下的局部效用 $\langle J_k^\top g,v_t\rangle$。论文实跑使用 AdamW，下面源码的主探针路径直接用参考梯度扰动 LoRA，D5.0 固定 SGD 的诊断则直接对应上式。[VCORE 正文 §3–4、附录 H](https://aclanthology.org/2026.acl-long.1298.pdf)

“One-backward”按单个参考方向计数。主批须有扰动和原点两套前向损失，原点前向可兼作实际训练前向，最终一步更新仍需要反传。作者的批累积会逐参考微批反传。D5.0 的全链、答案、三态方向各需相应的独立导数与探针，公共原点前向在输入与随机性相同时可共享。单次反传求和只能得到一个合成方向。真实更新及留出前向均须计费。[VCORE §4.2](https://aclanthology.org/2026.acl-long.1298.pdf) · [作者训练循环](https://github.com/coder-gx/VCORE/blob/2dc91e161b1b06bb3876892c1930bbb194c5088b/llama_factory/src/llamafactory/train/sft/trainer.py#L1114)

### 固定源码证据

作者仓库 HEAD 为 `2dc91e161b1b06bb3876892c1930bbb194c5088b`。以下是固定提交原始字节的 SHA-256。[作者提交](https://github.com/coder-gx/VCORE/tree/2dc91e161b1b06bb3876892c1930bbb194c5088b)

| 文件 | SHA-256 |
| --- | --- |
| `README.md` | `39543cd04328ccea550120b7128caeff29e43ab02ff75298fe7359bd22e8c030` |
| `llama_factory/src/llamafactory/train/sft/trainer.py` | `c89f19e772c9e459566cd3f5668f789ad59cc782dc4ca72e336110182524acd8` |
| `transformers-4.52.4/src/transformers/loss/loss_utils.py` | `f77fdf6ad29896923e938eb9082e60d8b5ae659e98305ac7508062ca156cba54` |

- 单机探针先备份可训练且名称匹配 `lora_` 的参数，再在抽取的参考批上反传，可选裁剪后用 `p.add_(p.grad, alpha=-eps)` 扰动。主批扰动损失在 `no_grad` 下获取并保存为 `pre_loss`，随后恢复 LoRA 并执行原点训练步骤。这里的 `pre_loss` 表示扰动后损失。分布式主/支路交接同样由支路反传并产生探针结果。参考采样来自训练数据且有放回，未发现按原题显式隔离的检查。[单机探针](https://github.com/coder-gx/VCORE/blob/2dc91e161b1b06bb3876892c1930bbb194c5088b/llama_factory/src/llamafactory/train/sft/trainer.py#L1114) · [分布式探针](https://github.com/coder-gx/VCORE/blob/2dc91e161b1b06bb3876892c1930bbb194c5088b/llama_factory/src/llamafactory/train/sft/trainer.py#L973) · [参考采样](https://github.com/coder-gx/VCORE/blob/2dc91e161b1b06bb3876892c1930bbb194c5088b/llama_factory/src/llamafactory/train/sft/trainer.py#L1215)
- 实际 softmax logits 为 `(cur_loss - pre_loss)/(eps*T)`，与上面的符号一致。代码对有效 token 在序列内做掩码 softmax，随后乘回各序列的有效 token 数，再作全批有效 token 归一化。因此平均单位有长度权重。示例主/支路配置给 `T=5000` 和 `eps=0.0001`，权重路径使用固定温度。示例保留 LoRA dropout，所审路径未见为两次前向显式重放同一 dropout RNG。单卡样例脚本的 `use_vcore=False`，复现需要单独核对启动参数。[损失实现](https://github.com/coder-gx/VCORE/blob/2dc91e161b1b06bb3876892c1930bbb194c5088b/transformers-4.52.4/src/transformers/loss/loss_utils.py#L97) · [主路样例](https://github.com/coder-gx/VCORE/blob/2dc91e161b1b06bb3876892c1930bbb194c5088b/llama_factory/train_multi_main.sh#L13) · [单卡样例](https://github.com/coder-gx/VCORE/blob/2dc91e161b1b06bb3876892c1930bbb194c5088b/llama_factory/train_single.sh#L19)
- 论文 §4.1 以序列内均匀分布 $u$ 为先验，推导 KL 约束下 $q_\beta(t)\propto\exp(\beta s_t)$。代码用 `T`，当分数尺度一致时 $T=1/\beta$。相同固定 `T` 在不同样本和方向上一般产生不同 KL。D5.0 对各臂求同一 KL 属于额外控制。因为 $\frac{d}{d\beta}D_{\rm KL}(q_\beta\Vert u)=\beta\operatorname{Var}_{q_\beta}(s)$，全平分数或最大分数并列会限制可达 KL。若有 $n$ 个有效 token、$m$ 个并列最大值，有限正 $\beta$ 的 KL 上界为 $\log(n/m)$，上界只在极限取得。求根失败、数值并列和零方向应留痕。相同 KL 仍允许 ESS、最大权重及参数步长不同。[VCORE §4.1](https://aclanthology.org/2026.acl-long.1298.pdf) · [掩码 softmax 与长度归一化](https://github.com/coder-gx/VCORE/blob/2dc91e161b1b06bb3876892c1930bbb194c5088b/transformers-4.52.4/src/transformers/loss/loss_utils.py#L118)
- 论文 §4.2 的方差式针对标量随机投影 $\sum_t q_ts_t$ 的方差 $V_q$ 与均匀参照的 $V_u$，由此提出缩放 $\sqrt{V_u/V_q}$。固定乘数的等方差代数只涉及这一标量。算法 1 第 6 行则使用损失比，源码最终启用分离梯度后的缩放 `min(1, loss_uniform / loss_weighted)`，相邻显式方差计算已注释。论文动机与代码缩放需分别报告，目前无等价证据，也未运行源码测缩放效果。D5.0 同学习率主结果和同参数范数复核可以直接解释方向影响，作者固定温度及损失比应另作忠实口径。[VCORE §4.2 和算法 1](https://aclanthology.org/2026.acl-long.1298.pdf) · [缩放实现](https://github.com/coder-gx/VCORE/blob/2dc91e161b1b06bb3876892c1930bbb194c5088b/transformers-4.52.4/src/transformers/loss/loss_utils.py#L149)

## 邻近方法与创新重叠

| 工作 | 信号和干预对象 | 对本轮的直接边界 |
| --- | --- | --- |
| VCORE（ACL 2026） | 独立批全链 CE 梯度与训练 token 梯度做有符号投影，按 Gibbs 分布重加权 SFT。 | token 参数投影、一步梯度探针及 KL 赋权已有直接先例。用同支持、同 KL 的全链方向测试信号替换，再把作者固定温度口径单列。[论文](https://aclanthology.org/2026.acl-long.1298/) |
| RECAP（2026，预印本 v1） | 对同一模型的逐步前缀比较参考答案似然，得到带符号的步骤效用。判别器标注 DAG 的支撑、上下文和复述边，从终点向前分配责任。步骤权重联合责任、似然增量和序列优势的符号进入 GRPO。 | 答案锚定、依赖传播和考虑正负序列结果已经合在一项方法内。其差分改变输入前缀，本轮改变参数方向。其依赖由判别器标注，本轮 E/W/C 对必须用同一前缀和可核验证据定义。作者报告 Qwen2.5-Math-7B 对 GRPO 的四基准 pass@1 提升和 token 下降，不能外推为本轮 SFT 一步优势。[方法 §4](https://arxiv.org/html/2609.27156v1#S4) · [作者结果](https://arxiv.org/abs/2609.27156v1) |
| GRAIL（2026，预印本 v1） | 对模型自己 rollout 的最终答案做 teacher-forced NLL，用逐 token 嵌入处 gradient × input 的非负范数作为显著度，结合正确性奖励产生的序列优势做 GRPO。 | 答案损失回传来定位早期 token 已有先例。嵌入空间敏感度、序列奖励的符号和本轮共享参数空间中的有符号方向是三种信号。相同前缀的双续写可进一步检验方向偏好。[方法 §3](https://arxiv.org/html/2606.04889v1#S3) |
| LESS（ICML 2024） | 估计候选训练样本的 Adam 更新与目标小验证集损失梯度的相似性，跨 LoRA 预热检查点聚合，再按目标任务排名选样本。 | 用目标批梯度定义有用训练内容已有直接先例。LESS 面向样本选择，D5.0 比较同一主批内 token 权重，目标取同前缀下的核验式局部转移。[论文](https://proceedings.mlr.press/v235/xia24c.html) · [方法 §3–4](https://arxiv.org/html/2402.04333v2#S4) |
| SCoRe（ICLR 2025）、GRACE（EMNLP Findings 2023） | SCoRe 通过多轮在线 RL 训练自纠，记录正确到错误等转移。GRACE 训练步骤判别器区分共享上下文下的正确和错误候选步骤。 | 保护正确状态与同前缀正反候选各有先例。还需测三态核验目标能否改善一步后独立题的局部依赖保留，及是否需要训练 token 重赋权。[SCoRe](https://arxiv.org/html/2409.12917v2) · [GRACE](https://aclanthology.org/2023.findings-emnlp.1022/) |
| Risk-Aware Intrinsic Self-Correction（2026，预印本 v1） | 分开统计模型修正和改坏的结果，并对比保留、接受修订、条件触发等运行策略。 | 把改坏单列是已有评估原则。该文的结论和本轮独立方向批的一步训练检验属于不同层次。[摘要](https://arxiv.org/abs/2609.35832v1) |

## 一步测试可以区分什么

同一前缀 $P_i$ 下，以核验通过的续写 $a_i^+$ 和同粒度反例 $a_i^-$ 定义 $m_i(\psi)=\log p_\psi(a_i^+\mid P_i)-\log p_\psi(a_i^-\mid P_i)$。在独立 $B'$ 上取 $L_T=-\frac13\sum_{z\in\{E,W,C\}}\operatorname{mean}_{i\in B'_z}m_i$。E 需要将有效更新传到指定下游量，W 在错误改口下保护已验证状态，C 在前提未变时保持原依赖。每一对都须绑定题目证据、前缀及目标作用域。缺少同粒度对照或依赖尚未验证时，记为未知。主分析用同 token 长度，另报长度不齐。前缀末尾提前写出新下游值会让测试变成读出或抄写检查。[D5.0 协议](D50_PROTOCOL_ZH.md) · [此前的转移目标审计](../algorithm_mechanism_20261105/transition_anchor_math_audit.md)

该聚合损失只产生一个方向，E/W/C 在参数空间中可能抵消。用相同主批支持和 KL 比较全链、答案及三态方向时，留出 $H$ 上各态的实际裕量、线性预测、残差、零步和重复噪声比聚合均值更有解释力。若同学习率的差距在同参数范数下消失，证据更接近步长差异。若 W 或 C 受损，E 的改善不足以支持安全修订。即使三态优于答案锚定，仍只能说这套训练目标在当前留出上有增益。进一步比较同预算、同标注权限的直接成对更新，可检验收益是否需要经 $B$ 的 token 赋权。比较真正独立的原题与自然轨迹，才能排除对符号名、模板或选项分布的记忆。[D5.0 协议](D50_PROTOCOL_ZH.md) · [LESS 的目标梯度参照](https://arxiv.org/html/2402.04333v2#S4)

当前核对范围内尚未发现与“同前缀的核验式 E/W/C 方向加 VCORE token 投影，再用独立原题做真实一步配对验证”完全相同的实验。主要反证是答案锚定或直接成对更新已经达到同样效果，或三态方向在噪声、同范数和 W/C 对照下失去收益。若仅小规模 NLL 或裕量好转，论文主张应限于一步训练机制，最终正确率和自然长链效用需要另测。
