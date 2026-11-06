# 极小 P0 协议独立审查：late KV mask 与干净重算

2026-11-05。审查输入：`cpu_cache_consistency_control.py/json`、`generate_p0_cases.py`、`proposed_p0_cases.json`，以及 Transformers **v4.55.2** 的官方 Qwen3、mask 和 DynamicCache 源码。本轮只审查协议并写此文件，没有连接 GPU、SSH、下载模型或修改主脚本。当前本地 Transformers 是 5.4.0，故不能用本地包的行为替代目标环境 4.55.2 的验收。

## 结论与首轮边界

**可以执行一个单 V100、Qwen3-1.7B、FP16 eager、最多 16 个注入状态的接口/机制 P0。** 核心比较是：同一错误分支在生成后的读取阶段才被屏蔽，和该分支从 prefill 开始始终不可读、由此重新构建后继状态，是否得到不同缓存、读出分布和答案行为。

首轮推荐 **5 臂，单次贪婪续写，每臂最多 32 个新 token**。不训练、不采样搜参、不添加 steering、不扩展自然基准。GPU 目标累计 0.5 小时，单 GPU 硬上限 1 小时；预算包括加载、控制检查、所有 prefill/重复前向/评分/续写，不把隐藏重算从账本移走。结果完成后立即逐案例分析并停止首轮。

这里的“错误/修订”是人工预设的 teacher-forced 注入，不是模型自然犯错、自然识别矛盾或完成自纠。已有 CPU 控制证明的是随机 Transformer 中的缓存不一致现象；尚无 Qwen3/V100 的实测结果。

## 1. 输入审计与防泄露

已重新运行 `generate_p0_cases.py --check-only`：16 例，8 个旧分支错误/修订正确（E），4 个旧分支正确/修订不变（C），4 个旧分支正确/带 Wait 的修订反而错误（W）。精确整数验证通过；当前输入 JSON SHA256：

`6ffe069718396dc2543f85aa9270780f356e293cc9764afdaf2f06a083c5cc27`

**模型可见字段白名单只有 `question`、`old_branch`、`revision`。** 再加协议中预先固定、与答案无关的过渡文本和读出后缀。不能直接把整个 case 字典序列化进 prompt。

- **不渲染 `independent_conclusion`。** 它含精确 oracle 算出的正确 x，是 privileged 核验消息；若使用，必须另立“给定外部验证器”的实验，而不能混入本轮。
- `required_final_value`、`oracle_values`、`oracle_trigger_label`、`group`、正确性和错误终值等只供离线评分。它们不能决定某题是否实施干预、删哪一行、采用哪个摘要或何时停机。
- `revision` 在 E 组确实人为给出了正确中间 x；这是本轮共享的注入条件，必须如实声明。所有臂看到逐 token 相同的 `revision`，不新增 gold z/y 或“这是正确修订”的提示。因此本轮至多研究给定修订后的承接，不能宣称发现正确修订或提升独立求解能力。
- W 组的错误修订必须原样保留；不能因 oracle 认为它错就跳过删段。C/W 组也按完全相同的强制干预规则运行，才能暴露误触发代价。

## 2. 最小前缀与 token/位置约定

每个状态只构造一次原始 token 序列，保存完整 ID 和分段边界：

`P = 用户题目及固定模型模板`

`B = 原 old_branch（目标屏蔽段）`

`U = 无答案信息的固定过渡文本`

`R = 原 revision（所有臂共享的可见摘要/修订）`

检查点为 `P | B | U | R` 末尾。其后给每臂一个相同的新读出后缀 S，例如“\n按题目原始定义核算，最终 z=”，再最多贪婪生成 32 token。

U 只用于提供 B 之后的幸存状态和随机控制候选，例如重复“继续依据题目给定定义进行核算。”；固定其构造算法，使 `B∪U` 有足够候选 token，并限制全检查点不超过 **512 token**，优先 256 以内。不使用几千 token 的填充、不调整到模型出错才保留。B 后的 R 本身也属于可能已读过 B 的幸存后继；保留它的旧 KV 正是 late-mask 的待测对象。

模板固定为目标 tokenizer 的 `apply_chat_template(..., add_generation_prompt=True, enable_thinking=False)`，记录实际文本、special-token ID 与设置。如果目标 tokenizer 不支持该参数，先停在模板验收，不默默切为 thinking 模式。手工注入的草稿在 assistant continuation 中，不伪装为真实采样。

为避免 BPE 边界重分词，使 P/B/U/R/S 独立编码后显式拼接，段编码均不重复添加 special token；后续各臂直接选取同一 ID 序列，**禁止删完字符串再重新 tokenize**。这是人工 token 注入接口，需保留可还原的文本/ID 映射。

原始位置为 `0..L-1`，S 从 L 开始，生成 token 接续相同原始位置。主比较不压缩位置。若另做物理移除对照，幸存 token 仍使用原始、带空洞的 `position_ids`，S 也仍从 L 开始；不得用 `cumsum(attention_mask)` 或保留长度自动把 RoPE 位置重编号。

## 3. 优先的 5 个实验臂

为使首轮 FP16 比较更干净，**主 clean 臂采用全长度、同矩阵形状的 masked re-prefill**：保留原 token 槽位，但从整个 prefill 开始，对所有层/所有 query 屏蔽 B 的 key 列，再重新计算所有状态。被屏蔽槽位可以被计算，但永远不能被任何幸存 query 读取；它们不是“活跃可见上下文”。这与“仅在未来读取时屏蔽、保留旧后继状态”形成直接对照，同时不混入压缩 shape/位置的 FP16 差异。

| 臂 | 检查点状态如何建立 | S 及后续生成如何读取 | 用途 |
|---|---|---|---|
| A：Full | 原 P/B/U/R 正常 prefill | 只施加标准因果限制 | 未干预基线；也包含同一 R |
| B：Target-Late | 与 A 相同的原检查点 KV | 从 S 开始，额外屏蔽 B 的 key 列 | 直接 KV read-mask；旧后继 KV 未重算 |
| C：Target-Clean | 从 prefill 起就屏蔽 B 的 key 列，整前缀重算 | 继续屏蔽 B | 核心重算对照；与 B 同位置、同可见 token 集 |
| D：Random-Late | 与 A 相同的原检查点 KV | 从 S 开始，屏蔽固定随机列集合 J | 同可见删除预算的 late-mask 控制 |
| E：Random-Clean | 从 prefill 起屏蔽同一 J，整前缀重算 | 继续屏蔽 J | 随机屏蔽的重算控制；形成一个小型配对设计 |

J 从 `B∪U` 的 token 槽位中按固定 seed（建议 20261105 加 case ID 的稳定 hash）无放回抽取，`|J|=|B|`。保护 P、R、S；同一题 D/E 必须用同一个 J，且不根据答案或结果重抽。记录 J 命中 B/U 的具体数量。随机单位是 token，目标单位是整个人工指定 B，粒度差异应明确报告；本轮不把这一控制描述成已经解决所有语义特异性问题。

本主实验没有压缩 tensor 大小；**不得由 mask 的可见行数推断显存节省或吞吐收益**。它优先回答一致性。若时间足够，仅在既有 E01/C01 两个状态加“物理移除 + 原 position_ids + 冷 prefill”的等价性控制，不新增状态、不把它当第六个方法臂。它应与 C 接近；若不接近，先排查位置、mask、DynamicCache 槽位及 FP16 shape 差异。

## 4. 目标版本的接口要点

以下仅是固定源码给出的实现依据，目标节点仍需现场验收：Qwen3 eager 将 additive mask 加到 attention score，softmax 在 FP32 计算；显式 `position_ids` 参与 RoPE。自定义 **4D mask 在 masking_utils 中会直接返回**，因此调用者必须自行合成因果限制与 key 屏蔽，不能只提交“B 列禁读”然后假设库还会补 causal。DynamicCache 会追加并修改自身；各臂不得共享可变 cache 对象。[Qwen3 v4.55.2](https://github.com/huggingface/transformers/blob/v4.55.2/src/transformers/models/qwen3/modeling_qwen3.py)，[masking_utils v4.55.2](https://github.com/huggingface/transformers/blob/v4.55.2/src/transformers/masking_utils.py)，[cache_utils v4.55.2](https://github.com/huggingface/transformers/blob/v4.55.2/src/transformers/cache_utils.py)

建议单 batch、单活动臂、`.eval()` + `inference_mode()`，无量化、无 FlashAttention、无自动混精改变 dtype，显式 FP16/eager。先确认本地模型 manifest、`transformers.__version__ == 4.55.2`、实际 attention 实现和 `layer_types`；若有 sliding/hybrid 层，不能静默按 full attention 假定运行。`logits_to_keep=1` 用于普通续写；评分另外单独处理。

全长度主臂的 `cache_position`、序列槽位与原 `position_ids` 可保持一致。物理移除对照必须区分 **cache 存储槽位** 与 **模型 RoPE 位置**：压缩后槽位长度变小，但显式 `position_ids` 仍是原始位置；不能让库的默认 `position_ids=cache_position` 把二者混为一谈。首轮不用 `generate()` 内部的默认 mask/位置更新代替已验收的手动单步循环。

每个臂从独立构建的检查点开始；原 KV 可作为只读 CPU 快照，但恢复时需新 cache/tensor。候选答案评分前必须完成该臂的自由生成并另建评分状态；不能把 gold candidate 的 teacher forcing 追加进随后用于自由续写的 cache。

## 5. 真正开始比较前的四项控制

这些控制复用原 16 个状态，不新增合成状态；不要求“CPU float64 的 1e-11”在 V100 FP16 上成立。

1. **同输入重复。** 对 E01、C01、W01 用相同 shape、token、位置、mask、前向分块重复运行，测最大绝对 logit 差、概率 TV 和 KV 相对差，建立 FP16 数值底噪。额外比较无删除的 cached S 与完整前缀+S 重算，单列 shape/分块差异，不能将它们直接归为干预效果。
2. **真实禁读。** 只在 S 的首次前向取 attention，逐层汇总所有头对被屏蔽列及未来列的最大概率；必须为零或达到明示的实现精度界。对被屏蔽 KV 的 V 行赋有限、FP16 安全的 sentinel（例如 ±8），再读同一 S，输出应处于同输入控制误差内。不要把 CPU float64 控制中的 1e6 poison 直接用于 FP16，避免产生 inf/NaN。
3. **causal/局部不变控制。** B 之前的幸存 KV 在 A/C 中应在底噪范围内一致；同位置、同 token 的第一层幸存 K/V 也应一致。若第一层已经明显不等，优先怀疑位置/投影输入或 cache 对齐，不把它解释为高层历史残留。
4. **clean 独立重建。** C 另行从同一 token/mask/位置重算，应复现 C 的状态与 S 输出；有限时间内可加上述两例物理移除等价性检查。检查每层 cache 长度、key/value 形状、dtype、device、保存/恢复前后的 hash 或摘要范数。不能仅凭 mask 张量里有零认定后端真的禁读。

任一控制失败：标记 `P0_INTERFACE_NO_GO`，保留失败前向与配置，立即停止行为效果解释；不继续跑完 80 个臂凑结果。

## 6. 指标：分布、缓存与行为分别报告

**主机制指标（B 对 C；并报告 D 对 E）：**

- 同一个 S 最后位置、全词表 next-token 分布的 TV / JS，以及 logit 最大绝对差；转换到 FP32 后归约，保存必要摘要和 top-k，不只看 argmax。
- 每层幸存 KV 的最大绝对差和相对 L2 差；按“B 之前 / B 之后 U / R”分组。共享位置下的高层差异才对应待测历史依赖；整个 tensor 的最大值不足以定位。
- 被屏蔽 key/未来 key 的最大 attention mass、no-op 数值差、是否有非有限值。

**行为指标（16 例描述性计数，不做总体准确率外推）：**

- 每臂最终输出能否解析成单个整数、是否等于题目定义的 z；逐例列出 A/B/C/D/E 结果。
- E 组是否回到 `old_wrong_final_value`；W 组是否服从错误修订的 `revision_implied_final_value`；C 组是否被干预破坏。这里是“注入旧分支/修订的答案承接”，不能把它命名为自然旧错复发率。
- 在隔离的离线评分调用中，计算完整候选整数序列的 logP（并固定终止分隔符），分别看正确值、旧分支值和修订推出值；去重重合候选。候选只供评估，不用于选择生成答案或方法。E 可报告正确值对旧错值的 log-odds，W 可报告正确值对错误修订值的 log-odds；C 无不同旧错候选时记 NA。不要把单个首数字 token 的概率当完整答案概率，也不要比较未声明的长度归一化分数。
- 每臂真实 prefill token、decode token、评分 token、所有重算、GPU 时间与峰值显存。此 P0 不评吞吐优胜，但必须保留成本。

机制差异需要超过该指标的 no-op 控制噪声。可预先采用“高于相同路径控制最大误差十倍，且 logit 最大差高于 1e-3”的筛查阈值；该阈值只是 FP16 工程筛查，须同时显示原始差值和噪声，不是统计显著性或因果正确性的证明。若 cached/full-recompute 分块控制噪声较大，单独标记，优先依赖同 shape 的主比较。

## 7. 一次短跑的调度和停止规则

冻结顺序为四个平衡小块：

`[E01,C01,W01,E02] → [E03,C02,W02,E04] → [E05,C03,W03,E06] → [E07,C04,W04,E08]`

先在第一块完成控制和五臂。只有接口通过才继续剩余块；继续与否不看哪个臂表现更好。每个状态五臂结束即写一条完整记录并 flush，避免超时只剩半成品。目标 30 分钟内结束；到 30 分钟不再扩大计划，到 55 分钟停止启动新状态并写报告，60 分钟前进程退出。硬时限仍以单 GPU 正式作业 walltime/实际累计占用为准；下载、长装包或环境重建不属于这次短跑。

最多 `16×5×32=2560` 个自由生成新 token，外加少量同状态控制和候选评分；不通过多种 seed/温度/填充长度扫描来找阳性。若只完成部分块，按实际完整状态报告，不用部分结果填满 16 例。

结果立即按以下顺序解释：

| 观察 | 可得结论 | 不能声称/后续决策 |
|---|---|---|
| 禁读、位置、no-op 或 clean 重建控制失败 | 接口尚未被验证 | 立即 NO-GO；只修这一个实现问题，不解释纠错效果 |
| B/C 高层 KV 与分布差均在噪声内 | 本设置未观察到可分辨的残留效应 | 停止扩大；检查短前缀/强修订是否已覆盖该现象，不把 CPU 结果强套到此模型 |
| KV/分布差明确，但整数答案相同 | 真实模型中存在状态差异，当前任务可能有行为天花板或鲁棒性 | 只报告机制；不因 argmax 相同判所有干预无效，也不宣称提高正确率 |
| C 改善 E，但 D/E 随机控制同样改善 | 有一般屏蔽/重算效应的可能 | 不支持“证伪特异性”；不扩展成语义 KV 算法 |
| C 优于 B，但 W/C 控制出现新伤害 | 重算可能强化错误修订或删除有用信息 | 不能用 Wait 触发上线；先解决证伪与检测，而非扩大压缩率 |
| E 组 C 相对 B 有至少两例净修复、对应候选分数同方向且超过噪声，C/W 没有新增错误，目标变化优于随机控制 | 有继续一次独立小复核的理由 | 仍仅是 16 例人工状态上的启动信号，不是显著性/自然数据性能证据；下一轮先换独立状态复核，不直接训练或大跑 |

上述“至少两例”是固定成本下的探索门槛，不是正式统计检验；必须把全部正反案例和候选分数一起交付。若没有满足继续条件，结论是本次 P0 不足以支持扩大，不临时增加样本/参数直到成功。

## 最小交付字段

每条记录至少保留：case ID、输入 JSON hash、模型/源文件 manifest、tokenizer/template/thinking 设置、三段可见文本与完整 token IDs、B/U/R/S 范围、原 position IDs、随机 J、4D mask 规则与校验结果、cache 形状/重建路径、各指标/原始输出、greedy 设置/随机控制 seed、耗时和峰值显存。原始 gold 与 group 留在独立评分记录；记录中可引用但不能被 prompt renderer 使用。

已有 CPU 结果文件的边界继续适用：它是缓存一致性机制控制，不是训练模型的自然纠错收益。此协议的交付同样允许 `INTERFACE_NO_GO`、`MECHANISM_ONLY`、`NO_BEHAVIORAL_GAIN`；完成这个短跑并分析即可结束首轮。
