# Phase 5-D3.8 形式证明最小释放准入收尾

**CPU 准入闭环完成，本阶段未启动模型试验。** 最小释放可以用 Lean 证明。修订后的方法在八个结构控制中完成七例，并核验了每例最小释放。更强的同候选池基线也完成七例，能一次核验完整证明和所有更小范围的反证，只用七次 Lean 调用。公开模型档案提供了真实失败动作，但所抽目标中没有两例支持超越已知局部修复。新增 GPU 用量、模型调用和独立模型题分母均为零。[交付审计](D38_DELIVERY_AUDIT.json) · [模型准入规则](D38_MODEL_ADMISSION.json)

## 正式环境和真实来源

使用正式发布的 Lean 4.27.0，固定可执行文件、基础 `.olean` 和下载归档哈希。默认 `sorry` 及引用带 `sorry` 的辅助声明都可返回零退出码，传递公理检查揭示了 `sorryAx`。自定义公理即使无警告也会出现在传递闭包中。同名真命题冒充原目标能单独编译，但绑定完整预期类型后被内核拒绝。九项控制通过。验收保留标准基础公理白名单，禁止实验新增公理。当前运行只检查可信代码和自己构造的固定模板。[工具链、负例和复现](lean_runtime_ZH.md)

构建了 DeepMind miniF2F 固定源码的官方 `ProblemImports`，核验十个锁定包和 7,869 个 Mathlib 缓存对象。Windows 的 `tar` 详细输出使用本地编码，触发 Lake UTF-8 解析失败。限定到已校验的公开归档和缓存目录，只去除详细输出标志后复测通过。官方环境十项检查符合预期。两份上游证明通过，三条 `by skip` 占位只完成题面并留下未解目标，五个目标声明在导入中按名不可见。按名不可见不覆盖其他名字的等价定理。未导入 `MiniF2F.Test` 或 `Valid`。[官方环境回执](lean_runtime_benchmark_controls.json) · [固定来源](https://github.com/google-deepmind/miniF2F/tree/f0a20e14c1eeccd859d51bb4c2b3ee487889c303)

来源清单覆盖 12 个实际公开声明，所选版本中七个有证明体，五个是占位。PutnamBench 与 VeriSoftBench 的部分候选使用不同版本，未纳入同版实跑。Lean Std 中三条真实的位向量验证证明用独立依赖上下文重编译成功。原目标名称在该上下文不可见，移除证明的三个控制均失败。存在其他版本的同名公开证明，归档中注明潜在污染来源。[证明来源清单](proof_intake_ZH.md) · [Std 核验](proof_intake_std_kernel.json) · [PutnamBench](https://arxiv.org/abs/2407.11214) · [VeriSoftBench](https://arxiv.org/abs/2602.18307)

对 miniF2F 的整数命题 $4x^3-7y^3\ne 2003$，独立用模 7 证明。$4r^3\bmod 7$ 只能取 $0,3,4$，而 $2003\bmod 7=1$。首次编写证明时，重写器未看到隐藏在 lambda 应用后的模运算。加一行 `change` 明确类型后，原完整目标通过，传递公理只有 `propext`、`Quot.sound`。核心环境里的五个直接通用 tactic 未闭合该命题。这是 CPU 编写中实际发生的一次局部 elaboration 失败，普通单步修复已经解决。证明未导入目标题源或其答案。[原命题及同源修补](competition_residue_results.json) · [完整证书](competition_residue_control.lean)

## 作用域身份和最小释放

六个实际 Lean 对照覆盖局部假设、目标顺序与存在见证。相同表面目标 `P` 在假设 `h : P` 与 `h : ¬P` 下，`exact h` 的结果相反。重排两个目标后原首步失败。未绑定见证时 Lean 可以用 `P 2` 实例化，锁到 3 后同样的证明项被拒绝。最初误用了当前工具链不认识的 `swap`，它造成的拒绝不能用于证明目标顺序的影响。用 `rotate_left` 复测，三对结果均符合预期，拒绝来自真正的类型不匹配。身份控制绑定了工具链、完整声明与精确前缀，只支持同源重放。[初次失败](context_identity_initial_results.json) · [作用域复测](context_identity_results.json)

八个合成案例的完整目标、失败草稿和共享候选池先冻结。每个草稿的已验部分和原始失败都由 Lean 复核。每臂最多 20 次调用。候选法只在严格更小释放范围均有已核验证明表明不可补全时，才扩大释放数量。对证明为假的固定范围，后续保留相同锁定值的候选一并剪掉。完整候选仍从头通过 Lean 核验。保留的源码单元数只表示哪些陈述和证明文本未改动，本轮没有复用已编译状态。[冻结控制](D38_STRUCTURAL_CONTROL_FREEZE.json) · [修订方法冻结](D38_STRUCTURAL_V2_FREEZE.json)

| 方法 | 完整目标 | Lean 调用 | 各例方法墙钟合计 |
| --- | ---: | ---: | ---: |
| 直接通用 Lean 自动化 | 2/8 | 38 | 73.26 秒 |
| 固定原选择的单步修复 | 1/8 | 36 | 59.04 秒 |
| 共享候选池整段重建 | 7/8 | 65 | 105.39 秒 |
| 编译诊断定位后按范围枚举 | 7/8 | 48 | 71.76 秒 |
| 有证书的最小释放 | 7/8 | 41 | 62.39 秒 |
| 同候选池直接算术预选后核验 | 7/8 | 7 | 11.87 秒 |
| 同候选池一次核验目标与最小释放 | 7/8 | 7 | 10.30 秒 |
| 完整有限域一次核验目标与最小释放 | 8/8 | 8 | 11.77 秒 |

七份最小释放证书包括零释放一例、单释放四例和双释放两例。初版跳过了已证矛盾的局部范围，进入更宽范围后仍检查了一些已经被反证覆盖的候选，耗费 61 次调用。修订后剪掉 20 次重复检查。合并核验的强基线直接在同一候选池内找到同样的最小改变，再将完整目标与各更小锁定范围的反证写成一个 Lean 证书。它在七个共享支持成功例中达到同一证明目标及最小范围。完整有限域额外解出候选池缺口例。该例的真正见证在池外，候选池的未解结果保留为有限支持未获证书。时间含候选生成、文件写入和进程核验的实测墙钟，公共真值、前缀和故障检查单独记录。不同运行的系统缓存状态可能不同，调用数和证书范围提供可直接比较的证据。[初版](structural_control_results.json) · [修订版](structural_control_v2_results.json) · [合并证书强基线](batched_release_baseline_results.json)

## 已有机制与模型档案反证

BlueprintRepair 已比较类型化编辑、精确局部补丁和整段重写。Goedel-Architect 已允许在下游需要时修改已证明节点，并重验仍要保留的证明。Lean 单步修复与有限候选的精确重放也已有专门对照。可研究的剩余问题是，在相同动作空间内，显式证明释放的必要性是否能改善完整证明质量或成本。这次合成控制的合并核验已经提供了竞争对照，不能据此主张结构修补能力的新颖性。[近邻核查](prior_art_review_ZH.md) · [BlueprintRepair](https://arxiv.org/abs/2607.28110) · [编译器引导单步修复](https://arxiv.org/abs/2610.26942)

从作者公开的 BlueprintTrace 预定六个 ID，复算 36 段记录和 60 次模型尝试。它们是受控起始状态上的真实模型动作，含 21 次作者 Lean 错误。11 次错误之前有已证明的目标依赖，但均集中在同一个目标 `p159`。该目标的 Qwen 类型化臂用完预算，作者的精确补丁仍原样保留三条已证依赖并完成，整段重写也已完成。这里核对了作者归档哈希和版本，使用的是作者 Lean 4.31.0 的日志，与本阶段 4.27.0 环境分开。[外部模型档案核对](blueprint_trace_ZH.md) · [p159 声明比对](blueprint_trace_preservation.json)

## 准入决定

当前已测的最小释放机制在准确率与完整核验成本上被强直接控制覆盖。公开模型样本也没有提供两条独立目标的结构增量。保留证明范围这一可靠性结果，模型试验和 12–24 题独立评估均未启动。后续若继续检验，应先从真实轨迹确认哪些任务的同态补丁确实无法保留原依赖，再在原版本以驻留 Lean 或合并核验为强成本对照。仅减少冷启动或能换一个证明节点，已经有可用对照，不能作为新增机制的证据。[准入审计](D38_DELIVERY_AUDIT.json)

## 复现

完整环境安装与缓存复现见[工具链记录](lean_runtime_ZH.md)。以下命令用官方 4.27.0 CPU 二进制。重测请用新文件保留归档耗时。最后的审计命令会复算原始证书账本和当前 Git 证据，无需重跑 Lean。

```powershell
$d = 'research/phase5d38_proof_release_20261110'
$lean = (Resolve-Path 'outputs/d38_lean_4_27_0_windows/lean-4.27.0-windows/bin/lean.exe').Path
python -X utf8 -B $d/check_context_identity.py --lean $lean --output "$env:TEMP/d38_context_replay.json"
python -X utf8 -B $d/check_competition_intake.py --lean $lean --output "$env:TEMP/d38_competition_replay.json"
python -X utf8 -B $d/run_structural_controls.py --lean $lean --output "$env:TEMP/d38_structural_replay.json"
python -X utf8 -B $d/check_batched_release_baseline.py --lean $lean --output "$env:TEMP/d38_batched_replay.json"
python -X utf8 -B $d/audit_d38_delivery.py
```
