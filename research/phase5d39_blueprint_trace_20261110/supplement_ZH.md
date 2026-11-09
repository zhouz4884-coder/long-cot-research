# p82 与 p30 的补充保留对照

在冻结的主样本 p94、p165 之外，验证两个补充候选。源文件由固定 BlueprintTrace 成员与确定性替换生成。完整目标经显式类型检查，并和作者基线的实际 elaborated 类型比较。公理闭包只允许 `propext`、`Classical.choice` 和 `Quot.sound`。固定审计命令从编译环境读取证明和类型常量，分开记录源码保留和实际依赖。运行使用作者 Lean 4.31.0 与已复核的依赖版本。[补充冻结](supplement_freeze.json) · [源码回执](supplement_source_receipt.json) · [运行回执](supplement_runtime_observed.json)

| 对照 | 完整目标 | 旧声明源码保留 | 实际使用旧声明 |
| --- | --- | --- | --- |
| p82 保留加等式运输 | 通过 | 是 | 是 |
| p30 保留加直接 `omega` | 通过 | 是 | 否 |
| p30 保留加模逆元推导 | 通过 | 是 | 是 |

p82 原已证明声明给出 `8 * 3720 = 120 * 248`。作者补丁把右端改成 `29760`。保留旧声明和另一个已有的余数声明，在目标证明中直接消费旧等式，再归约 `120 * 248`，得到相同目标。原归档失败涉及不可用的 `Nat.mul_left_cancel₀`，这项保留证明使用作者已验收的后续结构。[运行回执](supplement_runtime_observed.json)

p30 旧声明是 `5 * 7 % 17 = 1`。作者补丁把它改成带任意 `n` 的模方程结论。直接 `omega` 版复用归档中同目标的已验收证明，旧声明留在模块内，目标的实际依赖未使用它。模逆元版用旧等式把 `n % 17` 写成 `((5 * 7 % 17) * n) % 17`，再按乘积的模运算定理代入题设。目标编译后的证明常量中包含 `P30Bad.residue_wrong`。[补充冻结](supplement_freeze.json) · [实际依赖回执](supplement_inverse_retry_observed.json)

首轮模逆元证明完成类型与公理输出，但 `rw [h₀]` 已关掉目标，末尾 `<;> decide` 产生两条警告，被严格门槛拒绝。只删除这一冗余 tactic 后，完全相同的目标与旧依赖通过干净检查。首次诊断与单行修改分别保留。墙钟是共享主机上的功能检查观察，两个案例独立于主样本统计。[首次运行](supplement_runtime_observed.json) · [单行重试](supplement_inverse_retry_source.json) · [重试结果](supplement_inverse_retry_observed.json)

源码准备不调用 Lean。已有观察文件按原始字节保存，重复运行时为新测量指定新的输出文件。

```powershell
$d = 'research/phase5d39_blueprint_trace_20261110'
$bin = 'outputs/d39_lean_4_31_0_windows/lean-4.31.0-windows/bin'
$project = 'outputs/d39_blueprintrepair_954edd3/BlueprintRepair'
python -X utf8 -B "$d/supplement_controls.py" prepare --output-dir outputs/d39_supplement_reviewed
python -X utf8 -B "$d/supplement_controls.py" run --source-dir outputs/d39_supplement_reviewed --lean "$bin/lean.exe" --lake "$bin/lake.exe" --project $project --output "$env:TEMP/supplement_first_observation.json"
python -X utf8 -B "$d/supplement_inverse_retry.py" --source-dir outputs/d39_supplement_reviewed --lean "$bin/lean.exe" --lake "$bin/lake.exe" --project $project --output "$env:TEMP/supplement_retry_observation.json"
```
