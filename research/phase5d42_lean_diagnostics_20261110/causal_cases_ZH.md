# D4.2 三个归档错误的局部编辑对照

三个样本都来自同一家族的归档未解决起点。每个归档检查、作者诊断、尝试记录及初始提示均按哈希绑定。初始提示里的证明图仅有一个未证目标，无辅助声明。候选检查沿用初始目标的导入列表、命名空间、蓝图标签和完整定理签名。只允许执行人工审核过的三个精确源码及从各自源码确定性生成的对照，保留原有 `#print axioms` 指令。归档失败中没有显式 `sorry` 或 `admit`，编译器在报错后生成的 `sorryAx` 仍会使目标拒绝。源码审查凭据和本地运行凭据分别记录。 [源码审查凭据](causal_cases_source_receipt.json)

每份原件匹配三个对照。第一份对照逐字节重复原件。第二份在首处报错所在行加空格及必要的空行，使新增字节数和行数与实质编辑相同。第三份替换一段连续的原始证明行。p104 的两条新增行属于 `h` 的局部子证明。其余未改行在新源码里向后移两行，比较报错前映射回原位置。p113 与 p41 的编辑没有新增行。

| 目标 | 原始报错行 | 审核后唯一编辑 | 所要区分的情形 |
|---|---|---|---|
| p104，Qwen Typed 第 4 步 | 8、8 | 把 `ZMod.pow_card p a` 的用法替换为子证明，在局部加入 `Fact (Nat.Prime p)` 并以 `(a : ZMod p)` 调用引理 | 两条报错是否随同一处编辑一起消失，以及后续代码是否显露新错误 |
| p113，Qwen Patch 第 6 步 | 11、16、34、41 | 零分支在 `exfalso` 后以 `Nat.lt_irrefl 0 hk` 证明矛盾 | 另一分支及下游计算是否仍有原错误 |
| p41，DeepSeek Rewrite 第 4 步 | 18、44 | 用 `(Nat.zero_le m)` 给出所需的 `0 ≤ m` | 局部类型修复后末尾等式是否仍未证明 |

p104 的一个源码跨度同时改了实例和实参，实验只识别这次联合局部改动的效果。p113 较早的 Typed 第 2 步带有显式占位符，沿用预冻结的 Patch 第 6 步。p14 在 D4.0 已经有独立的单行删除控制，本轮三个归档目标的分母与它分开。真实失败的原文和诊断原文从公开归档重建到临时目录。普通策略基线用单独的空证明槽，只复制导入、命名空间、蓝图标签、定理签名和受信核验指令。三个未解决目标没有引入已知参考证明，既有 p40 参考证明沿用 D4.0 离线控制。 [p14 原控制](../phase5d40_proof_authoring_20261110/cases_p14_one_line_edit_runtime.json)

## 本地 Lean 结果

匹配作者版本的 Lean 4.31.0 完成三个目标、四份变体和两种传输的 24 次 CPU 检查。冷启动 CLI 与每题固定文档的驻留 LSP 给出相同的有序报错签名和严格目标状态。逐字节重复及等长度空白对照都保留了原始报错。原始报错的顺序、行、Unicode 字符列、错误类别和目标公理闭包与归档一致。p104、p113 部分实时消息补充了 `Note` 或分支上下文，归档短消息是实时文本的前缀。 [运行凭据](causal_cases_runtime.json)

| 目标 | 原始 → 编辑后错误数 | 消失的原始报告 | 保留或新出现的报告，按原始源码行标记 | 编辑后的严格结果 |
|---|---:|---|---|---|
| p104 | 2 → 2 | 第 8 行两条应用报告 | 第 9 行的 `ZMod.natCast_zmod_eq_zero_iff_dvd` 未识别，第 7 行的未证目标，两条均为新增报告 | 拒绝 |
| p113 | 4 → 3 | 第 11 行应用报告 | 第 16、34、41 行原样留存 | 拒绝 |
| p41 | 2 → 1 | 第 18 行应用类型报告 | 第 44 行末段等式仍未证明 | 拒绝 |

每次编辑都移除了所触及的原报告，完整目标通过 0/3。三份编辑结果的目标闭包均含 `sorryAx`，每次冷编译退出码均为 1。p104 表明总报错数相同也可能对应完全不同的错误位置。p113 与 p41 说明首处局部问题被修好以后，其余源码中的问题可以独立留存。这个有目的选取的小样本支持按位置与内容追踪报错的做法，无法估计全库中的发生率或证明完整目标的修复收益。

## 复现

先按 D3.9 的凭据准备已固定的作者运行时及两个归档。重建在新路径运行，已冻结结果保持可读。第一条 Python 命令生成的源码审查凭据应逐字节相同，Lean 运行记录包含重新测得的耗时。 [作者运行时](../phase5d39_blueprint_trace_20261110/author_runtime_smoke.json)

```powershell
$phase = 'research/phase5d42_lean_diagnostics_20261110'
$replay = Join-Path $env:TEMP ('longcot-d42-replay-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $replay | Out-Null
$fixtures = Join-Path $replay 'fixtures'
$review = Join-Path $replay 'source-review.json'
python -B "$phase/causal_cases_prepare.py" --scratch $fixtures --receipt $review
python -B "$phase/causal_cases_run.py" --scratch $fixtures --source-review $review --output (Join-Path $replay 'runtime.json')
```

默认归档参数指向 D3.9 在系统临时目录使用的文件名。也可以显式传入 `--deepseek` 和 `--qwen`。脚本先核验完整归档的哈希，再逐项读取，无需把归档成员直接解包进仓库。
