# D4.1 作用域拒绝边界

先冻结 19 个独立编写的 Lean 控制及精确字节。预期有 12 个闭合证明和 7 个有区分的错误。每个控制使用 p14 或 p41 的原导入列表，已审阅的别名、开放命名空间和本地记法仅在可信文件前缀中定义。候选正文只含普通证明。单独的全局查询若没有带上这个局部环境，只能作为错用查询口径的对照。[冻结输入](scope_cases_controls.json) · [源准备](scope_cases_prepare.py)

## 条件与负控

| 类型 | 对照与预期 |
| --- | --- |
| 显式根名与遮蔽 | 同一目标有局部 `add_zero : ℕ`。用 `_root_.Nat.add_zero` 可闭合，裸名应用到参数会遇到局部自然数 |
| 局部名与别名 | 假设 `h`、let 证明别名、由可信 `open` 引入的唯一名称、相对命名空间限定均交给上下文 elaboration |
| 记法与字段 | 文件本地记法、局部变量上的点投影、注释和字符串内的名字样式只由真实语法解析处理 |
| 类型类 | `default` 的全局声明存在，当前局部 `Inhabited α` 决定能否生成见证。缺实例属于实例合成失败 |
| 存在但不适用 | 对 `Int` 参数调用自然数引理会导致类型错误。一个构造子目标完成后也可能仍留另一个子目标 |
| 缺失且必用 | 仅一条单独的 `exact` 使用已审核的显式根限定缺名，可以在精确环境查询证实后进入拒绝控制 |
| 缺失但有回退 | 同一个缺名在 `first` 的备选分支出现。完整 Lean 可转向下一分支，局部缺名不足以否决整段证明 |

编译器实际错误从同一提交的诊断屏障读取，只有关闭完整目标且目标传递公理通过才记录证明通过。所有作者控制与真实归档尝试分别计数。

实际 19 项均与冻结标签一致。12 个完整目标通过，7 个分别落在函数或参数类型、局部名字解析、实例合成、缺少常量、记法解析和未闭合目标。根限定名在遮蔽对照中有效，同一个不存在的根名放在回退分支时完整证明也通过。

两组另设的仅导入 `#check` 查询省去了局部或可信前缀。若把这些查询的缺名结果作强制拒绝，实际会误拒绝 7 个已通过控制。具体包括局部假设、let 别名、回退分支中的缺名、注释、开放名称、本地记法和点投影。7 是这组特意设计的已检实例数，只描述删掉上下文后强拒绝的风险。[实际驻留检查](scope_cases_authored_runtime.json)

## 实际归档对照与延后范围

D4.0 已在固定 Lean 4.31.0 下复验 p14 的无剩余绑定项错误和 p41 的解析、实例合成、缺分支与未解目标错误。原窄导入中的七个可见候选名称查询均报未知。p14 原导入的首次已闭合完整目标位于固定 CPU 基线序列的第 21 个动作。同族 p40 的作者正例此前也用独立离线进程通过。两条正例的源及公理回执均绑定早期发布提交，p40 参考证明没有混入任何候选。[归档与首次通过证据](scope_cases_evidence.json)

p14 Qwen 重写第 8 步只留下 `Architect` 和 `Mathlib.Tactic.Ring`，并调用裸名 `sub_dvd_pow_sub_pow`。该作者编译结果是未知标识符。它没有保持 p14 的完整原导入，也没有形成精确根名。p41 DeepSeek 类型化第 3 步保留导入和目标，但在到达 `Nat.ModEq.pow` 之前先触发模记法解析和类型错误。两条均延后给普通编译处理，历史账本不增加预检拒绝。[逐字节来源与延后原因](scope_cases_evidence.json)

另外固定三个独立的已发表历史候选。p104 和 p139 的原文件与记录导入和目标一致，直接终结步骤包含一个必用的相对限定名，作者编译器明确报未知常量。两份完整负例经过逐行审阅，末尾仅含公理输出。p115 的缺名出现于 `match` 分支，本次只作同导入、同命名空间的查询。三例均另外准备相对限定及显式根名的标准 `#check`。原档没有显式根名这一事实保留，复查结果只覆盖审核过的候选和查询。[历史补充冻结](scope_cases_historical_supplement.json)

p104 和 p139 的完整负例在匹配运行时复现各自唯一的未知常量错误，行号和错误文本都相同。恢复出的目标公理报告仍含 `sorryAx`。p104、p139、p115 的相对限定和显式根名查询分别给出相同缺名结果。p115 只执行查询。三个测量均从单独驻留会话的导入屏障之后开始。[实际历史复验](scope_cases_historical_runtime.json)

| 历史候选 | 两条标准查询 | 完整负例检查 |
| --- | ---: | ---: |
| p104 | 0.2159 秒 | 1.2496 秒 |
| p139 | 0.2088 秒 | 0.2183 秒 |
| p115 | 0.2169 秒 | 未安排 |

表内为一次已加载前缀后的负例观测。启动、导入屏障和关闭在回执中单列。标准查询本身已经能取得所需缺名结果；这些检查没有测出相对 Lean 现有查询的额外收益。

## 复核入口

在含 D4.0 与 D3.9 Git 对象的检出运行，作者工具链用已校验的本地安装。准备器只写入新临时目录。历史补充需固定 DeepSeek 和 Qwen 压缩包在系统临时目录。运行器逐条校验冻结字节，并使用 Lean 驻留文档版本和诊断屏障。

```powershell
$phase = 'research/phase5d41_lean_scope_20261110'
$replay = Join-Path $env:TEMP ('d41-scope-cases-' + [Guid]::NewGuid().ToString('N'))
python -X utf8 -B "$phase/scope_cases_prepare.py" --output-dir "$replay/authored" --controls "$replay/controls.json" --evidence "$replay/evidence.json"
python -X utf8 -B "$phase/scope_cases_historical_supplement.py" --output-dir "$replay/supplement" --receipt "$replay/supplement.json"
python -X utf8 -B "$phase/scope_cases_runtime.py" authored --scratch "$replay/authored" --input "$replay/controls.json" --output "$replay/authored.runtime.json"
python -X utf8 -B "$phase/scope_cases_runtime.py" supplement --scratch "$replay/supplement" --input "$replay/supplement.json" --output "$replay/supplement.runtime.json"
```

初次源复核把 D4.0 接受动作字段当作整数检查，实际字段是列表。按固定动作列表核验后重新准备，19 个冻结控制的摘要逐字一致。源准备、旧证据绑定、现场编译和归档模型动作始终分开记录。
