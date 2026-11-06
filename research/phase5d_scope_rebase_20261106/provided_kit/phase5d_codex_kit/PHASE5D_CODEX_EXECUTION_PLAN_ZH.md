# Long-CoT Phase5-D：SCOPE-Rebase 算法与 Codex 执行契约

- 版本：2026-11-06 / 研究设计草案 v1，不是已运行实验或已证明收益。
- 仓库：https://github.com/zhouz4884-coder/long-cot-research
- 起始 Git SHA：`147080af9f36190ee853cba10b6521f936061280`（Phase5-C 刚收尾）
- 输入：用户提供的 `长思维链调研_文献与组合分析_20261105.zip`（62项去重文献；29项重点阅读，33项元数据/摘要核查），Phase1–5 原始资料、代码和审计。
- 执行资源：优先 2× RTX3090 24GB；8×V100为**可选**采样/横向验证资源，不得预设PBS可分配、FP16兼容及性能倍数。
- 目标：最终数学/结构推理正确率与同完整成本性能。先保证算法确实执行，再谈加速、训练、扩模型及论文结论。

## 0. 固定历史事实、不得覆盖

Phase5-C是**32道独立历史题、同一模型 Qwen3-4B、7个读出条件、224项实际输出**，不是224个独立任务。
- `ForcedBoxCue=27/32`；`FullContractEvidence=18/32`；`ProjectedContractEvidence=13/32`。
- `109/224` 输出触及384 token cap；部分解析拒绝了正确 `\boxed{10}` 后随单位/名词的形式。
- 历史思考27/32自然结束、至少28/32含`\boxed`，包含大量已有答案；`enable_thinking=False`、历史作为新User文本的读出不等于原生 in-flight continuation。
- 当前只有目标提示K与UNVERIFIED摘录E，无真实G、无在线依赖证书、无逐节点修复。
- Phase1的早停控制器300题FULL269/300，旧控制器248/300，节约时间不等于质量增益；不可将旧分数改写。

禁止修改旧 Phase 源码、评分、run及 frozen manifests。新增目录 `research/phase5d_scope_rebase_20261106/` 和 `docs/phases/Phase5D_...md`，文件名可按仓库风格定，但必须独立。

## 1. 研究假设和创新性范围

**H1（核验语义）**：反思中“有理由推翻”的判断需要同时验证计算、前提和适用范围。相比纯文本自检/无作用域微检，它能减少错误反例接受，同时不显著拒绝有效反例。

**H2（保留支持）**：在相同可用证据和后续计算预算下，对于多支路、有重复独立证明的自然Long-CoT，撤回失效**证明**、保留仍有证书的**结论**、将逻辑状态重新序列化到原生思考前缀，比全重算或普通文本回退提高修复/损害比。

**H3（后置选择性）**：若H1/H2有益，不同状态下的Continue/Audit/Rebase的相对价值可由运行时可观察特征预测，且相对于等预算重采样有稳定额外收益。

H1、H2是主线。H3/VOI仅在H2已有实测条件收益后启动。

直接近邻：TAAR(ACL Findings 2026)、VeryTrace(2026 arXiv)、Logic Tree(EMNLP Findings 2026)、DeepRewind(REALM 2026)、Dependency-Guided Rollback Repair(2026 arXiv)、Sherlock(2025 arXiv)、Thought-ICS(2026 arXiv)、SCoRe/Satori/TRAE。**依赖回退、选择性验证、VOI、局部修复和保留独立证据已有先例，不得简单宣称新发明。** 必须证明显式“作用域→证据失效→真实LongCoT续推”端到端新结果。

## 2. 正确的数学内核：多重证明支持，而非逻辑假言易位定位

### 2.1 版本化声明和 AND/OR 证明图

- 声明：`Claim(id, canonical_expression, scope, version, source_span, output_role)`；如 `x@0` 与 `x@1` 不同；canonical表达不等于数学真值。
- 证明超边：`Justification(id, conclusion, premises[], rule, scope, verdict, verifier_id, certificate_hash)`。
- `verdict=PASS` 的充分条件是：**该超边在真实核验条件内确实有效、全部所需前提和作用域已给齐，且证书可审计**。同模型投票/自信/启发式相似度不能称PASS，应写`UNKNOWN`或独立软分。
- 一条结论可有**多个 OR 备选证明**；每个证明的前提为 AND。只有被检查的支持关系有效，才能沿父声明得到认证。

对无环且范围一致的证明图，定义最小不动点：

`Cert = μ X. { c | 存在 proof p 指向 c，p.PASS，p.scope_valid，且 premises(p) ⊆ X }`。

真值与支持状态分开。撤销一条证明只会让某个结论失去该条依据；若有其他有效证明，结论不应被撤销。自然推理里任何未完成的依赖/范围应为 UNKNOWN，不允许因为文本相邻而构造依赖边。

### 2.2 冲突处理

外部新反例e须有`scope`与`certificate`，并能**有效反驳具体proof/claim**才允许触发失效：
- e自身非法/算错/不适用：不撤销旧依据；但旧答案仍非自动认证正确。
- e为UNKNOWN：不强制覆盖旧账，按既定Continue/Audit/Fallback策略处理。
- e合法且证明某个推导依据无效：撤销**该证明**，重新计算受影响下游的支持状态；不能宣布其结论必然假。
- 若全部相互冲突的证明都宣称PASS，说明前提、作用域或核验器有不一致：进入 `INCONSISTENT_CERTIFICATES`，不得任意推翻某一根。

### 2.3 Minimal Support Loss 与 Rebase

`before=Cert(G)`；`after=Cert(G minus revoked_proofs)`；`lost = before \ after`。这个`lost`是失去足够**认证支持**的声明，不是数学上证明其为假。

`cut_pos = min(start_token(claim) for claim in lost)`。`cut_pos`必须映射到合法、完整、尚未闭合的`<think>`步边界；若无法映射，则退回安全的更早边界或从原题重建。

`carry = { claim ∈ after | claim.start_token >= cut_pos and independently certified }`。只能将这些claim的**规范表达+范围+依据ID**重新序列化为桥接文本，不得复用其历史KV；注入桥接文本是否让模型真正复用知识是需要实验的行为效果。

注意：这个`cut_pos`仅是一个安全启发式候选，**不是已证明的最小计算成本点**。前沿重建+桥接可能比整链重新生成更慢或更差，必须在同一证据权限下比较。

### 2.4 有条件 VOI，而不是普适零价值定理

`EVI(s,e)=E_o[V(s|o,e)] - V(s) - cost_verify(e)`。

仅在图依赖完整、核验结果不影响隐含变量/未来动作/搜索路线/计算成本、且目标收益只依赖已建模的支持子图等充分条件下，才能推出非目标支持锥验证的毛收益为0。图不完整时返回`RELEVANCE_UNKNOWN`，不得强行跳过。

支持锥门控先做廉价优先级特征：`target_ancestry_overlap`, `challenge_to_certified_support`, `last_pending_parent`, `estimated_cost`，不直接声称高收益或60%节省。若以后学习策略，按问题分组的开发集拟合，冻结test后仅前向使用。

## 3. 模型机理、KV 和真实性协议

### 3.1 真正的同一 assistant thinking 前缀

- Qwen3-4B当前实测模型资产manifest沿用，但**重新核对其config/tokenizer与所加载具体checkpoint**。使用`apply_chat_template(...,enable_thinking=True,add_generation_prompt=True)`构造user问题的初始prefix。
- 新检查点由生成的完整`input_ids` + `generated_token_ids[:t]`定义（`t`为当前可观察的已生成token，不取未来条件）。保存`prompt_sha`, `prefix_sha`, `generated_ids`, `tokenizer_hash`, `model_hash`, `checkpoint_pos`, `event_type`, `prefix_stop_state`。
- **不得**把历史塞进新的User消息、不得`enable_thinking=False`、不得将未来“Wait/boxed/正确率”用于选取当前检查点。
- 第一版所有分支优先使用**相同token IDs重新prefill**得到准确参考；这只是token-exact prefix continuation，**不是物理热KV reuse**。后续如加热KV，先过相同token续写的 logits/KV一致性检查，避免为了速度污染质量实验。
- 官方Qwen3-4B thinking推荐`temperature=0.6, top_p=0.95, top_k=20, min_p=0`；greedy仅用于CPU/GPU接口确定性验证，正式质量评估使用冻结采样配置并多种子。不能把同seed说成跨CUDA、batch、版本100% bit-identical。
- 通过步级事件检测构造检查点：`candidate_observed`, `conflict_observed`, `stagnation_or_budget`；普通未触发样本也必须入全局分母。候选触发只能依据完整语义边界/可见输出，不能用未来事件，不能用Gold判断“首次正确”。
- 质量优先直到自然EOS或明确声明的上下文/资源保护上限；不得把384/512紧预算误称无限推理。分别报告`hit_context_cap`, `hit_technical_cap`, `EOS`, `output_unparsed`。

### 3.2 一般不允许无重算“物理嫁接”

任意后续 token 的KV由其整个因果前缀计算。如果修改了第j个token，则位置i≥j的旧KV通常全部无效，**即使第i段文字表示一个逻辑独立的正确声明也不能挪用旧KV**。

首版使用`prefix_ids[:cut_pos] + tokenizer.encode(bridge,add_special_tokens=False)`重新prefill；禁止 `decode(prefix)->string edit->retokenize` 当作token-exact；bridge只能插在稳定步边界。不允许引入 `<|im_start|>`, `<|im_end|>` 等新角色控制标签。

优化版仅在验证过cache及位置状态一致的情况下使用`DynamicCache.crop`尾回退，并通过增量prefill桥接token。要测试边界：回退0、回退1、回退到步骤开头、batch=1/2、不同padding、先结束样本、位置id、attention mask、FP16数值及随机种子，且检查具体Transformers版本支持，不能盲抄最新API。

### 3.3 性能计量：每条分支完整成本

`C_total = C_common_prefix + C_monitor + C_extract + C_verify + C_rebuild + C_decode + C_retry + C_final_delivery`。重复预填与被拒分支计费；batch wall不按样本数硬分配。除token数量外记录完整延迟与峰值HBM，统计工具CPU与异步执行重叠时间，不能重复相加。

## 4. 下一阶段分批执行，不要一次铺满所有动作

### D0：0-GPU旧基线终审（只开发，不发新性能稿）

- 在冻结原32题上实现Gold-blind LastBox、LastFinalAnswer、首个完整答案、无候选Abstain，对旧 `ForcedBoxCue` 27/32 保留原分数；使用统一**预冻结**的全答案语义grader在独立输出目录评分。
- 明确现有历史末尾LastBox多是已经完成的答案，不能拿该数据做原生修复成功率主证据。
- 新parser测试带单位、向量、区间、分数、多个boxed、未闭合和矛盾多个最终对象。不要针对个别旧错例后验挖掘并称正式confirm。
- 产物：`D0_Baseline_Audit.md`, `D0_scores.jsonl`, `D0_parser_contract.json`, `D0_commit_boundaries.md`。

### D1：原生检查点 engine + 实现一致性（CPU后小规模3090）

- 先实现 `native_prefix.py`, `checkpoint_stream.py`, `prefix_resume.py`, `cache_parity.py`；只需 `Continue` 的同token原生续写与 `AppendNeutralBridge`，不接G/图。
- 先CPU可验证检查：chat模板、think边界、token IDs不变、时间只向前推进、原生分支行为不包含未来。
- 再3090上用8道题进行stream vs exact-prefix-reprefill vs optional-cache-crop的logit/top1与输出对照；greedy只作一致性诊断。
- 如果fast cached branch比reference不一致，禁用fast路径。不能继续在不正确的执行器上测创新。
- 输出：`D1_NATIVE_INTERFACE_PASS.json`, 逐步token/hash、真实GPU成本。用户持有2张3090，不人为设极短任务时间截断；仍保留资源安全上限和断点续跑。

### D2：发生率、核验可靠性、动作收益先导（24–32全新不同题）

- 独立题，排除旧Phase1–5冻结样本与相同/近重复题；记录来源、语义难度、检查能力。若数据来自同一基准，不能宣称跨数据集。
- 对每题生成native thinking至EOS/技术保护顶；至少2个声明种子。记录3类事件率，以及**未触发事件的题**，不要以找到有利事件作为可评估分母选择。
- 首批只比较 ①Continue ②FullContextSelfAudit ③UnscopedIsolatedAudit ④ScopeQualifiedAudit；先测试诊断可靠性，避免反例抽错范围。
- 有准确可执行验证的步骤输出PASS/FAIL；其他步骤UNKNOWN。引用错变量、反例不在定义域、错符号、必要前提缺失、交替证明的情况全部保留。
- 细分`false_accept`, `false_reject`, `UNKNOWN`, `scope_mismatch`, `claimed_support_fraction`, `true_repair`, `harm`, `E2E`。
- 在**同一可用信息和完整计算预算下**比较，isolated audit额外模型调用必须计费。不能把真实Gold作为在线核验信息。
- 如自然题可精确核验的有效冲突很少，记录覆盖不足；可将可解释受控组合任务用于机制测试，但不得冒充自然基准结果。

### D3：有证据的修复 + 严格消融（仍以单3090主跑）

在D2确认有可测的作用域错误与独立支持后，真实实现三个核心动作：
1. `Continue`（原生无干预）；
2. `GenericRewind`（固定位置/最近步骤回退）；
3. `ScopedRebase`（有效证明撤销→重算认证支持→截前缀→桥接独立认证claim→原生继续）。

主要消融：`RebaseNoCarry`, `RebaseUnverifiedCarry`（仅用合成安全对照）、`RebaseRandomSameLength`, `UnscopedVerifier`, `AllAudit`, `NoScope`, `NoMultiProof`；受控变体按问题冻结。强对照：完整重启、等预算继续、独立再采样、可实现的TAAR-like或作者可用的官方实现（明确区分复现等级）。

强调 `ScopedRebase` 是否**真正带来额外答案正确**，不能把只减少prompt或从工具获得确定答案全部归功于神经推理。自然LongCoT的未解析图不得伪装为已认证完全DAG。

### D4：独立测试与统计确认

- 预先冻结算法、解析、阈值、模型和数据抽样。原开发题及Phase1–5病例不进独立confirm。
- 建议：独立100–200不同题视结果预算调整，多种子；最少一款跨家族模型作独立复测，8×V100仅核实可用且环境正确后作为补充。
- 主报告：按问题聚类的paired accuracy差值、95% bootstrap区间、McNemar辅助、correct→wrong/incorrect→correct、全请求E2E p50/p95、核验开销、prefill/decode token、context cap、UNKNOWN率。
- 质量优先EOS与同完整成本B曲线分开；不能以事后Oracle选择答案；从基线中预声明一个强主比较，避免多重挑选赢家。
- 备选路线：如果H2没有边际收益但H1可靠，考虑用有限on-policy反事实轨迹做4B LoRA/DPO来学习证据支持下的修订，不直接开32B RL。

### D5：仅在D3有效后加入VOI/学习路由

先计算 `H_actions` 与等预算 `H_resampling`，并区分 within-problem/within-seed随机采样机会。仅当动作产生稳定互补性，才试小型校准路由器或作用域VOI阈值。比较 `AlwaysContinue`, `AlwaysAudit`, `AlwaysRebase`, `UniformRandom`, `BestFixed`, `MatchedResampling`, `Learned`；训练集与独立test保持隔离。训练Oracle headroom不是部署成绩。

## 5. 必要的技术验收单

1. Phase5-C旧manifest与results任何字节不得变；检查提交前diff。
2. 给定相同原生prefix token IDs和无干预续写，回放参考输出/logits在许可数值容差内；不同结果须记录top2 margin及版本。
3. `gold`不能被`checkpoint`,`trigger`,`verification`,`action`,`bridge`和`generation`导入/传参；只在offline grader与开发分析使用。
4. 未观察到未来token不能触发future-dependent事件；在线事件与按prefix replay事件严格一致。
5. 验证结果不含适用范围或证书不完整时必须UNKNOWN；不得自动变PASS。
6. 删除某条证明后，如果结论有另一完整独立有效证明，不得错误撤销结论。
7. `UNKNOWN`和错误反例不得删除原有效依据；valid conflict不能无理由定位某个根假设。
8. 自然段落引用可能依赖被删除的上下文，因此仅使用独立规范表达重建bridge，不直接原文剪贴。
9. 验证器完成的精确求解必须给同工具强基线；不允许主方法独占正确中间数/Gold/隐藏标签。
10. 包括失败、拒绝、被截断输出、验证、桥接和重prefill在内计全成本；脚本异常也进入完整性台账。
11. 若正式评估引入sampling，固定采样配置并多种子；同seed不是100%字节级跨硬件复现承诺。
12. 始终报告全题/全触发率/条件子集3种分母；不能把一个题的多个checkpoint当多个独立测试题。

## 6. CPU参考实现说明

本包的 `scope_rebase_core.py` 实现了**仅CPU的形式支持/撤销原型**与受限整数有理数表达式检查。它的`Challenge`对象目前假定来自已验明的外部 checker；它**不会自己验证证书签名、不会自动读数学题、不会解析LLM自然语言、不会启动GPU或完成完整SCOPE-Rebase**。集成GPU前必须实现实际证书验证器和输入/作用域绑定，不能通过把`Challenge(verdict="PASS")`写死来制造正例。

`native_prefix_reference.py`展示Qwen3 thinking模板与同token续写的参考代码，但还不是在线流式检查点采集引擎，也没有热KV clone、采样状态复原、全成本采集；Codex必须完善且通过D1验收。

`tests/test_scope_rebase_core.py`目前是5个受控形式测试，不是模型有效性证据。测试应扩到多根、多证明、域冲突、循环依赖、失效起点早于支持段落、token桥接中断、cache一致性、parser/edge-case、并发恢复。

## 7. 必需文档与停机规则

每个子阶段输出：`PLAN_ZH.md`, `PROTOCOL.json`, `IMPLEMENTATION_AUDIT.md`, `RUN_STATUS_ZH.md`, `RAW_MANIFEST.json`, `RESULTS.jsonl`, `RESULT_ANALYSIS_ZH.md`, `NEXT_DECISION_ZH.md`。未执行事项不得写成成绩。

- 若D1原生续写不等价，先修执行器，禁止进入算法实验。
- 若D2的验证器误接受危险反例或提取器大量错绑作用域，先改诊断/收缩可核验任务，不先叠动作预测器。
- 若D3保留证据桥对同信息紧凑基线无增量，停止“神经状态保留”宣传，保留机制负结果，考虑数据驱动训练或其他长CoT方向。
- 若只节省token但Accuracy下降，或者只有Oracle选择才能显示收益，不宣布算法成功。
- 若在独立集有可靠正向改进，再扩至3模型/多数据集/长链不同长度，形成论文层证据。

## 8. 核心近邻与来源

调研包保留62项详细矩阵，重点参照：
- TAAR, ACL Findings 2026: https://aclanthology.org/2026.findings-acl.1930/
- Logic Tree, EMNLP Findings 2026: https://aclanthology.org/2026.findings-emnlp.844/
- Echo Trap/TRAE, ACL 2026: https://aclanthology.org/2026.acl-long.1636/
- DeepRewind, REALM 2026 workshop: https://aclanthology.org/2026.realm-1.73/
- VeryTrace, 2026 arXiv: https://arxiv.org/abs/2606.24124
- Dependency-Guided Rollback Repair, 2026 arXiv: https://arxiv.org/abs/2608.10502
- Sherlock, 2025 arXiv: https://arxiv.org/abs/2511.00330
- Qwen3-4B official card: https://huggingface.co/Qwen/Qwen3-4B
- HF cache API, verify exact locally installed version: https://huggingface.co/docs/transformers/en/kv_cache

---

**Codex第一轮授权边界：优先D0+D1 CPU验收，随后只启动有明确固定预算的8题GPU接口试验；不要自动扩跑D2–D5、不要修改现有历史数据，不要创建虚构性能成绩。遇到有效问题时修代码并继续完成当前阶段；只有新的机制问题要求重大方案变化时写决策日志。**

## 9. 备选结构创新（仅在D2结果支持后单独立项）：Quarantined Reflection

自然Long-CoT在已存在候选时继续出现`Wait`，可能将假反例写入主因果上下文。一个更小、可测的结构干预是**把新的自我反思先放在隔离分支**：保持主前缀和候选不变，fork一个reflection proposal分支；在分支外按作用域检查其“新反例/新规则”；只有对原候选或其证明的否定具有足够有效证据才将结果承接入主分支，否则放弃此分支；UNKNOWN保留保守继续选择。这个机制不要求先构建完整自然DAG，可能提高事件覆盖，但会增加采样和核验成本。请与“等预算多次独立续写”“普通自我反思”“TAAR式重启”“无核验直接选最新候选”公平比较。

**注意：这种隔离/提交不是理论上全新的事务或分支机制**，尤其Sherlock、Logic Tree等已有相关思想。若试验有效，真正需要证实的增量应是“在单回合原生CoT中，用具有作用范围的独立证据限制错误反思传播”，而不是分支这个名称本身。

## 10. 若结构法有效但在线审查过贵：后置轻量蒸馏

仅使用D2/D3在**训练集**产生的真实分支，在相同模型/数据/生成预算下构建正负偏好：保留合法中间支持并有正确最终答案 vs 盲目反思或过度回退导致错误/昂贵。将其用于Qwen3-4B LoRA或偏好微调；基线必须包括`SFT原始长链`、`随机步骤剪裁SFT`、`普通纠错数据SFT`、`同数量数据+普通DPO`及仅在线验证器。严格隔离训练Gold、线上无Gold。若训练只是提升短答案服从而未提升native长链复发/修复，不把它当核心创新。两张3090是否能容纳目标序列长度须先profile，不能预言数小时训练完成。
