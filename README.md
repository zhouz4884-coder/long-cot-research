# Long-CoT Research

长思维链研究：以**最终回答正确率、同预算的算法增量和完整成本**为主线，探索局部修订后的有效计算复用与答案交付。

仓库目前公开。工作目录为 `D:\ACL`。更新于 2026-11-10。[GitHub 仓库](https://github.com/zhouz4884-coder/long-cot-research)

## 从哪里开始

- [Phase 1–5 总索引](docs/phases/INDEX_ZH.md)
- [当前研究目标](docs/next_phase/CURRENT_RESEARCH_GOAL_20261105_ZH.md)
- [最新建议审查与下一轮公平对照](research/repository_phase_plan_20261106/ADVISOR_REVIEW_20261106_ZH.md)
- [Phase 5-D4.7 可行解退步与证书保全](research/phase5d47_delivery_preservation_20261110/D47_CLOSEOUT_ZH.md)
- [Phase 5-D4.6 点不可行性与候选绑定](research/phase5d46_point_infeasibility_20261110/D46_CLOSEOUT_ZH.md)
- [Phase 5-D4.5 可行见证与自然长链](research/phase5d45_feasible_witness_20261110/D45_CLOSEOUT_ZH.md)
- [Phase 5-D4.4 补抽与实时生成修复](research/phase5d44_candidate_generation_20261110/D44_CLOSEOUT_ZH.md)
- [Phase 5-D4.3 自然长链反证与终局选答](research/phase5d43_answer_refutation_20261110/D43_CLOSEOUT_ZH.md)
- [Phase 5-D4.2 同源最小修正与级联诊断](research/phase5d42_lean_diagnostics_20261110/D42_CLOSEOUT_ZH.md)
- [Phase 5-D4.1 引理可达性与预筛准入](research/phase5d41_lean_scope_20261110/D41_CLOSEOUT_ZH.md)
- [Phase 5-D4.0 新引理与子目标构造准入](research/phase5d40_proof_authoring_20261110/D40_CLOSEOUT_ZH.md)
- [Phase 5-D3.9 真实轨迹中的释放机会复核](research/phase5d39_blueprint_trace_20261110/D39_CLOSEOUT_ZH.md)
- [Phase 5-D3.8 形式证明最小释放准入收尾](research/phase5d38_proof_release_20261110/D38_CLOSEOUT_ZH.md)
- [Phase 5-D3.7 作用域修复与 CPU 准入收尾](research/phase5d37_scoped_repair_20261110/D37_CLOSEOUT_ZH.md)
- [Phase 5-D3.6 证据棘轮研究收尾](research/phase5d36_progressive_witness_20261109/D36_CLOSEOUT_ZH.md)
- [Phase 5-D3.5 见证门控修订收尾](research/phase5d35_witness_gated_revision_20261109/D35_CLOSEOUT_ZH.md)
- [Phase 5-D3 收尾与下一步判断](research/phase5d25_constraint_revision_20261109/D3_CLOSEOUT_ZH.md)
- [Phase5-D2 隔离反思与双前沿收尾](research/phase5d2_quarantined_rebase_20261107/D2_CLOSEOUT_ZH.md)
- [Phase5-D 第一批设计重构、D0 与原生 D1](research/phase5d_scope_rebase_20261106/STAGE1_CLOSEOUT_ZH.md)
- [强基线公平性与新题即时/大规模验证](research/phase5d_scope_rebase_20261106/FAIRNESS_AND_FRESH_VALIDATION_ZH.md)
- [Phase5-C简明报告](docs/phases/Phase5C_单模型自然轨迹验证与收尾_ZH.md)
- [对外部建议的逐条判断与当前进度](docs/phases/Phase5B_自然诊断与父边界投影_ZH.md)
- [当前算法公式与token上限解释](research/phase5_prototype_20261106/PLAN_AND_FORMULAS_ZH.md)
- [文件发布范围与来源](docs/repository/PUBLISH_SCOPE_ZH.md)

## Phase 导航

| 阶段 | 内容 | 当前状态 |
|---|---|---|
| [Phase 1](docs/phases/Phase1_历史研究与早停_NO_GO_ZH.md) | 历史步骤干预/早停研究、负结果与冻结的后续路线 | 原研究归档；后续大队列冻结 |
| [Phase 2](docs/phases/Phase2_从零文献与方向选择_ZH.md) | 从零长思维链文献地图、模块拆解与方向选择 | 62项资料；不是62篇全部复现 |
| [Phase 3](docs/phases/Phase3_P0状态恢复机制与首轮证据_ZH.md) | CPU缓存机制与真实P0五臂 | 短试完成；原严格与后验评分分列 |
| [Phase 4](docs/phases/Phase4_理论审查与P05五臂短试_ZH.md) | 模型/数学审查、P0.5、裁尾复用、候选溯源 | 16题primary完成，8题诊断完成 |
| [Phase 5](docs/phases/Phase5_候选算法与公平基线_计划_ZH.md) | 版本一致局部重推候选、同信息强baseline与质量优先短试 | Phase5-A按预算partial；当前静态帧未显示增量，正式benchmark未开展 |
| [Phase 5-B](docs/phases/Phase5B_自然诊断与父边界投影_ZH.md) | 自然失败条件诊断、后台证书/父边界投影、Raw与同G对照 | 10/10输出完整，三态覆盖；投影节省但未胜最强基线正确率 |
| [Phase 5-C](docs/phases/Phase5C_单模型自然轨迹验证与收尾_ZH.md) | 32不同自然题、7条件、自动候选投影与强读出对照 | 224/224完整；当前原型未过扩大门槛，阶段收尾完成 |
| [Phase 5-D第一批](docs/phases/Phase5D_方法重构与原生接口准入_ZH.md) | scope/完整支持设计、D0审计、CPU内核与原生D1准入 | D0/D1完整；8EOS/0cap，同调度参考8cp通过；自然修复收益未测 |
| [Phase 5-D2](research/phase5d2_quarantined_rebase_20261107/D2_CLOSEOUT_ZH.md) | 受限核验、隔离反思、双前沿重建、自然覆盖与同状态配对 | 48/48 EOS，四个 UNKNOWN 对照通过，修复准入 0/4 |
| [Phase 5-D2.5 与 D3](research/phase5d25_constraint_revision_20261109/D3_CLOSEOUT_ZH.md) | 类型化数学核验、旁路审计、历史回退对照与新题原生验证 | 4/4 实机一致性通过，32 条正式轨迹全部自然 EOS，正式修复准入 0 |
| [Phase 5-D3.5](research/phase5d35_witness_gated_revision_20261109/D35_CLOSEOUT_ZH.md) | 有界见证、终局一致性保护、同证据回退 | E12/E15 开发实机闭环完成。直接工具均答对，回退未显示额外正确率收益 |
| [Phase 5-D3.6](research/phase5d36_progressive_witness_20261109/D36_CLOSEOUT_ZH.md) | 零 GPU 全集诊断、可信点验证、同提示的事件棘轮对照 | 48/48 条件完成，47 个自然 EOS。棘轮 3/6，一次性认证提示和逐候选审核均 4/6，未过独立扩测门槛 |
| [Phase 5-D3.7](research/phase5d37_scoped_repair_20261110/D37_CLOSEOUT_ZH.md) | 451 个已付费事件的来源作用域修复、终局补读及构造任务 CPU 准入 | 两类受限实例各 6/6 已有强直接解，未启动模型试验 |
| [Phase 5-D3.8](research/phase5d38_proof_release_20261110/D38_CLOSEOUT_ZH.md) | 固定 Lean 工具链、最小释放证书及作者模型档案 | 作用域释放 7/8，合并证书的同候选池强基线也为 7/8，只用 7 次 Lean 调用。未启动模型试验 |
| [Phase 5-D3.9](research/phase5d39_blueprint_trace_20261110/D39_CLOSEOUT_ZH.md) | 141 个独立目标的真实动作归档、同版内核复验、驻留核验成本 | 四个改动候选均可保留已证明内容并完成目标。关闭最小释放主线 |
| [Phase 5-D4.0](research/phase5d40_proof_authoring_20261110/D40_CLOSEOUT_ZH.md) | 11 个未解原目标的归档支持、同版失败复验与普通证明基线 | 三个受审失败复现，普通 CPU 证明完成三个原目标。新增引理方法未达模型准入 |
| [Phase 5-D4.1](research/phase5d41_lean_scope_20261110/D41_CLOSEOUT_ZH.md) | 引理可达性、实际历史缺名与查询加完整核验成本 | 31 个目标的诊断对齐，两种等待设置下配对完整成本无稳定下降。预筛未达模型准入 |
| [Phase 5-D4.2](research/phase5d42_lean_diagnostics_20261110/D42_CLOSEOUT_ZH.md) | 115 份冻结候选、三个同源历史失败、等量编辑和完整 CPU 对照 | 区分同处诊断消失、下游残留和新露出的错误。级联策略未达模型准入 |
| [Phase 5-D4.3](research/phase5d43_answer_refutation_20261110/D43_CLOSEOUT_ZH.md) | 32 道独立 AIME、128 条原生轨迹、同池选答与原题反证 | 首抽 26/32，四抽多数票、普通复核和作用域反证均 29/32。当前选答未达独立扩测门槛 |
| [Phase 5-D4.4](research/phase5d44_candidate_generation_20261110/D44_CLOSEOUT_ZH.md) | 同合同补四抽、8 道独立新题、精确触发与官方键复核 | 补四抽与八抽覆盖均为 29/32。新题 0 次触发，冻结官方键 7/8、7/8、7/8、8/8。隔离争议题后四臂均 7/7 |
| [Phase 5-D4.5](research/phase5d45_feasible_witness_20261110/D45_CLOSEOUT_ZH.md) | 11 道新优化题、88 条归档轨迹、精确见证与完整求解对照 | 新增反证题为 0。两条持续错误均过于乐观，可行见证的一侧界无法排除。零 GPU |
| [Phase 5-D4.6](research/phase5d46_point_infeasibility_20261110/D46_CLOSEOUT_ZH.md) | 11 道新题、88 条归档轨迹、原题候选绑定与精确点核验 | 严格 1 条、盲审 6 条持续不可行值均来自同一可用短解覆盖的题。GPU 准入为 0 |
| [Phase 5-D4.7](research/phase5d47_delivery_preservation_20261110/D47_CLOSEOUT_ZH.md) | 8 道新题、64 条归档轨迹、同目标可行证书与朴素保留 | 49 对两值均可行且相等，0 条退步。证书保全与朴素保留全体同输出。零 GPU |

每个Phase统一记录：问题、输入与协议、实际动作、数据结论、失败与猜想、下一门槛、证据路径。后续工作继续新增Phase或阶段内子报告，不改写已冻结的结果。

## 当前实际结果

| 研究 | 实际结果 | 结论边界 |
|---|---|---|
| 历史主300题 | FULL269/300，旧控制器248/300；耗时节省44.89%伴随7pp损失 | 旧控制器NO-GO，历史数据保留 |
| P0人工16状态五臂 | 事后解析7/3/5/7/5；原严格各0/16 | 输出格式问题与数学结果分开；不作正式benchmark |
| P0.5同轮五臂 | 8/11/0/12/8；4.4591单卡分钟 | 80自由输出全完成，辅助诊断8题；联合净+1涉及预算/交付差异 |
| Phase5-A同信息质量优先原型 | 3个完整配对：Direct/Compact/Stepwise各3/3，Frame1/3；4.38345单卡分钟 | 两条Frame是正确JSON未解析；19/30输出完成、W主比较未跑；全部EOS、cap0；仅2个独立程序 |
| Phase5-B后台父边界投影 | Raw3/3、SharedGFull2/3、Projection3/3、唯一RestartP1/1；2.90678单卡分钟 | 10输出完整/全EOS/cap0；仅1程序三态，投影prompt相同；无自然任务或最强基线质量增益 |
| Phase5-C固定历史终局读出 | Forced27/32、Full15、Contract14、同证据Full18、Tail11、Projection13、Restart8；51.486914单卡分钟 | 224/224完整，109触384顶；严格交付评分，非无限长度能力；当前候选不扩大 |
| Phase5-D第一批 | 原T固定LastBox28/32；CPU30＋600；8原生题/8EOS/0cap；原bulk数值6/8、同调度参考8/8；18.897161单卡分钟 | 新读出审计不改旧分；8/8答案只是Continue，尚无SCOPE-Rebase自然收益 |
| Phase5-D2 | 24 题 × 2 种子，原生 46/48，五条配对臂均 4/4，330.77 GPU 分钟 | 两条原生失分均为多框读出，完整根集正确。当前自然适配没有获准的修复事件，配对准确率差为 0 |
| Phase5-D2.5 与 D3 | 历史三臂均答对，承接臂在该例少用 36.1% 的时间。新题原生 16/32，总计 628.95 GPU 分钟 | 正式配对准入 0，准确率增量与等成本修复效果无法估计 |
| Phase5-D3.5 | 选定历史 E12/E15 的原生错误均可修正。直接工具两题均答对。E15 三个干预模型臂都答对，实机合计约 58.03 单卡分钟 | 已完成开发闭环。回退未胜同证据强基线，独立扩测未启动 |
| Phase5-D3.6 | 32 条历史轨迹只有一次确认的值漂移。E15 棘轮阻止一次错误交付路径，但冻结质量低于同提示强基线 | 同一历史题的六个配对单元。有限点工具也给出正确值，完整程序独立证明最优，独立扩测未启动 |
| Phase5-D3.7 | 实际两处来源误触发被拦截。独立合成控制首轮 12/19 误授权，披露后复测为 0/19 | 复测和历史固定回放不构成在线安全证明。两类任务未过强求解对照门槛 |
| Phase5-D3.8 | 正式 Lean 环境通过 9 个核心、10 个 miniF2F 控制。最小释放的七个结构证书有强合并核验基线 | 合成结构控制与外部真实模型动作分列。当前没有通过独立模型试验门槛 |
| Phase5-D3.9 | 复算 852 个归档臂。p159 在作者同版环境通过，四个可能正例均有同目标保留证书 | 仍未知的 36 个状态保留未知。独立必要释放证据为零，未启动模型试验 |
| Phase5-D4.0 | 同族 31 个状态、1,201 个历史步骤。11 个未解目标均已有拆分或中间提案 | 局部精确复验范围为三个原始快照及一个受控编辑。完整历史候选图未封闭 |
| Phase5-D4.1 | 对齐 1,128 份 Lean 调用、4,283 条诊断。19 项受审控制中，导入级硬拒绝会误挡七个有效证明 | 查询与完整核验配对通过集合相同。局部性能差随顺序变化，未启动模型试验 |
| Phase5-D4.2 | 未解组 68/304 份多错误检查的首报行晚于另一报错。三个受审原稿分别做逐字节与等量编辑对照 | 报错顺序不足以推出根因。实际修正与强 CPU 基线分开归档 |
| Phase5-D4.3 | 正确候选覆盖 29/32，三题的必要条件可区分候选，排除六个错误值 | 多数票已达固定池上限。无正确值被排除，同权限准确率增量为零 |
| Phase5-D4.4 | 16 条实跑轨迹全为自然 EOS，七个启用题的真实观察中无数值条件被违反 | 两提示臂均按协议复用原生输出，未测得干预注入效应。官方分差唯一一题的题面与解答冲突，单列敏感性分析 |
| Phase5-D4.5 | 88 条轨迹中 65 条正确、2 条错误、21 条触顶。盲审将末答绑定从 12 提高到 67 | 两个持续错值都能被事后局部不可行性核验排除，可行见证并未触发。11 题金标均与独立精确求解一致 |
| Phase5-D4.6 | 88 条中 73 条正确、7 条错误、7 条触顶、1 条末框格式失败 | 点核验与普通点检结果一致。另有一条轨迹把已可行且正确的 791 改成交付较差的可行值 533 |
| Phase5-D4.7 | 64 条中 45 条正确、6 条错误、12 条触顶、1 条末框格式失败 | 六条错值都在思维末段已形成。另有两条终稿不可行，未复现可行值交付退步 |

P0与P0.5使用不同读出协议，不连成跨轮提升曲线。CPU随机模型、形式/代数控制、人工短状态、自然轨迹观察和正式benchmark各自标明，不互相替代。

## 研究定位与候选算法

定位可以随证据调整。目前不要求结果必须来自KV掩码，也不预设内部阶段指针已经存在。可研究的主线是：

```text
核验修订与旧状态依据
    → 维护变量/规则版本和依赖
    → 仅安排必要的待重推前沿
    → 显式绑定当前父值并验收结果
    → 在总预算内交付最终答案
```

这是完整候选协议，尚未实现逐节点验收/提交控制器。Phase5-A先比较共享根值核验/规则/依赖的Direct、Compact、普通步进和一次性版本工作帧；未显示候选增量，两个未解析为正确JSON的交付接口问题，不改冻结主分。质量优先生成到EOS，512仅为短控制保护顶，无尾窗；紧预算曲线以后单列。不会把顾问给出的90%正确率/省50%token预测写成结果。

Phase5-B先查历史自然失败，再后台维护受限DAG证书并投影当前父边界；较长受控程序使用768保护顶，实际10输出全部自然结束。投影161对共享G430输入token减少62.56%，但Raw/Restart同样答对；普通DAG切片也给相同输入，不称新增理论创新。下一问题优先是自然目标/答案类型与核验范围，正式自然算法与多数据集验证仍未开展。

Phase5-C将自动目标提示/未核验候选投影用于32个不同历史自然题，完整七条件后未胜强基线；109条触384顶、1项解析过严等交付问题必须与数学错误分开。用户已要求自有3090完整执行优先，下一轮解除紧token上限，正常EOS作质量主条件。具体已知问题/待证猜想与下一控制见阶段收尾，不改旧分数、不直接扩模型刷结果。

Phase5-D 聚焦完整结论覆盖、作用域与版本绑定、多重支持保护和失效证明文本退役。D2 完成 48 条新题自然轨迹和四题同状态配对。自然步骤抽取缺少可行动的作用域证据，下一门槛是离线验证完整数学对象和证明角色，再用独立新题做同证据配对。[D2 收尾](research/phase5d2_quarantined_rebase_20261107/D2_CLOSEOUT_ZH.md)

D2.5 验证了独立核查下的原生续推一致性。D3 正式样本的修复准入为零。D3.5 在已有失败前缀上测试了约束见证和认证交付，实际纠正两个历史开发案例。直接程序均能完整求解，同证据提示在 E15 也已答对，因此独立扩测暂未启动。[D3 收尾](research/phase5d25_constraint_revision_20261109/D3_CLOSEOUT_ZH.md) · [D3.5 收尾](research/phase5d35_witness_gated_revision_20261109/D35_CLOSEOUT_ZH.md)

主要指标是逐数据集accuracy或声明采样协议的pass@1；pass@k另列。完整成本包括核验、解析、被拒候选、注入前缀、prefill、重构与最终输出。NLL、梯度、KV距离和机制标签仅用于诊断。

## 目录

```text
docs/phases/                 Phase1、Phase2、Phase3……总报告与索引
research/long_cot_landscape_20261105/  文献与模块地图
research/direction_selection_20261105/ P0、平台与方向选择
research/next_design_20261105/         下一轮协议、抽样与合流控制
research/algorithm_mechanism_20261105/  算法/模型/数学分析
research/p05_design_review_20261105/    冻结P0.5与独立审计
research/repository_phase_plan_20261106/ 本次整理与建议审查
research/phase5_prototype_20261106/   算法公式、质量优先原型、真实partial与独立审计
research/phase5b_boundary_20261106/   自然诊断、建议取舍、后台投影、三态完整短试
research/phase5c_goal_contract_20261106/ 32题七条件完整终局读出、统一评分、阶段收尾
research/phase5d_scope_rebase_20261106/ 方法重构、D0审计、支持内核、原生接口与后续公平验证
research/phase5d25_constraint_revision_20261109/ D2.5 与 D3 源码、完整运行、评分和独立复核
research/phase5d35_witness_gated_revision_20261109/ D3.5 协议、见证内核、开发轨迹及实机审计
research/phase5d36_progressive_witness_20261109/ D3.6 全集诊断、点核验状态机、双检查点原始记录与收尾
research/phase5d37_scoped_repair_20261110/ D3.7 作用域与格式回归、两类任务强 CPU 准入和收尾
research/phase5d38_proof_release_20261110/ D3.8 Lean 内核、正式来源、最小释放与强 CPU 对照
research/phase5d39_blueprint_trace_20261110/ D3.9 全档案复算、作者同版证明与真实核验成本
research/phase5d40_proof_authoring_20261110/ D4.0 证明支持账本、同版失败与普通基线、引理构造准入
research/phase5d41_lean_scope_20261110/ D4.1 引理可达性、误拦截、配对成本和试验准入
research/phase5d42_lean_diagnostics_20261110/ D4.2 同源最小修正、诊断级联、冷与驻留对照
research/phase5d43_answer_refutation_20261110/ D4.3 固定候选池、原题必要条件、同权限正确率和成本
research/phase5d44_candidate_generation_20261110/ D4.4 同合同补抽、前缀准入与实时生成小试
research/phase5d45_feasible_witness_20261110/ D4.5 精确可行见证、归档自然候选和点核验诊断
research/phase5d46_point_infeasibility_20261110/ D4.6 直接点核验、真实候选绑定和交付退步诊断
research/phase5d47_delivery_preservation_20261110/ D4.7 同链可行值、证书保全和分阶段盲审
scripts/ reason_transition/ tests/     原研究实现与检查
experiments/radar20261013/             后续历史路线，当前冻结
data/ results/ provenance/ recovery/   历史输入、输出和恢复证据
```

仓库保留可上传的研究代码、协议、资料索引、原始结果与审计。模型权重、认证材料、本地依赖环境和重复打包文件留在本地；具体范围及原始Git来源见[发布说明](docs/repository/PUBLISH_SCOPE_ZH.md)。冻结证据按字节保存，新增Phase文档使用可在GitHub浏览的相对链接。历史报告中原机器绝对路径作为来源记录保留，不代表云端可访问路径。

## 历史入口

- [整理前根README](README_LEGACY_20261106.md)
- [历史综合报告](docs/REPORT_ZH.md)
- [历史18周目标（不作当前执行指令）](docs/next_phase/RESEARCH_GOAL_V2_20261014_ZH.md)

当前没有对外发布的正式新算法benchmark收益、录用结论或通用正确性保证。研究目标是通过新机制、强基线、消融和独立验证获得可复现的正增量；必要时保留负结果并调整方向。
