# D3.6 公开 CPU 复现

从包含 D3.6 阶段文件和基线提交 `306776757727` 的公开检出开始。旧 D3 原始轨迹、可见题面、评估参考与 F2 代码都来自基线 Git 对象。当前入口将生成文件写入新的目录，仓库中的冻结报告会保留原字节。

## 环境与命令

本次复现用 Python 3.13.5。在 PowerShell 下，从仓库根目录运行以下命令。安装单独的 CPU 环境后，复现入口从 ModelScope 固定提交下载 6 个小型配置和 tokenizer 文件。逐文件验证长度和 SHA-256，并与已发布的 D3.5 实机清单逐项比对。无需模型权重、GPU 或实验室主机。首次默认下载约 16 MB。已有相同文件可加 `--tokenizer-dir <目录>` 跳过下载，校验仍执行。[ModelScope 官方模型](https://modelscope.cn/models/Qwen/Qwen3-4B) · [固定资产清单](D36_CPU_TOKENIZER_ASSETS.json)

```powershell
git clone --filter=blob:none https://github.com/zhouz4884-coder/long-cot-research.git
Set-Location long-cot-research
$venv = Join-Path $env:TEMP ('longcot-d36-env-' + [Guid]::NewGuid().ToString('N'))
python -m venv $venv
$py = Join-Path $venv 'Scripts/python.exe'
& $py -m pip install transformers==5.4.0 tokenizers==0.22.2 math-verify==0.9.0 latex2sympy2_extended==1.11.0 sympy==1.14.0 antlr4-python3-runtime==4.13.2 mpmath==1.3.0
$replay = Join-Path $env:TEMP ('longcot-d36-cpu-' + [Guid]::NewGuid().ToString('N'))
& $py -X utf8 -B research/phase5d36_progressive_witness_20261109/replay_d36_cpu_public.py --output-dir $replay
```

Linux 和 macOS 可使用同一 Python 脚本，将虚拟环境解释器路径换成虚拟环境目录下的 `bin/python`，并给 `--output-dir` 传入一个尚未存在的本地目录。Git 浅检出若没有 `306776757727`，需先取得含该提交的历史。

脚本依次运行盲观察、绑定该次观察 SHA-256 的评分、数值上下文复核。验收比较三份报告的规范化 JSON。观察时间、证书测得耗时、首次参考答案打开时间与依赖这些字段的观察哈希随复跑变化，其他内容逐项一致才通过。输出目录中的 `D36_CPU_REPLAY_RECEIPT.json` 记录资产版本与规范化报告哈希。[复现入口](replay_d36_cpu_public.py)

本次在独立稀疏检出中用基线 Git 对象和待发布的本阶段 CPU 文件复跑，目录中起初没有 tokenizer。通过 ModelScope 下载并验证全部 6 个文件，三份报告的规范化 JSON 均一致，反向控制保留了 Final。[实际复核回执](D36_CPU_REPLAY_VALIDATION.json)

## 两个审计边界

冻结题面提取在 16 题中给出 15 个非空目标表述。E12 的末句用逗号接 `compute c5`，原词法入口漏掉该目标表述。该题的公开题干仍由 D3.5 数列契约绑定到 `c5`，实际改值与完整证书由该契约独立核验。E13 的题意要求找全部整数，原冻结题库的公开答案类型为标量。这两点约束词法覆盖解读，原矩阵和冻结提取规则保留。[初始观察](D36_CROSS_PHASE_OBSERVATIONS.json)

真实 D3 的 32 条轨迹没有发现 Thinking 错而 Final 对的反向例。原合成控制覆盖未知契约的弃权。复现入口另跑一个可信 E15 契约下的合成反向例。前段提出并选择可行但次优的 `1011235`，最终文本改为 `10112369`。Qwen tokenizer 重解码后，见证门控签发 `FEASIBLE_ONLY`，原题约束成立，完整最大值仍未认证。交付保留 Final。这个反向对照只验证权限边界，独立真题的改错率仍需另外测量。
