# 18周研究连续执行与恢复入口

此工作始终对应用户已授权的18周完整路线。按科学依赖推进，不等待日历周，不将后台启动、源码、哈希或CPU检查记作模型实验完成。此文件是恢复说明，不是完整研究交付。

用户新增要求：每轮读并更新 `RESEARCH_DECISION_LOG_ZH.md`，记录独立判断、决策依据、遇到的问题、实际尝试与结果；效果不好写出未证实猜想、支持/反对证据及可证伪的下一检查。最终统一汇总，不把猜想写成已确认原因。

最新进展：39状态/351分支/1170读出已完整并全量审计。短等待暂未显示准确率正收益，FULL8k有+13.89pp操作性平均收益但72/117分支触顶；先看 `NOISE_PILOT_REVIEW_20261014_ZH.md` 及D08–D09。合法阶乘答案的候选schema误拒绝已修复，原分数不变；正式GPU验收必须用修复后的candidate_schema。native两worker已启动并实时校验10个模型文件，不重启；等58个预期请求完整后再冻结正式参照。

远端目录：`/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/projects/radar20261013`。使用被gitignore的 `.tools/remote.py` 的 `connect()`；凭据不展示或在命令行传递。两张3090独立执行。旧研究目录、1648条输出、旧发布ZIP不覆盖。

## 当前实际任务

旧 `post_pilot_queue.py` 负责交叉噪声采集。预期39状态（分片19/20），每状态3个STOP读出，DEFER1/DEFER4/FULL各3推导种子×3读出种子；缺失、重复、无资格、未完成段落和触顶保留。

新 `continue_study.py` 用Linux flock独占调度，等旧队列进入 `formal_reference`，核验完整预算/噪声后执行29题×2预算的native敏感性（58请求）。它会等现有GPU进程退出，不与测量请求争用GPU。状态：`results/continuation_state.json`；日志：`logs/continuation_supervisor.log`。不要重复启动活着的监督器/采集器。监督器中断时保留已有推理进程；恢复先核查进程和文件，再按逐题断点续跑。

每小时本聊天heartbeat已启用，automation ID18，其目标是继续实施与审查完整研究，不只是监视。无变化时安静，仅重大结论、失败、用户需处理或完整交付时通知。不在每次唤醒创建新的自动任务，不给其他聊天发消息。

## 下一次唤醒实际执行

1. 核查远端主机/GPU、两个队列的进程/状态/错误、完整记录数。CPU分析可并行；GPU验收/生成只能在当前测量结束后执行。
2. 同步最新结果/日志/证据。`.tools/sync_radar.py` 会取远端证据；本地新增派生报告先部署或另存，避免被较旧同名远端文件覆盖。正式冻结运行后不要上传改变源码/数据。
3. 若噪声/native未完整，继续源码、原文实现、评分审查等独立工作，不用部分统计选择最终机制，不报告完整成绩。
4. 完整后运行并实际审阅 `analyze_budget_pilot.py`、`analyze_noise_bank.py`、`analyze_native_pilot.py`、`audit_pilot_evidence.py`、`budget_repair_audit.json`。查所有不一致。噪声FULL上限8192，不能当16384参考的机制标签。
5. 写 `provenance/formal_scientific_review.json`，包含 `pilot_interpretation`、`reference_choice_reason`、`noise_interpretation`、`native_readout_interpretation`、`proceed_to_development`、`reviewed_evidence_sha256`。SHA键至少含上述4个完整结果JSON和 `results/budget_repair_audit.json`，取实际远端文件哈希。不是从marker推断科学审查通过。
6. GPU空闲时重跑 `validate_new_protocol.py` 核对权重/缓存，再跑 `validate_candidate_protocol.py --lengths 128 8192 16384 --prefix-source saved_pilot --output candidate_formal_admission.json` 覆盖当前主模型潜在16k上限。它按长度从已完成同模型pilot选token IDs，不看正确性，通过完整prefill恢复cache，不称历史incremental KV。生成模式仍可另测实际生成前缀；请求上限不等于实际长度。跨模型不能借主模型token IDs验收；失败原样保留。审查文件写 `fresh_live_admission_sha256`。
7. 按完整pilot选正式有界FULL，执行 `freeze_formal_protocol.py --review-file provenance/formal_scientific_review.json --max-think-tokens <8192或12288或16384> --candidate-admission candidate_formal_admission.json --capture-hidden`。16384目前比8192多答对5题，但仍11/29触顶，不能称完全自然FULL。native/boxed独立，不合并成绩；读出或输入不可靠先修复复测。

## 正式开发与M1

正式协议/科学review与真实证据绑定后，新队列自动推进530开发题、265选择题银行、题目隔离训练、有限候选选择、M1真实在线请求及完整统计。银行计时标proxy；线上计入全部拒绝读出/探针和最终回答。

M1包括12方法×265题=3180请求：FULL、固定1024/2048/4096/8192、预声明主风险门禁、同特征当前正确率、EAT独立适配、DEER启发的试答置信度proxy、Conformal双阈值独立适配、旧控制器原8192上限、旧控制器匹配新上限。后两者分别保留原预算和作受控适配；作者完整DEER/PRo/Conformal/其他强基线仍需W10–12完成，proxy不能取代。Conformal操作点只在选择集按共同配对质量选择，不继承作者保证；论文损失和harmful分别报告。选择集结果是探索性。

正式GPU分配改为固定problem ID哈希，独立于split成员和行顺序；CUDA环境、银行、线上与分析均检查。开发272/258、选择118/147、校准395/400、测试529/533。当前pilot/噪声/native分片保持原样。M1时间包含输入tokenization至答案完成，仍为单请求后端compute，不能称网络/队列/Serving延迟。

`analyze_m1_online.py` 核验完整ID/token前缀、真实wall-clock、问题配对Bootstrap、主策略银行/在线候选身份一致性，单列FULL正确题上的节省。验收绑定具体spec哈希、模型、协议，不能借给未测候选。

队列在 `m1_review` 等代理判读，不等用户再次确认。主目标仍为准确率下降≤1pp、wall-clock下降≥15%，并比较最佳同质量固定/EAT前沿。无收益先查风险门禁、测量/评分、固定预算与共同错题，再按原W6规则决定，不直接开发复杂网络或包装零效率。

## 后续必须完成

DTSR已实现独立64-token触发decoder与online入口，避免错误复用128-token段落hook；当前只有4个CPU协议控制，未有GPU/模型成绩。native测量结束且GPU空闲后执行 `CUDA_VISIBLE_DEVICES=0 .venv/bin/python scripts/validate_dtsr_gpu.py --model <已冻结Qwen3-4B路径>`，三前缀rating/父KV/续写实际通过后，再用 `freeze_dtsr_protocol.py` 绑定主formal哈希及独立source集合。选择集调用 `evaluate_dtsr_online.py --split selection --protocol-file provenance/dtsr_protocol.json --out-tag dtsr_selection --shard <0或1> --model <路径>`，两卡按固定ID分片。最终测试须另有dtsr_final_test_freeze且覆盖完整ID，不能在所有策略冻结前生成。见决策D10。它不改变已计划M1的12种方法，也不替代完整强基线阶段。

- W7–9：M1有实测收益才扩展DEFER1/2/4、毫秒成本、稀疏检测及消融；新动作/协议另验收冻结，不混写银行。
- W10–12：作者可执行强基线和明确标记的独立适配；独立795题校准。候选全集/主策略/alpha在校准前冻结，采集与分析绑定家族SHA。有限分层池界按 `CALIBRATION_SAMPLING_CONTRACT_ZH.md`；IID界只作条件敏感性。不得看校准后换主策略或把1pp失败改称2pp主目标。
- W13–15：全部策略/源码/模型/预算/数据冻结前，不生成或人工查看1062题测试。冻结时实际测试记录为0，之后覆盖完整ID。Thinking-2507和DeepSeek8B各自数值/显存/terminator/readout验收后实测；至少一个非数学任务。LCB容器接口通过不等于模型pass@1，仍需实际生成、执行与失败留档。
- W16–18：算法门槛成立才做真实batch/并发Serving/goodput；单请求节省不能当吞吐。阶段NO-GO须有真实证据并明确后续不适用项。无论GO/NO-GO，完成消融、失败审计、复现包、论文材料、工作记录和交付核查后统一报告，停止heartbeat。不要在pilot/训练/校准/盲测子任务结束时停止研究。

仓库目前没有Git remote，本地提交不叫GitHub上传；归档阶段核对授权目的地/身份，优先现有Git Credential Manager，不打印凭据。

## 本轮错误修正

旧几何oracle坐标对应三边平方2601/16、81、5625/16，不能验证9/10/17；面积碰巧同为1155/4。旧源码/JSON保存在 `provenance/oracle_archive/`。v2核对81/100/289、圆心(5,75/8)、半径平方7225/64、六点在圆、对径关系和凸包顺序后仍得1155/4。撤回原“题设精确验证”证据，不改变GPU输出/冻结评分。
