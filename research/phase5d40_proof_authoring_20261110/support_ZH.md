# D4.0 已观察的证明候选支持

先按 [D4.0 题目冻结](D40_SOURCE_SELECTION_FREEZE.json) 和 [支持提取规则](support_freeze.json) 复核两份发布归档。保留 11 个未解状态和同族 20 个已解对照的全部步骤。每个步骤的 SHA-256 与 D3.9 全量账本一致。`p104` 的同目标状态 `p142` 另入查重索引，不增加主样本题数。初始失败来自作者构造，模型尝试来自实际归档运行。[作者发布版本](https://huggingface.co/datasets/Karifannaa/BlueprintTrace/tree/504b7ae3604f363a3cf5e32308b08d2ac258ac25)

| 归档证据 | 11 个未解目标 | 20 个已解对照 |
| --- | ---: | ---: |
| 轨迹 / 步骤 | 66 / 528 | 120 / 673 |
| 有明确模型代码或结构化工具动作 | 518 | 659 |
| 有当次可见的当前模块源码 | 383 | 491 |
| 可绑定作者检查的物化候选源 | 440 | 577 |
| 另有作者装配的模块源 | 0 | 2 |
| 明确 `split_node` 调用 | 33 | 29 |
| 结构化工具显式提出的中间声明 | 86 | 83 |
| 可比较前后源码且出现新非目标声明名的步骤 | 37 | 47 |

未解组 11 个状态都已有拆分或新增中间声明的证据。已交付模型证明中，`rw` 在 343 步、`norm_num` 在 242 步、`omega` 和 `simp` 各在 232 步、`induction` 在 77 步出现。这些是可见证明词面指标，允许一条证明含多种 tactic。结构化工具调用可被作者框架拒绝，已物化模块也会包含此前已有声明，不能据此计为新的成功证明。两种来源在账本中分开。[完整账本](support_ledger.json) · [分题统计](support_summary.json)

未解组有 10 步缺明确代码或结构化动作，145 步缺可见当前模块；对照组分别为 14 和 182。物化源码与装配记录合计对齐两组作者报告的 440 和 579 次验证调用。归档未提供完整的 tactic 状态转移图，超出这些明确归档动作的搜索仍未闭合。模型推理通道未用于提取 tactic 或声明。这里的覆盖率只界定可复查的可见材料。

## 对三个手写直接对照的静态查重

- p14 的 `sub_dvd_pow_sub_pow` 已出现在 Qwen 重写第 8 步。手写 `simpa` 用法的证明 token 不同，但仍复用已有库事实与同一种证明思路。
- p41 手写证明使用的 `Nat.sub_one_dvd_pow_sub_one` 未在可见交付中出现同名引用。此前已出现 `simpa`、归纳和常见算术自动化，直接库定理检索应作为强对照。
- p138 中 `∑ k ∈ Nat.divisors 500, k = 1092` 的子目标在 14 次可见交付中出现。手写 `subst a; decide` 的精确证明 token 未出现，已有归档已尝试了相同的有限算术事实。

查重正控用 p104 一条完整归档证明，返回模型动作、可见前缀与物化源码三处匹配。负控在 `exact` 后使用虚构的常量名，返回可见证明 token 未见，同时保留 `exact` 已见的标记。新 token 序列单独无法证明存在新机制，也不能补齐隐含或缺失的支持。[查重控件与原档锚点](support_probe.json) · [同目标索引](support_index.json)

在仓库根目录可复查归档和静态比较新候选。`--candidate` 读取文本并输出指纹，无须调用 Lean。

```powershell
python -X utf8 -B research/phase5d40_proof_authoring_20261110/support_recount.py
python -X utf8 -B research/phase5d40_proof_authoring_20261110/support_recount.py --target-id induction_11div10tonmn1ton --candidate <reviewed-lean-source>
```
