# D3.8 Lean 4 CPU 运行环境

已在工作区 `outputs/` 安装官方 Windows x64 Lean 4.27.0。实际编译器报告提交 `db93fe1608548721853390a10cd40580fe7d22ae`，Lake 为 `5.0.0-src+db93fe1`。这个版本与 DeepMind miniF2F 的固定提交 `f0a20e14c1eeccd859d51bb4c2b3ee487889c303` 所声明的工具链一致。[Lean 发行版](https://github.com/leanprover/lean4/releases/tag/v4.27.0) · [miniF2F 工具链](https://github.com/google-deepmind/miniF2F/blob/f0a20e14c1eeccd859d51bb4c2b3ee487889c303/lean-toolchain)

发行包为 `lean-4.27.0-windows.tar.zst`，505,567,614 字节，官方 SHA-256 为 `c34b9c2820857185978fc7310c8badeda68c9c16e83edecf176a8003c5fda1b2`。已校验实际下载包。下载用时 55.39 秒，安全解包用时 57.77 秒。运行调用固定的可执行文件，读取的 Lean 前缀也位于该目录。未安装 Elan，未更改用户或系统 PATH。编译器、Lake 和三个核心模块的实际哈希见证据。[官方资产哈希](https://github.com/leanprover/lean4/releases/expanded_assets/v4.27.0) · [运行回执](lean_runtime_controls.json)

## 固定核验控制

实际运行九项 CPU 控制，九项均观察到预期行为。该组只运行预先写好的可信 Lean 文件。

| 控制 | Lean 退出码 | 内核或诊断 |
| --- | ---: | --- |
| 目标命题与正确证明 | 0 | `#print axioms` 显示无公理依赖 |
| 默认 `sorry` | 0 | 告警且目标依赖 `sorryAx` |
| 严格 `sorry` | 1 | `warningAsError` 将告警升级为错误 |
| 带 `sorry` 的间接引理 | 0 | 目标的传递依赖包含 `sorryAx` |
| 严格 `admit` | 1 | 展开后触发严格模式错误 |
| 自定义公理 | 0 | 严格告警仍通过，目标依赖 `fakeEvidence` |
| 同名、错误类型的定理单独检查 | 0 | `True` 的证明合法且无公理依赖 |
| 锁定预期命题后使用同名假定理 | 1 | 类型不符，Lean 报错 |
| 在预期命题里直接提交错误证明 | 1 | 类型不符，Lean 报错 |

这些证据表明，检查返回码、严格告警、目标声明和传递公理依赖要分别验收。默认模式下两种未完成证明通过进程退出码检查。同名假声明还通过了无公理检查，只有绑定预期命题才识别出错误。这里的独立安装隔离了版本与依赖，普通本地子进程没有操作系统沙箱。公开对照不包含模型提交或 GPU 运行。[控制脚本](lean_runtime_controls.py)

## 复现

从仓库根目录运行。安装使用 Python 3.13.5 的标准库及 `zstandard` 0.23.0。运行控制使用标准库与已安装的 Lean 自带模块。

```powershell
python -X utf8 -B research/phase5d38_proof_release_20261110/lean_runtime_install.py
$lean = 'outputs/d38_lean_4_27_0_windows/lean-4.27.0-windows/bin/lean.exe'
& $lean --version
& $lean --print-prefix
python -X utf8 -B research/phase5d38_proof_release_20261110/lean_runtime_controls.py --output "$env:TEMP/d38-lean-controls-recheck.json"
```

## miniF2F 官方依赖

已读取固定 manifest 中十个 Lake 包的实际 checkout，提交均一致。Mathlib 为 `a3a10db0e9d66acbebf76c5e6a135066525ac900`，FormalConjectures 为 `f564f8d7a6d28bfeea4deeb0c12aa81348da6d73`。三个主项目的 Git 源码 tar 哈希和全部依赖的树身份见源回执。[miniF2F 固定 manifest](https://github.com/google-deepmind/miniF2F/blob/f0a20e14c1eeccd859d51bb4c2b3ee487889c303/lake-manifest.json) · [源码回执](lean_runtime_benchmark_sources.json)

首次 `lake exe cache get Mathlib` 在提取 ProofWidgets 公开资产时退出 1。Windows 的 `tar -xvvz` 在可正常完成解包的同时，用 GBK 向标准错误写入本地化月份，Lake 按 UTF-8 读取时失败。进程内 `LC_ALL=C` 复测未改变输出。恢复时使用进程私有的 `tar.exe` 适配器。它核对指定 ProofWidgets 路径和官方 SHA-256，调用相同系统 `tar.exe` 并省略详细列表，保持输入、输出和解包行为。重试从官方 Azure 缓存取回并解包 7,869 个对象，解包用时 35.044 秒。随后实际构建 `MiniF2F.ProblemImports` 成功。[ProofWidgets 发行哈希](https://github.com/leanprover-community/ProofWidgets4/releases/expanded_assets/v0.0.85) · [Mathlib 缓存说明](https://github.com/leanprover-community/mathlib4/blob/a3a10db0e9d66acbebf76c5e6a135066525ac900/Cache/README.md) · [解包适配器源码](lean_runtime_tar_quiet.cs)

从仓库根目录执行以下步骤以准备官方依赖。环境变量只用于当前 PowerShell 及其子进程。实测使用 `curl` 8.12.1、Windows `bsdtar` 3.8.9 及 Lean 自带的 Lake。官方缓存脚本在工作区准备 `leantar` 0.1.16，下载包 SHA-256 为 `454207666684180ac38bd914b028dfb3511bcd7106fe2c846231a9e235881fce`，与公开发行哈希一致。[leantar 发行资产](https://github.com/digama0/leangz/releases/expanded_assets/v0.1.16)

```powershell
$repo = (Resolve-Path .).Path
$leanBin = Join-Path $repo 'outputs/d38_lean_4_27_0_windows/lean-4.27.0-windows/bin'
$lake = Join-Path $leanBin 'lake.exe'
$bench = Join-Path $repo 'outputs/d38_minif2f_f0a20e14'
$cache = Join-Path $repo 'outputs/d38_mathlib_cache_f0a20e14'
$env:PATH = $leanBin + ';' + $env:PATH
$env:MATHLIB_CACHE_DIR = $cache
$env:XDG_CACHE_HOME = $cache
$env:GIT_TERMINAL_PROMPT = '0'
$env:GIT_CONFIG_COUNT = '1'
$env:GIT_CONFIG_KEY_0 = 'core.longpaths'
$env:GIT_CONFIG_VALUE_0 = 'true'
git clone --filter=blob:none --no-checkout https://github.com/google-deepmind/miniF2F.git $bench
git -C $bench checkout --detach f0a20e14c1eeccd859d51bb4c2b3ee487889c303
Push-Location $bench
try {
    & $lake exe cache get Mathlib
    if ($LASTEXITCODE -eq 0) { & $lake build MiniF2F.ProblemImports }
} finally { Pop-Location }
```

若观察到上述 ProofWidgets UTF-8 错误，可用以下实际恢复命令。成功后的 `build MiniF2F.ProblemImports` 只引入公共依赖，比赛的 `Test` 和 `Valid` 模块未编译到对照环境中。

```powershell
$shim = Join-Path $cache 'quiet-tar'
New-Item -ItemType Directory -Force -Path $shim | Out-Null
$shimSource = (Resolve-Path research/phase5d38_proof_release_20261110/lean_runtime_tar_quiet.cs).Path
$shimBinary = Join-Path $shim 'tar.exe'
& 'C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe' /nologo /optimize+ /target:exe "/out:$shimBinary" $shimSource
$env:D38_PROOFWIDGETS_ROOT = Join-Path $bench '.lake/packages/proofwidgets/.lake'
$env:PATH = $shim + ';' + $env:PATH
Push-Location $bench
try {
    & $lake exe cache get Mathlib
    if ($LASTEXITCODE -eq 0) { & $lake build MiniF2F.ProblemImports }
} finally { Pop-Location }
```

## 官方导入下的定理复核

十项检查均观察到预期行为。原作者提供的 `mathd_numbertheory_66` 完整证明通过且无公理。`mathd_algebra_302` 完整证明通过，依赖 `Classical.choice`、`Quot.sound` 和 `propext`。另外三个未经修改的正式题面只运行 `by skip`，Lean 报告未完成目标，属于题面编译对照。五个相同名称的 `#check` 导入对照都报未知标识符，确认该运行导入没有预装这些目标定理。[题源与范围](proof_intake_manifest.json) · [官方运行回执](lean_runtime_benchmark_controls.json)

七千余个缓存文件的总量为 397,805,659 字节。对排序后的相对路径、大小和逐文件 SHA-256 计算总哈希，结果为 `c8b1ae1e755e5a6eeac9a29909b5f30ad00d4ae2c1fe64756b302770a5e14dc6`。回执另含实际使用的 `MiniF2F.ProblemImports`、`Mathlib` 和 `FormalConjectures.Util.Answer` 编译产物哈希。每项复核用单独的 `lake env lean` 子进程，墙钟介于 31.43 至 32.89 秒，包含启动和导入。作者证明和 `by skip` 控制均未用于模型结果。[复核脚本](lean_runtime_benchmark.py)

复核脚本默认从固定 Git 源文件重建十份已验哈希的夹具，拒绝执行哈希不同的夹具。准备好依赖后，从仓库根目录运行。

```powershell
python -X utf8 -B research/phase5d38_proof_release_20261110/lean_runtime_benchmark.py --output "$env:TEMP/d38-minif2f-recheck.json"
```
