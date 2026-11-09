# D3.9 审核过的原目标复验

按 D3.8 冻结的 BlueprintTrace 数据版本和两个压缩包 SHA-256 读取指定成员。归档仅作为数据解析。没有运行原始 `gate.lean` 中的 `#eval`、含占位证明的初始模块、失败草稿或模型消息里的任何外部指令。仅当目标头、整段源码哈希、作者检查记录和逐段语法复核一致时，才将固定证明写到独立临时目录。可运行片段仍使用原作者固定的 Lean 4.31.0、Mathlib 与 LeanArchitect，校验解释器、项目配置、包提交及导入构件。此流程使用已审定的源码，未建立面向任意模型代码的操作系统沙箱。[作者归档版本](https://huggingface.co/datasets/Karifannaa/BlueprintTrace/tree/504b7ae3604f363a3cf5e32308b08d2ac258ac25) · [作者项目配置](https://github.com/Karifannaa/BlueprintRepair/blob/954edd366a0d1474ecfebe418d4cac14aaf8c6bf/BlueprintRepair/lake-manifest.json)

## p159 精确补丁与已证前置项

从归档的共同初始模块重建 Qwen 四次局部补丁。每个 SEARCH 片段只匹配一次，逐步重建的模块哈希都与作者记录一致，目标声明头始终一致。前三次作者检查都报 `No goals to be solved`，第 4 次闭合。完整终局模块有五条审核过的普通定理。用于精确复跑的作者检查文件只有这些声明与既有的公理打印后缀。[来源和逐步跨度回执](p159_reviewed_source_receipt.json)

匹配运行时中，原检查文件与独立目标类型检查均通过。单独复验最初三条已证声明 `diff_four`、`a_value`、`diff_ten`。初始与修复后分别启动 Lean，三个声明的 elaborated 类型显示、类型直接常量、证明体直接常量及传递公理集合全部相同。五个目标命名空间内的常量在未载入审核声明时均报未知。实际目标证明直接引用 `a_value`、`diff_ten`、`final_step`，并通过 `a_value` 传递使用 `diff_four`。这些引用边与归档作者图一致。这里比较的运行时证据覆盖明确列出的声明、类型和常量集合。[原检查及运行观察](p159_p159_runtime_observed.json) · [身份比对回执](p159_identity_receipt.json)

初始辅助命题 `final_step` 没有约束 `a = 3`，由 `a = d = 0` 得到反例。该反例的独立 Lean 证书通过。作者补丁改变错误辅助命题并修复目标证明，保留原来三个已证单元。这个例子的完整修复已在作者局部补丁中出现。[受审源提取器](p159_prepare_reviewed.py)

## p165 原证明体回填

DeepSeek 重写轨迹的 episode 终局模块字段为空。真正验收的是第 3 步 rescan。其回复 Lean 围栏和步骤模块哈希一致，作者检查源另外附带公理输出指令，因此文件哈希单列。原目标声明头与初始档案相同。作者重写改变了三个原来具有完整证明的前置体。对照仅把这三个证明体换回旧字节，保留成功版本的目标、签名、注解和其他证明。[作者 rescan 与回填源码回执](p159_p165_source_receipt.json)

四个审核片段全部通过匹配环境。原作者检查与显式类型检查通过，三条旧证明单独通过，同目标回填完整证明也通过。两个完整证明通过相同的独立目标类型检查，旧证明对应的传递公理集合一致。读取回填后的 Lean 证明项确认，目标直接引用 `a_value`、`b_cubed`、`b_value`，三个恢复的旧证明都进入实际依赖闭包。由此得到本例的保留证书，三个旧已证单元无需释放。该控制使用作者已经找到的成功后缀，尚未测得在线寻找后缀的能力。[运行观察](p159_p165_runtime_observed.json) · [内核比对回执](p159_p165_kernel_receipt.json) · [实际依赖回执](p159_closure_probe_receipt.json)

## p94 保留旧辅助引理的桥接

Qwen 与 DeepSeek 从完全相同的初始模块出发。Qwen 第 1 次修改已经完整证明带和约束的乘积上界。作者公理报告没有 `sorryAx`。同一检查中，目标证明在自然数截断减法的等式上失败，目标自己的公理报告带 `sorryAx`。DeepSeek 的另一条轨迹通过了展开形式的目标。由这两个已绑定档案制作跨轨迹控制，精确保留 Qwen 的旧辅助声明，并加入一个经加法展开连接两种上界的桥接。[桥接源码回执](p159_p94_source_receipt.json)

作者精确检查、作者显式类型检查、Qwen 旧引理独立复验和保留引理后的桥接均通过。两个完整证明的显式目标类型相同，旧引理在独立检查和桥接中的传递公理集合也一致。桥接用 `ring` 展开加法恒等式，再由和等于 12 和旧上界推出新上界。旧引理的源码字节全部保留。Lean 证明项给出的实际依赖路径为 `p94_target → product_bound_expanded → product_bound_wrong`。该证书验证同一目标在保留引理时可证明，桥接是本轮独立构造的跨轨迹对照。[运行观察](p159_p94_runtime_observed.json) · [内核比对回执](p159_p94_kernel_receipt.json) · [实际依赖回执](p159_closure_probe_receipt.json)

p149 和 p151 的作者最终检查也经过源审核。作者图中看似发生更换的已证前置在初始源里是带占位的证明，不能据标签把它们算作已证单元被释放。初次准备时 p149 的 episode 摘要转录有误，脚本按哈希拒绝。随后重新从固定压缩包计算摘要并通过。两份审核源仅作为单独来源对照，本报告未对其启动 Lean。[候选对照](p159_adjacent_source_receipt.json)

## 复核入口

使用含 D3.8 基线 Git 对象的检出，并按 [作者运行环境](author_runtime_ZH.md) 准备固定工具链。将两个作者归档放入系统临时目录，文件名与准备脚本的默认路径一致，或显式传入归档路径。每次使用新输出目录，原有回执保持原字节。下面命令从仓库根目录执行。

```powershell
$phase = 'research/phase5d39_blueprint_trace_20261110'
$replay = Join-Path $env:TEMP ('d39-reviewed-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $replay | Out-Null
python -X utf8 -B "$phase/p159_prepare_reviewed.py" --output-dir "$replay/p159" --receipt "$replay/p159.source.json"
python -X utf8 -B "$phase/p159_p165_prepare.py" --output-dir "$replay/p165" --receipt "$replay/p165.source.json"
python -X utf8 -B "$phase/p159_p94_prepare.py" --output-dir "$replay/p94" --receipt "$replay/p94.source.json"
foreach ($suite in 'p159','p165','p94') {
    python -X utf8 -B "$phase/p159_run_reviewed.py" $suite --scratch "$replay/$suite" --output "$replay/$suite.runtime.json"
    if ($LASTEXITCODE -ne 0) { throw "Lean runtime check failed for $suite" }
}
python -X utf8 -B "$phase/p159_identity_audit.py" --observed "$replay/p159.runtime.json" --output "$replay/p159.identity.json"
python -X utf8 -B "$phase/p159_preserving_audit.py" p165 --observed "$replay/p165.runtime.json" --output "$replay/p165.kernel.json"
python -X utf8 -B "$phase/p159_preserving_audit.py" p94 --observed "$replay/p94.runtime.json" --output "$replay/p94.kernel.json"
python -X utf8 -B "$phase/p159_closure_probe.py" --p165-scratch "$replay/p165" --p94-scratch "$replay/p94" --freeze "$replay/closure.freeze.json" --output "$replay/closure.receipt.json"
```

固定运行器核对源回执与本地夹具哈希、运行时正例回执、作者项目与各依赖提交，再调用 Lean。最后一个脚本只给两份已检查的保留夹具添加固定的只读类型和依赖探针，记录类型和证明表达式里的全部直接常量、审核声明内的传递路径及全局传递公理集合。模型输入仍与归档证明、编译输出及对照证书分开。[固定运行器](p159_run_reviewed.py) · [依赖探针](p159_closure_probe.py) · [探针输入冻结](p159_closure_probe_freeze.json)
