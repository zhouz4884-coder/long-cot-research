# D4.0 作者环境与同题 Lean 自动化基线

已重新核对 D3.9 的 Lean 4.31.0 和 Lake 二进制、BlueprintRepair 子树、十个 Lake 包提交、实际 `Mathlib.olean` 与 `Architect.olean`，以及 8,542 个压缩缓存文件的聚合哈希。运行目录保持为作者项目。复用 Lean 自带的同文档驻留服务器，每次按文档版本提交，并通过 `waitForDiagnostics` 读取该版本的具名公理闭包。依赖构建模式为 `never`。[D3.9 作者环境回执](../phase5d39_blueprint_trace_20261110/author_runtime_smoke.json) · [驻留核验实现](../phase5d39_blueprint_trace_20261110/lean_resident_probe.py) · [D4.0 可信控制](baseline_runtime_trusted.json)

## 固定方法

- `exact?` 在当前导入的 Lean 环境中搜索可以完整关闭当前目标的引理。`apply?` 独立提交，只有完成所有目标并通过具名闭包时才计成功。建议文本仅供诊断记录。[固定版本的引理搜索实现](https://github.com/leanprover/lean4/blob/68218e876d2a38b1985b8590fff244a83c321783/src/Lean/Elab/Tactic/LibrarySearch.lean)
- 常规方法逐项提交 `assumption`、`rfl`、`simp_all`、`norm_num`、`omega`、`ring`、`linarith`、`nlinarith`、`decide`、`solve_by_elim`、`aesop` 和 `grind`。适合的形状另外测试命名自然数归纳和代入后的有限内核计算。
- 对幂差整除另查公开几何和与 `ModEq` 引理是否在原导入范围内可见。通用签名组合依目标统一参数，使用数值归一化关闭底数条件。导入缺少相应库时照实记录。[Mathlib 幂差整除](https://github.com/leanprover-community/mathlib4/blob/fabf563a7c95a166b8d7b6efca11c8b4dc9d911f/Mathlib/Algebra/Ring/GeomSum.lean) · [整数同余](https://github.com/leanprover-community/mathlib4/blob/fabf563a7c95a166b8d7b6efca11c8b4dc9d911f/Mathlib/Data/Int/ModEq.lean) · [自然数同余](https://github.com/leanprover-community/mathlib4/blob/fabf563a7c95a166b8d7b6efca11c8b4dc9d911f/Mathlib/Data/Nat/ModEq.lean)

三份开发题的导入顺序、命名空间、蓝图标签和定理头均以源回执固定。脚本仅填唯一证明槽、统一加入严格告警与 heartbeat 预算，并追加当前目标的 `#print axioms`。原题的 `import` 没有扩张。每个题先用原导入验证目标名不可见，再进行独立的证明提交。每份定理声明允许 200,000 heartbeats，每次驻留请求超时为 120 秒。接受仅限具名完整闭包、无 Lean 错误、仅依赖 `propext`、`Classical.choice` 和 `Quot.sound` 中的公理。p40 作者证明仅供独立冷进程阳性复核。[冻结协议](baseline_runtime_protocol.json) · [源审阅回执](cases_source_receipt.json)

## 可信控制修正

首轮使用 Lean 内部 `first` 短路组合和附加 `done`。部分策略实际形成闭合证明，但严格告警把未运行分支的 `unreachableTactic` 升格成错误。第二轮仅关闭这项 lint，未使用分支仍触发独立的 `unusedTactic` lint。第三轮改为逐项提交固定策略，不关闭任何 lint。真实驻留序列九项全部达到预期，含正常证明、错误类型、重复回到正确版本、`sorry`、`exact?`、`apply?`、两类通用幂差引理和有限内核计算。前两轮失败与第三轮成功各有独立回执。[首轮](baseline_runtime_trusted_v1.json) · [第二轮](baseline_runtime_trusted_v2.json) · [最终可信控制](baseline_runtime_trusted.json)

## 作者未解决开发题上的实际结果

| 题目 | 固定提交数 | 通过数 | 最主要的发现 |
| --- | ---: | ---: | --- |
| p14 | 21 | 1 | `induction n <;> grind [pow_succ]` 通过，排第 21。截止首个接受累计提交墙钟 5.362 秒。 |
| p41 | 22 | 0 | 两个 `clear h₀` 后的归纳动作已经形成具名闭包，但严格告警因 `h₀` 未在证明项中使用而拒绝。 |
| p138 | 16 | 0 | `subst_vars` 后的 `decide` 遇到默认递归深度上限。`norm_num` 仍留有未完成目标。 |

三个目标名在各自原导入的独立检查中均不存在。p14 和 p41 的七个幂差与同余签名检查全部报未知标识符或常量。有限证明与结构证明因此分别保留证据。p40 在所有作者题基线提交结束后用全新冷进程核对，三个具名公理闭包均接受并与作者记录一致，墙钟 7.761 秒。其证明材料没有进入作者题的驻留序列。[完整开发结果](baseline_runtime_approved.json)

59 次实际证明提交均有单次耗时、诊断和源哈希。整段驻留墙钟 72.115 秒，涵盖启动、各题导入上下文切换、目标名缺失控制、签名检查、各策略提交和关闭。一次环境复核与 p40 冷进程分开计时。该计时来自同一工作站的一次固定次序运行，包含普通系统调度与文件缓存状态。p41 的告警和 p138 的深度错误都保留在冻结结果中，无法据此推断原目标无解。

## 复现

先按源审阅脚本重新生成哈希绑定的目标槽与独立 p40 冷进程夹具，再从仓库根目录运行。每次复核指定新的输出路径。

```powershell
$phase = 'research/phase5d40_proof_authoring_20261110'
python -X utf8 -B "$phase/baseline_runtime_probe.py" --output "$env:TEMP/d40-trusted-recheck.json"
python -X utf8 -B "$phase/baseline_runtime_authoring.py" `
    --slots "$env:TEMP/longcot-d40-authoring-slots-20261110" `
    --reference-dir "$env:TEMP/longcot-d40-offline-reference-20261110" `
    --output "$env:TEMP/d40-approved-recheck.json"
```
