# Phase5-A 结果解释

2026-11-06。已读完全部19个实际输出；本页不改变冻结评分，不补生成、不运行GPU，也不修改原始资料。

**结论：本轮没有显示 VersionFrame 超过简单强基线；它的两条失分主要是格式未交付，不是观察到的算术错误。** 下一步宜先统一未来输出契约、审阅真实自然失败，不扩大训练、KV或模型队列。

## 完整性与原分数

计划30输出，实际完成19：6个能力控制、3个完整四臂配对（T1E/T2E/T1C），以及T2C的Direct一条。余下11输出未跑；W主方法零样本。额外T2C Direct答对63，但不加入完整配对主表。

worker约261.08秒、状态 `QUALITY_PARTIAL_TIME_BUDGET`；进程退出0不等于全完成。19个完成输出均自然EOS，最长419 token，没有512 cap或被切断的generation。partial发生在日程覆盖层，不是已有答案撞到保护顶。

| 方法 | 冻结正确 / 完整配对 | EOS | cap | 未解析 |
|---|---:|---:|---:|---:|
| SharedGDirect | 3/3 | 3 | 0 | 0 |
| SharedGCompact | 3/3 | 3 | 0 | 0 |
| SharedGStepwise | 3/3 | 3 | 0 | 0 |
| VersionFrame | 1/3 | 3 | 0 | 2 |

分母只有两个程序的三个相关状态，不支持自然总体准确率、统计优越性或W安全结论。

## 两个失败应怎样归类

T1E和T1C的VersionFrame都在102 token正常EOS，输出JSON：候选y的表达式为`3*18+2`、值56；候选z为`56+24`、值80；末尾为`"final_answer":80`。

数值与题目相符，但没有以冻结契约的“最终答案：整数”结尾。parser不接受该JSON闭括号尾部，因此两条仍计 `unresolved`，主分维持1/3。**不能说模型把这两题算错，也不能事后增加JSON提取给它补分。** 这是表示/交付接口不对齐。

T2E的VersionFrame答对63，但先复制了`current_roots`、`dirty_descendants`和`symbolic_ready_plan`等整份状态，再给候选计算和正式答案，共419 token。这支持“工作帧诱导结构复制”的线索，不是完整controller在逐步验收。

Direct/Compact/Stepwise三配对均给出正确计算和答案。Direct实际也展开了r/x/y/z，不能把提示名称理解成“没有推导”。Stepwise在T1C称某中间值有效，是模型自己的叙述，不是代码颁发的证书；本轮从未验收新y/z。

## 能力与成本的边界

2个P-only、4个P+R均自然EOS且正确，包括两个错误R控制。这只说明两个程序在这些简短提示下可解，错误R本身并不必然造成失败；它不证明G必需或自然任务100%可解。

同三配对的实际生成token：Direct350、Compact339、Stepwise906、Frame623；prompt token分别2535、2547、2667、3686。Frame没有展现可靠的质量增量或“一半token”优势。质量优先也应诚实保留这些成本，但不能以短输出替代答对。

全轮模型前向2994次、输入15925 token、同步forward约191.94秒，已包括在worker总wall中，不重复相加。`summary.basis_results.kind`粗写为`basis`，P-only/PR分类应依冻结prepared_dataset和逐job provenance还原；不改raw或分数。

## 支持什么、还不能说什么

- 支持：宽松顶使已运行子集摆脱了64-token提交截断；简单强基线已有充分能力；两个Frame失败主要是JSON输出契约，另一条有状态复制。
- 不支持：Frame已提高数学能力、版本管理原理无效、完整controller已实现、W安全、自然泛化或训练/KV必要性。
- shared G只认证根x/r，结构来自受限AST；最终答对并不等于y/z已由外部检查器认证。主轮W未测，能力控制的错误R不能代替它。

## 下一最小检查

暂不自动补齐11输出，也不扩大GPU。先用无gold的通用例做CPU交付契约测试，统一未来各方法是否接受JSON/自然语言终端标记、如何处理歧义和未完成字段；本轮分数不动。

可证伪猜想是“JSON-heavy状态表示诱导schema模仿/复制，而非数值失败”。未来若确需一次小确认，应在独立新程序上用同数学信息的简洁文本frame与JSON-frame、强Compact对照；若同样无质量增量，就停止该提示表示的升级，而不是继续换词调到赢。

更重要的CPU/人工工作是找出自然轨迹里“正确根修订后，强Compact仍出现真实传播错误”的案例与unknown。若没有足够事件，当前两个简单程序不足以支撑主算法。保持简单高质基线，是这次短试允许的研究决定。

依据：[原始结果](results/quality_round_01/summary.json)、[冻结协议](QUALITY_PROTOCOL_V1.json)、[判读预案](RESULT_INTERPRETATION_PLAN_ZH.md)。本报告不重评分、不把格式失分改称算术失败。
