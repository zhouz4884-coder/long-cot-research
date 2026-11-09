# BlueprintTrace 已发布模型尝试的外部复核

从固定发布数据 `504b7ae3604f363a3cf5e32308b08d2ac258ac25` 的 142 个 `state_id` 中，在读取轨迹前按带盐 SHA-256 排序冻结六个 ID。每个 ID 保留两种模型与三种接口的全部正式发布轨迹。两个压缩档和状态表都通过作者清单的 SHA-256 校验。作者对初始蓝图注入故障，后续模型回复和验证器日志来自公开运行。[样本冻结](blueprint_trace_freeze.json) · [作者数据版本](https://huggingface.co/datasets/Karifannaa/BlueprintTrace/tree/504b7ae3604f363a3cf5e32308b08d2ac258ac25)

| 固定样本 | 结果 |
| --- | --- |
| 状态与完整轨迹 | 6 个蓝图状态，36 条轨迹，60 次模型尝试 |
| 作者轨迹终局 | 35 条修复成功，1 条用尽预算 |
| 模型尝试 | 35 次作者验收、21 次归档 Lean 错误、1 次修复框架拒绝、3 次应用后仍未完成 |
| 含已证明前置项的 Lean 错误 | 11 次，全部来自同一个 `p159_bad.state0` |
| 最终模块档案 | 24 条独立模块文件与所报 SHA-256 一致，12 条重写轨迹只保留步骤级源与检查记录 |

前置项从该次请求中可见的最新已应用图恢复，沿目标声明边向上找作者记录为 `proved` 或 `proved_and_used` 的祖先。60 次请求均能定位目标图。该统计描述作者记录的声明闭包和状态，包含同题重复尝试。它只提供一个具有相关失败的独立目标。[逐步复核和哈希](blueprint_trace_intake.json)

## p159 的反向对照

Qwen3.6-Flash 的类型化臂在第一步对错误节点调用 `weaken_node`。当时已有三条作者记录的已证明前置声明 `diff-four`、`diff-ten`、`a-value`。归档 `step01.check.elab.json` 退出码为 1，报告意外的 `theorem` token 和 `final_step` 重复声明。该臂在八步后仍未闭合。其余 Lean 错误中有重复的后续修复尝试，不能计成不同题目。[逐步原档索引](blueprint_trace_intake.json)

同题同模型的原子源码补丁在第 4 步获得作者验收。复核首轮输入和最终已验收模块，三条原有已证明前置声明从蓝图注解到下一注解的源码片段完全一致，仅在比对时去除片段两端的空白。整模块重写也在第 1 步通过。该例表明模型能在正确前置项仍然存在时遇到真实编译失败，也表明修复这一例无需替换这三条已证明声明。源码片段一致性只覆盖此处明确比较的三条声明。[保留证据](blueprint_trace_preservation.json)

## 精确复验边界

逐步归档检查均匹配作者锁定的 Lean `4.31.0`、Mathlib `fabf563a…` 和 LeanArchitect `f38c8481…`。D3.8 本地已验证环境是 Lean `4.27.0`。本次交付复核公开字节、来源身份和作者验证结果。要对原始 `.lean` 补丁做同环境本地复验，需使用作者的完整锁定工具链和依赖。[作者工具链](https://github.com/Karifannaa/BlueprintRepair/blob/954edd366a0d1474ecfebe418d4cac14aaf8c6bf/BlueprintRepair/lean-toolchain) · [作者依赖清单](https://github.com/Karifannaa/BlueprintRepair/blob/954edd366a0d1474ecfebe418d4cac14aaf8c6bf/BlueprintRepair/lake-manifest.json) · [本地运行环境](lean_runtime_controls.json)

取回后首先发现作者重写臂的终局模块字段为空，因此改用其实际发布的步骤源和编译日志记录证据。后续图边的表示也同时存在对象和二元数组，复核器分别读入后统一按声明边求祖先。两处均保留原始档案身份。重放档案计数可运行 `python -X utf8 -B research/phase5d38_proof_release_20261110/blueprint_trace_intake.py`。
