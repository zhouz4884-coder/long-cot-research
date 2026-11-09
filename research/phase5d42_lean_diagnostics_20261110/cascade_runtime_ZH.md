# D4.2 Lean 诊断锚点与普通 CPU 对照

复核并使用 D3.9 作者 Lean 4.31.0、Lake、Mathlib 与 Architect 环境。运行器保留每条诊断的原报告顺序、类别、消息和范围，另提供按源字节偏移排序的索引。命令行位置按 Unicode 标量列解释，LSP 位置按 UTF-16 单元列解释，两者都映射到当次实际提交源码的 UTF-8 字节锚点与行哈希。驻留检查等待同 URI 同版本的诊断完成，并要求具名目标公理闭包。[作者环境](../phase5d39_blueprint_trace_20261110/author_runtime_smoke.json) · [Lean 位置转换源码](https://github.com/leanprover/lean4/blob/68218e876d2a38b1985b8590fff244a83c321783/src/Lean/Data/Lsp/Utf16.lean) · [运行器](cascade_runtime_probe.py)

## 可信级联预检

固定原 p14 导入和目标 `True`。源码把 `True.intro` 赋给局部 `Nat`，后续又以该局部变量直接提交目标。冷进程和驻留均先报告 `True.intro` 的类型不符，UTF-8 锚点为字节 270。之后报告 `exact hβ` 的类型不符，锚点为字节 283。第一处之前包含补充平面字符，命令行标量列为 27，驻留 UTF-16 列为 28。两种传输映射到同一源码范围。

无关编辑只把一个填充值末位从 `3` 改为 `4`，两条错误的报告顺序、消息和起点均一致。局部类型 `Nat` 改为 `True` 的单处编辑让两条错误消失，并通过同一目标的具名闭包。普通直接 `trivial` 的全证明体也单独通过。驻留切回原版本后重新报告两条错误。七项冻结检查全部通过。该设计的依赖关系来自人工夹具，只说明报告与锚点运行器能区分这两个编辑。[可信冻结](cascade_runtime_freeze.json) · [原始诊断](cascade_runtime_trusted.json)

| 可信版本 | 冷进程墙钟秒 | 驻留预热后墙钟秒 | 完整错误数 |
| --- | ---: | ---: | ---: |
| 原始 | 7.250 | 0.224 | 2 |
| 无关编辑 | 7.337 | 0.209 | 2 |
| 局部类型编辑 | 7.360 | 0.204 | 0 |
| 普通直接 tactic | 7.322 | 0.204 | 0 |

环境复核 5.876 秒，驻留初始化、导入预热和关闭为 1.642、8.517、0.059 秒。冷表示每次新进程，操作系统文件缓存仍可能已经预热。驻留使用 Lean 默认诊断延迟，不能将墙钟等同于内核计算时间，也不能从合成结果推断真实修复的性能增益。

## 已审槽的比较边界

普通基线只读取三份经哈希绑定的目标槽和原导入。通过源核对后，保留原定理头、命名空间与导入，填预冻结的证明体并使用相同严格告警与 200,000 heartbeats。动作包括独立库检索、标准自动化、适用的签名或归纳，以及一个普通完整证明体。完整证明体替换属于独立权限层次，与局部修正归档故障分开。通过条件为当前版本无错误且指定目标的传递公理只来自批准列表。完整结果保留每次提交及未通过诊断。[动作冻结](cascade_runtime_ordinary_freeze.json) · [审阅源码](causal_cases_source_receipt.json)

冷完整证明和驻留完整证明使用完全相同的普通证明体字节。冷进程耗时包含写入、Lake 启动、导入和编译。驻留记录同导入会话初始化、预热、逐提交完成屏障和关闭。源码审查、固定动作推导及环境重验分开记录，核验墙钟不替代这些工作。归档原失败的重新核验和局部编辑不在本普通动作队列内。

## 第一轮实际普通动作

| 原目标 | 驻留提交 | 首轮可接受动作 | 普通完整证明的驻留秒 | 同字节冷进程秒 |
| --- | ---: | --- | ---: | ---: |
| p104 | 7 | 完整证明体通过 | 0.223 | 18.007 |
| p113 | 7 | 全部拒绝 | 0.467 | 18.065 |
| p41 | 8 | 完整证明体通过 | 0.209 | 7.712 |

22 次驻留提交中 2 次通过、20 次拒绝。三份普通完整证明的冷、驻留状态与具名公理闭包逐项一致，没有请求超时。p104 的普通证明先建立自然数幂差的非负性，再使用整数费马整除引理并转换类型。p41 用普通归纳、正指数前提和显式整除见证完成。p113 的完整体只有一条严格 lint 错误，指出一次 `change` 没有改变目标。保留首轮拒绝及完整诊断。[第一轮不可变回执](cascade_runtime_ordinary.json)

两个驻留会话分别共享 p104/p113 的全 Mathlib 导入和 p41 的原窄导入。两组预热实际 43.467 和 8.760 秒。运行中观察到同工作站另有 Lean 任务，因此这里只记录实跑墙钟与编译结果，不能用冷、驻留差值声称算法加速。[全部分项时钟](cascade_runtime_ordinary.json)

## p113 独立的普通实现修正

按首轮实际诊断预冻结一处删除。它只去掉没有改变目标的 `change`，保持原导入、原定理头、严格 lint 和奇数商归纳构造。相同修正源码在新驻留会话和冷进程中均通过，目标传递公理为 `propext`、`Classical.choice` 与 `Quot.sound`。驻留预热后 0.480 秒，冷进程 18.051 秒。首轮仍为 2/3 个目标通过，另做的一次普通实现修正使操作覆盖达到 3/3。这个修正属于独立构造的普通基线，不能当作已修复 p113 的归档尝试。[单独修正冻结](cascade_runtime_plain_correction_freeze.json) · [实际核验](cascade_runtime_plain_correction.json)

## 复现

先恢复 D3.9 作者环境。普通动作需要从已审回执重新生成精确目标槽。使用新的输出文件，保留原回执。独立修正已有冻结文件，复跑时无需重新准备。

```powershell
$phase = 'research/phase5d42_lean_diagnostics_20261110'
$slots = "$env:TEMP/longcot-d42-causal-cases-20261110"
python -X utf8 -B "$phase/cascade_runtime_probe.py" --output "$env:TEMP/d42-trusted-cascade-recheck.json"
python -X utf8 -B "$phase/cascade_runtime_ordinary.py" --slots $slots --output "$env:TEMP/d42-ordinary-recheck.json"
python -X utf8 -B "$phase/cascade_runtime_plain_correction.py" --slots $slots --output "$env:TEMP/d42-ordinary-correction-recheck.json"
```
