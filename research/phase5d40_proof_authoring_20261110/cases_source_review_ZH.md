# D4.0 原目标、归档起点与正向对照

按预先冻结的 `monolithic_needs_split` 构造族选出三个尚未验收的原目标。三个起点各有两种模型与三种接口的完整档案。复核 24 条初始请求，包含这三个起点和同族正向对照 p40。每个目标的六份初始模块字节一致。起点均只有一条目标定理，原证明位置是 `sorry`，图中没有已证辅助声明。这些是作者构造起点上的真实归档动作，统计单位是不同原题。[筛选冻结](D40_SOURCE_SELECTION_FREEZE.json) · [源复核回执](cases_source_receipt.json)

| 用途 | 起点与固定目标 | 作者归档 |
| --- | --- | --- |
| 主要 | p14，`induction_11div10tonmn1ton`，整数幂差被 11 整除 | 六条均用尽预算。48 个步骤中有 40 个 Lean 错误、7 个框架拒绝、1 个无记录模型动作 |
| 主要 | p41，`induction_divisibility_9div10tonm1`，带正指数假设的自然数幂差被 9 整除 | 六条均用尽预算。48 个步骤中有 40 个 Lean 错误、6 个框架拒绝、2 个应用后未解决 |
| 有限算术对照 | p138，`mathd_numbertheory_427`，先求约数之和，再核对其素约数之和 | 六条均用尽预算。48 个步骤中有 33 个 Lean 错误、12 个框架拒绝、2 个应用后未解决、1 个无记录模型动作 |
| 已接受正例 | p40，`induction_12dvd4expnp1p20`，另一条自然数指数整除目标 | 6 条中有 3 条作者终局验收。固定使用 DeepSeek 类型化轨迹第 5 步的完整检查源 |

本阶段逐条绑定归档 episode、首请求、请求中 Lean 模块和第一次真实 Lean 错误的日志摘要。证明输入取自原始空槽。每个起点的目标头和初始导入保留原字节。初步考虑过统一导入 Mathlib，读取原始源码后发现这样会给 p14 和 p41 增加原题环境没有的导入，因此按题保留实际列表。p14 只用 `Architect` 及 Ring、Linarith、NormNum、LinearCombination 四个 tactic 模块。p41 和 p40 少一个 LinearCombination。p138 用 `Architect` 和 Mathlib。完整定理头及导入数组见机器回执的 `source_cases`。[作者固定档案](https://huggingface.co/datasets/Karifannaa/BlueprintTrace/tree/504b7ae3604f363a3cf5e32308b08d2ac258ac25)

## 隔离与核验入口

准备器只在定理体中替换唯一的占位词，得到含 `d40_slot` 的本地夹具。模型或搜索接口可以提议这一处证明体。定理头、命名空间、蓝图标注、导入、既有配置和最终公理检查由调用端控制。后续实际运行先独立检查原目标名在导入环境中不存在，再对完整证明做固定类型和传递公理检查。p14 与 p41 的目标保持原来的整数和自然数类型。p41 中的自然数减法不能换成整数差。

p40 的参考证明与所有空白夹具写入不同且互不包含的目录。作者完整检查文件的固定哈希为 `d1d235455e42cd09ac77dae91c33cd41f269c8df5f65ac13d357240dec3a66fd`。参考文件仅含原声明、已审核的普通证明体和公理打印后缀。原作者 `gate` 元程序及其它动作文件不进入运行夹具。源复核只校验作者检查记录和传递公理输出，本阶段此项源审阅未启动本地 Lean。

拟执行的最小同目标对照以 p14、p41、p138 为三个开发输入，p40 验证同族固定环境的正向路径。每个输入从相同空槽开始。直接完整证明和结构分解必须保持同一目标、导入和工具权限。p14 与 p41 可分别观察整数幂差和自然数减法的归一化问题。p138 单列闭式有限算术，避免只在同一种幂运算上判断效果。归档未闭合只描述所观察的六条尝试，不判定该题无证明。

## 独立归档失败夹具

按 DeepSeek、Qwen，类型化、补丁、重写，步骤号与成员路径的顺序，筛出第一个满足实际编译错误、原目标头、原导入和普通证明语法的检查文件。逐行复核后固定 p14 类型化第 2 步、p41 类型化第 1 步与 p138 类型化第 1 步。每份检查文件的模块前缀都与作者该步记录的模块摘要一致，后缀只打印实际声明的传递公理。三份文件和完整原始诊断写入另一个离线目录。空槽作者输入依旧只取初始模块。[负例固定回执](cases_archive_failure_receipt.json) · [精确源审阅与复跑脚本](cases_archive_failure_review.py)

在匹配的 Lean 4.31.0 环境中实际复跑三份文件，三份均退出 1。p14 的 1 条、p41 的 5 条及 p138 的 6 条错误类别和行号与归档完全一致，原目标的传递公理集合也逐项一致，均含 `sorryAx`。p138 的逐字错误相同。p14 的本地输出多显示了当前目标，p41 多显示了类型类调试提示。完整失败草稿和逐字诊断仍保存在离线目录。这个对照单独计量作者环境复验。[实际负例复跑](cases_archive_failure_runtime.json)

对 p14 另做一次编辑复跑。冻结检查文件在第 11 行唯一的 `intro n` 后，只删去这一行，并在编译前固定新源码摘要。原目标头、导入和公理检查后缀保持原字节。再次运行退出 1，原先的无绑定项错误消失。首条错误移至第 17 行的乘法交换等式，随后出现未知标识符 `dvd_add` 和无剩余目标错误。目标传递依赖仍含 `sorryAx`。这项控制隔离了首次诊断给出的单行编辑，归档原失败保持原始记录。[编辑冻结](cases_p14_one_line_edit_freeze.json) · [实际复跑](cases_p14_one_line_edit_runtime.json)

## 重建临时夹具

从仓库根目录运行，保留 D3.9 基线的 Git 对象。将固定的两个作者压缩包放到准备器的默认临时位置，或显式传入 `--deepseek-archive` 和 `--qwen-archive`。脚本只读取精确成员，禁止解包任意归档路径，要求新输出目录。

```powershell
$phase = 'research/phase5d40_proof_authoring_20261110'
$replay = Join-Path $env:TEMP ('d40-cases-' + [Guid]::NewGuid().ToString('N'))
python -X utf8 -B "$phase/cases_source_review.py" --output-dir "$replay/slots" --offline-reference-dir "$replay/offline" --receipt "$replay/source.receipt.json"
```

向核验器传入 `slots/` 中的文件及回执摘要。`offline/` 只用于经过授权的正例复跑。两个目录的内容均未加入仓库，发布材料保留可复查的来源、完整目标头、隔离口径和哈希。[准备脚本](cases_source_review.py)

在匹配作者工具链且允许执行审核过的负例时，可将离线负例准备和复跑分别写入新的目录及回执。

```powershell
python -X utf8 -B "$phase/cases_archive_failure_review.py" prepare --output-dir "$replay/archived-errors" --receipt "$replay/error.source.json"
python -X utf8 -B "$phase/cases_archive_failure_review.py" replay --scratch "$replay/archived-errors" --review-receipt "$replay/error.source.json" --output "$replay/error.runtime.json"
python -X utf8 -B "$phase/cases_p14_one_line_edit.py" --original "$replay/archived-errors/p14_archived_exact_failure.lean" --freeze "$replay/p14.edit.freeze.json" --output "$replay/p14.edit.runtime.json"
```
