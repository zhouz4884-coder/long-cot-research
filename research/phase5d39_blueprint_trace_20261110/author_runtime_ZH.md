# D3.9 BlueprintRepair 作者工具链

D3.8 冻结的 BlueprintTrace 作者提交为 `954edd366a0d1474ecfebe418d4cac14aaf8c6bf`。已在工作区安装与作者 `lean-toolchain` 一致的 Windows x64 Lean **4.31.0**，实际编译器提交为 `68218e876d2a38b1985b8590fff244a83c321783`，Lake 报告 `5.0.0-src+68218e8`。已核验官方 tar.zst 的 571,062,457 字节和 SHA-256 `9d482ee0c1af858cddb5bfb582969499a787caf9c4f953bc81d512da6dcc12c7`。下载 44.06 秒，解包 66.52 秒。Lean、Lake 和核心 `.olean` 哈希另列。[固定轨迹选择](../phase5d38_proof_release_20261110/blueprint_trace_freeze.json) · [作者工具链](https://github.com/Karifannaa/BlueprintRepair/blob/954edd366a0d1474ecfebe418d4cac14aaf8c6bf/BlueprintRepair/lean-toolchain) · [官方资产](https://github.com/leanprover/lean4/releases/expanded_assets/v4.31.0) · [工具链回执](author_runtime_toolchain.json)

## 源文件与安装问题

Windows Git 拒绝作者仓库部分旧导出的 `.tex` 路径，文件名包含冒号。完整检出、初始稀疏检出和给完整提交加路径筛选的归档均触发同一限制。最终从裸 Git 对象库直接定位 `BlueprintRepair` 子树对象 `dcbd16eb1acb227965f3ec346254465c6b499c21`，只物化该项目。第一次子树归档还受到机器原有 `core.autocrlf=true` 影响，例如 `BlueprintRepair.lean` 从 345 字节变为 353 字节。使用仅对该归档命令有效的 `git -c core.autocrlf=false` 重新物化后，939 个项目文件均与 Git blob 相符。完整的 Git 与 NTFS 路径保护保留。子树 tar 为 1,710,080 字节，SHA-256 `d1a81a9e9d7a6e461aefa966fda06fc5a3b40381899ac80e5d2b462b9f9ea850`。[源文件回执](author_runtime_sources.json)

核对了作者 `lean-toolchain`、`lake-manifest.json` 和 `lakefile.toml` 的原字节，以及 manifest 中十个依赖的实际提交和树。直接依赖是 Mathlib `fabf563a7c95a166b8d7b6efca11c8b4dc9d911f` 和 LeanArchitect `f38c848196b0467e7b9dcc3d129a866b4051c23c`。LeanArchitect 的实际模块名为 `Architect`。[作者 manifest](https://github.com/Karifannaa/BlueprintRepair/blob/954edd366a0d1474ecfebe418d4cac14aaf8c6bf/BlueprintRepair/lake-manifest.json) · [LeanArchitect 库定义](https://github.com/hanwenzhu/LeanArchitect/blob/f38c848196b0467e7b9dcc3d129a866b4051c23c/lakefile.lean)

## 实际编译结果

官方 Azure Mathlib 缓存一次完成，下载并解包 **8,542/8,542** 个对象，总用时 103.72 秒。本版本使用发行包内的 `leantar` 0.1.19，未触发 D3.8 的详细解包日志编码错误。缓存的 8,542 个压缩文件合计 432,264,798 字节，按相对路径、大小与逐文件 SHA-256 聚合后的哈希为 `101959261c0f56313baaf01dd6f1f826fed480ae1c1a5c0d665754a0bc70e58a`。`lake build @LeanArchitect/Architect` 完成 13 个作业，用时 12.41 秒。[Mathlib 缓存回执](author_runtime_cache_azure1.json) · [LeanArchitect 构建回执](author_runtime_build.json)

可信夹具同时导入 `Mathlib` 和 `Architect`，在严格告警下使用 `@[blueprint]` 标注，由 `ring` 证明固定自然数平方恒等式。Lean 返回 0，目标的传递公理仅含 `propext`。从 Lake 启动到返回用时 21.17 秒。Mathlib 和 Architect 实际导入产物哈希在回执中。作者依赖导入已通过，可供后续经过审查的夹具使用。[实际 Lean 回执](author_runtime_smoke.json)

## 复现入口

从仓库根目录运行。Python 3.13.5 和 `zstandard` 0.23.0 用于解包。Git 2.53.0 支持按作者提交时间冻结子树 tar。所有下载、Git 对象、缓存与二进制均在 `outputs/`，命令只修改其子进程环境。

```powershell
$phase = 'research/phase5d39_blueprint_trace_20261110'
python -X utf8 -B "$phase/author_runtime_setup.py" toolchain --output "$env:TEMP/d39-lean-release.json"
python -X utf8 -B "$phase/author_runtime_setup.py" sources --output "$env:TEMP/d39-lean-sources.json"
python -X utf8 -B "$phase/author_runtime_verify.py" cache --attempt repro --output "$env:TEMP/d39-lean-cache.json"
python -X utf8 -B "$phase/author_runtime_verify.py" build --attempt repro --output "$env:TEMP/d39-lean-build.json"
python -X utf8 -B "$phase/author_runtime_verify.py" smoke --output "$env:TEMP/d39-lean-smoke.json"
```

首次缓存需要额外磁盘空间，脚本以 7 GB 可用空间作为启动条件。已有上述编译缓存时可直接复核夹具。

运行目录是 `outputs/d39_blueprintrepair_954edd3/BlueprintRepair`。使用工作区 `outputs/d39_lean_4_31_0_windows/lean-4.31.0-windows/bin` 内的 Lean 与 Lake，将该目录置于子进程 PATH 首部，清除外部 `LEAN_PATH` 和 `LEAN_SYSROOT`，再执行 `lake.exe env <绝对路径>/lean.exe --json AuthorRuntimePositive.lean`。此方式固定编译器和导入依赖。它是 Windows 上的可信 CPU 夹具验证，未执行归档模型代码，也未启动 GPU。
