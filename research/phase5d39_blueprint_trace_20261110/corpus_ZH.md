# BlueprintTrace 全量归档复核

冻结作者发布的 `equal_source_v2` 完整矩阵。覆盖两种模型、三种接口、142 个受控初始状态和 141 个原始 miniF2F 目标。逐步恢复 852 条轨迹与 3,499 次尝试。目标 `induction_pprime_pdvdapowpma` 有两个初始状态，因此按目标统计时合并。D3.8 已查看的六个状态仍保留并单列。所有初始故障均来自作者构造，模型回复和检查记录来自真实公开运行。[纳入冻结](corpus_freeze.json) · [作者数据固定版本](https://huggingface.co/datasets/Karifannaa/BlueprintTrace/tree/504b7ae3604f363a3cf5e32308b08d2ac258ac25)

## 已观察的成功与失败

| 模型 | 接口 | 循环判为完成 | 作者终局依赖复核通过 |
| --- | --- | ---: | ---: |
| DeepSeek-V4-Flash | 类型化编辑 | 105 | 104 |
| DeepSeek-V4-Flash | 原子源码补丁 | 109 | 109 |
| DeepSeek-V4-Flash | 整模块重写 | 104 | 104 |
| Qwen3.6-Flash | 类型化编辑 | 84 | 84 |
| Qwen3.6-Flash | 原子源码补丁 | 89 | 88 |
| Qwen3.6-Flash | 整模块重写 | 84 | 84 |

两条差额对应 `p145_compound_toolsrc_v0` 与 `p96_missing_hypothesis_patchsrcq_v0`。作者终局检查记录显示归档模块仍有 `sorry`，且缺少装配后的模块。按复核口径共接受 573 条轨迹，覆盖 123 个不同原始目标。成功步骤有 197 次源码补丁、188 次重写、188 次类型化动作。类型化成功包括删除错误节点 74 次、设置证明 58 次、加依赖 30 次、删死节点 12 次，以及较少的声明改写、弱化、拆分和加强假设。动作计数描述最终通过的那一步，不能估计动作的单独因果贡献。[完整清单](corpus_inventory.json) · [统计](corpus_summary.json) · [DeepSeek 作者复核](https://github.com/Karifannaa/BlueprintRepair/blob/954edd366a0d1474ecfebe418d4cac14aaf8c6bf/data/stats/graph_consistency_v0.json) · [Qwen 作者复核](https://github.com/Karifannaa/BlueprintRepair/blob/954edd366a0d1474ecfebe418d4cac14aaf8c6bf/data/stats/graph_consistency_qwen_v2_v0.json)

尝试层有 2,148 次归档 Lean 错误、392 次框架拒绝、327 次应用后仍未完成、57 次没有记录到模型动作，以及 575 次循环验收。作者前置图能定位 3,498 次请求的原目标闭包。851 次 Lean 错误发生时，作者前置图已有 `proved` 或 `proved_and_used` 的目标祖先，涉及 85 个独立目标，其中 84 个未在 D3.8 小样本出现。该计数以作者状态为准，能否在可见源码中找到已证明的非占位证明单列。

## 保留前置声明与候选筛选

严格源码口径要求终局源码与作者记录的模块 SHA-256 对上。重写轨迹缺少独立终局模块，多数检查文件和循环的模块哈希也无法逐字节对上。为补足可观察证据，另按作者终局复核表指向的归档成员作补充比对，并在原档 SHA-256 下核对成员身份。这个口径没有改写严格哈希结论。补充口径中有 127 条通过复核的终局保留所有可识别的初始已证明前置声明源码，覆盖 38 个目标。其中 118 条、37 个目标的已保留声明还都出现在作者提取的实际证明或类型依赖闭包。源码改变或标签缺失单列，不作为强制释放的证据。[逐轨迹证据](corpus_inventory.json)

随后按 [预先冻结的复验门槛](D39_REPLAY_GATE.json) 对失败前的动态源进行筛选。851 次带已证明标签的错误中，536 次可绑定到可见的非占位声明。294 次缺当前源码，21 次只有占位或不可定位声明。按原始状态对照作者复核通过的输出，45 个状态有保留反例，36 个状态证据未闭合，四个状态观察到类型或证明源码变化且当前档案没有找到匹配的保留成功。比较要求精确声明名和唯一标签后缀同时匹配，去除 `lem:` 等展示前缀的差别。此静态对照不比较 Lean 证明项的定义相等性。[候选、缺失和反例](corpus_replay_nomination.json)

按原始题目 ID 字典序，前两个进入静态源审查的候选是 `amc12_2000_p12`（p94）和 `mathd_algebra_362`（p165）。p94 的 `product_bound_wrong` 从乘积形式换到展开后的不等式，原有假设 `a+m+c=12` 使两者代数等价。p165 的 `a_value`、`b_cubed`、`b_value` 保持定理类型并更换证明脚本，作者复核源为重写步骤文件，循环终局模块哈希仍不匹配。两者的最小释放必要性均为 `UNKNOWN`。p149 与 p151 初看发生源码变化，逐步复查只观察到对应 `sorry_using` 占位或不可见的前置源。p158 的声明标签改名前后，三条定理与证明文本本身保留。[候选源码与编译诊断](corpus_replay_nomination.json)

复核命令在仓库根目录执行，读取相同作者归档并对已有输出逐字节比对。

```powershell
python -X utf8 -B research/phase5d39_blueprint_trace_20261110/corpus_recount.py
python -X utf8 -B research/phase5d39_blueprint_trace_20261110/corpus_replay_nomination.py
```
