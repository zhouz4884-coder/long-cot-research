# 18周研究连续执行与恢复入口

**当前授权已变更（2026-11-05）**：用户已清除持续目标，明确要求丢下旧基础，从零做长思维链文献调研，理解模块、效果和可组合突破口。本轮不恢复旧GPU队列，不创建持续目标或计时任务。新资料入口：[从零长思维链调研](../../research/long_cot_landscape_20261105/README.md)。下文的快迭代和18周路线均为历史记录，不是当前调研的预设科学目标。

2026-10-14用户要求阅读新版计划和上传评议后重新修改目标。后续科学优先级以 [研究目标V2](RESEARCH_GOAL_V2_20261014_ZH.md) 为准，输入、分歧决策及三道门槛均已记录；原路线保留为历史。

接续前先读取应用内目标状态。用户最新“重新制定目标并删除每小时任务”指令后，旧目标已不在应用中，新版连续研究目标已成功建立，status=active。按V2科学依赖完成全部适用阶段，不等待日历周，不将后台启动、源码、哈希或CPU检查记作模型实验完成。没有停止或重启现有后台采集。此文件是恢复说明，不是完整研究交付；若用户之后暂停，遵守新的暂停状态。

用户新增要求：每轮读并更新 `RESEARCH_DECISION_LOG_ZH.md`，记录独立判断、决策依据、遇到的问题、实际尝试与结果；效果不好写出未证实猜想、支持/反对证据及可证伪的下一检查。最终统一汇总，不把猜想写成已确认原因。

最新进展：完整58个native已审查/重评分，五组fresh GPU有限接口均通过，正式16k boxed协议已冻结，SHA `423f8b632d628443d9a4517bb8bb280714940776e1a4ddf2fbe166593ce323f2`。DTSR/REFRAIN/ASAG独立协议也已冻结。当前进入530题development bank，两原worker PID1874879/1874880确认存活，最近36/530落盘；不是530题完成或算法收益。主监督器PID1780322继续执行后续selection/train/M1。每次醒来重新查实际PID，不重启活着的worker。

后续当前实际核查：SSH观察两次timeout后恢复，同一两worker继续存活、47/530落盘。只读snapshot的36题/1800 prefix审计保持历史证据；更新进度不扩大其审计范围。新strong-baseline分析工具见D19；缺结果guard与统计helper已验证，无新的baseline任务分数。

native8k/16k为13/18正确，matched boxed为17/22（每组29），两组各4个native损失/0收益，精确paired p=.125。native增加预算的5个改善中4个在boxed8k已正确；2例已闭合thinking却截断final，延长同一轨迹后完成。正式参考为有界boxed FULL16384，仍有11/29触顶，不称自然无限FULL。详见D16–D17与 `NATIVE_PILOT_REVIEW_20261014_ZH.md`。

远端目录：`/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/projects/radar20261013`。使用被gitignore的 `.tools/remote.py` 的 `connect()`；凭据不展示或在命令行传递。两张3090独立执行。旧研究目录、1648条输出、旧发布ZIP不覆盖。

## 当前实际任务

当前只核查development/selection的既有实际进程、错误、newline-complete记录和协议身份；bank时间标proxy。**正式生成已开始，不再上传或改变formal/baseline绑定源码、数据、模型/协议文件、科学review及其证据。** 新的只读分析脚本和日志可独立增加。已完成的native/有限GPU验收不用重跑；下方保留当时放行步骤作审计历史。

只读完成记录审计：`CUDA_VISIBLE_DEVICES= .venv/bin/python scripts/audit_running_bank.py --split development --output results/<新的snapshot文件>.json`。它核对实际prompt+trace的checkpoint hash、ID/shard/seed、labels-after-generation及proxy标识，排除尚未写完的尾行；不统计部分正确率或声称全银行完成。原snapshot不覆盖。

旧 `post_pilot_queue.py` 负责交叉噪声采集。预期39状态（分片19/20），每状态3个STOP读出，DEFER1/DEFER4/FULL各3推导种子×3读出种子；缺失、重复、无资格、未完成段落和触顶保留。

新 `continue_study.py` 用Linux flock独占调度，等旧队列进入 `formal_reference`，核验完整预算/噪声后执行29题×2预算的native敏感性（58请求）。它会等现有GPU进程退出，不与测量请求争用GPU。状态：`results/continuation_state.json`；日志：`logs/continuation_supervisor.log`。不要重复启动活着的监督器/采集器。监督器中断时保留已有推理进程；恢复先核查进程和文件，再按逐题断点续跑。

2026-10-14用户明确要求删除每小时定时任务，automation ID18已由应用工具确认删除。新版研究目标作为独立目标保留，不建立替代定时任务；原文中的heartbeat设置仅为历史。此删除不终止或重启既有GPU采集，未来执行按用户授权和应用目标状态推进。

## 已完成的pilot放行步骤（审计历史，不重复执行）

1. 核查远端主机/GPU、两个队列的进程/状态/错误、完整记录数。CPU分析可并行；GPU验收/生成只能在当前测量结束后执行。
2. 同步最新结果/日志/证据。`.tools/sync_radar.py` 会取远端证据；本地新增派生报告先部署或另存，避免被较旧同名远端文件覆盖。正式冻结运行后不要上传改变源码/数据。
3. 若噪声/native未完整，继续源码、原文实现、评分审查等独立工作，不用部分统计选择最终机制，不报告完整成绩。
4. 完整后运行并实际审阅 `analyze_budget_pilot.py`、`analyze_noise_bank.py`、`analyze_native_pilot.py`、`audit_pilot_evidence.py`、`budget_repair_audit.json`。查所有不一致。噪声FULL上限8192，不能当16384参考的机制标签。

native完整分析已补两预算对forced逐题对照、精确配对检验/Bootstrap、实际思考prefix、模型身份/采样/预算分配分类和待审阅差异案例。先看完整对照及D12，不能把两协议所有差异当cue-only；旧forced8k额外捕获features，native允许thinking占用名义+192总cap且闭合后随机数耦合不同。
5. 写 `provenance/formal_scientific_review.json`，包含 `pilot_interpretation`、`reference_choice_reason`、`noise_interpretation`、`native_readout_interpretation`、`proceed_to_development`、`reviewed_evidence_sha256`。SHA键至少含上述4个完整结果JSON和 `results/budget_repair_audit.json`，取实际远端文件哈希。不是从marker推断科学审查通过。
6. GPU空闲时重跑 `validate_new_protocol.py` 核对权重/缓存，再跑 `validate_candidate_protocol.py --lengths 128 8192 16384 --prefix-source saved_pilot --output candidate_formal_admission.json` 覆盖当前主模型潜在16k上限。它按长度从已完成同模型pilot选token IDs，不看正确性，通过完整prefill恢复cache，不称历史incremental KV。生成模式仍可另测实际生成前缀；请求上限不等于实际长度。跨模型不能借主模型token IDs验收；失败原样保留。审查文件写 `fresh_live_admission_sha256`。已准备的DTSR/REFRAIN/ASAG有限GPU验收也应在这一空闲窗口依次执行（命令见下），随后才释放formal_review；正式freeze会立即唤醒监督器生成开发银行，不能让额外验收与正式测量争用GPU。它们的CPU protocol freeze可在main formal之后执行。
7. 按完整pilot选正式有界FULL，执行 `freeze_formal_protocol.py --review-file provenance/formal_scientific_review.json --max-think-tokens <8192或12288或16384> --candidate-admission candidate_formal_admission.json --capture-hidden`。16384目前比8192多答对5题，但仍11/29触顶，不能称完全自然FULL。native/boxed独立，不合并成绩；读出或输入不可靠先修复复测。

## 正式开发与M1

正式协议/科学review与真实证据绑定后，新队列自动推进530开发题、265选择题银行、题目隔离训练、有限候选选择、M1真实在线请求及完整统计。银行计时标proxy；线上计入全部拒绝读出/探针和最终回答。

M1包括12方法×265题=3180请求：FULL、固定1024/2048/4096/8192、预声明主风险门禁、同特征当前正确率、EAT独立适配、DEER启发的试答置信度proxy、Conformal双阈值独立适配、旧控制器原8192上限、旧控制器匹配新上限。后两者分别保留原预算和作受控适配；作者完整DEER/PRo/Conformal/其他强基线仍需W10–12完成，proxy不能取代。Conformal操作点只在选择集按共同配对质量选择，不继承作者保证；论文损失和harmful分别报告。选择集结果是探索性。

正式GPU分配改为固定problem ID哈希，独立于split成员和行顺序；CUDA环境、银行、线上与分析均检查。开发272/258、选择118/147、校准395/400、测试529/533。当前pilot/噪声/native分片保持原样。M1时间包含输入tokenization至答案完成，仍为单请求后端compute，不能称网络/队列/Serving延迟。

`analyze_m1_online.py` 核验完整ID/token前缀、真实wall-clock、问题配对Bootstrap、主策略银行/在线候选身份一致性，单列FULL正确题上的节省。验收绑定具体spec哈希、模型、协议，不能借给未测候选。

队列在 `m1_review` 等代理判读，不等用户再次确认。主目标仍为准确率下降≤1pp、wall-clock下降≥15%，并比较最佳同质量固定/EAT前沿。无收益先查风险门禁、测量/评分、固定预算与共同错题，再按原W6规则决定，不直接开发复杂网络或包装零效率。

## 后续必须完成

独立完整strong-baseline分析入口已准备 `scripts/analyze_controlled_baseline.py`，使用与边界见 `CONTROLLED_BASELINE_ANALYSIS_CONTRACT_ZH.md` 及D19。它要求完整ID/markers并重新评分；ASAG/REFRAIN用内嵌新FULL，DTSR另绑定真实M1 FULL及policy plan。REFRAIN有序自适应不套普通IID统计或M1风险证书。当前只验证分析程序，不要运行缺结果分析并把拒绝当模型失败；不改冻结生成源码。

ASAG独立适配已准备真实QK-window observer和四动作decoder。3组真实随机权重tiny Qwen3 CPU controls与9个CPU方程/tape controls通过；不是4B模型结果。第一次lazy-cache越界已修复/留档。细节、明确的实现歧义、待检验猜想见D14和 `ASAG_IMPLEMENTATION_CONTRACT_ZH.md`。

native之后空闲GPU依次执行 `CUDA_VISIBLE_DEVICES=0 .venv/bin/python scripts/validate_asag_gpu.py --model <主模型路径>`，按长度恢复实际128/8192/16384并重复scratch probes、核验父KV，另有512-token真实集成。成功后main formal再运行 `freeze_asag_protocol.py --model <路径>`，选择集入口 `evaluate_asag_online.py --split selection --model <路径> --protocol-file provenance/asag_protocol.json --out-tag asag_selection --shard <0或1>`（各CUDA_VISIBLE_DEVICES固定物理卡）。每题另实际执行matched FULL；所有副本/probe/注入/J成本计入。仍是声明差异的独立适配，不称作者完整BF16/greedy复现。所有测试未生成前另建ASAG final freeze。

REFRAIN准备已补入D13及 `WORKLOG_20261014_REFRAIN_PREPARATION_ZH.md`：真实MiniLM默认编码器CPU检查、五个协议控制与一个全局有序bandit流。默认trigger从PDF表5排除扩展消融；不要把空行检查改为128-token hook。模型在远端 `/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/models/all-MiniLM-L6-v2`，manifest在provenance。首次远端编码检查因为SFTP未结束而被SHA拒绝，先确认原传输结束及文件哈希再复测，不能推断模型损坏。未有GPU方法成绩。

此传输失败已纠正：原handle完成，远端冻结环境CPU编码器报告passed已同步，本地/远端5个协议控制也通过。下一依赖是空闲GPU实际缓存/prefix/reader身份验收，不需再下载模型或升级环境。

native空闲后执行 `CUDA_VISIBLE_DEVICES=0 .venv/bin/python scripts/validate_refrain_gpu.py --model <主模型路径> --encoder <MiniLM路径> --encoder-manifest provenance/refrain_encoder_manifest.json`。三实际前缀父KV和共同reader token身份通过、main formal已冻结后再 `freeze_refrain_protocol.py --model <路径>`。选择集运行需 `CUDA_VISIBLE_DEVICES=0,1 .venv/bin/python scripts/evaluate_refrain_online.py --split selection --model <路径> --encoder <MiniLM路径> --protocol-file provenance/refrain_protocol.json --out-tag refrain_selection`，它按ID路由两卡但串行、单一全局有序bandit，不拆成两个worker。test另要求REFRAIN独立final freeze和实际零已生成测试记录；不要借M1风险证书给这个跨题自适应基线。

DTSR已实现独立64-token触发decoder与online入口，避免错误复用128-token段落hook；当前只有4个CPU协议控制，未有GPU/模型成绩。native测量结束且GPU空闲后执行 `CUDA_VISIBLE_DEVICES=0 .venv/bin/python scripts/validate_dtsr_gpu.py --model <已冻结Qwen3-4B路径>`，三前缀rating/父KV/续写实际通过后，再用 `freeze_dtsr_protocol.py` 绑定主formal哈希及独立source集合。选择集调用 `evaluate_dtsr_online.py --split selection --protocol-file provenance/dtsr_protocol.json --out-tag dtsr_selection --shard <0或1> --model <路径>`，两卡按固定ID分片。最终测试须另有dtsr_final_test_freeze且覆盖完整ID，不能在所有策略冻结前生成。见决策D10。它不改变已计划M1的12种方法，也不替代完整强基线阶段。

- W7–9（V2）：完整M1后依据错误与成本分解，在廉价候选重读和长程纠错机会识别中选择一个核心机制。短DEFER1/4不再默认作为纠错动作；完成性、按需前瞻、复用及稀疏检测须有增量信息和净成本依据后再扩展。M1不达标则完成有界机制检验或有证据的转向，不无限加阈值；新动作/协议另验收冻结，不混写银行。见目标V2的M2和G2。
- W10–12：作者可执行强基线和明确标记的独立适配；独立795题校准。候选全集/主策略/alpha在校准前冻结，采集与分析绑定家族SHA。有限分层池界按 `CALIBRATION_SAMPLING_CONTRACT_ZH.md`；IID界只作条件敏感性。不得看校准后换主策略或把1pp失败改称2pp主目标。
- W13–15：全部策略/源码/模型/预算/数据冻结前，不生成或人工查看1062题测试。冻结时实际测试记录为0，之后覆盖完整ID。Thinking-2507和DeepSeek8B各自数值/显存/terminator/readout验收后实测；至少一个非数学任务。LCB容器接口通过不等于模型pass@1，仍需实际生成、执行与失败留档。
- W16–18：算法门槛成立才做真实batch/并发Serving/goodput；单请求节省不能当吞吐。阶段NO-GO须有真实证据并明确后续不适用项。无论GO/NO-GO，完成消融、失败审计、复现包、论文材料、工作记录和交付核查后统一报告。不要在pilot/训练/校准/盲测子任务结束时停止研究。每小时定时任务已按用户要求删除，不再作为执行入口。

仓库目前没有Git remote，本地提交不叫GitHub上传；归档阶段核对授权目的地/身份，优先现有Git Credential Manager，不打印凭据。

## 本轮错误修正

旧几何oracle坐标对应三边平方2601/16、81、5625/16，不能验证9/10/17；面积碰巧同为1155/4。旧源码/JSON保存在 `provenance/oracle_archive/`。v2核对81/100/289、圆心(5,75/8)、半径平方7225/64、六点在圆、对径关系和凸包顺序后仍得1155/4。撤回原“题设精确验证”证据，不改变GPU输出/冻结评分。
