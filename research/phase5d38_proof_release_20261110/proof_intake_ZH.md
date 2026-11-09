# D3.8 公开证明题面与来源验收

本轮核对了 12 个保持上游题面不变的公开声明。所选版本有 7 个源码证明体与 5 个占位证明。实际在匹配的 Lean 4.27.0 标准库环境中核验了 3 个完整证明，另做 3 个独立的删证明对照。其余条目仍是源码验收。全部操作使用 CPU，未生成模型任务或读取任何新增模型结果。[源码与环境清单](proof_intake_manifest.json) · [Lean 实机回执](proof_intake_std_kernel.json)

## 公开源码候选

| 来源 | 声明 | 核查结果 |
| --- | --- | --- |
| DeepMind MiniF2F | `mathd_numbertheory_66` | 闭合自然数取模等式，Lean 4 源码有完整证明。[精确行号](https://github.com/google-deepmind/miniF2F/blob/f0a20e14c1eeccd859d51bb4c2b3ee487889c303/MiniF2F/Test.lean#L1271-L1272) |
| DeepMind MiniF2F | `mathd_algebra_302` | 缩放复单位的平方，Lean 4 源码有完整证明。[精确行号](https://github.com/google-deepmind/miniF2F/blob/f0a20e14c1eeccd859d51bb4c2b3ee487889c303/MiniF2F/Test.lean#L1437-L1438) |
| DeepMind MiniF2F | `mathd_algebra_141` | 由边长积及周长求对角线平方，所选 Lean 4 版本只有占位。[精确行号](https://github.com/google-deepmind/miniF2F/blob/f0a20e14c1eeccd859d51bb4c2b3ee487889c303/MiniF2F/Test.lean#L37-L39) |
| DeepMind MiniF2F | `numbertheory_4x3m7y3neq2003` | 两个加权立方的差不可取目标值，所选 Lean 4 版本只有占位。[精确行号](https://github.com/google-deepmind/miniF2F/blob/f0a20e14c1eeccd859d51bb4c2b3ee487889c303/MiniF2F/Test.lean#L17-L18) |
| DeepMind MiniF2F | `induction_12dvd4expnp1p20` | 自然数指数式的整除性，所选 Lean 4 版本只有占位。[精确行号](https://github.com/google-deepmind/miniF2F/blob/f0a20e14c1eeccd859d51bb4c2b3ee487889c303/MiniF2F/Test.lean#L172-L173) |
| PutnamBench | `putnam_1978_a1` | 等差有限集内的鸽巢配对，仅有公开题面。[精确行号](https://github.com/trishullab/PutnamBench/blob/a635813f5edf297d928f9bd5ef8324a26bdde09c/lean4/src/putnam_1978_a1.lean#L6-L11) |
| PutnamBench | `putnam_1994_a1` | 由正项二叉不等式证明部分和趋于无穷，仅有公开题面。[精确行号](https://github.com/trishullab/PutnamBench/blob/a635813f5edf297d928f9bd5ef8324a26bdde09c/lean4/src/putnam_1994_a1.lean#L8-L12) |
| VeriSoftBench 363 | `compile_aexp_correct` | 算术表达式编译的模拟契约。题面及证明与原项目按空白规范化后逐项一致。[上游源码](https://github.com/leanprover/LeroyCompilerVerificationCourse/blob/a2730e7f9228b9d7ecf4510f1f8652f2cae7ba01/LeroyCompilerVerificationCourse/Compil.lean#L351-L393) |
| VeriSoftBench 364 | `cexec_to_reds` | 大步终止蕴含归约至跳过指令。题面及证明与原项目按空白规范化后逐项一致。[上游源码](https://github.com/leanprover/LeroyCompilerVerificationCourse/blob/a2730e7f9228b9d7ecf4510f1f8652f2cae7ba01/LeroyCompilerVerificationCourse/Imp.lean#L363-L385) |
| Lean Std | `denote_blastGetLsbD` | 索引读取的电路语义。改名后保留原证明，实机通过。[精确行号](https://github.com/leanprover/lean4/blob/db93fe1608548721853390a10cd40580fe7d22ae/src/Std/Tactic/BVDecide/Bitblast/BVExpr/Circuit/Lemmas/Operations/GetLsbD.lean#L42-L52) |
| Lean Std | `denote_blastAppend` | 拼接电路两侧索引的正确语义。改名后保留原证明，实机通过。[精确行号](https://github.com/leanprover/lean4/blob/db93fe1608548721853390a10cd40580fe7d22ae/src/Std/Tactic/BVDecide/Bitblast/BVExpr/Circuit/Lemmas/Operations/Append.lean#L29-L49) |
| Lean Std | `mkEq_denote_eq` | 位向量等价电路的正确性。改名后保留原证明，实机通过。[精确行号](https://github.com/leanprover/lean4/blob/db93fe1608548721853390a10cd40580fe7d22ae/src/Std/Tactic/BVDecide/Bitblast/BVExpr/Circuit/Lemmas/Operations/Eq.lean#L27-L44) |

DeepMind 测试文件含 244 个顶层 `theorem` 行和 242 个 `sorry` 词元。选中的五个名称在 OpenAI 原版 Lean 3 中都存在完整源码证明，因此三个占位只描述所选 Lean 4 fork 的状态。Lean 3 参考和 Lean 4 目标分别记录字节及声明哈希，未假定其跨版本等价或移植成功。它们属于公开开发题，不能当作证明新颖性留出数据。[DeepMind 目标文件](https://github.com/google-deepmind/miniF2F/blob/f0a20e14c1eeccd859d51bb4c2b3ee487889c303/MiniF2F/Test.lean) · [OpenAI 原版 Lean 3](https://github.com/openai/miniF2F/blob/4e433ff5cadff23f9911a2bb5bbab2d351ce5554/lean/src/test.lean)

DeepMind 的 Lean 4.27.0 同时固定 Mathlib 和 Formal Conjectures，原版 OpenAI 为 Lean 3.42.1，Yang 移植版为 Lean 4.24.0。PutnamBench 的两个候选同属 Lean 4.33.1，源文件没有数值答案占位声明。排除另有答案注释和占位答案的 1988 A1。所查 VeriSoftBench 的 23 个原项目无一固定到 Lean 4.27.0。Leroy 项目使用 Lean 4.23.0-rc2 和 Batteries，两个证明保留在这个独立环境。二者还需要各自文件中合法的前置本地定义或辅助引理。未将多个工具链混算。[DeepMind 环境](https://github.com/google-deepmind/miniF2F/blob/f0a20e14c1eeccd859d51bb4c2b3ee487889c303/lake-manifest.json) · [Yang 环境](https://github.com/yangky11/miniF2F-lean4/blob/5746b7d6c47855ce1294bed87329618ff7f1bc31/lean-toolchain) · [Putnam 环境](https://github.com/trishullab/PutnamBench/blob/a635813f5edf297d928f9bd5ef8324a26bdde09c/lean4/lean-toolchain) · [VeriSoft 项目快照](https://github.com/utopia-group/VeriSoftBench/blob/8f5e8b36ab5fbdec6fd8d8f4ee0580d29647097a/repos.json)

## 最小可运行块与目标泄漏控制

当前实机块用正式发布的 Lean 4.27.0 二进制执行。每题仅取原文件的 Basic 和相应操作实现两项导入，重建原命名空间与类型类环境，删去目标定理本身所在的 Lemmas 操作模块。三个原目标的限定名在这个环境中均经 `#check` 证实为未知。原目标模块导入只出现在单独的正向泄漏控制进程。实际验收进程编译改名后的原始声明和原始证明，未携带同文件辅助证明。声明去掉额外的可见性和 simp 属性，类型和证明体仍按源码绑定。

每题的原证明与隔离改名证明都有相同的传递公理集合。GetLsbD 和 Append 为 `propext`、`Quot.sound`，Eq 另有 `Classical.choice`。没有额外公理。三个独立删证明控制仅把原证明替换成 `by skip`，在相同声明上均留下未解目标。三次各自同导入的 `exact?` 查询都没有闭合，这一控制只能覆盖所用查询。首轮尝试把 `#print axioms` 放在 `module` 内，Lean 拒绝该命令。调整为独立 prelude 文件和相同两项普通导入后通过。用干净临时文件再跑一次，除时钟与路径规范化外的记录一致。[检查脚本](proof_intake_std_checks.py) · [原始诊断的公开回执](proof_intake_std_kernel.json)

这些自然来源的正例用于确认声明与内核边界。三条删证明对照是合成控制，数据中没有自然模型失败，也没有由同题多种修改构成的独立样本。已知证明的正文不放入任务清单，隔离执行从固定提交取源码，保留声明、证明及环境摘要。正式放入模型前仍需完整比对目标类型、预先冻结合法导入、核对参考证书与模型草稿隔离，并通过原目标及别名泄漏控制。

## 复核

清单 `sources` 记录各 Git URL 和精确提交。将相应提交取到一个共同前缀的七个目录，后缀依次为 `-0` OpenAI、`-1` Yang、`-2` Putnam、`-3` VeriSoftBench、`-4` DeepMind、`-5` Lean、`-7` Leroy。可用不检出的 Git 克隆，脚本按固定对象读取源文件。

先运行 `proof_intake_std_checks.py --checkout <前缀-5> --lean <Lean 4.27.0 可执行文件> --output <新回执>`，再运行 `proof_intake_sources.py --checkout-prefix <前缀> --std-receipt <新回执> --output <新清单>`。生成的复算报告使用独占写入。DeepMind 和另外两套项目的独立工具链状态单列。[源码核对脚本](proof_intake_sources.py)
