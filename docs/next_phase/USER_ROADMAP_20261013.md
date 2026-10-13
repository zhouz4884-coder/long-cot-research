# 2026-10-13 研究路线图：从错误 STOP 到风险约束的自适应推理

**证据范围**：本方案依据用户上传的 10 份 Markdown 文件（实验报告、协议、基线审计、数值验收、创新假设、复现说明、工作日志）。未获得原始代码仓库、1648 条在线输出、逐题预测 JSON 或 GPU 主机访问，所以文中所有新增机制与收益均为**待验证方案**，不是实测成果。公开文献截至 2026-10-13。

## 1. 当前冻结成果与失败事实

- 主模型 Qwen3-4B（模型 revision `1cfa9a7208912126459214e8b04321603b3df60c`），FP16/SDPA、Torch 2.8.0+cu128、Transformers 4.55.2；Thinking，T=0.6，top_p=.95，top_k=20，思考≤8192、答案≤192。
- MATH-500，数据 revision `6e4ed1a2a79af7d8630a6b768ec859cb5af4d3be`，150/50/300 题独立划分。既有 300 题现在属于已观察测试，未来新算法**不可**再次作为未见测试。
- 1648 条真实在线记录已审计；300 题 FULL 269/300，净收益控制器 248/300，正确率停止 261/300，EAT 适配 255/300。
- 控制器对 FULL：−7.00 pp 准确率，节约 45.45% 生成 Token、44.89% 真实单请求 wall-clock；控制器 mean 113.00 s，FULL 205.03 s。该策略质量约束**NO-GO**。
- 主试验 25 个 harmful STOP、4 个 beneficial；所有 25 个有害结果最终选择 STOP，只有 1 个解析非成功；18 个有害决策在“固定当前预测值且取消成本惩罚”局部比较中变为 CONTINUE，**不是**移除惩罚后真实能修复 18 题的干预实测。
- 开发集 699 检查点的 STEP 四态计数：1→1 388、0→0 283、1→0 11、0→1 17。一步净收益排序弱，回答侧特征较擅长预测当前答题正确率或长程收益。
- 额外 50 题检测频率替换：与主控制器同样 40/50 正确，耗时少 9.93%；这一差异涉及决策发生时间变化，**不能全部归因于探针计算节省**。
- 统一 `Final answer: \\boxed{` 协议、Math-Verify 与向量/`log`/`cot` 表示敏感性审计是质量基础设施，不构成新论文方法。主报告结论不改写。

## 2. 工作假设

**H1（动作价值分解）**：同一状态的 STOP/CONTINUE 差异，部分由“额外推导更改解题状态”驱动，部分由“答案读出采样/类型化解析”驱动。重复推导种子 × 重复读出种子可以估计两部分方差和边际均值，减少稀少 STEP 事件标签噪声。

**H2（质量先行准入）**：对有害 STOP 风险独立施加准入条件、在不确定时继续，不再允许 `lambda*C` 覆盖明显不足的正确率/获益证据；该机制有希望救回一部分错误 STOP 而保留真正冗余 Token。

**H3（风险与成本分层）**：在已被准许的控制动作中，用真实毫秒而非仅用生成 Token 进行成本排序，并采用稀疏在线检查点（等待 1/2/4 个完整语义段落）；可能进一步减少不必要读出和延迟。

**H4（可移植性）**：该决策规则的收益可在独立数学数据、Qwen3-4B-Thinking-2507，以及 DeepSeek-R1-Distill-Llama-8B 上保留。若仅 MATH-500 有效，不能宣称一般性。

## 3. 提议机制：Risk-Admissible Deferred Reasoning（暂用工作名）

输入：已经生成的推理前缀 `s`、已付出计算成本、当前候选答案读出特征、预测的未来风险和剩余时间。在线动作：`COMMIT`（以统一协议提交答案）、`DEFER_1`、`DEFER_2`、`DEFER_4`（允许指定个数完整自然段落后再检测）、`FALLBACK`（按有界自然基线推理至结束或预设上限）。不是一开始就全量训练复杂 SMDP。

核心质量目标：

`min E[T_policy]` subject to `E[Y_ref − Y_policy] ≤ ε`，其中 `ref` 是相同模型/采样/终止与读出协议下的有界 FULL。另采用更加保守的 harmful-only risk `H=1{Y_ref=1, Y_policy=0}`，因为 `E[Y_ref − Y_policy] ≤ E[H]`。如果校准时上界不满足，候选策略不能被认证。

**注意**：条件概率模型的预测区间不自动产生逐题分布无关保证；最终风险只能在所列独立样本、指定交换性/采样假设下以*策略级*置信界声明。多阈值选择需要独立策略选择集与校准集，或相应的多重比较修正。

最小有效版本（先复现再扩展）：

1. 答案读出信号：完整性、预声明答案类型、logprob/熵、重复读出一致性；无完整候选时强制 `DEFER`。既有 boxed 模式仅作主对照，另外预声明独立的 native readout 敏感性协议。
2. 弱风险模型：预计 STOP 相对有界 FULL 的有害错误风险/边际正确率差及不确定度；显式单独记录当前正确率预测。禁止用金标准答案或未来 Token 作在线特征。
3. STOP 独立准入：最小正确率、读出完整性、允许的风险区间与任务难度/检测置信区间；不确定则 `DEFER`。**成本权重只在通过质量准入的候选中起作用**。
4. 稀疏检测：在 1/2/4 个自然步骤后观察；软语义步界限与硬 Token 上限需分别记录；禁止把达到硬上限的状态静默删除。
5. 缓存探针：复用通过验收的 append→crop 和实际 KV clone；先复测 3 个前缀结果在多长度、跨模型仍成立。若读出结果要真正提交，验证能否复用已有前向状态而不额外重做答案生成。

## 4. 先做失败归因，不立即训练

使用归档中的 `results/analysis/online_statistics.json`、`results/audit/online_reversals.json`、`results/analysis/grouped_cv.json`、`results/online/*.jsonl`（实际路径以源归档为准）；运行已经存在的 `scripts/validate_study_artifacts.py`、`scripts/audit_online_trajectories.py`、`scripts/diagnose_online_failures.py`。

制作 25 harmful STOP + 4 beneficial 的逐题矩阵（允许多标签）：

- STOP 预测当前正确率区间：<0.5 / 0.5–0.9 / ≥0.9；预测剩余增益、成本惩罚、STOP margin、实际检查点位置；
- 是否属于局部取消成本会切换决策的 18 个；读出解析失败 / 错误值 / 缺失答案分量 / 数值四舍五入 / 非法早停；
- 配对 FULL 是否自然结束、是否触顶 8192、实际剩余 Token 与 wall-clock；
- 低成本守门能否识别该类案例；测“可挽救错误”同时统计丧失的 4 个 early-stop benefit；
- 画 `risk_score` 对 `actual harmful` 的可靠性曲线，按检查点、题目难度、剩余预算分层；标注探索性分析，**不可**在此 300 题上选择最终策略再称盲测。

## 5. 新数据和多重随机性的设计

- **新的数学主体**：官方 Omni-MATH（4428 题，官方仓库 `KbsdJames/Omni-MATH`）。先做 100 题回答解析/正确率 pilot；再按难度/学科/答案类型冻结例如开发 600、选择 300、独立校准 400、最终测试 1000；只在自动判分合理的子集建立主结果，同时公布覆盖率、剔除规则、审阅误差。数量允许根据 pilot 吞吐和有效性调整，在测试前冻结。
- **紧凑应力集**：AIME 2025/2026，因题目少只能做压力诊断，不支撑 1pp 风险声明；多任务选 LiveCodeBench 按发布时间过滤，依真实代码评测，不强制使用 math boxed finalizer。
- **模型**：开发 Qwen3-4B FP16；第二模型 Qwen3-4B-Thinking-2507；第三模型 `deepseek-ai/DeepSeek-R1-Distill-Llama-8B`，用各自适配的 tokenizer/terminator/readout，事先验证显存与推理协议。两张 3090 分别执行独立任务，原则上不用 Tensor Parallel。
- **采样层次**：同一个 checkpoint，3 次独立短答案读出；选取分层状态，对 `DEFER_1/2/4` 用 2 个推理种子 × 各 2–3 次独立读出。估计动作边际正确率、读出方差与继续推理方差。分层抽样比例变化要加权还原总体分布。
- **在线 test**：所有检查点/动作仅使用已生成 Token；按 Problem ID 完整隔离。训练每个模型不得偷用测试集答案。新的 final test 一次性冻结策略后运行。

## 6. 必须比较的强基线

1. 自然 FULL（受限 8192）和必要时更长预算 12288/16384，报告 censoring；另外单列原生模型完全自然结束模式，不和强制 boxed 结果混算。
2. 固定 1024/2048/4096/8192 等预算；最优固定预算只能在开发/校准数据上选择。
3. 冻结旧成本控制器、同特征正确率早停、EAT 共同协议适配、Conformal Thinking 作者能复现的完整实现（其公开仓库为 preliminary，先核对可执行范围）。
4. `Dynamic Early Exit`（ICLR 2026）、`DTSR`（ACL 2026）、`ASAG`（ICML 2026）、`REFRAIN`（ACL 2026）：能复现作者实现则按官方设置做结果；无法复现时将受控独立适配明确标记，不用论文作者原报告数字冒充同协议对比。
5. `SEVRA`（2026 预印本+公开代码）：注意它在**已经得到首次答案后**判断追加验证，动作空间与我们检查点停止不同；测试时可做独立部署策略对照，不能强行混为完全一致基线。
6. 优先级消融：无风险门禁；当前正确率阈值替代相对风险；不做多种子；只有 STOP/FULL；固定检测周期；无稀疏检测；Token 成本替代毫秒成本；不复用缓存。

## 7. 质量与系统指标

**主质量**：样本级 accuracy，配对 `Δaccuracy=accuracy_policy−accuracy_FULL`，95% 单侧/双侧置信区间；`harmful STOP`、`beneficial STOP`、统计上界；数值/格式失败率；自然结束率与 8192 触顶比例。

**主效率**：真实 end-to-end 单请求秒数，P50/P95/P99、生成 Token、实际 GPU decode/prefill/decision/readout 开销、峰值 GPU 显存。CPU 决策调用开销不是总 GPU benchmark。原始生成速度主报告约 `3854.4 / 205.03 ≈ 18.8 tok/s`，下轮采样成本按实际实测更新。

**选做 serving**：有可行策略后接入冻结 vLLM/SGLang 版本，验证多请求 offered-load 的请求/s、quality-gated goodput、P95/P99 端到端延迟、TTFT/ITL、显存、调度干扰；未经并发实验不可将单请求节省称为 serving goodput 提高。

主目标（不是已有结果）：对 FULL 准确率下降 ≤1pp 并同时降低 wall-clock ≥15%–25%；对最佳**同质量**强基线仍有 ≥5%–10% wall-clock 净收益才算积极论文主图。风险控制证明需充足新校准/测试量，达不到上界就报告经验值，不能伪称认证。

## 8. 18 周路线（从 2026-10-14）

| 时间 | 阶段 | 主要交付与阶段决策 |
|---|---|---|
| W1（10/14–10/20） | 代码与旧失败复核 | 重算归档统计、25/4 决策矩阵、协议和 runtime 差异；得出可以实现的最小守门器，**仅诊断，旧300不可调阈值** |
| W2–3（10/21–11/03） | 新鲜数据与干预噪声银行 | Omni-MATH pilot、新划分、读出种子×推理种子；量化 readout vs reasoning 变异；检测 1/2/4 步边界 |
| W4–6（11/04–11/24） | 质量准入 M1 | 当前正确率门槛、harmful risk 模型、校准选择；与固定/EAT/原控制器同协议在线对比。若没有任何质量—成本改善，不进入复杂动态预算 |
| W7–9（11/25–12/15） | 稀疏检测与条件成本 M2 | `DEFER_1/2/4`、毫秒成本回归、GPU 增量开销；针对显著类型的有害早停设守门，完成逐机制消融 |
| W10–12（12/16–01/05） | 风险审计与强基线 | 预注册有限参数集合、独立校准上界、Qwen3 Thinking-2507 迁移、作者可执行的强基线复测；没通过 2pp 经验容忍且无 Pareto 改善则转路线 |
| W13–15（01/06–01/26） | 新盲测与跨家族复验 | 冻结全部阈值，Omni-MATH 保留集、DeepSeek-R1-Distill-Llama-8B、至少一个非数学任务；问题级 Bootstrap 和罕见风险置信区间 |
| W16–18（01/27–02/16） | 系统服务扩展与论文材料 | 若前期成立，增加 batch=1/2/4/8 与并发 workload 的 real wall-clock/Goodput；完整消融、失败审计、开源可复现包、投稿准备 |

**阶段切换门槛**：W3若重复读出严重主导标签噪声，则先改答案类型/读出协议并重测；W6若连续新样本没有质量—成本收益，优先查风险门禁和 fixed-budget frontier，仍无改善则不开发多动作网络；W12若始终被固定预算或 EAT 的质量—延迟前沿支配，则当前方法停止作为主研究创新，保留这套实验平台转向 Agent/serving 的其他已证实问题。

## 9. 明天的四个动作

1. 在归档目录核验文件与代码：`python scripts/validate_study_artifacts.py && python scripts/audit_online_trajectories.py && python scripts/diagnose_online_failures.py`。若任何脚本依赖缺失，不改原始输出，记录错误并修复环境。
2. 导出全部主测试 25 harmful STOP + 4 beneficial 的 CSV：问题 ID、预测值、成本项、判断阈值、最后步骤、答案类型、解析状态、配对 FULL 时间/触顶状态、原始回答和错误类别。对不完全清楚的分类留 `unknown`。
3. 做一个**只用于诊断**的离线守门敏感性审计：例如不许 `p_stop` 低于门槛时 STOP、不让成本项覆盖明确的继续收益、只在答案类型完整时 STOP；按共同配对题目展示质量回退多少与损失多少省时。不能把此审计结果当新策略盲测。
4. 冻结下一批 Omni-MATH 小 pilot 的模型、答案协议、停止条件与 100 题学科分层 ID，先验证评分准确性和 natural baseline，再采集新价值标签。

## 10. 核查过的外部文献/资源入口

- Conformal Thinking（ICML 2026）https://proceedings.mlr.press/v306/wang26hd.html ，代码预览 https://github.com/xidulu/reasoning_risk_control
- Statistical Early Stopping（ICML 2026）https://proceedings.mlr.press/v306/xie26z.html
- Attention-State Adaptive Generation ASAG（ICML 2026）https://proceedings.mlr.press/v306/li26ev.html
- Weak and Strong Verification（ICML 2026）https://proceedings.mlr.press/v306/kiyani26a.html ，代码 https://github.com/nooranisima/weak-and-strong-verification
- Reasoning Theater（ICML 2026）https://proceedings.mlr.press/v306/boppana26a.html
- Dynamic Early Exit（ICLR 2026）https://proceedings.iclr.cc/paper_files/paper/2026/hash/8df90a1440ce782d1f5607b7a38f2531-Abstract-Conference.html
- REFRAIN（ACL 2026）https://aclanthology.org/2026.acl-long.1256/
- DTSR（ACL 2026）https://aclanthology.org/2026.acl-long.1080/
- SEVRA（2026 预印本）https://arxiv.org/abs/2606.19808 ，代码 https://github.com/Sajib-006/SEVRA
- Omni-MATH https://github.com/KbsdJames/Omni-MATH
- LiveCodeBench https://github.com/LiveCodeBench/LiveCodeBench
- Math-Verify https://github.com/huggingface/Math-Verify
